from __future__ import annotations

import pandas as pd
import streamlit as st

from agentforge_ui.api_client import AgentForgeClient


@st.cache_resource
def get_client() -> AgentForgeClient:
    return AgentForgeClient.from_env()


def render_page() -> None:
    st.title("Audit Log")
    st.caption("Browse recorded audit events and verify the hash chain integrity.")

    client = get_client()
    filters = st.columns(3)
    with filters[0]:
        event_types_raw = st.text_input("Event types", placeholder="guardrail.input_blocked,task.completed")
    with filters[1]:
        session_id = st.text_input("Session ID", placeholder="optional")
    with filters[2]:
        per_page = st.number_input("Rows", min_value=10, max_value=200, value=50, step=10)

    if st.button("Verify Integrity", use_container_width=True):
        try:
            integrity = client.verify_audit()
            if integrity["verified"]:
                st.success(f"Audit chain verified across {integrity['events_checked']} events.")
            else:
                st.error(str(integrity))
        except Exception as exc:  # pragma: no cover - streamlit display path
            st.error(f"Integrity verification failed: {exc}")

    try:
        events = client.list_audit_events(
            per_page=int(per_page),
            event_types=[item.strip() for item in event_types_raw.split(",") if item.strip()] or None,
            session_id=session_id or None,
        )["data"]
        frame = pd.DataFrame(events)
        if frame.empty:
            st.info("No audit events matched the current filters.")
        else:
            st.dataframe(frame, use_container_width=True, hide_index=True)
    except Exception as exc:  # pragma: no cover - streamlit display path
        st.error(f"Unable to load audit events: {exc}")


render_page()
