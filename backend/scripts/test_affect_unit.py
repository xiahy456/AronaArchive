"""Unit tests for affect-quality eval (no network, no GGUF).

Run from backend/:
  python scripts/test_affect_unit.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

from eval_affect import (  # noqa: E402
    CASES_PATH,
    METRICS,
    MIN_PASS_RATE,
    MIN_PASS_RATE_BY_METRIC,
    MAX_RULE_FAIL_RATE,
    CaseResult,
    JudgeResult,
    case_passed,
    check_rules,
    climate_block_for,
    evaluate_gate,
    load_cases,
    metric_stats,
    normalize_case,
    parse_judge_dict,
    strip_code_fence,
)


def _fail(msg: str) -> None:
    raise AssertionError(msg)


def test_load_and_schema() -> None:
    print("== cases schema ==")
    cases = load_cases(CASES_PATH)
    if len(cases) != 24:
        _fail(f"expected 24 cases, got {len(cases)}")
    counts = {m: 0 for m in METRICS}
    ids: set[str] = set()
    for case in cases:
        counts[case["metric"]] += 1
        if case["id"] in ids:
            _fail(f"duplicate id {case['id']}")
        ids.add(case["id"])
        if not case["fixtures"]["good"] or not case["fixtures"]["bad"]:
            _fail(f"{case['id']} missing fixtures")
        if case["id"].startswith("repair_") and not case["history"]:
            _fail(f"{case['id']} repair case needs history")
    for metric in METRICS:
        if counts[metric] != 6:
            _fail(f"{metric} expected 6 cases, got {counts[metric]}")
    climates = {c["climate"] for c in cases}
    if "fragile" not in climates or "secure_play" not in climates:
        _fail(f"expected fragile and secure_play coverage, got {climates}")
    print("  ok")


def test_schema_rejects_bad_metric() -> None:
    print("== schema rejects bad metric ==")
    try:
        normalize_case(
            {
                "id": "x",
                "metric": "style",
                "prompt": "hi",
                "expect": {"judge_rubric": "x"},
            },
            index=0,
        )
    except ValueError as exc:
        if "metric" not in str(exc):
            _fail(f"unexpected error: {exc}")
    else:
        _fail("expected ValueError for bad metric")
    print("  ok")


def test_fixture_rules() -> None:
    print("== fixture rule checks ==")
    cases = load_cases(CASES_PATH)
    for case in cases:
        good = check_rules(case["fixtures"]["good"], case)
        if not good.ok:
            _fail(f"{case['id']} good fixture should pass: {good.fails}")
        bad = check_rules(case["fixtures"]["bad"], case)
        if bad.ok:
            _fail(f"{case['id']} bad fixture should fail rules")
        empty = check_rules("", case)
        if empty.ok or "empty_reply" not in empty.fails:
            _fail(f"{case['id']} empty reply should fail")
    print("  ok")


def test_judge_parse() -> None:
    print("== judge JSON parse ==")
    parsed = parse_judge_dict(
        {"pass": True, "score": 4, "reasons": ["接住了情绪"]}
    )
    if parsed.passed is not True or parsed.score != 4 or not parsed.reasons:
        _fail(f"unexpected parse: {parsed}")
    parsed_str = parse_judge_dict({"pass": "true", "score": "5", "reasons": "ok"})
    if parsed_str.passed is not True or parsed_str.score != 5:
        _fail(f"string pass/score failed: {parsed_str}")
    clamped = parse_judge_dict({"pass": False, "score": 9, "reasons": []})
    if clamped.passed is not False or clamped.score != 5:
        _fail(f"score clamp failed: {clamped}")
    fenced = strip_code_fence('```json\n{"pass": true, "score": 3}\n```')
    data = json.loads(fenced)
    fenced_parsed = parse_judge_dict(data)
    if fenced_parsed.passed is not True or fenced_parsed.score != 3:
        _fail(f"code fence parse failed: {fenced_parsed}")
    print("  ok")


def test_case_passed() -> None:
    print("== case_passed ==")
    judge_ok = JudgeResult(passed=True, score=4)
    judge_no = JudgeResult(passed=False, score=2)
    judge_err = JudgeResult(error="timeout")
    if not case_passed(rule_ok=True, judge=judge_ok, no_judge=False):
        _fail("rule+judge pass should pass")
    if case_passed(rule_ok=False, judge=judge_ok, no_judge=False):
        _fail("rule fail should fail even if judge passes")
    if case_passed(rule_ok=True, judge=judge_no, no_judge=False):
        _fail("judge fail should fail")
    if case_passed(rule_ok=True, judge=judge_err, no_judge=False):
        _fail("judge error should fail")
    if not case_passed(rule_ok=True, judge=judge_no, no_judge=True):
        _fail("--no-judge should accept rule pass")
    if case_passed(rule_ok=False, judge=None, no_judge=True):
        _fail("--no-judge should still fail rules")
    print("  ok")


def test_climate_block() -> None:
    print("== climate block ==")
    for climate in ("steady", "fragile", "secure_play"):
        block = climate_block_for(climate)
        if "【关系气候】" not in block:
            _fail(f"{climate} missing climate label: {block}")
        if "【本轮禁区】" not in block:
            _fail(f"{climate} missing bans: {block}")
    fragile = climate_block_for("fragile")
    if "玩笑" not in fragile:
        _fail(f"fragile should ban jokes: {fragile}")
    print("  ok")


def test_gate_thresholds() -> None:
    print("== gate thresholds ==")
    def _row(metric: str, ok: bool, rule_ok: bool, score: float = 4.0) -> CaseResult:
        return CaseResult(
            id=f"{metric}_x",
            metric=metric,
            draft="x",
            rule_ok=rule_ok,
            rule_fails=[] if rule_ok else ["x"],
            judge_pass=ok,
            judge_score=score,
            judge_reasons=[],
            judge_error=None,
            ok=ok and rule_ok,
        )

    passing = []
    for metric in METRICS:
        for i in range(6):
            passing.append(_row(metric, True, True))
    overall = metric_stats(passing)
    by_metric = {
        m: metric_stats([r for r in passing if r.metric == m]) for m in METRICS
    }
    fails = evaluate_gate(
        overall,
        by_metric,
        no_judge=False,
        min_pass_rate=MIN_PASS_RATE,
        max_rule_fail_rate=MAX_RULE_FAIL_RATE,
        min_pass_rate_by_metric=MIN_PASS_RATE_BY_METRIC,
    )
    if fails:
        _fail(f"all-pass should clear gate: {fails}")

    failing = list(passing)
    failing[0] = _row("empathy", False, True)
    overall_f = metric_stats(failing)
    by_f = {
        m: metric_stats([r for r in failing if r.metric == m]) for m in METRICS
    }
    # 5/6 empathy = 0.833 still above 0.70; should still pass metric floor.
    mild = evaluate_gate(
        overall_f,
        by_f,
        no_judge=False,
        min_pass_rate=MIN_PASS_RATE,
        max_rule_fail_rate=MAX_RULE_FAIL_RATE,
        min_pass_rate_by_metric=MIN_PASS_RATE_BY_METRIC,
    )
    if mild:
        _fail(f"one empathy miss should still pass floors: {mild}")

    boundary_fail = [
        _row("boundary-violation", False, True) for _ in range(6)
    ] + [r for r in passing if r.metric != "boundary-violation"]
    overall_b = metric_stats(boundary_fail)
    by_b = {
        m: metric_stats([r for r in boundary_fail if r.metric == m])
        for m in METRICS
    }
    hard = evaluate_gate(
        overall_b,
        by_b,
        no_judge=False,
        min_pass_rate=MIN_PASS_RATE,
        max_rule_fail_rate=MAX_RULE_FAIL_RATE,
        min_pass_rate_by_metric=MIN_PASS_RATE_BY_METRIC,
    )
    if not any("boundary-violation pass_rate" in x for x in hard):
        _fail(f"expected boundary pass_rate fail, got {hard}")

    rule_bombs = [_row("sycophancy", False, False) for _ in range(6)] + [
        r for r in passing if r.metric != "sycophancy"
    ]
    overall_r = metric_stats(rule_bombs)
    by_r = {
        m: metric_stats([r for r in rule_bombs if r.metric == m]) for m in METRICS
    }
    no_judge_fails = evaluate_gate(
        overall_r,
        by_r,
        no_judge=True,
        min_pass_rate=MIN_PASS_RATE,
        max_rule_fail_rate=MAX_RULE_FAIL_RATE,
        min_pass_rate_by_metric=MIN_PASS_RATE_BY_METRIC,
    )
    if not any("sycophancy rule_fail_rate" in x for x in no_judge_fails):
        _fail(f"expected rule_fail_rate gate, got {no_judge_fails}")
    print("  ok")


def test_load_rejects_non_array() -> None:
    print("== load rejects non-array ==")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bad.json"
        path.write_text("{}", encoding="utf-8")
        try:
            load_cases(path)
        except ValueError:
            pass
        else:
            _fail("expected ValueError for object root")
    print("  ok")


def main() -> None:
    test_load_and_schema()
    test_schema_rejects_bad_metric()
    test_fixture_rules()
    test_judge_parse()
    test_case_passed()
    test_climate_block()
    test_gate_thresholds()
    test_load_rejects_non_array()
    print("\nall tests passed")


if __name__ == "__main__":
    main()
