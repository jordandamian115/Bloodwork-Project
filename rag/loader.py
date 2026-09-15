from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document

from agents.lab_parser import looks_like_patient_lab_filename


def load_pdf(path: str):
    return PyPDFLoader(path).load()


def load_text(path: str) -> list[Document]:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8", errors="replace")
    return [
        Document(
            page_content=text,
            metadata={"source": str(file_path), "page": 0, "filename": file_path.name},
        )
    ]


def load_document(path: str) -> list[Document]:
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return load_pdf(path)
    if suffix in {".md", ".txt"}:
        return load_text(path)
    raise ValueError(f"Unsupported knowledge file type: {suffix}")


def load_knowledge_dir(directory: str) -> list[Document]:
    folder = Path(directory)
    docs: list[Document] = []
    if not folder.exists():
        return docs
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in {".pdf", ".md", ".txt"} or path.name == ".gitkeep":
            continue
        if looks_like_patient_lab_filename(path.name):
            continue
        docs.extend(load_document(str(path)))
    return docs
