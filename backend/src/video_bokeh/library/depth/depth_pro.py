"""Apple Depth Pro via Hugging Face transformers (4.49 and later).

Depth Pro is a metric model, but only after post-processing. Its head outputs canonical
inverse depth, and `post_process_depth_estimation` is what turns that into metres, by
scaling with the focal length and taking the reciprocal. Reading the raw
`predicted_depth` and skipping the post-processing therefore gives disparity directly.
The focal scale it also skips is one number per image, which the library's min/max
normalization removes anyway.

The weights are licensed for research only.
"""

from __future__ import annotations

from typing import ClassVar

from video_bokeh.library.depth._transformers import TransformersDepthEstimator


class DepthPro(TransformersDepthEstimator):
    name: ClassVar[str] = "depth-pro"
    hf_model_id: ClassVar[str] = "apple/DepthPro-hf"
