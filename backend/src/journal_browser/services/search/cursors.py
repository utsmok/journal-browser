import base64
import json
from typing import Any


def parse_cursor(cursor: str | None) -> tuple[str, str] | None:
    """Decodes a page cursor; raises ValueError when malformed (router → 400)."""
    if not cursor:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        v, k = data["v"], data["k"]
        if not isinstance(v, (str, int, float)) or not isinstance(k, str):
            raise KeyError("bad shape")
        return str(v), k
    except Exception as exc:
        raise ValueError(f"malformed cursor: {cursor[:32]!r}") from exc


def encode_cursor(value: Any, issn_l: str) -> str:
    raw = json.dumps({"v": value, "k": issn_l}, default=str)
    return base64.urlsafe_b64encode(raw.encode()).decode()
