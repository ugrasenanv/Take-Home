from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class ReturnRecord:
    order_id: str
    customer_id: str
    store_id: str
    country: str
    channel: str
    product_name: str
    category: str
    brand: str
    unit_price: float
    currency: str
    quantity: int
    return_date: str
    purchase_date: str
    reason_text: str
    reason_code: str
    warranty_claim: int
    refund_status: str
    support_language: str
    agent_notes: str


class TransactionDB:
    def __init__(self, db_path: str = "data/returns.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS returns (
                    return_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    store_id TEXT NOT NULL,
                    country TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    brand TEXT NOT NULL,
                    unit_price REAL NOT NULL,
                    currency TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    return_date TEXT NOT NULL,
                    purchase_date TEXT NOT NULL,
                    reason_text TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    warranty_claim INTEGER NOT NULL,
                    refund_status TEXT NOT NULL,
                    support_language TEXT NOT NULL,
                    agent_notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_returns_unique ON returns(order_id, product_name, return_date)"
            )

    def _next_return_id(self, conn: sqlite3.Connection) -> str:
        cursor = conn.execute("SELECT COUNT(*) FROM returns")
        count = int(cursor.fetchone()[0]) + 1001
        return f"R{count}"

    def insert_return(self, record: ReturnRecord) -> tuple[bool, str]:
        with self._connect() as conn:
            duplicate = conn.execute(
                "SELECT return_id FROM returns WHERE order_id = ? AND product_name = ? AND return_date = ?",
                (record.order_id, record.product_name, record.return_date),
            ).fetchone()
            if duplicate:
                return False, f"Duplicate return prevented. Existing return_id={duplicate[0]}"

            return_id = self._next_return_id(conn)
            conn.execute(
                """
                INSERT INTO returns (
                    return_id, order_id, customer_id, store_id, country, channel,
                    product_name, category, brand, unit_price, currency, quantity,
                    return_date, purchase_date, reason_text, reason_code, warranty_claim,
                    refund_status, support_language, agent_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    return_id,
                    record.order_id,
                    record.customer_id,
                    record.store_id,
                    record.country,
                    record.channel,
                    record.product_name,
                    record.category,
                    record.brand,
                    record.unit_price,
                    record.currency,
                    record.quantity,
                    record.return_date,
                    record.purchase_date,
                    record.reason_text,
                    record.reason_code,
                    record.warranty_claim,
                    record.refund_status,
                    record.support_language,
                    record.agent_notes,
                ),
            )
            return True, return_id

    def bulk_upsert_csv(self, csv_path: str) -> dict[str, int]:
        frame = pd.read_csv(csv_path)
        inserted, skipped = 0, 0
        for _, row in frame.iterrows():
            ok, _ = self.insert_return(
                ReturnRecord(
                    order_id=str(row["order_id"]),
                    customer_id=str(row["customer_id"]),
                    store_id=str(row["store_id"]),
                    country=str(row["country"]),
                    channel=str(row["channel"]),
                    product_name=str(row["product_name"]),
                    category=str(row["category"]),
                    brand=str(row["brand"]),
                    unit_price=float(row["unit_price"]),
                    currency=str(row["currency"]),
                    quantity=int(row["quantity"]),
                    return_date=str(row["return_date"]),
                    purchase_date=str(row["purchase_date"]),
                    reason_text=str(row["reason_text"]),
                    reason_code=str(row["reason_code"]),
                    warranty_claim=int(row["warranty_claim"]),
                    refund_status=str(row["refund_status"]),
                    support_language=str(row["support_language"]),
                    agent_notes=str(row.get("agent_notes", "")),
                )
            )
            inserted += int(ok)
            skipped += int(not ok)
        return {"inserted": inserted, "skipped": skipped}

    def query_df(self, sql: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
        with self._connect() as conn:
            return pd.read_sql_query(sql, conn, params=params)
