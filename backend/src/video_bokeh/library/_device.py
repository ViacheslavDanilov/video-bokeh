"""Torch device selection. Separate from _seq_io so path helpers stay torch-free."""

from __future__ import annotations

import torch


def select_device(prefer: str) -> torch.device:
    """Select a torch device honoring ``prefer`` with auto fallback."""
    if prefer == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    if prefer == "mps" and torch.backends.mps.is_available():
        return torch.device("mps")
    if prefer == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if torch.backends.mps.is_available():
            return torch.device("mps")
    return torch.device("cpu")
