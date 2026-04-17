from __future__ import annotations

import os
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

DEFAULT_CORPUS_PATH = Path(os.getenv("CORPUS_PATH", "/data/corpus"))


def _read_document(path: Path) -> tuple[str, str]:
    content = path.read_text(encoding="utf-8")
    title = path.stem.replace("-", " ").title()
    for line in content.splitlines():
        if line.startswith("title: "):
            title = line.split(":", 1)[1].strip()
            break
        if line.startswith("# "):
            title = line[2:].strip()
            break
    return title, content


def _normalize(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if token]


def _term_variants(terms: list[str]) -> set[str]:
    variants: set[str] = set()
    for term in terms:
        variants.add(term)
        if len(term) > 3 and term.endswith("s"):
            variants.add(term[:-1])
        elif len(term) > 3:
            variants.add(f"{term}s")
    return variants


def build_server(corpus_path: Path | None = None) -> FastMCP:
    search_root = corpus_path or DEFAULT_CORPUS_PATH
    mcp = FastMCP(
        "file_search",
        json_response=True,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8101")),
        streamable_http_path="/mcp",
    )

    @mcp.tool()
    def search_corpus(query: str, limit: int = 5) -> list[dict]:
        """Search the markdown corpus using simple keyword scoring."""
        terms = _term_variants(_normalize(query))
        results: list[dict] = []
        for path in sorted(search_root.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            title, content = _read_document(path)
            normalized = _normalize(content)
            score = sum(normalized.count(term) for term in terms)
            if score == 0:
                continue
            snippet = " ".join(content.split())[:220]
            results.append(
                {
                    "filename": path.name,
                    "snippet": snippet,
                    "score": score,
                },
            )

        results.sort(key=lambda item: (-item["score"], item["filename"]))
        return results[: max(1, min(limit, 20))]

    @mcp.tool()
    def read_document(filename: str) -> dict:
        """Read one markdown document from the corpus."""
        target = (search_root / filename).resolve()
        if target.parent != search_root.resolve() or not target.exists():
            raise FileNotFoundError(filename)
        title, content = _read_document(target)
        return {
            "filename": target.name,
            "title": title,
            "content": content,
        }

    return mcp


def main() -> None:
    build_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()
