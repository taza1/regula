"""Deterministic offline review checks: injection scan, citations, fact-check.

These are rule-based gates, not model judgments. They are intended to run
before (and alongside) any model-backed reviewer, and never call the network.
"""

from __future__ import annotations

import re

# Source text is untrusted data. These patterns flag text that tries to give
# instructions to whatever model later reads the passage.
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "instruction-override",
        re.compile(
            r"\b(ignore|disregard|forget)\b[^.\n]{0,30}\b(previous|prior|above|earlier|system)\b"
            r"[^.\n]{0,30}\b(instructions?|prompts?|rules?|messages?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role-hijack",
        re.compile(
            r"\b(you are now|pretend to be|from now on you)\b"
            r"|\bact as (an? |the )?(assistant|ai|system|admin|developer|jailbroken)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt-exfiltration",
        re.compile(
            r"\b(reveal|print|show|output|repeat|leak)\b[^.\n]{0,25}"
            r"\b(system prompt|hidden instructions|developer message|api[- ]?key|secrets?|credentials?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "chat-template-token",
        re.compile(
            r"<\|?\s*(im_start|im_end|system|assistant)\s*\|?>|\[/?INST\]|<<SYS>>",
            re.IGNORECASE,
        ),
    ),
    (
        "exfiltration-url",
        re.compile(
            r"\b(send|post|upload|exfiltrate|forward)\b[^.\n]{0,60}https?://",
            re.IGNORECASE,
        ),
    ),
]

_STOPWORDS = frozenset(
    "the and for are was were this that with from has have had not but its their "
    "than then them they there which while into over also can may will been being "
    "such these those our out any all one two".split()
)

SUPPORT_THRESHOLD = 0.8


def scan_for_prompt_injection(text: str) -> list[str]:
    """Return the distinct injection pattern labels found in ``text``."""

    return [label for label, pattern in _INJECTION_PATTERNS if pattern.search(text)]


def _content_tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]{3,}", text.casefold())
        if token not in _STOPWORDS
    ]


def support_ratio(claim_text: str, passage: str) -> float:
    """Fraction of the claim's content tokens that appear in the passage.

    A claim that is a verbatim (whitespace/case-insensitive) excerpt of the
    passage scores 1.0. Claims with no content tokens score 0.0.
    """

    claim_norm = " ".join(claim_text.casefold().split())
    if claim_norm and claim_norm in " ".join(passage.casefold().split()):
        return 1.0
    claim_tokens = set(_content_tokens(claim_text))
    if not claim_tokens:
        return 0.0
    passage_tokens = set(_content_tokens(passage))
    return len(claim_tokens & passage_tokens) / len(claim_tokens)
