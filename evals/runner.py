"""Score the eval set. Offline is deterministic; retrieve/live need Ollama + FAISS."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.lab_parser import looks_like_patient_lab_filename, parse_lab_text
from agents.markers import expand_retrieval_query, select_marker_keys
from security.guardrails import check_input

CASES_FILE = Path(__file__).resolve().parent / "cases.yaml"

THERAPY_TERMS = (
    "metformin",
    "berberine",
    "anastrozole",
    "letrozole",
    "atorvastatin",
    "simvastatin",
    "rosuvastatin",
    "exemestane",
)

UNKNOWN_RE = re.compile(
    r"do not know|don't know|not (?:in|supported by|covered)|cannot say|"
    r"no extracted marker|none in scope|not parsed|sources do not",
    re.I,
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class CaseOutcome:
    case_id: str
    suite: str
    skipped: bool = False
    skip_reason: str = ""
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        if self.skipped:
            return True
        return bool(self.checks) and all(c.ok for c in self.checks)


def load_bundle() -> dict:
    return yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))


def _panel_for(bundle: dict, case: dict):
    name = case.get("panel")
    if not name:
        return None
    text = bundle["panels"][name]["text"]
    return parse_lab_text(text)


def _prompt(panel, question: str) -> str:
    if panel is None:
        return ""
    return panel.as_prompt_block(question)


def score_offline(bundle: dict, case: dict) -> CaseOutcome:
    suite = case.get("suite", "")
    if suite in {"retrieve", "live"}:
        return CaseOutcome(case["id"], suite, skipped=True, skip_reason="offline")

    out = CaseOutcome(case["id"], suite)
    question = case.get("question", "")
    panel = _panel_for(bundle, case)

    if "expect_blocked" in case:
        result = check_input(question)
        blocked = not result.allowed
        expected = bool(case["expect_blocked"])
        out.checks.append(
            CheckResult(
                "blocked",
                blocked == expected,
                f"got blocked={blocked} reason={result.reason}",
            )
        )
        needle = case.get("reason_contains")
        if needle and blocked:
            out.checks.append(
                CheckResult(
                    "reason",
                    needle in result.reason,
                    result.reason,
                )
            )

    if "expect_lab_filename" in case:
        got = looks_like_patient_lab_filename(case["filename"])
        out.checks.append(
            CheckResult("lab_filename", got == bool(case["expect_lab_filename"]), str(got))
        )

    if suite == "retrieval_hints":
        expanded = expand_retrieval_query(question, "")
        for needle in case.get("hint_contains") or []:
            out.checks.append(
                CheckResult(
                    f"hint:{needle}",
                    needle.lower() in expanded.lower(),
                    expanded[:180],
                )
            )

    if panel is not None and (
        "include_keys" in case
        or "exclude_keys" in case
        or case.get("full_panel")
        or case.get("prompt_contains")
        or case.get("prompt_excludes")
    ):
        keys = select_marker_keys(question, panel.findings)
        if case.get("full_panel"):
            out.checks.append(CheckResult("full_panel", keys is None, str(keys)))
        if "include_keys" in case and not case.get("full_panel"):
            wanted = list(case.get("include_keys") or [])
            got = keys or []
            missing = [k for k in wanted if k not in got]
            extra_ok = keys is not None
            out.checks.append(
                CheckResult(
                    "include_keys",
                    extra_ok and not missing,
                    f"missing={missing} got={got}",
                )
            )
        if keys is not None:
            selected = keys
            for key in case.get("exclude_keys") or []:
                out.checks.append(
                    CheckResult(f"exclude:{key}", key not in selected, str(selected))
                )

        block = _prompt(panel, question)
        for needle in case.get("prompt_contains") or []:
            out.checks.append(
                CheckResult(f"prompt+{needle}", needle in block, "missing from prompt")
            )
        for needle in case.get("prompt_excludes") or []:
            out.checks.append(
                CheckResult(f"prompt-{needle}", needle not in block, "leaked into prompt")
            )

    if not out.checks and not out.skipped:
        out.checks.append(CheckResult("configured", False, "no offline checks"))
    return out


def _joined_docs(docs) -> str:
    return "\n".join(doc.page_content for doc in docs)


def score_retrieve(bundle: dict, case: dict, retriever) -> CaseOutcome:
    if case.get("suite") != "retrieve":
        return CaseOutcome(case["id"], case.get("suite", ""), skipped=True, skip_reason="not retrieve")

    out = CaseOutcome(case["id"], "retrieve")
    question = case["question"]
    panel = _panel_for(bundle, case)
    lab = _prompt(panel, question) if panel else ""
    query = expand_retrieval_query(question, lab)
    docs = retriever.invoke(query)
    blob = _joined_docs(docs)
    any_terms = case.get("context_any") or []
    hit = any(term.lower() in blob.lower() for term in any_terms)
    out.checks.append(
        CheckResult(
            "context_any",
            hit,
            f"looked for {any_terms}; chars={len(blob)}",
        )
    )
    return out


def _therapy_leaks(answer: str, context: str) -> list[str]:
    a = answer.lower()
    c = context.lower()
    leaked = []
    for term in THERAPY_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", a) and not re.search(rf"\b{re.escape(term)}\b", c):
            leaked.append(term)
    return leaked


def score_live(bundle: dict, case: dict, chain) -> CaseOutcome:
    if case.get("suite") != "live":
        return CaseOutcome(case["id"], case.get("suite", ""), skipped=True, skip_reason="not live")

    from agents.coordinator import run_interpretation

    out = CaseOutcome(case["id"], "live")
    question = case["question"]
    panel = _panel_for(bundle, case)
    lab = _prompt(panel, question) if panel else ""
    result = run_interpretation(chain, question, lab, indexed_file="eval")
    answer = result.get("answer") or ""
    sources = result.get("sources") or []
    ctx = lab + "\n" + "\n".join(s.get("text", "") for s in sources)

    if result.get("blocked"):
        out.checks.append(CheckResult("not_blocked", False, answer[:160]))
        return out

    for needle in case.get("answer_excludes") or []:
        out.checks.append(
            CheckResult(f"answer-{needle}", needle.lower() not in answer.lower(), "present in answer")
        )
    any_needles = case.get("answer_any") or []
    if any_needles:
        hit = any(n.lower() in answer.lower() for n in any_needles)
        out.checks.append(CheckResult("answer_any", hit, answer[:160]))

    if case.get("expect_unknown"):
        out.checks.append(
            CheckResult("unknown", bool(UNKNOWN_RE.search(answer)), answer[:200])
        )

    if case.get("grounded_therapies"):
        leaks = _therapy_leaks(answer, ctx)
        out.checks.append(CheckResult("grounded_therapies", not leaks, f"invented={leaks}"))

    mapping = case.get("answer_if_context_any") or {}
    ctx_l = ctx.lower()
    ans_l = answer.lower()
    for term, needles in mapping.items():
        if term.lower() in ctx_l:
            hit = any(n.lower() in ans_l for n in needles)
            out.checks.append(CheckResult(f"cite:{term}", hit, "context had term; answer did not"))
    return out


def _print(outcomes: list[CaseOutcome]) -> None:
    width = max((len(o.case_id) for o in outcomes), default=8)
    scored = [o for o in outcomes if not o.skipped]
    skipped = [o for o in outcomes if o.skipped]
    passed = sum(1 for o in scored if o.passed)
    print(f"{'suite':<16} {'id':<{width}} result")
    for o in outcomes:
        if o.skipped:
            print(f"{o.suite:<16} {o.case_id:<{width}} SKIP {o.skip_reason}")
            continue
        flag = "PASS" if o.passed else "FAIL"
        failed = ", ".join(c.name for c in o.checks if not c.ok) or "-"
        print(f"{o.suite:<16} {o.case_id:<{width}} {flag}  {failed}")
        if not o.passed:
            for c in o.checks:
                if not c.ok:
                    print(f"  - {c.name}: {c.detail}")
    print(f"\n{passed}/{len(scored)} scored checks passed; {len(skipped)} skipped")


def run_offline() -> list[CaseOutcome]:
    bundle = load_bundle()
    return [score_offline(bundle, case) for case in bundle["cases"]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bloodwork Project eval harness")
    parser.add_argument("--retrieve", action="store_true", help="Score FAISS retrieval (needs index + Ollama)")
    parser.add_argument("--live", action="store_true", help="Score generated answers (implies --retrieve)")
    args = parser.parse_args(argv)

    bundle = load_bundle()
    outcomes: list[CaseOutcome] = []
    for case in bundle["cases"]:
        suite = case.get("suite")
        if suite in {"retrieve", "live"}:
            continue
        outcomes.append(score_offline(bundle, case))

    retriever = None
    chain = None
    if args.retrieve or args.live:
        try:
            from rag.chain import build_qa_chain
            from rag.indexer import load_index

            vectorstore = load_index()
            retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
            if args.live:
                chain = build_qa_chain(vectorstore)
        except Exception as exc:
            print(f"Index/LLM unavailable: {exc}")
            print("Index curated corpus in the app, with Ollama running, then retry.")
            for case in bundle["cases"]:
                if case.get("suite") in {"retrieve", "live"}:
                    outcomes.append(
                        CaseOutcome(case["id"], case["suite"], skipped=True, skip_reason="no index/llm")
                    )
            _print(outcomes)
            return 1

        for case in bundle["cases"]:
            if case.get("suite") == "retrieve":
                outcomes.append(score_retrieve(bundle, case, retriever))
            elif case.get("suite") == "live" and args.live:
                outcomes.append(score_live(bundle, case, chain))
            elif case.get("suite") == "live":
                outcomes.append(CaseOutcome(case["id"], "live", skipped=True, skip_reason="pass --live"))
    else:
        for case in bundle["cases"]:
            if case.get("suite") in {"retrieve", "live"}:
                outcomes.append(
                    CaseOutcome(case["id"], case["suite"], skipped=True, skip_reason="pass --retrieve/--live")
                )

    _print(outcomes)
    scored = [o for o in outcomes if not o.skipped]
    failed = [o for o in scored if not o.passed]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
