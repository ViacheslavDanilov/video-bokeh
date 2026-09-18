"""The A2B bridge walks directories. It must not drag a 2.5 GB tensor library along."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]


def test_bridge_imports_without_torch() -> None:
    code = (
        "import sys\n"
        "import data.prepare_any_to_bokeh\n"
        "sys.exit(1 if 'torch' in sys.modules else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_BACKEND,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"torch was imported by the bridge\n{result.stdout}{result.stderr}"
    )
