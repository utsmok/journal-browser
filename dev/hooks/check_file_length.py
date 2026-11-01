#!/usr/bin/env python3
"""Pre-commit gate: reject source files that grow past a line budget.

Big files concentrate review risk and defeat targeted diffs; this keeps
single files from becoming dumping grounds. Lockfiles, generated schemas,
committed docs, and migration history are exempt (alembic versions are
never reformatted or reworked by convention).

Usage: check_file_length.py FILE [FILE ...]  (pre-commit passes the
matched staged files).
"""

import sys

MAX_LINES = 2000

#: Never measured: generated artifacts, lockfiles, and binary formats where
#: "lines" is meaningless.
SKIP_SUFFIXES = (
    "package-lock.json",
    "uv.lock",
    "openapi.json",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".gz",
    ".zip",
    ".woff2",
)

#: Generated code, exempt from budgets like it is exempt from hand edits.
GENERATED_FILES = frozenset({"frontend/lib/api-types.ts"})


def is_binary(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            return b"\0" in handle.read(8192)
    except OSError:
        return False


def main(argv: list[str]) -> int:
    offenders: list[tuple[str, int]] = []
    for path in argv:
        if (
            path.endswith(SKIP_SUFFIXES)
            or path.replace("\\", "/") in GENERATED_FILES
            or "/alembic/versions/" in path
            or path.startswith(("droid-wiki/", "docs/"))
        ):
            continue
        if is_binary(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                lines = sum(1 for _ in handle)
        except OSError:
            continue
        if lines > MAX_LINES:
            offenders.append((path, lines))
    for path, lines in offenders:
        print(f"{path}: {lines} lines exceeds the {MAX_LINES}-line budget; split it")
    return 1 if offenders else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
