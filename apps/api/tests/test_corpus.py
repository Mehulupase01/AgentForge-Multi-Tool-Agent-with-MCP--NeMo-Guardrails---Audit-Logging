from __future__ import annotations

import sqlite3
from pathlib import Path

from click.testing import CliRunner

from agentforge.config import settings
from agentforge.services.corpus_service import CorpusService
from agentforge.tools.cli import main as cli_main
from agentforge.tools.generate_corpus import generate_corpus


def test_seed_creates_synthetic_db(tmp_path: Path) -> None:
    output_path = tmp_path / "synthetic.sqlite"
    runner = CliRunner()

    result = runner.invoke(cli_main, ["seed-synthetic", "--output", str(output_path)])

    assert result.exit_code == 0
    assert output_path.exists()

    connection = sqlite3.connect(output_path)
    try:
        employee_count = connection.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        project_count = connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        assignment_count = connection.execute("SELECT COUNT(*) FROM project_assignments").fetchone()[0]
    finally:
        connection.close()

    assert employee_count == 200
    assert project_count == 30
    assert assignment_count == 600


def test_corpus_generator_produces_53_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "corpus"

    written = generate_corpus(output_dir)

    assert len(written) == 53
    assert (output_dir / "README.md").exists()
    assert len(list(output_dir.glob("*.md"))) == 54
    assert all(len(path.read_text(encoding="utf-8").split()) >= 200 for path in written)


async def test_corpus_reindex_idempotent(db_session, monkeypatch, tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    generate_corpus(corpus_dir)
    monkeypatch.setattr(settings, "corpus_path", str(corpus_dir))
    service = CorpusService()

    first = await service.reindex(db_session)
    second = await service.reindex(db_session)

    assert first.indexed == 53
    assert first.skipped_unchanged == 0
    assert second.indexed == 0
    assert second.skipped_unchanged == 53


async def test_corpus_reindex_detects_change(db_session, monkeypatch, tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    written = generate_corpus(corpus_dir)
    monkeypatch.setattr(settings, "corpus_path", str(corpus_dir))
    service = CorpusService()

    await service.reindex(db_session)
    target = written[0]
    target.write_text(
        target.read_text(encoding="utf-8") + "\nA deterministic appendix for change detection.\n",
        encoding="utf-8",
    )

    result = await service.reindex(db_session)

    assert result.indexed == 1
    assert result.skipped_unchanged == 52


async def test_corpus_documents_endpoint_paginates(client, db_session, monkeypatch, tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    generate_corpus(corpus_dir)
    monkeypatch.setattr(settings, "corpus_path", str(corpus_dir))
    service = CorpusService()
    await service.reindex(db_session)

    response = await client.get("/api/v1/corpus/documents", params={"page": 2, "per_page": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"] == {"page": 2, "per_page": 10, "total": 53}
    assert len(payload["data"]) == 10
