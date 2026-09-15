"""Extract numeric markers from de-identified lab text. No PHI persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass

from agents.markers import SPECS, select_marker_keys, sex_adjusted
from security.phi import InternalDemographics, extract_demographics, redact_phi

# Allow a wider gap so Quest/LabCorp-style tables still match (name, then flags, then value).
MARKER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("wbc", re.compile(r"\bWBC\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("hemoglobin", re.compile(r"\b(?:hemoglobin|hgb|hb)\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("hematocrit", re.compile(r"\b(?:hematocrit|hct)\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("platelets", re.compile(r"\b(?:platelets?|plt)\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("glucose", re.compile(r"\bglucose\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("bun", re.compile(r"\bBUN\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("creatinine", re.compile(r"\bcreat(?:inine)?\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("egfr", re.compile(r"\beGFR\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    (
        "cystatin_c",
        re.compile(
            r"\b(?:cystatin[\s\-]*c|cysc|cys[\s\-]*c)\b[\s\S]{0,120}?(\d+(?:\.\d+)?)",
            re.I,
        ),
    ),
    ("sodium", re.compile(r"\bsodium\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("potassium", re.compile(r"\bpotassium\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("alt", re.compile(r"\bALT\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("ast", re.compile(r"\bAST\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("ldl", re.compile(r"\bLDL(?:-C)?\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("hdl", re.compile(r"\bHDL(?:-C)?\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("triglycerides", re.compile(r"\btriglycerides?\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("apob", re.compile(r"\bApoB\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("lpa", re.compile(r"\bLp\(?a\)?\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("shbg", re.compile(r"\bSHBG\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("estradiol", re.compile(r"\bestradiol\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("lh", re.compile(r"\bLH\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("fsh", re.compile(r"\bFSH\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("cortisol", re.compile(r"\bcortisol\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("tsh", re.compile(r"\bTSH\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("ferritin", re.compile(r"\bferritin\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("vitamin_d", re.compile(r"\b(?:vitamin\s*d|25-?oh)\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("hs_crp", re.compile(r"\b(?:hs-?crp|crp)\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("magnesium", re.compile(r"\b(?:rbc\s+)?magnesium\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
    ("homocysteine", re.compile(r"\bhomocysteine\b[\s\S]{0,80}?(\d+(?:\.\d+)?)", re.I)),
]

# Quest/LabCorp-style rows: "TESTOSTERONE, FREE 747.4" vs "TESTOSTERONE, TOTAL, MS 1796"
NUMBER = r"(?<![A-Za-z])(\d+(?:\.\d+)?)(?![A-Za-z])"

TESTOSTERONE_RULES: list[tuple[str, list[re.Pattern[str]]]] = [
    (
        "free_testosterone",
        [
            re.compile(
                rf"testosterone\s*,\s*free(?!\s*,?\s*bioavailable)(?!\s+and\b)[^\n\d]{{0,20}}{NUMBER}",
                re.I,
            ),
            re.compile(rf"\bfree\s+testosterone(?!\s*%)[^\n\d]{{0,20}}{NUMBER}", re.I),
        ],
    ),
    (
        "bioavailable_testosterone",
        [
            re.compile(rf"testosterone\s*,\s*bioavailable[^\n\d]{{0,20}}{NUMBER}", re.I),
            re.compile(rf"\bbioavailable\s+testosterone[^\n\d]{{0,20}}{NUMBER}", re.I),
        ],
    ),
    (
        "total_testosterone",
        [
            re.compile(
                rf"testosterone\s*,\s*total(?:\s*,?\s*ms)?[^\n\d]{{0,20}}{NUMBER}",
                re.I,
            ),
            re.compile(rf"\btotal\s+testosterone[^\n\d]{{0,20}}{NUMBER}", re.I),
            re.compile(
                rf"\btestosterone\b(?!\s*,\s*(?:free|bioavailable))[^\n\d]{{0,16}}{NUMBER}",
                re.I,
            ),
        ],
    ),
]


@dataclass
class LabPanel:
    findings: dict[str, float]
    demographics: InternalDemographics
    redacted_text: str

    def as_prompt_block(self, question: str = "") -> str:
        keys = select_marker_keys(question, self.findings)
        if keys is None:
            subset = self.findings
            scope = "Full panel (user asked for an overview)."
        elif keys:
            subset = {key: self.findings[key] for key in keys}
            scope = "Only markers named in the question. Do not list other panel results."
        else:
            subset = {}
            scope = (
                "No extracted marker matched the question. "
                "Do not list the rest of the panel; answer from papers or say the marker was not parsed."
            )
        lines = [scope, "Findings:"]
        if not subset:
            lines.append("- none in scope")
        for name, value in subset.items():
            spec = SPECS.get(name)
            if spec:
                band = sex_adjusted(spec, self.demographics.sex)
                lines.append(
                    f"- {band.label}: {value} {band.unit} (literature band {band.low}–{band.high})"
                )
            else:
                lines.append(f"- {name}: {value}")
        pub = self.demographics.public_view()
        lines.append("Range context (no identifiers):")
        lines.append(f"- sex-specific intervals requested: {pub['sex_specific_ranges']}")
        lines.append(f"- age band: {pub['age_band'] or 'unknown'}")
        lines.append(f"- weight considered: {pub['weight_considered']}")
        return "\n".join(lines)

    def public_dict(self) -> dict:
        return {
            "findings": self.findings,
            "range_context": self.demographics.public_view(),
        }


def _normalize(name: str, value: float) -> float:
    if name == "wbc" and value > 100:
        return value / 1000.0
    if name == "platelets" and value > 1000:
        return value / 1000.0
    return value


def _plausible(name: str, value: float) -> bool:
    spec = SPECS.get(name)
    if not spec:
        return True
    low, high = spec.plausible
    return low <= value <= high


def _first_plausible(name: str, patterns: list[re.Pattern[str]], text: str) -> float | None:
    for pattern in patterns:
        for match in pattern.finditer(text):
            value = _normalize(name, float(match.group(1)))
            if _plausible(name, value):
                return value
    return None


def _extract_testosterone(text: str) -> dict[str, float]:
    found: dict[str, float] = {}
    for name, patterns in TESTOSTERONE_RULES:
        value = _first_plausible(name, patterns, text)
        if value is not None:
            found[name] = value
    return found


def parse_lab_text(raw_text: str) -> LabPanel:
    demographics = extract_demographics(raw_text)
    redacted, _ = redact_phi(raw_text)
    findings: dict[str, float] = {}
    findings.update(_extract_testosterone(redacted))
    for name, pattern in MARKER_PATTERNS:
        if name in findings:
            continue
        for match in pattern.finditer(redacted):
            value = _normalize(name, float(match.group(1)))
            if _plausible(name, value):
                findings[name] = value
                break
    return LabPanel(findings=findings, demographics=demographics, redacted_text=redacted)


def parse_lab_documents(documents) -> LabPanel:
    text = "\n".join(doc.page_content for doc in documents)
    return parse_lab_text(text)


def looks_like_patient_lab_filename(name: str) -> bool:
    lowered = name.lower()
    return any(
        token in lowered
        for token in ("lab-results", "lab_results", "labresults", "patient-lab", "my-labs")
    )
