from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from agentforge_ui.api_client import AgentForgeClient


@st.cache_resource
def get_client() -> AgentForgeClient:
    return AgentForgeClient.from_env()


def render_cost_chart(cost_payload: dict) -> None:
    rows = cost_payload.get("by_agent", [])
    if not rows:
        st.info("No cost records are available for this task yet.")
        return
    frame = pd.DataFrame(rows)
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=frame["role"],
            y=frame["usd"],
            mode="lines+markers",
            name="USD",
        )
    )
    figure.update_layout(
        title="Task Cost by Agent",
        xaxis_title="Agent Role",
        yaxis_title="USD",
        margin=dict(l=20, r=20, t=50, b=20),
    )
    st.plotly_chart(figure, use_container_width=True)


def render_confidence_gauge(confidence_payload: dict) -> None:
    value = confidence_payload.get("task_confidence")
    if value is None:
        st.info("No confidence score is available for this task yet.")
        return
    figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=value,
            title={"text": "Task Confidence"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "#0F766E"},
                "steps": [
                    {"range": [0, 50], "color": "#FEE2E2"},
                    {"range": [50, 80], "color": "#FEF3C7"},
                    {"range": [80, 100], "color": "#DCFCE7"},
                ],
                "threshold": {"line": {"color": "#7F1D1D", "width": 3}, "value": 80},
            },
        )
    )
    figure.update_layout(margin=dict(l=20, r=20, t=50, b=20))
    st.plotly_chart(figure, use_container_width=True)


def render_handoff_sankey(handoff_payload: dict) -> None:
    edges = handoff_payload.get("edges", [])
    if not edges:
        st.info("No multi-agent handoffs have been recorded yet.")
        return

    labels: list[str] = []
    label_index: dict[str, int] = {}

    def index_for(label: str) -> int:
        if label not in label_index:
            label_index[label] = len(labels)
            labels.append(label)
        return label_index[label]

    sources = [index_for(edge["from_role"]) for edge in edges]
    targets = [index_for(edge["to_role"]) for edge in edges]
    values = [edge["count"] for edge in edges]

    figure = go.Figure(
        go.Sankey(
            node={"label": labels, "pad": 16, "thickness": 18},
            link={"source": sources, "target": targets, "value": values},
        )
    )
    figure.update_layout(title_text="Agent Handoffs", margin=dict(l=20, r=20, t=50, b=20))
    st.plotly_chart(figure, use_container_width=True)


def render_page() -> None:
    st.title("AgentOps")
    st.caption("Inspect per-task cost and confidence, then zoom out to the system-wide handoff flow.")

    client = get_client()
    default_task_id = st.session_state.get("run_agent_task_id", "")
    task_id = st.text_input("Task ID", value=default_task_id, placeholder="Paste a task id to inspect observability data.")

    try:
        summary = client.get_observability_summary()
        top = st.columns(4)
        top[0].metric("Tasks", summary["tasks"])
        top[1].metric("Total USD", f"{summary['total_usd']:.6f}")
        top[2].metric("Avg Confidence", f"{summary['avg_confidence']:.1f}")
        top[3].metric("Retry Rate", f"{summary['retry_rate']:.2f}")

        handoffs = client.get_agent_handoffs()
        render_handoff_sankey(handoffs)
    except Exception as exc:  # pragma: no cover - streamlit display path
        st.warning(f"Observability API is unavailable right now: {exc}")
        handoffs = {"edges": []}

    if not task_id.strip():
        st.info("Enter a task id to load the task-specific cost and confidence charts.")
        return

    try:
        task_cost = client.get_task_cost(task_id)
        task_confidence = client.get_task_confidence(task_id)
    except Exception as exc:  # pragma: no cover - streamlit display path
        st.error(f"Unable to load task observability data: {exc}")
        return
    left, right = st.columns(2)
    with left:
        render_cost_chart(task_cost)
    with right:
        render_confidence_gauge(task_confidence)

    steps = task_confidence.get("steps", [])
    if steps:
        st.subheader("Step Confidence")
        st.dataframe(pd.DataFrame(steps), use_container_width=True, hide_index=True)


render_page()
