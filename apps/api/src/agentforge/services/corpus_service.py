from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.config import settings
from agentforge.models.corpus import CorpusDocument
from agentforge.schemas.common import Envelope, Pagination
from agentforge.schemas.corpus import CorpusDocumentResponse, ReindexResponse

REPO_ROOT = Path(__file__).resolve().parents[5]


@dataclass(slots=True)
class ParsedCorpusDocument:
    filename: str
    title: str
    tokens: int
    content_hash: str


class CorpusService:
    def resolve_path(self, raw_path: str | Path | None = None) -> Path:
        path = Path(raw_path or settings.corpus_path)
        return path if path.is_absolute() else REPO_ROOT / path

    def list_markdown_files(self, raw_path: str | Path | None = None) -> list[Path]:
        corpus_dir = self.resolve_path(raw_path)
        if not corpus_dir.exists():
            raise FileNotFoundError(f"Corpus directory does not exist: {corpus_dir}")

        return sorted(
            path
            for path in corpus_dir.glob("*.md")
            if path.name.lower() != "readme.md"
        )

    def parse_document(self, path: Path) -> ParsedCorpusDocument:
        raw = path.read_text(encoding="utf-8")
        metadata, body = self._split_frontmatter(raw)
        title = str(metadata.get("title") or self._fallback_title(path, body))
        content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        tokens = len(body.split())

        return ParsedCorpusDocument(
            filename=path.name,
            title=title,
            tokens=tokens,
            content_hash=content_hash,
        )

    def _split_frontmatter(self, raw: str) -> tuple[dict, str]:
        if not raw.startswith("---\n"):
            return {}, raw

        parts = raw.split("\n---\n", 1)
        if len(parts) != 2:
            return {}, raw

        metadata_raw = parts[0][4:]
        body = parts[1]
        metadata = yaml.safe_load(metadata_raw) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        return metadata, body

    def _fallback_title(self, path: Path, body: str) -> str:
        for line in body.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return path.stem.replace("-", " ").title()

    async def reindex(
        self,
        session: AsyncSession,
        *,
        raw_path: str | Path | None = None,
    ) -> ReindexResponse:
        started = time.perf_counter()
        indexed = 0
        skipped = 0

        for file_path in self.list_markdown_files(raw_path):
            parsed = self.parse_document(file_path)
            existing = (
                await session.execute(
                    select(CorpusDocument).where(CorpusDocument.filename == parsed.filename),
                )
            ).scalar_one_or_none()

            if existing is not None and existing.content_hash == parsed.content_hash:
                skipped += 1
                continue

            if existing is None:
                session.add(
                    CorpusDocument(
                        filename=parsed.filename,
                        title=parsed.title,
                        tokens=parsed.tokens,
                        content_hash=parsed.content_hash,
                        ingested_at=datetime.now(UTC),
                    ),
                )
            else:
                existing.title = parsed.title
                existing.tokens = parsed.tokens
                existing.content_hash = parsed.content_hash
                existing.ingested_at = datetime.now(UTC)

            indexed += 1

        await session.commit()

        return ReindexResponse(
            indexed=indexed,
            skipped_unchanged=skipped,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    async def list_documents(
        self,
        session: AsyncSession,
        *,
        page: int,
        per_page: int,
    ) -> Envelope[CorpusDocumentResponse]:
        total = int((await session.execute(select(func.count()).select_from(CorpusDocument))).scalar_one())
        documents = list(
            (
                await session.execute(
                    select(CorpusDocument)
                    .order_by(CorpusDocument.filename.asc())
                    .offset((page - 1) * per_page)
                    .limit(per_page),
                )
            ).scalars()
        )

        return Envelope(
            data=[CorpusDocumentResponse.model_validate(document) for document in documents],
            meta=Pagination(page=page, per_page=per_page, total=total),
        )
