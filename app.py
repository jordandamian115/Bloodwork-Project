from pathlib import Path

import streamlit as st

from agents.coordinator import run_interpretation
from agents.lab_parser import looks_like_patient_lab_filename, parse_lab_documents
from agents.markers import SPECS, band_status, sex_adjusted
from rag.chain import build_qa_chain
from rag.indexer import add_documents, build_index, index_error_hint
from rag.loader import load_document, load_knowledge_dir, load_pdf
from security.audit import log_event
from security.aws_adapters import get_phi_detector
from security.responsible_ai import AWS_CONTROL_MAP, MEDICAL_DISCLAIMER

KNOWLEDGE_DIR = Path("knowledge/documents")
UPLOAD_DIR = Path("data/uploads")
CHROMA_DIR = "./chroma_db"

st.set_page_config(page_title="Bloodwork Project", layout="wide")
st.title("Bloodwork Project")
st.caption("HIPAA-aligned educational RAG — local inference, PHI redaction, source-grounded lab literacy")
st.info(MEDICAL_DISCLAIMER)

for key, default in (
    ("vectorstore", None),
    ("chain", None),
    ("messages", []),
    ("indexed_file", None),
    ("lab_panel", None),
):
    if key not in st.session_state:
        st.session_state[key] = default

if st.session_state.indexed_file and looks_like_patient_lab_filename(str(st.session_state.indexed_file)):
    st.session_state.vectorstore = None
    st.session_state.chain = None
    st.session_state.indexed_file = None
    st.session_state.messages = []
    st.warning("A patient lab PDF was removed from knowledge. Click **Index curated corpus** again.")

KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def render_lab_gauges(panel) -> None:
    pub = panel.demographics.public_view()
    st.caption(
        f"Literature bands only (not the performing lab). "
        f"Age band {pub['age_band'] or 'unknown'} · "
        f"sex-specific ranges {'on' if pub['sex_specific_ranges'] else 'off'}"
    )
    if not panel.findings:
        st.warning("No markers parsed. Re-run **Parse labs** after this update.")
        return

    grouped: dict[str, list[tuple[str, float]]] = {}
    for key, value in panel.findings.items():
        spec = SPECS.get(key)
        grouped.setdefault(spec.group if spec else "Other", []).append((key, value))

    for group, items in grouped.items():
        with st.expander(group, expanded=group in {"CBC", "Kidney"}):
            for key, value in items:
                spec = SPECS.get(key)
                if not spec:
                    st.write(f"{key}: {value}")
                    continue
                spec = sex_adjusted(spec, panel.demographics.sex)
                status = band_status(value, spec)
                pad = max(spec.high - spec.low, 0.1) * 0.25
                axis_min = min(spec.low, value) - pad
                axis_max = max(spec.high, value) + pad
                st.markdown(f"**{spec.label}** · {value:g} {spec.unit} · {status}")
                st.slider(
                    spec.label,
                    min_value=float(axis_min),
                    max_value=float(axis_max),
                    value=float(value),
                    disabled=True,
                    key=f"gauge-{key}",
                    label_visibility="collapsed",
                )
                st.caption(f"Band {spec.low:g}–{spec.high:g} {spec.unit}")

