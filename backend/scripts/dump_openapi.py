"""Dump the FastAPI OpenAPI schema to the repo root openapi.json.

The schema is committed and feeds the frontend typegen (`npm run generate`
in frontend/). Refresh after any API change:

    cd backend && uv run python scripts/dump_openapi.py

Runs offline: the schema is derived from route/response models, no live
server or database needed. Set JB_SKIP_EMBEDDING_WARMUP=1 to skip the
embedding-model preload the app starts on import (CI does this; the schema
never depends on it).
"""

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("JB_SKIP_EMBEDDING_WARMUP", "1")

from journal_browser.main import app

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--out", type=Path, default=ROOT / "openapi.json")
args = parser.parse_args()
out = args.out
out.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
print(f"wrote {out}")
