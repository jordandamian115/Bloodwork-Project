import os
from dataclasses import dataclass
from functools import lru_cache

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class Settings:
    ollama_model: str
    embed_model: str
    chroma_dir: str
    phi_backend: str
    aws_region: str
    comprehend_min_score: float
    bedrock_guardrail_id: str
    bedrock_guardrail_version: str
    bedrock_apply_guardrail: bool


@lru_cache
def get_settings() -> Settings:
    return Settings(
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2"),
        embed_model=os.getenv("EMBED_MODEL", "nomic-embed-text"),
        chroma_dir=os.getenv("CHROMA_DIR", "./chroma_db"),
        phi_backend=os.getenv("PHI_BACKEND", "local").lower(),
        aws_region=os.getenv("AWS_REGION", "us-east-1"),
        comprehend_min_score=float(os.getenv("COMPREHEND_MEDICAL_MIN_SCORE", "0.5")),
        bedrock_guardrail_id=os.getenv("BEDROCK_GUARDRAIL_ID", ""),
        bedrock_guardrail_version=os.getenv("BEDROCK_GUARDRAIL_VERSION", "DRAFT"),
        bedrock_apply_guardrail=os.getenv("BEDROCK_APPLY_GUARDRAIL", "false").lower()
        == "true",
    )
