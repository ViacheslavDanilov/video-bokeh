"""Transformers depth worker: runs in a model's Docker image, never imported by video_bokeh.

Started by a ``TransformersDepthEstimator`` under ``VIDEO_BOKEH_RUNNER=docker`` as
``python _transformers_worker.py <model id> <device>``, it speaks the protocol in
``video_bokeh.core._worker``: one request per image, ``{"image": path, "output": path}``,
and writes the model's raw ``predicted_depth``, disparity for every model it serves, to
``output`` as a float32 ``.npy``. The caller resizes it, as it does in process. A request
``{"memory": true}`` answers with the bytes this process has used on its device.
"""

import json
import os
import sys

# Run as a script, this file's own directory comes first on sys.path. None of its
# siblings shadows a package imported here, but Depth Anything 3's worker was bitten that
# way, so the directory goes.
del sys.path[0]

# fd 1 is the protocol's alone; see the Depth Anything 3 worker for why.
reply = os.fdopen(os.dup(1), "w", encoding="utf-8")
os.dup2(2, 1)
sys.stdout = sys.stderr

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402
from transformers import (  # noqa: E402
    AutoImageProcessor,
    AutoModelForDepthEstimation,
)


def _send(message: dict) -> None:
    reply.write(json.dumps(message) + "\n")
    reply.flush()


def _peak_memory(device: str) -> int:
    """The figure ``library._measure.peak_memory`` reports, for this process."""
    if device.startswith("cuda"):
        return int(torch.cuda.max_memory_allocated(device))
    import resource

    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)


def main() -> None:
    model_id, device = sys.argv[1], sys.argv[2]
    processor = AutoImageProcessor.from_pretrained(model_id)
    # As in process: float32, whatever the checkpoint's own dtype.
    model = AutoModelForDepthEstimation.from_pretrained(model_id)
    model = model.to(device=device, dtype=torch.float32).eval()
    _send({"ready": True})
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("memory"):
            _send({"memory": _peak_memory(device)})
            continue
        try:
            image = Image.open(request["image"]).convert("RGB")
            inputs = processor(images=[image], return_tensors="pt").to(device)
            with torch.no_grad():
                depth = model(**inputs).predicted_depth[0]
            np.save(request["output"], depth.float().cpu().numpy())
        except Exception as exc:
            _send({"error": f"{type(exc).__name__}: {exc}"})
            continue
        _send({"ok": True})


if __name__ == "__main__":
    main()
