"""Apple Depth Pro via Hugging Face transformers (4.49 and later).

The weights are licensed for research only.
"""

from __future__ import annotations

from typing import ClassVar

from video_bokeh.library.depth._transformers import TransformersDepthEstimator


class DepthPro(TransformersDepthEstimator):
    """Depth Pro read before its post-processing, which is where it becomes metric.

    Its head outputs canonical inverse depth, and ``post_process_depth_estimation`` turns
    that into metres by scaling with the focal length and taking the reciprocal. The raw
    ``predicted_depth`` is therefore disparity already. The focal scale it skips is one
    number per image, which the library's min/max normalization removes anyway.
    """

    name: ClassVar[str] = "depth-pro"
    hf_model_id: ClassVar[str] = "apple/DepthPro-hf"
    docker_image: ClassVar[str] = "video-bokeh-depth-pro"
