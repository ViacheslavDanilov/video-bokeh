"""Per-asset diagnostic metadata sidecar (``meta.json``).

Stores how each library asset was produced (estimator, source, propagation
params) and raw-depth statistics, so depth artifacts can be diagnosed without
re-running Stage A. Purely diagnostic: Stage B never reads it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_META_NAME = "meta.json"


def write_asset_metadata(asset_dir: Path, meta: dict[str, Any]) -> None:
    """Write ``meta`` as pretty JSON to ``<asset_dir>/meta.json``."""
    asset_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(meta, indent=2, sort_keys=True, ensure_ascii=False)
    (asset_dir / _META_NAME).write_text(text + "\n", encoding="utf-8")


def read_asset_metadata(asset_dir: Path) -> dict[str, Any] | None:
    """Read ``<asset_dir>/meta.json``; return None if it does not exist."""
    path = asset_dir / _META_NAME
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
