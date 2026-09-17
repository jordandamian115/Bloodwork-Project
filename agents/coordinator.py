"""Lightweight agent steps: privacy scan → knowledge retrieve → interpret."""

from __future__ import annotations

from security.audit import log_event
from security.aws_adapters import get_phi_detector, optional_bedrock_check
from agents.markers import expand_retrieval_query
from rag.chain import chain_inputs
from security.guardrails import check_input, sanitize_output, unmatched_marker_refusal


def run_interpretation(chain, question: str, lab_context: str, indexed_file: str = "") -> dict:
    input_check = check_input(question)
    if not input_check.allowed:
        log_event(
            "query_blocked",
            question=question,
            indexed_file=indexed_file,
            reason=input_check.reason,
        )
        return {
            "blocked": True,
            "answer": input_check.message,
            "reason": input_check.reason,
            "sources": [],
            "warnings": [],
        }

    unmatched = unmatched_marker_refusal(question, lab_context)
    if unmatched:
        log_event(
            "query_unmatched_marker",
            question=question,
            indexed_file=indexed_file,
            reason="unmatched_marker",
        )
        return {
            "blocked": False,
            "answer": unmatched,
            "reason": "unmatched_marker",
            "sources": [],
            "warnings": [],
        }

    detector = get_phi_detector()
    redacted_question, tags = detector.redact(input_check.message)
    redacted_question = expand_retrieval_query(redacted_question, lab_context)
    bedrock = optional_bedrock_check(redacted_question, source="INPUT")
    if bedrock.get("action") == "GUARDRAIL_INTERVENED":
        log_event("bedrock_blocked", question=question, indexed_file=indexed_file, reason="guardrail")
        return {
            "blocked": True,
            "answer": "Blocked by Amazon Bedrock Guardrails.",
            "reason": "bedrock_guardrail",
            "sources": [],
            "warnings": [],
        }

    context_docs = []
    pieces: list[str] = []
    for chunk in chain.stream(chain_inputs(redacted_question, lab_context)):
        if "context" in chunk:
            context_docs.clear()
            context_docs.extend(chunk["context"])
        if chunk.get("answer"):
            pieces.append(chunk["answer"])

    raw_answer = "".join(pieces) or "No answer returned."
    answer, warnings = sanitize_output(raw_answer)
    if tags:
        warnings.append("input_phi_redacted")

    output_check = optional_bedrock_check(answer, source="OUTPUT")
    if output_check.get("action") == "GUARDRAIL_INTERVENED":
        answer = "The model response was withheld by the output guardrail."
        warnings.append("bedrock_output_blocked")

    sources = [
        {
            "text": doc.page_content,
            "page": doc.metadata.get("page", "?"),
            "source": doc.metadata.get("source", ""),
        }
        for doc in context_docs
    ]

    log_event(
        "query_success",
        question=question,
        indexed_file=indexed_file,
        extra={
            "answer_length": len(answer),
            "source_count": len(sources),
            "output_warnings": warnings,
            "phi_tags": tags,
        },
    )
    return {
        "blocked": False,
        "answer": answer,
        "reason": "",
        "sources": sources,
        "warnings": warnings,
    }
