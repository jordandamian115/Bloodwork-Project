from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config.settings import get_settings
from rag.embeddings import SafeOllamaEmbeddings
from security.phi import redact_phi


def _deidentify_documents(documents):
    cleaned = []
    for doc in documents:
        text, tags = redact_phi(doc.page_content)
        if tags:
            doc.metadata["phi_redacted"] = ",".join(sorted(set(tags)))
        doc.page_content = text
        cleaned.append(doc)
    return cleaned


def ensure_ollama(embed_model: str) -> None:
    import json
    import urllib.request

    url = "http://127.0.0.1:11434/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.loads(resp.read().decode())
    except Exception as exc:
        raise RuntimeError(
            "Ollama is not running on http://127.0.0.1:11434. "
            "Start the Ollama app, wait until it is ready, then retry. "
            f"Also run: ollama pull {embed_model}"
        ) from exc

    names = []
    for model in payload.get("models", []):
        name = str(model.get("name") or "")
        names.append(name)
        names.append(name.split(":")[0])
    if embed_model not in names:
        raise RuntimeError(
            f"Ollama is running, but the embedding model '{embed_model}' is missing. "
            f"Run: ollama pull {embed_model}"
        )


def _embeddings():
    settings = get_settings()
    ensure_ollama(settings.embed_model)
    emb = SafeOllamaEmbeddings(settings.embed_model)
    emb.embed_query("blood test reference interval")
    return emb


def _split(documents):
    splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=100)
    return splitter.split_documents(documents)


def build_index(documents, persist_dir: str | None = None, collection_name: str = "knowledge"):
    settings = get_settings()
    persist_dir = persist_dir or settings.chroma_dir
    chunks = _split(_deidentify_documents(documents))
    if not chunks:
        raise RuntimeError("No text chunks to index. Check knowledge/documents.")

    embeddings = _embeddings()
    vectorstore = FAISS.from_documents(chunks, embeddings)
    Path(persist_dir).mkdir(parents=True, exist_ok=True)
    vectorstore.save_local(persist_dir)
    return vectorstore


def add_documents(vectorstore, documents, persist_dir: str | None = None):
    settings = get_settings()
    persist_dir = persist_dir or settings.chroma_dir
    chunks = _split(_deidentify_documents(documents))
    if chunks:
        vectorstore.add_documents(chunks)
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        vectorstore.save_local(persist_dir)
    return vectorstore


def load_index(persist_dir: str | None = None, collection_name: str = "knowledge"):
    settings = get_settings()
    persist_dir = persist_dir or settings.chroma_dir
    embeddings = _embeddings()
    return FAISS.load_local(
        persist_dir,
        embeddings,
        allow_dangerous_deserialization=True,
    )


def index_error_hint(exc: Exception) -> str:
    text = str(exc).lower()
    if "tokenize" in text or "embedding runner" in text or "status code: 400" in text:
        return (
            "Ollama's embedding process crashed mid-batch (Windows /tokenize). "
            "This build now embeds a few short chunks at a time. "
            "Restart the Ollama desktop app, then restart Streamlit and index again. "
            "First run can take several minutes."
        )
    if "11434" in text or "ollama" in text:
        return str(exc)
    return (
        "Indexing uses local Ollama embeddings (nomic-embed-text). "
        "Confirm Ollama is running: ollama list"
    )