with st.sidebar:
    st.header("Knowledge corpus")
    st.caption("Curated NIH/PMC pages live in knowledge/documents after ingest.")
    if st.button("Index curated corpus", type="primary", use_container_width=True):
        try:
            with st.spinner("Indexing curated knowledge (PHI-scanned)..."):
                documents = load_knowledge_dir(str(KNOWLEDGE_DIR))
                if not documents:
                    st.error("No .md/.pdf files in knowledge/documents. Run: python -m knowledge.ingest")
                else:
                    detector = get_phi_detector()
                    leaked = []
                    for doc in documents:
                        leaked.extend(detector.detect(doc.page_content))
                    vectorstore = build_index(documents, persist_dir=CHROMA_DIR)
                    st.session_state.vectorstore = vectorstore
                    st.session_state.chain = build_qa_chain(vectorstore)
                    st.session_state.indexed_file = f"corpus ({len(documents)} docs)"
                    st.session_state.messages = []
                    log_event(
                        "knowledge_indexed",
                        indexed_file="curated_corpus",
                        extra={"phi_hits": len(leaked), "pages": len(documents)},
                    )
                    st.success(f"Indexed {len(documents)} knowledge document(s).")
                    if leaked:
                        st.warning("Possible identifier patterns were redacted before embedding.")
        except Exception as exc:
            st.error(f"Failed to index corpus: {exc}")
            st.info(index_error_hint(exc))

    knowledge_file = st.file_uploader("Add another scientific PDF or markdown file", type=["pdf", "md"], key="knowledge")
    if st.button("Index extra file", use_container_width=True):
        if knowledge_file is None:
            st.error("Choose a file first.")
        elif looks_like_patient_lab_filename(knowledge_file.name):
            st.error(
                "That looks like a patient lab report. Use **Parse labs** below so it is not stored in the knowledge index."
            )
        else:
            try:
                with st.spinner("De-identifying and indexing extra file..."):
                    path = KNOWLEDGE_DIR / knowledge_file.name
                    path.write_bytes(knowledge_file.getvalue())
                    documents = load_document(str(path))
                    detector = get_phi_detector()
                    leaked = []
                    for doc in documents:
                        leaked.extend(detector.detect(doc.page_content))
                    if st.session_state.vectorstore is None:
                        vectorstore = build_index(documents, persist_dir=CHROMA_DIR)
                    else:
                        vectorstore = add_documents(
                            st.session_state.vectorstore,
                            documents,
                            persist_dir=CHROMA_DIR,
                        )
                    st.session_state.vectorstore = vectorstore
                    st.session_state.chain = build_qa_chain(vectorstore)
                    st.session_state.indexed_file = knowledge_file.name
                    log_event(
                        "knowledge_indexed",
                        indexed_file=knowledge_file.name,
                        extra={"phi_hits": len(leaked), "pages": len(documents)},
                    )
                    st.success(f"Indexed {len(documents)} page(s) from {knowledge_file.name}")
                    if leaked:
                        st.warning("Possible identifier patterns were redacted before embedding.")
            except Exception as exc:
                st.error(f"Failed to index: {exc}")
                st.info(index_error_hint(exc))

    if st.session_state.indexed_file:
        st.info(f"Knowledge ready: {st.session_state.indexed_file}")
        st.caption("Lab PDFs belong under Lab panel, not knowledge.")

    st.divider()
    st.header("Lab panel (ephemeral)")
    lab_file = st.file_uploader("Bloodwork PDF", type=["pdf"], key="labs")
    if st.button("Parse labs (do not index PHI)", use_container_width=True):
        if lab_file is None:
            st.error("Upload a lab PDF first.")
        else:
            try:
                tmp = UPLOAD_DIR / lab_file.name
                tmp.write_bytes(lab_file.getvalue())
                docs = load_pdf(str(tmp))
                panel = parse_lab_documents(docs)
                st.session_state.lab_panel = panel
                tmp.unlink(missing_ok=True)
                log_event(
                    "labs_parsed",
                    indexed_file=lab_file.name,
                    extra={"marker_count": len(panel.findings), **panel.demographics.public_view()},
                )
                st.success(f"Extracted {len(panel.findings)} marker(s). Identifiers withheld.")
            except Exception as exc:
                st.error(f"Failed to parse labs: {exc}")

    if st.session_state.lab_panel:
        render_lab_gauges(st.session_state.lab_panel)

    st.divider()
    st.header("Controls")
    st.markdown(
        "- Prompt-injection blocking\n"
        "- PHI redaction (local or Comprehend Medical)\n"
        "- Labs parsed in memory; not written to the knowledge index\n"
        "- Minimum-necessary audit log\n"
        "- Optional Bedrock ApplyGuardrail"
    )
    with st.expander("AWS Responsible AI map"):
        for pillar, items in AWS_CONTROL_MAP.items():
            st.markdown(f"**{pillar}**")
            for item in items:
                st.markdown(f"- {item}")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("sources"):
            with st.expander("Sources"):
                for i, source in enumerate(message["sources"], start=1):
                    st.markdown(f"**Source {i}** (page {source.get('page', '?')})")
                    st.text(source["text"][:500])

if st.session_state.chain is None:
    st.warning("Index the curated corpus in the sidebar (or add a file) before chatting.")
else:
    question = st.chat_input("Ask about markers, ranges, or what the papers say to discuss with a clinician")
    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            lab_context = ""
            if st.session_state.lab_panel:
                lab_context = st.session_state.lab_panel.as_prompt_block(question)
            try:
                result = run_interpretation(
                    st.session_state.chain,
                    question,
                    lab_context,
                    indexed_file=st.session_state.indexed_file or "",
                )
                if result["blocked"]:
                    st.warning(result["answer"])
                else:
                    st.markdown(result["answer"])
                    if result["warnings"]:
                        st.caption("Guardrail notes: " + ", ".join(result["warnings"]))
                    if result["sources"]:
                        with st.expander("Sources"):
                            for i, source in enumerate(result["sources"], start=1):
                                st.markdown(f"**Source {i}** (page {source.get('page', '?')})")
                                st.text(source["text"][:500])
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": result["answer"],
                        "sources": result.get("sources", []),
                    }
                )
            except Exception as exc:
                error_msg = f"Could not get an answer: {exc}"
                st.error(error_msg)
                log_event(
                    "query_error",
                    question=question,
                    indexed_file=st.session_state.indexed_file or "",
                    reason=str(exc),
                )
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
