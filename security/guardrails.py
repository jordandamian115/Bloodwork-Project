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

IDENTIFIER_REQUEST = re.compile(
    r"\bmy\s+(ssn|social\s*security|social-security|full name|address|phone|"
    r"e-?mail|date of birth|dob|mrn|medical record)\b"
    r"|\b(what(?:['’]?s| is)|whats|tell me|give me|show me|reveal)\b.{0,48}\b"
    r"(ssn|social\s*security(?:\s*number)?)\b",
    re.I,
)

KNOWLEDGE_QUESTION = re.compile(
    r"\b(papers?|literature|indexed|guideline|medlineplus|nhlbi|pmc|"
    r"what do the (?:papers|sources|corpus))\b",
    re.I,
)

IDENTIFIER_REFUSAL = (
    "This assistant does not store or return identifiers. "
    "SSN, name, address, phone, email, and similar fields are redacted from lab PDFs "
    "and never shown in chat. Ask about a de-identified marker or what the papers say."
)

UNMATCHED_MARKER_REFUSAL = (
    "That was not extracted from the parsed lab panel, so I will not list other results "
    "or guess from unrelated papers. Ask about a parsed marker, say “full panel”, "
    "or ask what the indexed papers say about a named topic."
)

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

    if IDENTIFIER_REQUEST.search(cleaned):
        return GuardrailResult(False, IDENTIFIER_REFUSAL, "identifier_request")

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


def unmatched_marker_refusal(question: str, lab_context: str) -> str | None:
    """Skip RAG when no marker is in scope and the user did not ask about the papers."""
    if "none in scope" not in (lab_context or "").lower():
        return None
    if KNOWLEDGE_QUESTION.search(question or ""):
        return None
    return UNMATCHED_MARKER_REFUSAL
