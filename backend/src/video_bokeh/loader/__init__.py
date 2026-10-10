"""On-the-fly training data: sequences rendered in memory from a library, never written."""

from video_bokeh.loader._stream import SequenceStream, batch_bokeh

__all__ = ["SequenceStream", "batch_bokeh"]
