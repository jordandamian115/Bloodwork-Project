"""
HIPAA Safe Harbor–oriented PHI detection and redaction.

Identifiers are blocked from logs, model transcripts, and knowledge indexes.
Sex, age, and weight may be used **in memory** for reference-interval selection,
then withheld from user-facing text and audit previews.

This is an engineering control, not a HIPAA certification or BAA.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Comprehend Medical DetectPHI-style labels (local regex analogue)
PHI_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "ID"),
    (re.compile(r"\b\d{9}\b"), "ID"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "PAYMENT"),
    (re.compile(r"\b(?:acct|account|member|subscriber|mrn|medical record)[#:\s]+\w+\b", re.I), "ID"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "EMAIL"),
    (re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"), "PHONE"),
    (re.compile(r"\b\d{1,5}\s+[A-Za-z0-9.\s]{2,40}\s(?:Street|St|Avenue|Ave|Road|Rd|Blvd|Lane|Ln|Drive|Dr)\b", re.I), "ADDRESS"),
    (re.compile(r"\b\d{5}(?:-\d{4})?\b"), "ZIP"),
    (re.compile(r"\b(?:visit|appointment|dos|date of service)[:\s]+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", re.I), "DATE"),
    (re.compile(r"\b(?:\d{1,2}:\d{2}\s?(?:am|pm)?)\b", re.I), "TIME"),
    (re.compile(r"\b(?:ssn|social security)\b", re.I), "ID"),
]

DEMOGRAPHIC_PATTERNS = {
    "age": re.compile(r"\b(?:age[:\s]*)?(\d{1,3})\s*(?:years?\s*old|yo|y/o|yrs?)\b", re.I),
    "sex": re.compile(r"\b(sex|gender)\s*[:\-]\s*(male|female|m|f|man|woman)\b", re.I),
    "sex_word": re.compile(r"\b(male|female)\b", re.I),
    "weight": re.compile(r"\b(?:weight|wt)\s*[:\-]?\s*(\d{2,3}(?:\.\d+)?)\s*(kg|lbs?|pounds?)\b", re.I),
}

NAME_LINE = re.compile(
    r"(?im)^(?:patient(?:\s+name)?|name)\s*[:\-]\s*.+$"
)


@dataclass
class InternalDemographics:
    """Ephemeral attributes for range selection. Never write to disk as-is."""

    sex: str | None = None
    age_years: int | None = None
    weight_kg: float | None = None
    used_fields: list[str] = field(default_factory=list)

    def age_band(self) -> str | None:
        return to_age_band(self.age_years)

    def public_view(self) -> dict:
        return {
            "sex_specific_ranges": bool(self.sex),
            "age_band": self.age_band(),
            "weight_considered": bool(self.weight_kg),
        }


def to_age_band(age_years: int | None) -> str | None:
    if age_years is None:
        return None
    if age_years >= 90:
        return "90+"
    if age_years < 18:
        return "<18"
    for start, end in ((18, 29), (30, 39), (40, 49), (50, 59), (60, 69), (70, 79), (80, 89)):
        if start <= age_years <= end:
            return f"{start}-{end}"
    return "unspecified"


def extract_demographics(text: str) -> InternalDemographics:
    demo = InternalDemographics()
    age_match = DEMOGRAPHIC_PATTERNS["age"].search(text)
    if age_match:
        age = int(age_match.group(1))
        if 0 < age < 130:
            demo.age_years = age
            demo.used_fields.append("age")

    sex_match = DEMOGRAPHIC_PATTERNS["sex"].search(text) or DEMOGRAPHIC_PATTERNS["sex_word"].search(text)
    if sex_match:
        token = sex_match.group(sex_match.lastindex or 1).lower()
        if token in {"m", "male", "man"}:
            demo.sex = "male"
        elif token in {"f", "female", "woman"}:
            demo.sex = "female"
        demo.used_fields.append("sex")

    weight_match = DEMOGRAPHIC_PATTERNS["weight"].search(text)
    if weight_match:
        value = float(weight_match.group(1))
        unit = weight_match.group(2).lower()
        demo.weight_kg = value * 0.453592 if unit.startswith("lb") or unit.startswith("pound") else value
        demo.used_fields.append("weight")

    return demo


def redact_phi(text: str) -> tuple[str, list[str]]:
    tags: list[str] = []
    sanitized = text

    sanitized = NAME_LINE.sub("[REDACTED-NAME]", sanitized)
    if NAME_LINE.search(text):
        tags.append("NAME")

    for pattern, label in PHI_PATTERNS:
        if pattern.search(sanitized):
            tags.append(label)
            sanitized = pattern.sub(f"[REDACTED-{label}]", sanitized)

    # Strip identifiers from output; keep lab values.
    sanitized = DEMOGRAPHIC_PATTERNS["age"].sub("[REDACTED-AGE]", sanitized)
    sanitized = DEMOGRAPHIC_PATTERNS["weight"].sub("[REDACTED-WEIGHT]", sanitized)
    sanitized = DEMOGRAPHIC_PATTERNS["sex"].sub("sex: [REDACTED]", sanitized)

    if any(k in tags for k in ("ID", "PAYMENT", "ADDRESS", "EMAIL", "PHONE")) or "NAME" in tags:
        pass

    return sanitized, tags


def scan_for_phi(text: str) -> list[str]:
    _, tags = redact_phi(text)
    return tags
