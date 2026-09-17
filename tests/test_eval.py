import pytest

from evals.runner import load_bundle, score_offline


def _offline_cases() -> list[dict]:
    bundle = load_bundle()
    return [c for c in bundle["cases"] if c.get("suite") not in {"retrieve", "live"}]


@pytest.mark.parametrize("case", _offline_cases(), ids=lambda c: c["id"])
def test_offline_eval_case(case: dict) -> None:
    outcome = score_offline(load_bundle(), case)
    assert not outcome.skipped
    failed = [c for c in outcome.checks if not c.ok]
    assert not failed, "; ".join(f"{c.name}: {c.detail}" for c in failed)
