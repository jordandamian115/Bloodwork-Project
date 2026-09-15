"""
Input/output guardrails.

Maps to OWASP LLM Top 10 plus AWS Bedrock Guardrails policy types:
content filters, denied topics, word filters, sensitive information, grounding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from security.phi import redact_phi
from security.responsible_ai import denied_topic_hit

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(your|the)\s+(instructions|rules|guidelines)",
    r"forget\s+(everything|all|your)\s+(you|instructions|rules)",
    r"you\s+are\s+now\s+(a|an|in)\s+",
    r"new\s+instructions?\s*:",
    r"system\s+prompt",
    r"reveal\s+(your|the)\s+(prompt|instructions|rules)",
    r"jailbreak",
    r"do\s+anything\n?now",
    r"do\s+anything\s+now",
    r"developer\s+mode",
    r"bypass\s+(safety|filter|guardrail|restriction)",
    r"disregard\s+prior\s+guidance",
    r"act\s+as\s+(an?\s+)?unrestricted",
    r"pretend\s+you\s+are\s+(a\s+)?(licensed\s+)?(physician|doctor|md)\b",
]

INJECTION_REGEX = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)

MAX_INPUT_LENGTH = 4000
MAX_OUTPUT_LENGTH = 8000


@dataclass
class GuardrailResult:
    allowed: bool
    message: str
    reason: str = ""


def check_input(text: str) -> GuardrailResult:
    cleaned = text.strip()

    if not cleaned:
        return GuardrailResult(False, "Please enter a question.", "empty_input")

    if len(cleaned) > MAX_INPUT_LENGTH:
        return GuardrailResult(
            False,
            f"Question too long (max {MAX_INPUT_LENGTH} characters).",
            "input_too_long",
        )

    if INJECTION_REGEX.search(cleaned):
        return GuardrailResult(
            False,
            "Blocked by the input guardrail (possible prompt injection).",
            "prompt_injection_detected",
        )

    topic = denied_topic_hit(cleaned)
    if topic:
        return GuardrailResult(
            False,
            "This request is outside the allowed educational lab-interpretation scope.",
            f"denied_topic:{topic}",
        )

    return GuardrailResult(True, cleaned)


def sanitize_output(text: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    sanitized, phi_tags = redact_phi(text)
    if phi_tags:
        warnings.append(f"redacted_phi:{','.join(sorted(set(phi_tags)))}")

    if len(sanitized) > MAX_OUTPUT_LENGTH:
        sanitized = sanitized[:MAX_OUTPUT_LENGTH] + "\n\n[Output truncated for safety.]"
        warnings.append("output_truncated")

    leak_phrases = [
        "system prompt",
        "my instructions are",
        "i was told to ignore",
        "here is the hidden prompt",
    ]
    lower = sanitized.lower()
    if any(phrase in lower for phrase in leak_phrases):
        warnings.append("possible_instruction_leak")

    return sanitized, warnings
