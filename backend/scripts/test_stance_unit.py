"""Unit tests for relationship stage decision (no network)."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.life.thought.prompt import SECOND_HOP_NOTE, build_thought_system, second_hop_system
from app.planner.prompts import build_planner_system_base, select_planner_system
from app.relationship.stance import (
    apply_day,
    parse_observation,
    validate_observation,
)
from app.relationship.stance_schema import (
    DEFAULT_STAGE,
    STAGE_FRIEND,
    STAGE_LOVER,
    STAGE_STEADY,
    PatchProposal,
    StageObservation,
    StanceState,
)
from app.relationship.stance_store import StanceStore


def _fail(msg: str) -> None:
    raise AssertionError(msg)


def _obs(
    stage: str,
    confidence: str,
    *,
    evidence: list[str] | None = None,
    patch: PatchProposal | None = None,
) -> StageObservation:
    return StageObservation(
        target_stage=stage,
        confidence=confidence,
        evidence=evidence
        or ["[2026-09-01 12:00:00 面对面交流] 老师：你好啊"],
        rationale="unit",
        personal_patch=patch or PatchProposal(),
    )


def _day_text(*snippets: str) -> str:
    return "\n".join(snippets)


def test_prompt_order() -> None:
    print("== prompt section order ==")
    text = build_planner_system_base(stage=STAGE_STEADY)
    for title in ("## 身份", "## 口吻", "## 性格", "## 语气锚定", "## 个性化补丁", "## 边界"):
        if title not in text:
            _fail(f"missing {title}")
    order = [text.index(t) for t in ("## 身份", "## 口吻", "## 性格", "## 语气锚定", "## 个性化补丁", "## 边界")]
    if order != sorted(order):
        _fail(f"section order wrong: {order}")
    if "服从气候" not in text:
        _fail("climate priority missing")
    thought = build_thought_system(stage=STAGE_FRIEND, patch="叫我小老师")
    if "## 语气锚定" in thought:
        _fail("thought prompt should omit tone anchors")
    if "助手与朋友" not in thought or "叫我小老师" not in thought:
        _fail("thought stage/patch missing")
    if "不把内心写成分析报告" not in thought:
        _fail("thought output rule missing")
    second = second_hop_system(stage=STAGE_LOVER)
    if SECOND_HOP_NOTE not in second or "助手与恋人" not in second:
        _fail("second hop should keep stage overlay")


def test_evidence_gate() -> None:
    print("== evidence validation ==")
    day = _day_text(
        "[2026-09-01 12:00:00 面对面交流] 老师：想和你在一起",
        "[2026-09-01 12:00:01 面对面交流] 阿洛娜：诶……",
        "[2026-09-01 12:00:02 面对面交流] 互动：摸头",
    )
    ok = _obs(
        STAGE_LOVER,
        "high",
        evidence=["[2026-09-01 12:00:00 面对面交流] 老师：想和你在一起"],
    )
    if validate_observation(ok, day_text=day, committed_stage=STAGE_STEADY):
        _fail("valid lover evidence should pass")
    bad = _obs(STAGE_LOVER, "high", evidence=["老师：不存在的话"])
    if validate_observation(bad, day_text=day, committed_stage=STAGE_STEADY) != "evidence_not_in_source":
        _fail("fabricated evidence must fail")
    alone = _obs(
        STAGE_LOVER,
        "high",
        evidence=["[2026-09-01 12:00:01 面对面交流] 阿洛娜：诶……"],
    )
    if (
        validate_observation(alone, day_text=day, committed_stage=STAGE_STEADY)
        != "missing_teacher_evidence"
    ):
        _fail("Arona-only evidence must fail when changing stage")
    touch = _obs(
        STAGE_LOVER,
        "high",
        evidence=["[2026-09-01 12:00:02 面对面交流] 互动：摸头"],
    )
    if (
        validate_observation(touch, day_text=day, committed_stage=STAGE_STEADY)
        != "lover_touch_only"
    ):
        _fail("touch-only must not promote to lover")


def test_promote_three_days() -> None:
    print("== promote in 3 high-ending days ==")
    state = StanceState(committed_stage=STAGE_STEADY)
    evidence = ["[t] 老师：我想和你在一起"]
    day_text = evidence[0]
    start = date(2026, 9, 1)
    for i, conf in enumerate(("medium", "low", "high")):
        result = apply_day(
            state,
            day=start + timedelta(days=i),
            kind="observation",
            observation=_obs(STAGE_LOVER, conf, evidence=evidence),
            day_text=day_text,
            promote_days=3,
            demote_days=30,
        )
        state = result.state
        if i < 2 and result.changed_stage:
            _fail("should not promote before day 3")
        if i == 2 and (not result.changed_stage or state.committed_stage != STAGE_LOVER):
            _fail("day 3 high should promote")

    # Non-high ending day does not promote; streak continues.
    state2 = StanceState(committed_stage=STAGE_FRIEND)
    for i, conf in enumerate(("medium", "medium", "medium")):
        result = apply_day(
            state2,
            day=start + timedelta(days=i),
            kind="observation",
            observation=_obs(STAGE_LOVER, conf, evidence=evidence),
            day_text=day_text,
        )
        state2 = result.state
        if result.changed_stage:
            _fail("medium ending must not promote")
    result = apply_day(
        state2,
        day=start + timedelta(days=3),
        kind="observation",
        observation=_obs(STAGE_LOVER, "high", evidence=evidence),
        day_text=day_text,
    )
    if not result.changed_stage or result.state.committed_stage != STAGE_LOVER:
        _fail("fourth day high after 3 same-stage days should promote")


def test_demote_thirty_days() -> None:
    print("== demote after 30 days ==")
    state = StanceState(committed_stage=STAGE_LOVER)
    evidence = ["[t] 老师：今天帮我查一下文件"]
    start = date(2026, 1, 1)
    for i in range(29):
        result = apply_day(
            state,
            day=start + timedelta(days=i),
            kind="observation",
            observation=_obs(STAGE_FRIEND, "medium", evidence=evidence),
            day_text=evidence[0],
            demote_days=30,
        )
        state = result.state
        if result.changed_stage:
            _fail("should not demote before day 30")
    result = apply_day(
        state,
        day=start + timedelta(days=29),
        kind="observation",
        observation=_obs(STAGE_FRIEND, "high", evidence=evidence),
        day_text=evidence[0],
        demote_days=30,
    )
    if not result.changed_stage or result.state.committed_stage != STAGE_FRIEND:
        _fail("day 30 high should demote")


def test_streak_breaks() -> None:
    print("== streak breaks on empty / stage change ==")
    state = StanceState(committed_stage=STAGE_STEADY)
    evidence = ["[t] 老师：喜欢你"]
    start = date(2026, 3, 1)
    for i in range(2):
        state = apply_day(
            state,
            day=start + timedelta(days=i),
            kind="observation",
            observation=_obs(STAGE_LOVER, "high", evidence=evidence),
            day_text=evidence[0],
        ).state
    state = apply_day(state, day=start + timedelta(days=2), kind="empty").state
    result = apply_day(
        state,
        day=start + timedelta(days=3),
        kind="observation",
        observation=_obs(STAGE_LOVER, "high", evidence=evidence),
        day_text=evidence[0],
    )
    if result.changed_stage:
        _fail("empty day must break promote streak")

    state = StanceState(committed_stage=STAGE_STEADY)
    state = apply_day(
        state,
        day=start,
        kind="observation",
        observation=_obs(STAGE_LOVER, "high", evidence=evidence),
        day_text=evidence[0],
    ).state
    other = ["[t] 老师：今天天气不错"]
    state = apply_day(
        state,
        day=start + timedelta(days=1),
        kind="observation",
        observation=_obs(STAGE_FRIEND, "high", evidence=other),
        day_text=other[0],
    ).state
    result = apply_day(
        state,
        day=start + timedelta(days=2),
        kind="observation",
        observation=_obs(STAGE_LOVER, "high", evidence=evidence),
        day_text=evidence[0],
    )
    if result.changed_stage:
        _fail("target stage change must reset streak")


def test_patch_ops() -> None:
    print("== personal patch keep/set/clear ==")
    state = StanceState(committed_stage=DEFAULT_STAGE)
    day = "[t] 老师：以后叫我小老师吧"
    keep = apply_day(
        state,
        day=date(2026, 4, 1),
        kind="observation",
        observation=_obs(
            STAGE_STEADY,
            "high",
            evidence=[day],
            patch=PatchProposal(op="keep"),
        ),
        day_text=day,
    )
    if keep.changed_patch or keep.state.personal_patch:
        _fail("keep must not change patch")

    set_result = apply_day(
        keep.state,
        day=date(2026, 4, 2),
        kind="observation",
        observation=_obs(
            STAGE_STEADY,
            "high",
            evidence=[day],
            patch=PatchProposal(op="set", text="老师希望被叫小老师。", evidence=[day]),
        ),
        day_text=day,
    )
    if not set_result.changed_patch or "小老师" not in set_result.state.personal_patch:
        _fail("set should store nickname patch")

    long_text = "x" * 201
    too_long = apply_day(
        set_result.state,
        day=date(2026, 4, 3),
        kind="observation",
        observation=_obs(
            STAGE_STEADY,
            "high",
            evidence=[day],
            patch=PatchProposal(op="set", text=long_text, evidence=[day]),
        ),
        day_text=day,
        patch_max_chars=200,
    )
    if too_long.changed_patch or too_long.state.personal_patch != set_result.state.personal_patch:
        _fail("oversized patch must be rejected without clearing old patch")

    cleared = apply_day(
        too_long.state,
        day=date(2026, 4, 4),
        kind="observation",
        observation=_obs(
            STAGE_STEADY,
            "high",
            evidence=[day],
            patch=PatchProposal(op="clear", evidence=[day]),
        ),
        day_text=day,
    )
    if not cleared.changed_patch or cleared.state.personal_patch:
        _fail("clear should wipe patch")


def test_parse_and_store() -> None:
    print("== parse + persist ==")
    raw = (
        '{"target_stage":"挚友","confidence":"medium","evidence":["老师：你好"],'
        '"rationale":"平稳","personal_patch":{"op":"keep","text":"","evidence":[]}}'
    )
    obs, reason = parse_observation(raw)
    if obs is None or reason:
        _fail(f"parse failed {reason}")
    bad, reason = parse_observation('{"target_stage":"闺蜜","confidence":"high","evidence":["a"]}')
    if bad is not None or reason != "bad_stage":
        _fail("invented stage must be rejected")

    path = Path(__file__).resolve().parent / "_tmp_stance.json"
    try:
        store = StanceStore(path)
        state = StanceState(committed_stage=STAGE_FRIEND, personal_patch="叫我小老师")
        store.save(state)
        loaded = store.load()
        if loaded.committed_stage != STAGE_FRIEND or loaded.personal_patch != "叫我小老师":
            _fail("store roundtrip failed")
    finally:
        if path.is_file():
            path.unlink()


def test_default_steady_matches_old_voice() -> None:
    print("== default steady keeps old voice lines ==")
    text = select_planner_system(renderer_enabled=True)
    for needle in (
        "亲密语境下害羞、撒娇",
        "对老师有喜欢的情感",
        "我等您很久啦",
        "不要理阿洛娜了",
    ):
        if needle not in text:
            _fail(f"missing steady line: {needle}")


def main() -> None:
    test_prompt_order()
    test_evidence_gate()
    test_promote_three_days()
    test_demote_thirty_days()
    test_streak_breaks()
    test_patch_ops()
    test_parse_and_store()
    test_default_steady_matches_old_voice()
    print("OK")


if __name__ == "__main__":
    main()
