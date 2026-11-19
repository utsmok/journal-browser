"""Served-row shaping shared by the search paths: the SQL alias `twoyr`
renames to the API field `twoyr_mean_citedness` and the internal ranking
key drops before rows reach a response model."""

from typing import Any


def rename_twoyr(item: dict[str, Any]) -> dict[str, Any]:
    """Rename the SQL alias twoyr (float or NULL) and drop the internal
    rank key; the dict is modified in place and returned."""
    item["twoyr_mean_citedness"] = (
        float(item.pop("twoyr")) if item.get("twoyr") is not None else None
    )
    item.pop("rank", None)
    return item
