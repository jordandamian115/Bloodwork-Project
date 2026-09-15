"""Fetch curated public sources into knowledge/documents/ as markdown."""

from __future__ import annotations

import html
import re
import ssl
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "knowledge" / "sources.yaml"
OUT_DIR = ROOT / "knowledge" / "documents"

USER_AGENT = "BloodworkProject/0.1 educational-RAG (portfolio; +local-only ingest)"


def compact_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        lines.append(stripped)
    return "\n".join(lines).strip()


def _strip_html(raw: str) -> str:
    raw = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style.*?>.*?</style>", " ", raw)
    raw = re.sub(r"(?is)<nav.*?>.*?</nav>", " ", raw)
    raw = re.sub(r"(?is)<footer.*?>.*?</footer>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", raw)
    return compact_text(html.unescape(text))


def fetch_url(url: str, timeout: int = 45) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    contexts = [ssl.create_default_context()]
    try:
        contexts.append(ssl._create_unverified_context())
    except Exception:
        pass
    last_error: Exception | None = None
    for ctx in contexts:
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read(), resp.headers.get("Content-Type", "")
        except Exception as exc:
            last_error = exc
            continue
    raise last_error or RuntimeError("fetch failed")


def load_catalog() -> list[dict]:
    payload = yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8"))
    return payload.get("sources", [])


def write_markdown(entry: dict, body: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    topics = ", ".join(entry.get("topics") or [])
    targets = entry.get("teaches") or ""
    header = (
        f"# {entry['title']}\n\n"
        f"- Source id: `{entry['id']}`\n"
        f"- URL: {entry['url']}\n"
        f"- Cluster: {entry.get('cluster', '')}\n"
        f"- Topics: {topics}\n"
        f"- Teaching target: {targets}\n\n"
        "Educational extract for local RAG. Prefer the live page for updates.\n\n---\n\n"
    )
    path = OUT_DIR / f"{entry['id']}.md"
    path.write_text(header + body.strip() + "\n", encoding="utf-8")
    return path


def ingest_entry(entry: dict) -> dict:
    url = entry["url"]
    try:
        data, ctype = fetch_url(url)
    except Exception as exc:
        return {"id": entry["id"], "ok": False, "error": str(exc)}

    if "pdf" in ctype.lower() or url.lower().endswith(".pdf"):
        pdf_path = OUT_DIR / f"{entry['id']}.pdf"
        pdf_path.write_bytes(data)
        return {"id": entry["id"], "ok": True, "path": str(pdf_path), "bytes": len(data)}

    text = data.decode("utf-8", errors="replace")
    if "<html" in text.lower() or "<body" in text.lower():
        text = _strip_html(text)
    if len(text) < 400:
        return {"id": entry["id"], "ok": False, "error": "too_little_text_or_paywall", "chars": len(text)}
    path = write_markdown(entry, compact_text(text)[:80_000])
    return {"id": entry["id"], "ok": True, "path": str(path), "chars": len(text)}


def ingest_all(only_ids: list[str] | None = None) -> list[dict]:
    results = []
    for entry in load_catalog():
        if entry.get("skip_fetch"):
            results.append({"id": entry["id"], "ok": False, "error": "skip_fetch"})
            continue
        if only_ids and entry["id"] not in only_ids:
            continue
        results.append(ingest_entry(entry))
    return results


def compact_documents() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in OUT_DIR.glob("*.md"):
        original = path.read_text(encoding="utf-8", errors="replace")
        path.write_text(compact_text(original) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import json
    import sys

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if sys.argv[1:] == ["--compact"]:
        compact_documents()
        print("compacted", len(list(OUT_DIR.glob("*.md"))), "markdown files")
        raise SystemExit(0)
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    results = ingest_all(only or None)
    ok = sum(1 for r in results if r.get("ok"))
    print(json.dumps({"ok": ok, "total": len(results)}, indent=2))
    for row in results:
        print(row)
