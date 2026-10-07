"""Caption formatting for Scribe ``segments``. Pure and local: no API call.

Keep the algorithm identical to the Node SDK (``src/lib/captions.ts``).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping

from ._exceptions import AddisAIError

MAX_LINE = 42
MAX_LINES = 2


def _segments(result: Mapping[str, Any]) -> List[Dict[str, Any]]:
    segments = result.get("segments") if isinstance(result, Mapping) else None
    if not isinstance(segments, list):
        raise AddisAIError('Scribe result has no segments. Transcribe with timestamps="word" to build captions.')
    for segment in segments:
        if (not isinstance(segment, Mapping) or not isinstance(segment.get("text"), str)
                or not all(_finite(segment.get(key)) for key in ("start", "end"))):
            raise AddisAIError("Scribe segments need text, start and end.")
    return segments


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _wrap(text: str) -> List[str]:
    """Greedy wrap at 42 characters per line; at most 2 lines, overflow joins line 2."""
    lines: List[str] = []
    line = ""
    for word in text.split():
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= MAX_LINE:
            line += " " + word
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES - 1] + [" ".join(lines[MAX_LINES - 1:])]
    return lines


def _timestamp(seconds: float, separator: str) -> str:
    ms = max(0, int(math.floor(seconds * 1000 + 0.5)))
    return "%02d:%02d:%02d%s%03d" % (ms // 3_600_000, ms // 60_000 % 60, ms // 1000 % 60, separator, ms % 1000)


def _cues(segments: List[Dict[str, Any]], separator: str, numbered: bool) -> List[str]:
    blocks = []
    for index, segment in enumerate(segments, 1):
        lines = [str(index)] if numbered else []
        lines.append("%s --> %s" % (_timestamp(segment["start"], separator), _timestamp(segment["end"], separator)))
        lines.extend(_wrap(segment["text"]))
        blocks.append("\n".join(lines))
    return blocks


def to_srt(result: Mapping[str, Any]) -> str:
    """Format a Scribe result's ``segments`` as SubRip (SRT) text; raises if segments are missing."""
    blocks = _cues(_segments(result), ",", True)
    return "\n\n".join(blocks) + "\n" if blocks else ""


def to_vtt(result: Mapping[str, Any]) -> str:
    """Format a Scribe result's ``segments`` as WebVTT text; raises if segments are missing."""
    blocks = _cues(_segments(result), ".", False)
    return "WEBVTT\n\n" + "\n\n".join(blocks) + "\n" if blocks else "WEBVTT\n"
