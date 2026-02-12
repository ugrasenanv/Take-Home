from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from src.agents import build_system

st.set_page_config(page_title="Returns & Warranty Intelligence", layout="wide")

if "system" not in st.session_state:
    st.session_state.system = build_system()
if "messages" not in st.session_state:
    st.session_state.messages = []
if "audit_log" not in st.session_state:
    st.session_state.audit_log = []

st.title("Returns & Warranty Intelligence Platform (MCP-style)")
st.caption("Coordinator + Retrieval + Report + Forecast agents with local RAG and SQLite.")

with st.sidebar:
    st.subheader("System Controls")
    if st.button("Bootstrap with training dataset"):
        msg = st.session_state.system.retrieval.ingest_csv("data/training_returns.csv")
        st.success(msg)

    st.markdown("### Guardrails")
    st.json(st.session_state.system.guardrails())

    st.markdown("### Tool Contracts")
    st.json(st.session_state.system.tool_contracts())

user_prompt = st.chat_input(
    "Ask analytics, forecast returns, or add a return. Example: return product=Apple TV 4K, order id=O999, ..."
)

if user_prompt:
    st.session_state.messages.append({"role": "user", "content": user_prompt})
    result = st.session_state.system.route(user_prompt)
    ts = datetime.utcnow().isoformat()

    assistant_msg = result.get("message", "No response")
    st.session_state.messages.append({"role": "assistant", "content": assistant_msg})
    st.session_state.audit_log.append(
        {
            "ts": ts,
            "input": user_prompt,
            "output_type": result.get("type"),
            "tools": [result.get("type")],
            "meta": {k: str(v) for k, v in result.items() if k not in ["message"]},
        }
    )

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.write(m["content"])

if st.session_state.messages:
    latest = st.session_state.messages[-1]["content"]
    st.markdown("---")
    st.subheader("Latest Result")
    st.write(latest)

last_result = None
if st.session_state.audit_log:
    # find latest full result by replay route from latest user input (lightweight demo)
    try:
        last_user = [m for m in st.session_state.messages if m["role"] == "user"][-1]["content"]
        last_result = st.session_state.system.route(last_user)
    except Exception:
        last_result = None

if last_result and last_result.get("type") == "forecast" and isinstance(last_result.get("table"), pd.DataFrame):
    table = last_result["table"]
    st.dataframe(table, use_container_width=True)
    fig = px.line(table, x="return_date", y="predicted_returns", title="Forecast: Daily Return Volume")
    st.plotly_chart(fig, use_container_width=True)

if last_result and last_result.get("report_path"):
    report_path = Path(last_result["report_path"])
    if report_path.exists():
        with open(report_path, "rb") as f:
            st.download_button("Download Excel Report", data=f, file_name=report_path.name)

st.markdown("---")
st.subheader("Audit Trail")
st.code(json.dumps(st.session_state.audit_log[-10:], indent=2), language="json")
