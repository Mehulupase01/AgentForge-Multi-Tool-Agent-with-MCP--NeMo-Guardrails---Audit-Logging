from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest
import pytest_asyncio
import uvicorn
from httpx import ASGITransport, AsyncClient
from sse_starlette.sse import AppStatus

from agentforge.database import get_db
from agentforge.guardrails.runner import GuardrailsRunner, get_guardrails_runner
from agentforge.guardrails.tool_allowlist import ToolAllowlist
from agentforge.main import create_app
from agentforge.routers.tasks import orchestrator_dependency
from agentforge.services.agent_orchestrator import AgentOrchestrator
from agentforge.services.approval_service import ApprovalService
from agentforge.services.audit_service import AuditService
from agentforge.services.task_event_bus import TaskEventBus, get_task_event_bus
from tests.test_agent_orchestrator import (
    FakeMCPPool,
    MockLLMProvider,
    create_session_and_task,
    wait_for_status,
    write_allowlist,
)


ROOT = Path(__file__).resolve().parents[3]
UI_SRC = ROOT / "apps" / "ui" / "src"
CLI_SRC = ROOT / "apps" / "cli" / "src"
if str(UI_SRC) not in sys.path:
    sys.path.insert(0, str(UI_SRC))
if str(CLI_SRC) not in sys.path:
    sys.path.insert(0, str(CLI_SRC))

from agentforge_cli.main import parse_sse_lines as parse_cli_sse  # noqa: E402
from agentforge_ui.api_client import parse_sse_lines as parse_ui_sse  # noqa: E402


pytestmark = pytest.mark.asyncio


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def run_server(app, *, host: str = "127.0.0.1", port: int) -> Iterator[str]:
    AppStatus.should_exit = False
    AppStatus.should_exit_event = None
    config = uvicorn.Config(app, host=host, port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("Test server did not start in time")
    try:
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        AppStatus.should_exit = False
        AppStatus.should_exit_event = None


@pytest_asyncio.fixture(autouse=True)
async def reset_sse_app_status():
    AppStatus.should_exit = False
    AppStatus.should_exit_event = None
    yield
    AppStatus.should_exit = False
    AppStatus.should_exit_event = None


@pytest_asyncio.fixture
async def sse_orchestrator(session_factory, tmp_path: Path) -> AgentOrchestrator:
    event_bus = TaskEventBus()
    orchestrator = AgentOrchestrator(
        session_factory=session_factory,
        mcp_pool=FakeMCPPool(),
        llm_provider=MockLLMProvider(),
        event_bus=event_bus,
        guardrails_runner=GuardrailsRunner(tool_allowlist=ToolAllowlist(write_allowlist(tmp_path / "sse_allowlist.yml"))),
        approval_service=ApprovalService(),
        audit_service=AuditService(),
        checkpoint_path=str(tmp_path / "sse_checkpoints.sqlite"),
    )
    orchestrator._event_bus = event_bus  # type: ignore[attr-defined]
    return orchestrator


@pytest_asyncio.fixture
async def sse_app(session_factory, sse_orchestrator: AgentOrchestrator):
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[orchestrator_dependency] = lambda: sse_orchestrator
    app.dependency_overrides[get_task_event_bus] = lambda: sse_orchestrator._event_bus  # type: ignore[attr-defined]
    app.dependency_overrides[get_guardrails_runner] = lambda: sse_orchestrator._guardrails_runner  # type: ignore[attr-defined]
    yield app
    await sse_orchestrator.close()
    app.dependency_overrides.clear()


async def test_sse_stream_is_compatible_with_ui_and_cli_parsers(sse_app) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=sse_app),
        base_url="http://test",
        headers={"X-API-Key": "dev-key"},
    ) as client:
        _, task_id = await create_session_and_task(client, "Find transformer content and summarize it.")
        await wait_for_status(client, task_id, "completed")

        async with client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as response:
            assert response.status_code == 200
            lines = [line async for line in response.aiter_lines()]

    ui_events = list(parse_ui_sse(lines))
    cli_events = list(parse_cli_sse(lines))

    assert ui_events
    assert cli_events
    assert [item["event"] for item in ui_events] == [item["event"] for item in cli_events]
    assert all(isinstance(item["data"], dict) for item in ui_events)
    assert ui_events[-1]["event"] == "task_completed"


async def test_cli_task_run_emits_stream(session_factory, sse_app) -> None:
    port = free_port()
    python_exe = ROOT / ".venv" / "Scripts" / "python.exe"
    cli_pythonpath = os.pathsep.join([str(CLI_SRC)])

    with run_server(sse_app, port=port) as base_url:
        result = subprocess.run(
            [str(python_exe), "-m", "agentforge_cli.main", "task", "run", "Find transformer content and summarize it."],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "AGENTFORGE_API_URL": base_url,
                "AGENTFORGE_API_KEY": "dev-key",
                "PYTHONPATH": cli_pythonpath,
            },
            check=False,
        )

    assert result.returncode == 0, result.stderr
    assert "event=step" in result.stdout
    assert "summary=completed" in result.stdout
