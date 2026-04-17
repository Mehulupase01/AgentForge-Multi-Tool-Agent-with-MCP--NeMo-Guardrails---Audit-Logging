from __future__ import annotations

import pandas as pd
import streamlit as st

from agentforge_ui.api_client import AgentForgeClient


@st.cache_resource
def get_client() -> AgentForgeClient:
    return AgentForgeClient.from_env()


def render_page() -> None:
    st.title("Approvals")
    st.caption("Review pending approval gates and record a decision.")

    client = get_client()
    decision_filter = st.selectbox("Filter", ["pending", "approved", "rejected"], index=0)

    try:
        approvals = client.list_approvals(decision=decision_filter, per_page=50)["data"]
    except Exception as exc:  # pragma: no cover - streamlit display path
        st.error(f"Unable to load approvals: {exc}")
        return

    if not approvals:
        st.info("No approvals match the current filter.")
        return

    frame = pd.DataFrame(approvals)
    st.dataframe(frame, use_container_width=True, hide_index=True)

    selected_id = st.selectbox("Approval ID", options=[item["id"] for item in approvals])
    selected = next(item for item in approvals if item["id"] == selected_id)

    st.json(selected)

    rationale = st.text_area("Rationale", placeholder="Record why this approval should be approved or rejected.")
    approve_col, reject_col = st.columns(2)

    with approve_col:
        if st.button("Approve", type="primary", use_container_width=True):
            try:
                client.decide_approval(selected_id, decision="approved", rationale=rationale or None)
                st.success("Approval recorded as approved.")
            except Exception as exc:  # pragma: no cover - streamlit display path
                st.error(f"Approval failed: {exc}")

    with reject_col:
        if st.button("Reject", use_container_width=True):
            try:
                client.decide_approval(selected_id, decision="rejected", rationale=rationale or None)
                st.success("Approval recorded as rejected.")
            except Exception as exc:  # pragma: no cover - streamlit display path
                st.error(f"Rejection failed: {exc}")


render_page()
