from __future__ import annotations

import asyncio

import click

from agentforge.database import dispose_engine, get_session_factory, init_engine
from agentforge.services.corpus_service import CorpusService


async def ingest_corpus() -> dict[str, int]:
    init_engine()
    session_factory = get_session_factory()
    service = CorpusService()

    async with session_factory() as session:
        result = await service.reindex(session)

    await dispose_engine()
    return result.model_dump()


@click.command("ingest-corpus")
def ingest_corpus_command() -> None:
    result = asyncio.run(ingest_corpus())
    click.echo(
        "Indexed corpus documents "
        f"(indexed={result['indexed']}, skipped_unchanged={result['skipped_unchanged']}, duration_ms={result['duration_ms']})",
    )


if __name__ == "__main__":
    ingest_corpus_command()
