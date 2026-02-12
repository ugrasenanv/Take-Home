from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from sklearn.linear_model import LinearRegression

from .data_layer import ReturnRecord, TransactionDB
from .rag_store import VectorRAGStore


class RetrievalAgent:
    def __init__(self, db: TransactionDB, rag: VectorRAGStore) -> None:
        self.db = db
        self.rag = rag

    def ingest_csv(self, csv_path: str) -> str:
        summary = self.db.bulk_upsert_csv(csv_path)
        frame = self.db.query_df("SELECT * FROM returns")
        count = self.rag.index_dataframe(frame, version=datetime.utcnow().strftime("v%Y%m%d%H%M%S"))
        return f"Ingestion complete. Inserted={summary['inserted']} skipped_duplicates={summary['skipped']} indexed_chunks={count}."

    def add_return_from_nl(self, user_text: str) -> str:
        # Minimal parsing for demo. In production, this comes from a structured form/tool call.
        fields = {
            "order_id": self._extract(user_text, r"order\s*id\s*[:=]\s*(\w+)", "UNKNOWN_ORDER"),
            "customer_id": self._extract(user_text, r"customer\s*id\s*[:=]\s*(\w+)", "UNKNOWN_CUSTOMER"),
            "store_id": self._extract(user_text, r"store\s*id\s*[:=]\s*(\w+)", "UNK"),
            "country": self._extract(user_text, r"country\s*[:=]\s*([A-Za-z]{2})", "US").upper(),
            "channel": self._extract(user_text, r"channel\s*[:=]\s*(\w+)", "online"),
            "product_name": self._extract(user_text, r"product\s*[:=]\s*([^,;]+)", "Unknown product").strip(),
            "category": self._extract(user_text, r"category\s*[:=]\s*([^,;]+)", "Other").strip(),
            "brand": self._extract(user_text, r"brand\s*[:=]\s*([^,;]+)", "Unknown").strip(),
            "unit_price": float(self._extract(user_text, r"price\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)", "0")),
            "currency": self._extract(user_text, r"currency\s*[:=]\s*([A-Za-z]{3})", "USD").upper(),
            "quantity": int(self._extract(user_text, r"quantity\s*[:=]\s*(\d+)", "1")),
            "return_date": self._extract(user_text, r"return\s*date\s*[:=]\s*([0-9\-]+)", datetime.today().strftime("%Y-%m-%d")),
            "purchase_date": self._extract(user_text, r"purchase\s*date\s*[:=]\s*([0-9\-]+)", datetime.today().strftime("%Y-%m-%d")),
            "reason_text": self._extract(user_text, r"reason\s*[:=]\s*([^;]+)", "No reason provided").strip(),
            "reason_code": self._extract(user_text, r"reason\s*code\s*[:=]\s*(\w+)", "OTHER").upper(),
            "warranty_claim": int(self._extract(user_text, r"warranty\s*[:=]\s*(\d)", "0")),
            "refund_status": self._extract(user_text, r"refund\s*status\s*[:=]\s*(\w+)", "pending"),
            "support_language": self._extract(user_text, r"language\s*[:=]\s*([A-Za-z]{2})", "en"),
            "agent_notes": self._extract(user_text, r"notes\s*[:=]\s*(.+)$", "").strip(),
        }

        if fields["unit_price"] <= 0:
            return "Cannot confirm refund: missing/invalid price. Please provide price > 0."

        ok, msg = self.db.insert_return(ReturnRecord(**fields))
        if not ok:
            return msg

        frame = self.db.query_df("SELECT * FROM returns")
        self.rag.index_dataframe(frame, version=datetime.utcnow().strftime("v%Y%m%d%H%M%S"))
        return f"Refund record inserted successfully with return_id={msg}. Refund status={fields['refund_status']}."

    @staticmethod
    def _extract(text: str, pattern: str, default: str) -> str:
        m = re.search(pattern, text, flags=re.I)
        return m.group(1) if m else default


class ReportAgent:
    def __init__(self, db: TransactionDB, rag: VectorRAGStore, reports_dir: str = "data/reports") -> None:
        self.db = db
        self.rag = rag
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def answer(self, question: str) -> tuple[str, str | None]:
        q = question.lower()
        days = 14
        m = re.search(r"(\d+)\s*(day|days|week|weeks)", q)
        if m:
            val = int(m.group(1))
            days = val * 7 if "week" in m.group(2) else val

        since = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
        frame = self.db.query_df(
            """
            SELECT *, (unit_price * quantity) as exposure
            FROM returns
            WHERE return_date >= ?
            """,
            (since,),
        )

        if "iphone" in q:
            frame = frame[frame["product_name"].str.contains("iphone", case=False, na=False)]

        count = len(frame)
        exposure = float(frame["exposure"].sum()) if count else 0.0
        top_reason = frame["reason_code"].mode().iloc[0] if count else "N/A"

        retrieved = self.rag.search(question, top_k=3)
        rag_hint = "; ".join([chunk.text for chunk in retrieved]) if retrieved else "No matching context."

        report_path = self.reports_dir / f"returns_report_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.xlsx"
        with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
            frame.to_excel(writer, index=False, sheet_name="returns")
            pd.DataFrame([{"count": count, "financial_exposure": exposure, "top_reason": top_reason}]).to_excel(
                writer, index=False, sheet_name="summary"
            )

        answer = (
            f"Returns in last {days} days: {count}. Financial exposure: {exposure:.2f}. "
            f"Possible defect/driver: {top_reason}.\nEvidence snippets: {rag_hint}"
        )
        return answer, str(report_path)


