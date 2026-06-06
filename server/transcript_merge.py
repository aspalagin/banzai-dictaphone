"""Слияние частичных STT-завершений в читаемый транскрипт."""
from __future__ import annotations

import re


_WORD_RE = re.compile(r"\w+", re.UNICODE)
_LEADING_FILLERS = {"а", "и", "ну", "вот"}


def merge_transcript_line(lines: list[str], transcript: str) -> str:
    """Слить завершённый STT-фрагмент в ``lines`` и вернуть действие."""
    clean = transcript.strip()
    if not clean:
        return "empty"

    new_norm = normalize_text(clean)
    if not new_norm:
        return "empty"

    for index in range(len(lines) - 1, max(-1, len(lines) - 6), -1):
        previous = lines[index]
        prev_norm = normalize_text(previous)
        if not prev_norm:
            continue
        if new_norm == prev_norm:
            return "duplicate"
        if new_norm in prev_norm:
            return "covered_by_previous"
        if prev_norm in new_norm or looks_like_revision(previous, clean):
            lines[index:] = [clean]
            return "replace_previous" if index == len(lines) - 1 else "replace_recent"

    lines.append(clean)
    return "append"


def normalize_text(text: str) -> str:
    return " ".join(text.strip().lower().replace("ё", "е").split())


def looks_like_revision(previous: str, transcript: str) -> bool:
    prev_tokens = _tokens(previous)
    new_tokens = _tokens(transcript)
    if not prev_tokens or not new_tokens:
        return False

    if _revision_by_tokens(prev_tokens, new_tokens):
        return True

    new_without_fillers = _drop_leading_fillers(new_tokens)
    if new_without_fillers != new_tokens and _revision_by_tokens(prev_tokens, new_without_fillers):
        return True

    if len(normalize_text(transcript)) <= len(normalize_text(previous)):
        return False

    prev_norm = normalize_text(previous)
    new_norm = normalize_text(transcript)
    common_chars = _common_prefix_len(prev_norm, new_norm)
    return common_chars >= 8 and common_chars / max(1, len(prev_norm)) >= 0.6


def _revision_by_tokens(prev_tokens: list[str], new_tokens: list[str]) -> bool:
    common = 0
    for prev_token, new_token in zip(prev_tokens, new_tokens):
        if prev_token != new_token:
            break
        common += 1

    if common == 0:
        return False
    if len(prev_tokens) <= 3:
        return len(new_tokens) >= len(prev_tokens) + 1 and common / len(prev_tokens) >= 0.5
    if common >= 4:
        return True
    return common >= 8


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower().replace("ё", "е"))


def _drop_leading_fillers(tokens: list[str]) -> list[str]:
    index = 0
    while index < len(tokens) and tokens[index] in _LEADING_FILLERS:
        index += 1
    return tokens[index:]


def _common_prefix_len(left: str, right: str) -> int:
    count = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        count += 1
    return count
