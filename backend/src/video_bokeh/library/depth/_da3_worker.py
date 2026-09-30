"""Depth Anything 3 worker: runs under its own environment, never imported by video_bokeh.

Started by ``depth_anything_v3.DepthAnything3MonoLarge`` as
``python _da3_worker.py <model id> <device>``, it speaks the protocol in
``video_bokeh.core._worker``: one request per image, ``{"image": path, "output": path}``,
and writes the model's depth map to ``output`` as a float32 ``.npy``.
"""

import json
import os
import sys
import types

# Run as a script, this file's own directory comes first on sys.path, ahead of the
# installed packages. A sibling once shadowed depth_anything_3 exactly that way, when the
# estimator module next to this one still carried that name.
del sys.path[0]

# fd 1 is the protocol's alone. Depth Anything 3 logs to stdout, and native code or a
# child process would write to fd 1 directly, so fd 1 now points at stderr and replies
# go to a duplicate of the original.
reply = os.fdopen(os.dup(1), "w", encoding="utf-8")
os.dup2(2, 1)
sys.stdout = sys.stderr

# The COLMAP export imports pycolmap at module level and uses it only inside its
# functions. pycolmap bundles a second OpenMP runtime, which aborts the process next to
# torch's, and inference never exports to COLMAP.
sys.modules.setdefault("pycolmap", types.ModuleType("pycolmap"))

import numpy as np  # noqa: E402
from depth_anything_3.api import (  # noqa: E402  # ty: ignore[unresolved-import]
    DepthAnything3,
)


def _send(message: dict) -> None:
    reply.write(json.dumps(message) + "\n")
    reply.flush()


def main() -> None:
    model_id, device = sys.argv[1], sys.argv[2]
    model = DepthAnything3.from_pretrained(model_id).to(device)
    _send({"ready": True})
    for line in sys.stdin:
        request = json.loads(line)
        try:
            prediction = model.inference([request["image"]])
            np.save(request["output"], np.asarray(prediction.depth[0], np.float32))
        except Exception as exc:
            # Any failure on one image goes back to the caller, who decides; the worker
            # stays up for the next request.
            _send({"error": f"{type(exc).__name__}: {exc}"})
            continue
        _send({"ok": True})


if __name__ == "__main__":
    main()
