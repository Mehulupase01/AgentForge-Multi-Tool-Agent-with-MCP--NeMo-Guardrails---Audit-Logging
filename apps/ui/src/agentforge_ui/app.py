from __future__ import annotations

import pandas as pd
import streamlit as st

from agentforge_ui.api_client import AgentForgeClient


@st.cache_resource
def get_client() -> AgentForgeClient:
    return AgentForgeClient.from_env()


def render_home() -> None:
    st.set_page_config(page_title="AgentForge", layout="wide")
    st.title("AgentForge Control Plane")
    st.caption("Operator view for health, sessions, approvals, audit, and red-team execution.")

    client = get_client()

    left, right = st.columns([1, 1])
    with left:
        st.subheader("Readiness")
        try:
            readiness = client.get_readiness()
            st.json(readiness)
        except Exception as exc:  # pragma: no cover - streamlit display path
            st.error(f"Failed to load readiness: {exc}")

    with right:
        st.subheader("Recent Sessions")
        try:
            sessions = client.list_sessions(per_page=10)
            frame = pd.DataFrame(sessions["data"])
            if frame.empty:
                st.info("No sessions yet.")
            else:
                st.dataframe(frame, use_container_width=True, hide_index=True)
        except Exception as exc:  # pragma: no cover - streamlit display path
            st.error(f"Failed to load sessions: {exc}")

    st.markdown(
        """
        Use the pages in the sidebar to:
        - submit and stream agent tasks
        - review and decide approvals
        - inspect the audit trail and integrity state
        - trigger and inspect red-team runs
        """
    )


render_home()