class ForecastAgent:
    def __init__(self, db: TransactionDB) -> None:
        self.db = db

    def forecast_daily_volume(self, horizon_days: int = 30) -> tuple[pd.DataFrame, str]:
        frame = self.db.query_df("SELECT return_date, category FROM returns")
        if frame.empty:
            return pd.DataFrame(), "No data available for forecasting."

        frame["return_date"] = pd.to_datetime(frame["return_date"])
        daily = frame.groupby("return_date").size().reset_index(name="returns")
        all_days = pd.date_range(daily["return_date"].min(), daily["return_date"].max())
        daily = daily.set_index("return_date").reindex(all_days, fill_value=0).rename_axis("return_date").reset_index()
        daily["t"] = range(len(daily))

        model = LinearRegression()
        model.fit(daily[["t"]], daily["returns"])

        future_idx = pd.DataFrame({"t": range(len(daily), len(daily) + horizon_days)})
        future_idx["predicted_returns"] = model.predict(future_idx[["t"]]).clip(min=0)
        future_idx["return_date"] = pd.date_range(daily["return_date"].max() + timedelta(days=1), periods=horizon_days)

        metrics_mae = float((daily["returns"] - model.predict(daily[["t"]])).abs().mean())
        summary = (
            f"Forecast horizon={horizon_days} days, granularity=daily, target=return_volume, "
            f"metric=MAE ({metrics_mae:.3f}), model=LinearRegression with time index feature."
        )
        return future_idx[["return_date", "predicted_returns"]], summary


class CoordinatorAgent:
    """MCP-style coordinator routing user intents to tool-capable agents with guardrails."""

    def __init__(self, retrieval: RetrievalAgent, report: ReportAgent, forecast: ForecastAgent) -> None:
        self.retrieval = retrieval
        self.report = report
        self.forecast = forecast

    def route(self, user_text: str) -> dict:
        lowered = user_text.lower()
        if "ingest" in lowered and ".csv" in lowered:
            path = re.search(r"([\w/\.\-]+\.csv)", user_text)
            if not path:
                return {"type": "error", "message": "CSV path missing."}
            return {"type": "retrieval", "message": self.retrieval.ingest_csv(path.group(1))}
        if "return" in lowered and "product" in lowered:
            return {"type": "retrieval", "message": self.retrieval.add_return_from_nl(user_text)}
        if "forecast" in lowered:
            m = re.search(r"(\d+)\s*day", lowered)
            horizon = int(m.group(1)) if m else 30
            table, summary = self.forecast.forecast_daily_volume(horizon)
            return {"type": "forecast", "message": summary, "table": table}
        response, report_path = self.report.answer(user_text)
        return {"type": "report", "message": response, "report_path": report_path}

    @staticmethod
    def tool_contracts() -> dict:
        return {
            "retrieval.ingest_csv": {"input": {"csv_path": "str"}, "output": "status string"},
            "retrieval.add_return_from_nl": {"input": {"user_text": "str"}, "output": "insert/validation message"},
            "report.answer": {"input": {"question": "str"}, "output": "answer + optional excel path"},
            "forecast.forecast_daily_volume": {
                "input": {"horizon_days": "int"},
                "output": "dataframe(date,prediction) + model summary",
            },
        }

    @staticmethod
    def guardrails() -> dict:
        return {
            "no_duplicate_returns": "enforced by DB unique index (order_id, product_name, return_date)",
            "no_fake_refund_confirmation": "refund confirmation only after DB insert success",
            "pii_leakage": "chat outputs never expose customer_id unless asked by authorized analysts",
            "prompt_injection_from_csv": "retrieval sanitizes suspicious instructions before indexing/search",
        }


def build_system() -> CoordinatorAgent:
    db = TransactionDB()
    rag = VectorRAGStore()
    retrieval = RetrievalAgent(db, rag)
    report = ReportAgent(db, rag)
    forecast = ForecastAgent(db)
    return CoordinatorAgent(retrieval, report, forecast)
