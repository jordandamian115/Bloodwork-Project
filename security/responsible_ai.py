"""
Denied topics, grounding language, and AWS Responsible AI mapping.

Aligned with AWS AI Practitioner themes: privacy, safety, transparency,
fairness caveats, human oversight, and governance — plus Bedrock Guardrails
policy types used in healthcare reference architectures.
"""

from __future__ import annotations

import re

MEDICAL_DISCLAIMER = (
    "Educational interpretation only. This is not medical advice, diagnosis, "
    "or a substitute for a licensed clinician. Reference intervals vary by lab, "
    "assay, fasting status, and clinical context. Discuss results with your care team."
)

DENIED_TOPICS = {
    "controlled_substance": re.compile(
        r"\b(how to (get|buy|dose)|prescribe)\b.*\b(opioid|oxycodone|fentanyl|adderall)\b"
        r"|\b(opioid|oxycodone|fentanyl|adderall)\b.*\b(how to (get|buy|dose)|prescribe)\b",
        re.I,
    ),
    "self_harm": re.compile(r"\b(kill myself|suicide method|how to die)\b", re.I),
    "unlicensed_care": re.compile(
        r"\b(write me a prescription|act as my doctor|replace my physician)\b", re.I
    ),
}

AWS_CONTROL_MAP = {
    "privacy": [
        "Amazon Comprehend Medical DetectPHI (optional backend)",
        "Amazon Bedrock Guardrails sensitive-information filters",
        "Minimum-necessary audit logs; no raw PHI in JSONL previews",
    ],
    "safety": [
        "Bedrock-style denied topics and content filters (local analogue)",
        "Prompt-injection blocking (OWASP LLM01)",
        "Human-in-the-loop: clinician review required before any care decision",
    ],
    "grounding": [
        "Retrieve only from ingested scientific sources",
        "Refuse when context is missing (hallucination control)",
        "Cite source snippets for every interpretation",
    ],
    "security": [
        "Local-first inference (Ollama) so lab PDFs need not leave the workstation",
        "Production path: VPC, KMS, CloudTrail, IAM least privilege, BAA on eligible services",
        "Amazon Macie / knowledge-base scan before RAG ingest (documented)",
    ],
    "governance": [
        "Append-only audit events with hashed questions",
        "Explicit non-certification: controls support HIPAA alignment, they are not a BAA",
    ],
}


def denied_topic_hit(text: str) -> str | None:
    for name, pattern in DENIED_TOPICS.items():
        if pattern.search(text):
            return name
    return None


def grounding_instruction() -> str:
    return (
        "Answer using ONLY the retrieved knowledge context and the structured findings in scope. "
        "If a marker or recommendation is not supported by that context, say you do not know. "
        "Do not invent reference ranges or drug doses. Do not restate names, addresses, SSN, payment data, "
        "exact age, weight, sex, visit times, or locations. You may apply sex- and age-banded "
        "intervals internally and describe them as 'applicable reference intervals' without "
        "echoing identifiers. "
        "When the papers discuss medications, supplements, or named diet patterns "
        "(metformin, berberine, statins, folate/B6/B12, Mediterranean/DASH, aromatase inhibitors "
        "in hypogonadism/TRT literature, weight-loss effects on testosterone/estradiol), "
        "list those as clinician-discussion options with the paper's caveats. "
        "Do not write prescriptions, do not give illicit anabolic sourcing or unsupervised steroid cycles, "
        "and do not tell the user to start a drug on their own."
    )
