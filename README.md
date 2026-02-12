# Take-Home Assignment: AI System Design & Implementation

This repository contains a production-oriented design + runnable prototype for an **AI-powered Returns & Warranty Intelligence Platform**.

## 1) Product Requirements & Scope

### Core pain points
- Return records are fragmented (CSV exports, call logs, analyst spreadsheets) and not normalized.
- Return reasons are multilingual/free-text, causing low-quality analytics.
- No natural-language interface for support/ops staff.
- No reliable forecasting to proactively manage defect spikes and refund exposure.

### Sub-problems decomposition
1. **Data ingestion**: ingest CSV and natural-language return submissions with validation + deduplication.
2. **Conversation**: chat-first interface with coordinator routing to purpose-specific agents.
3. **Analytics**: retrieval-augmented insights, trend summaries, and defect drivers.
4. **Forecasting**: daily return volume prediction for planning horizon.
5. **Reporting**: downloadable Excel output for operations and finance.
6. **Governance**: audit trails, tool contracts, guardrails, and deterministic write confirmation.

### Assumptions and trade-offs
- This prototype runs locally with SQLite + TF-IDF vector retrieval (offline, deterministic, low ops overhead).
- Forecast model uses linear regression baseline to keep explainability high; accuracy can be improved with richer features.
- Natural-language return insertion is parsed via regex for demo simplicity; production should use schema-validated forms/tool calls.

### In scope
- MCP-style coordinator and 3 agents.
- CSV ingestion, dedupe enforcement, NL return insertion.
- RAG search over return narratives.
- NL analytics answers + downloadable Excel.
- Daily return volume forecasting with metrics.
- Chat UI and audit trail.

### Out of scope
- Multi-tenant authN/authZ implementation.
- Real-time POS integration/webhooks.
- Advanced MLOps pipelines/model registry.
- Human-in-the-loop review UI.

---

## 2) System Architecture (MCP-style Agents)

### Components and responsibilities
- **UI (Streamlit)**: ChatGPT-like interaction, report download, forecast chart, audit view.
- **Coordinator Agent**: intent routing and tool invocation contract boundary.
- **Retrieval Agent (read/write)**:
  - ingest CSV into transaction DB
  - index records into vector store
  - parse NL return requests and insert verified records
- **Report Agent (read/insights/reporting)**:
  - answer analytics questions
  - calculate counts/exposure/top reasons
  - generate Excel files
- **Forecast Agent**:
  - train baseline on historical daily return counts
  - forecast next horizon and expose model summary/metric
- **Transaction DB (SQLite)**: source of truth for write operations and dedupe.
- **Vector store (local TF-IDF)**: semantic retrieval for reason/context snippets.
- **Object storage (filesystem)**: raw CSV dataset and generated reports.

### Tool/function contracts
- `retrieval.ingest_csv(csv_path: str) -> str`
- `retrieval.add_return_from_nl(user_text: str) -> str`
- `report.answer(question: str) -> (answer: str, report_path: Optional[str])`
- `forecast.forecast_daily_volume(horizon_days: int) -> (DataFrame, summary: str)`

### Message routing
- `ingest ...csv` → Retrieval Agent
- `return product=...` → Retrieval Agent write flow
- `forecast ...` → Forecast Agent
- default analytics questions → Report Agent

### Guardrails
- **Duplicate returns**: unique DB index `(order_id, product_name, return_date)`.
- **Fake refund confirmations**: confirmation emitted only after DB insert success.
- **PII leakage control**: responses avoid exposing customer IDs by default.
- **Prompt injection from CSV**: sanitization strips suspicious instruction-like payloads before indexing/retrieval.

### RAG technique and context constraints
- Chunking strategy: one normalized narrative per return row.
- Metadata: return ID, product, category, country, version.
- Filtering: optional metadata filter in vector search.
- Context limit: top-k retrieval (default 3-5), short snippets only.
- Versioning: re-index with timestamped version on each ingestion/write refresh.

---

## 3) Data Architecture & Knowledge Design

### Storage layout
- **Transaction database (SQLite)**
  - normalized return records
  - dedupe and write auditability
