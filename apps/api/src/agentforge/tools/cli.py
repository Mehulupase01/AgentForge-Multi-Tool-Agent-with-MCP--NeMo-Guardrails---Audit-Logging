from __future__ import annotations

import click

from agentforge.tools.ingest_corpus import ingest_corpus_command
from agentforge.tools.seed_synthetic_db import seed_synthetic_command


@click.group()
def main() -> None:
    """AgentForge operator CLI."""


main.add_command(seed_synthetic_command)
main.add_command(ingest_corpus_command)


if __name__ == "__main__":
    main()
