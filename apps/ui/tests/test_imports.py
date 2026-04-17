from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
UI_SRC = ROOT / "apps" / "ui" / "src"
PAGES_DIR = UI_SRC / "agentforge_ui" / "pages"


def load_module(path: Path, module_name: str) -> None:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def test_streamlit_imports_only() -> None:
    sys.path.insert(0, str(UI_SRC))
    __import__("agentforge_ui.app")
    __import__("agentforge_ui.api_client")
    for path in sorted(PAGES_DIR.glob("*.py")):
        load_module(path, f"streamlit_page_{path.stem}")
