"""Stable source units for model selection; quotes and offsets are server-owned."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceUnit:
    id: str
    evidence_id: str
    content: str
    start: int


def source_units(chunks, maximum=28, width=280):
    units, seen, groups = {}, set(), []
    for chunk in chunks:
        ranges = []
        for match in re.finditer(r"[^\n]+", chunk.content):
            line = match.group().strip()
            if not line or line.startswith(("![", "```", "├", "└", "│")) or re.fullmatch(r"[-*_\s]+", line):
                continue
            start, end = match.span()
            while start < end:
                boundary = min(start + width, end)
                if boundary < end:
                    candidate = chunk.content.rfind(" ", start + 100, boundary)
                    if candidate > start:
                        boundary = candidate
                left, right = start, boundary
                if right - left < 12:
                    left = max(0, left - 50)
                    right = min(len(chunk.content), max(right, left + 60))
                if right - left >= 12:
                    ranges.append((left, right))
                start = max(start + 1, boundary)
        if not ranges and len(chunk.content) >= 12:
            ranges = [(0, min(width, len(chunk.content)))]
        group = []
        for start, end in ranges:
            quote = chunk.content[start:end]
            key = (chunk.evidence_id, chunk.start + start, quote)
            if key in seen:
                continue
            seen.add(key)
            group.append(SourceUnit(chunk.id, chunk.evidence_id, quote, chunk.start + start))
        groups.append(group)
    for index in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if index < len(group):
                units[f"u{len(units) + 1}"] = group[index]
                if len(units) >= maximum:
                    return units
    return units


def embedding_segments(text, byte_limit=96):
    """Bound UTF-8 payloads without dropping text, including unusual Unicode."""
    pieces, current, size = [], [], 0
    for character in text:
        width = len(character.encode("utf-8"))
        if current and size + width > byte_limit:
            pieces.append("".join(current))
            current, size = [], 0
        current.append(character)
        size += width
    if current:
        pieces.append("".join(current))
    return pieces or [""]
