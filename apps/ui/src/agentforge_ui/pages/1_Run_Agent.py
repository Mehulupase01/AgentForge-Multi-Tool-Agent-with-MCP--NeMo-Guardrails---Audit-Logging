from __future__ import annotations

import pandas as pd
import streamlit as st

from agentforge_ui.api_client import AgentForgeClient


@st.cache_resource
def get_client() -> AgentForgeClient:
    return AgentForgeClient.from_env()


def render_page() -> None:
    st.title("Run Agent")
    st.caption("Submit a prompt, then watch the step-by-step event stream in real time.")

    client = get_client()
    prompt = st.text_area("Prompt", height=140, placeholder="Describe the task you want the agent to perform.")

    if "run_agent_events" not in st.session_state:
        st.session_state["run_agent_events"] = []

    if st.button("Start Task", type="primary", use_container_width=True):
        if not prompt.strip():
            st.warning("Enter a prompt before starting a task.")
        else:
            st.session_state["run_agent_events"] = []
            try:
                session = client.create_session()
                task = client.create_task(session["id"], user_prompt=prompt)
                st.session_state["run_agent_session_id"] = session["id"]
                st.session_state["run_agent_task_id"] = task["id"]

                timeline = st.empty()
                notices = st.empty()

                for event in client.stream_task(task["id"]):
                    st.session_state["run_agent_events"].append(event)
                    rows = []
                    for item in st.session_state["run_agent_events"]:
                        data = item["data"]
                        rows.append(
                            {
                                "event": item["event"],
                                "step_id": data.get("step_id"),
                                "description": data.get("description"),
                                "status": data.get("status"),
                                "error": data.get("error"),
                            }
                        )
                    timeline.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                    if event["event"] == "approval_requested":
                        notices.warning("Task paused for approval. Switch to the Approvals page to review it.")
                    if event["event"] == "task_completed":
                        notices.success("Task completed successfully.")
                    if event["event"] in {"task_failed", "task_rejected"}:
                        notices.error(data.get("error", "Task did not complete successfully."))
            except Exception as exc:  # pragma: no cover - streamlit display path
                st.error(f"Unable to run task: {exc}")

    task_id = st.session_state.get("run_agent_task_id")
    if task_id:
        st.subheader("Current Task")
        st.code(task_id)


render_page()
