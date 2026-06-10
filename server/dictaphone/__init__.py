"""Dictaphone server package."""
from __future__ import annotations

from dictaphone.stt import AbstractTranscriber, get_transcriber

__all__ = ["AbstractTranscriber", "get_transcriber"]