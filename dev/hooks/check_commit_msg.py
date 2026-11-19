"""Check that a commit subject follows the repo's conventional format.

Runs as a local pre-commit hook (commit-msg stage, see
.pre-commit-config.yaml). The subject must be `type(scope): subject`,
`type: subject`, or `type!: subject` with type one of feat fix docs chore
refactor test perf build ci style revert and a lowercase `[a-z0-9-]`
scope. `Merge ...`, `Revert "..."`, and `fixup! ...` subjects are exempt.
"""

import re
import sys

# Mirrors the convention in AGENTS.md; keep the two in sync.
SUBJECT = re.compile(
    r"^(feat|fix|docs|chore|refactor|test|perf|build|ci|style|revert)"
    r"(\([a-z0-9-]+\))?!?: .+"
)


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: check_commit_msg.py <commit-msg-file>", file=sys.stderr)
        return 1
    with open(argv[0], encoding="utf-8") as handle:
        subject = handle.readline().rstrip("\r\n")
    if subject.startswith(("Merge ", 'Revert "', "fixup! ")):
        return 0
    if SUBJECT.match(subject):
        return 0
    print(
        f"commit subject not allowed: {subject!r}\n"
        "expected 'type(scope): subject' (type: feat fix docs chore "
        "refactor test perf build ci style revert; scope lowercase letters, "
        "digits, dashes); Merge/Revert/fixup! subjects are exempt",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