- **Vector database (local TF-IDF store)**
  - searchable semantic text chunks + metadata
- **Object storage (filesystem)**
  - source CSVs
  - generated Excel reports

### High-level schema (`returns` table)
- keys: `return_id` (PK), unique composite for dedupe
- core fields: `order_id`, `product_name`, `category`, `brand`, `unit_price`, `quantity`, dates
- reason fields: `reason_text`, `reason_code`, `warranty_claim`
- workflow fields: `refund_status`, `support_language`, `agent_notes`

### Data quality rules
- Required fields enforced via NOT NULL and write parser defaults.
- Validation: price > 0 for refund confirmation; typed numeric/date fields.
- Normalization: uppercase currency/country, reason code normalization.
- Deduplication: composite uniqueness + pre-insert duplicate check.

### Update flow after new return
1. Parse/validate NL payload.
2. Write to SQLite.
3. Rebuild/re-version RAG index from current transactional dataset.
4. Expose deterministic confirmation with new return ID.

---

## 4) Analytics & Forecasting Design

### Predictions supported
- **Daily return volume forecast** for next N days (default 30).
- Also supports category-level analytics in reporting views.

### Forecast definition
- Horizon: configurable (`forecast ... 30 day` etc.).
- Granularity: daily.
- Target variable: count of returns per day.
- Metric: MAE on in-sample historical fit.

### Data cleaning and features
- Parse `return_date` to datetime.
- Fill missing dates in sequence with zero volume.
- Feature engineering: monotonic time index `t`.

### Model choice and justification
- Baseline **LinearRegression** for transparency, speed, and deterministic behavior.
- Easy to explain to operations teams and sufficient for prototype stage.
- Upgrade path: tree-based models, Prophet, or hybrid with seasonality/events.

### Insight delivery
- Chat response includes count, financial exposure, likely defect driver.
- Dashboard shows downloadable Excel report and forecast chart/table.

---

## 5) Deployment Architecture & Reliability

### Services
- Streamlit UI
- Python coordinator API layer (in-process)
- Retrieval/Report/Forecast agent modules
- SQLite DB, vector store files, report storage
- Optional workers/schedulers (future: periodic retraining/report jobs)

### Observability
- Chat/audit log in UI
- Tool usage metadata in audit entries
- Extendable points for logs/metrics/traces and LLM/token-cost accounting

### Reliability controls
- Idempotent dedupe on writes
- Input validation guardrails
- Deterministic local retrieval and forecast fallback
- Graceful responses when no data is available
- Production recommendations: retries, timeouts, circuit breakers, rate limiting

### Security controls
- Secrets management (production: vault/KMS)
- Encryption at rest/in transit (production deployment)
- Data retention policy for CSV/report artifacts

---

## Section B — Coding Assignment Coverage

✅ Retrieval Agent (read/write): CSV ingestion, NL return insert, DB storage, refund confirmation

✅ Report Agent: NL questions, insights, downloadable Excel report

✅ Forecast Agent: daily return volume prediction + summary metric

✅ Demo UI: ChatGPT-like Streamlit chat interface

✅ Dataset attached: `data/training_returns.csv`

---

## Run Instructions

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

Open `http://localhost:8501`.

Suggested demo steps:
1. Click **Bootstrap with training dataset**.
2. Ask: `How many iPhones were returned in the last 2 weeks?`
3. Ask: `Forecast daily return volume for next 30 days`.
4. Add return:
   `return product=Apple TV 4K, order id=O9999, customer id=C123, store id=SF01, country=US, channel=online, category=Streaming, brand=Apple, price=179, currency=USD, quantity=1, return date=2026-01-12, purchase date=2026-01-01, reason=remote not working, reason code=DEFECT_REMOTE, warranty=1, refund status=pending, language=en, notes=customer asks refund`

---

## AI Tool Usage Disclosure

AI assistance was used to accelerate drafting and implementation:
- **Design drafting**: initial architecture decomposition and guardrail checklist.
- **Code scaffolding**: generation of starter module structure/classes.
- **Documentation**: formatting and coverage validation against assignment checklist.

All generated outputs were manually reviewed and edited for correctness, consistency, and local execution.

