from __future__ import annotations

import click
import httpx

from agentforge.config import settings
from agentforge.tools.ingest_corpus import ingest_corpus_command
from agentforge.tools.run_redteam import run_redteam_command
from agentforge.tools.seed_synthetic_db import seed_synthetic_command


@click.group()
def main() -> None:
    """AgentForge operator CLI."""


@click.command("task-replay")
@click.argument("task_id")
@click.option("--api-url", default=settings.agentforge_api_url, show_default=True)
@click.option("--api-key", default=settings.agentforge_api_key, show_default=False)
def task_replay_command(task_id: str, api_url: str, api_key: str) -> None:
    """Replay a previously failed AgentForge task."""

    response = httpx.post(
        f"{api_url.rstrip('/')}/api/v1/tasks/{task_id}/replay",
        headers={"X-API-Key": api_key},
        json={},
        timeout=30.0,
    )
    response.raise_for_status()
    click.echo(response.text)


main.add_command(seed_synthetic_command)
main.add_command(ingest_corpus_command)
main.add_command(run_redteam_command)
main.add_command(task_replay_command)


if __name__ == "__main__":
    main()
