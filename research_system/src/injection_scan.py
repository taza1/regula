"""Deterministic prompt-injection pre-gate for untrusted source text.

Source text is data. These patterns flag text that tries to give instructions to
whatever model later reads it. The scan is a rule-based backstop that runs
before, and independently of, any model-based reviewer; it will miss novel
phrasing, so it complements the model review rather than replacing it.
"""
from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
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


def scan_for_prompt_injection(text: str) -> list[str]:
    """Return the distinct pattern labels found in ``text`` (empty when clean)."""

    return [label for label, pattern in _PATTERNS if pattern.search(text)]


def scan_evidence(evidence: list[dict]) -> dict[str, list[str]]:
    """Map evidence_id -> labels for every record whose title or passage is flagged."""

    flagged = {}
    for record in evidence:
        labels = scan_for_prompt_injection(f"{record.get('title') or ''}\n{record.get('passage') or ''}")
        if labels:
            flagged[record["evidence_id"]] = labels
    return flagged
