"""Serving the repo's markdown docs (docs/) through the API.

Read-only discovery + a dependency-free block parser: the frontend renders
individual blocks so the admin can override any single one (doc_edits table;
see routers/docs.py for the public GETs and routers/admin.py for the edit
endpoints). A missing/unreadable docs dir degrades to an empty list / 404 —
docs are a nice-to-have, never a hard dependency.
"""

import os
import re
from pathlib import Path

_HEADING = re.compile(r"^(#{1,6}) ")
_LIST = re.compile(r"^(\s*)([-*]|\d+\.) ")


def docs_root() -> Path | None:
    """Docs directory: JB_DOCS_DIR if set, else <repo>/docs next to this
    package (src/journal_browser/docs.py → parents[3] is the repo root)."""
    env = os.environ.get("JB_DOCS_DIR")
    if env:
        p = Path(env)
        return p if p.is_dir() else None
    repo_docs = Path(__file__).resolve().parents[3] / "docs"
    return repo_docs if repo_docs.is_dir() else None


def _title(md: str, slug: str) -> str:
    for line in md.splitlines():
        m = _HEADING.match(line)
        if m and len(m.group(1)) == 1:
            return _HEADING.sub("", line, count=1).strip()
    return slug


def _docs_in(root: Path, subdir: str) -> list[Path]:
    return sorted((root / subdir).glob("*.md"))


def list_docs() -> list[dict]:
    """Metadata for every served doc, in list order (OVERVIEW, then the
    pipeline traces alphabetically, then pitch docs)."""
    root = docs_root()
    if root is None:
        return []
    out: list[dict] = []
    for order, path in enumerate(_docs_in(root, "data-pipeline") + _docs_in(root, "pitch")):
        stem = path.stem
        if path.parent.name == "data-pipeline" and stem == "OVERVIEW":
            group, order = "overview", 0
        elif path.parent.name == "data-pipeline":
            group = "sources"
        else:
            group = "pitch"
        try:
            title = _title(path.read_text(encoding="utf-8"), stem)
        except OSError:
            continue
        out.append({"slug": stem.lower(), "title": title, "group": group, "order": order})
    return out


def read_doc(slug: str) -> dict | None:
    """One doc's metadata + raw markdown, or None if the slug is unknown.
    Slugs are lower-cased file stems; lookup is case-insensitive so
    /docs/overview resolves even though the file is OVERVIEW.md."""
    slug = slug.lower()
    for meta in list_docs():
        if meta["slug"] != slug:
            continue
        root = docs_root()
        assert root is not None  # list_docs found the slug, so the root exists
        for subdir in ("data-pipeline", "pitch"):
            for path in (root / subdir).glob("*.md"):
                if path.stem.lower() == slug:
                    meta["markdown"] = path.read_text(encoding="utf-8")
                    return meta
    return None


def _classify(first_line: str) -> tuple[str, int | None, str | None]:
    if first_line.lstrip().startswith("```"):
        return "code", None, first_line.lstrip()[3:].strip() or None
    m = _HEADING.match(first_line)
    if m:
        return "heading", len(m.group(1)), None
    if first_line.lstrip().startswith("|"):
        return "table", None, None
    if _LIST.match(first_line):
        return "list", None, None
    if first_line.lstrip().startswith(">"):
        return "quote", None, None
    if first_line.strip() == "---":
        return "hr", None, None
    return "paragraph", None, None


def parse_blocks(md: str) -> list[dict]:
    """Split markdown into renderable blocks. Blocks are separated by blank
    lines, except inside ``` fences, where blank lines stay in-block. Each
    block keeps its raw markdown text (fence markers included)."""
    blocks: list[dict] = []
    current: list[str] = []
    fence = False

    def flush() -> None:
        if current:
            btype, level, lang = _classify(current[0])
            block = {"type": btype, "text": "\n".join(current)}
            if level is not None:
                block["level"] = level
            if lang is not None:
                block["lang"] = lang
            blocks.append(block)
            current.clear()

    for line in md.splitlines():
        if fence:
            current.append(line)
            if line.lstrip().startswith("```"):
                fence = False
                flush()
        elif line.lstrip().startswith("```"):
            flush()
            current.append(line)
            fence = True
        elif not line.strip():
            flush()
        else:
            current.append(line)
    flush()
    return blocks
