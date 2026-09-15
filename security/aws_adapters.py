"""
Optional AWS backends. Default runtime stays local so a portfolio demo
does not require cloud credentials or a BAA.

Production (covered entity) would: sign a BAA, use HIPAA-eligible services
only, private subnets, KMS CMKs, CloudTrail, and Bedrock Guardrails
ApplyGuardrail on both prompts and completions.
"""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import get_settings
from security.phi import redact_phi, scan_for_phi


@dataclass
class PhiFinding:
    category: str
    score: float
    backend: str


class PhiDetector:
    def detect(self, text: str) -> list[PhiFinding]:
        raise NotImplementedError

    def redact(self, text: str) -> tuple[str, list[str]]:
        raise NotImplementedError


class LocalPhiDetector(PhiDetector):
    def detect(self, text: str) -> list[PhiFinding]:
        return [PhiFinding(category=tag, score=1.0, backend="local") for tag in scan_for_phi(text)]

    def redact(self, text: str) -> tuple[str, list[str]]:
        return redact_phi(text)


class ComprehendMedicalDetector(PhiDetector):
    """Amazon Comprehend Medical DetectPHI. Requires IAM + BAA in production."""

    def __init__(self) -> None:
        import boto3

        settings = get_settings()
        self._min_score = settings.comprehend_min_score
        self._client = boto3.client("comprehendmedical", region_name=settings.aws_region)

    def detect(self, text: str) -> list[PhiFinding]:
        response = self._client.detect_phi(Text=text[:20000])
        findings: list[PhiFinding] = []
        for entity in response.get("Entities", []):
            score = float(entity.get("Score") or 0)
            if score < self._min_score:
                continue
            findings.append(
                PhiFinding(
                    category=str(entity.get("Type", "PHI")),
                    score=score,
                    backend="comprehend_medical",
                )
            )
        return findings

    def redact(self, text: str) -> tuple[str, list[str]]:
        findings = self.detect(text)
        # Offset-accurate masking belongs in production; fall back to local patterns too.
        redacted, local_tags = redact_phi(text)
        tags = local_tags + [f.category for f in findings]
        return redacted, tags


class BedrockGuardrail:
    """Amazon Bedrock ApplyGuardrail for input/output policy evaluation."""

    def __init__(self) -> None:
        import boto3

        settings = get_settings()
        self._id = settings.bedrock_guardrail_id
        self._version = settings.bedrock_guardrail_version
        self._client = boto3.client("bedrock-runtime", region_name=settings.aws_region)

    def evaluate(self, text: str, source: str = "INPUT") -> dict:
        if not self._id:
            return {"skipped": True, "action": "NONE"}
        response = self._client.apply_guardrail(
            guardrailIdentifier=self._id,
            guardrailVersion=self._version,
            source=source,
            content=[{"text": {"text": text[:20000]}}],
        )
        return {
            "skipped": False,
            "action": response.get("action"),
            "outputs": response.get("outputs"),
        }


def get_phi_detector() -> PhiDetector:
    settings = get_settings()
    if settings.phi_backend == "comprehend_medical":
        return ComprehendMedicalDetector()
    return LocalPhiDetector()


def optional_bedrock_check(text: str, source: str = "INPUT") -> dict:
    settings = get_settings()
    if not settings.bedrock_apply_guardrail:
        return {"skipped": True, "action": "NONE"}
    return BedrockGuardrail().evaluate(text, source=source)
