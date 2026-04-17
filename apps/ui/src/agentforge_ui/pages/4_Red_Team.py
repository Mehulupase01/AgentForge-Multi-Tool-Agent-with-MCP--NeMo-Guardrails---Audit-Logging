from __future__ import annotations

import pandas as pd
import streamlit as st

from agentforge_ui.api_client import AgentForgeClient


@st.cache_resource
def get_client() -> AgentForgeClient:
    return AgentForgeClient.from_env()


def render_page() -> None:
    st.title("Red Team")
    st.caption("Trigger a red-team run and inspect the most recent category-level breakdown.")

    client = get_client()

    if st.button("Start Red-Team Run", type="primary", use_container_width=True):
        try:
            run = client.start_redteam_run()
            st.success(f"Started red-team run {run['id']}. Refresh to see progress.")
        except Exception as exc:  # pragma: no cover - streamlit display path
            st.error(f"Unable to start red-team run: {exc}")

    try:
        runs = client.list_redteam_runs(per_page=10)["data"]
    except Exception as exc:  # pragma: no cover - streamlit display path
        st.error(f"Unable to load red-team runs: {exc}")
        return

    if not runs:
        st.info("No red-team runs recorded yet.")
        return

    latest = runs[0]
    st.subheader("Latest Run")
    st.json(latest)

    try:
        results = client.list_redteam_results(latest["id"], per_page=200)["data"]
        frame = pd.DataFrame(results)
        if not frame.empty:
            summary = (
                frame.groupby(["category", "passed"])
                .size()
                .reset_index(name="count")
                .pivot(index="category", columns="passed", values="count")
                .fillna(0)
            )
            st.bar_chart(summary)
            st.dataframe(frame, use_container_width=True, hide_index=True)
    except Exception as exc:  # pragma: no cover - streamlit display path
        st.error(f"Unable to load red-team results: {exc}")


render_page()
