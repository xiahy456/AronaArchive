"""Unit tests for relationship climate (no GGUF).

Run from backend/:
  python scripts/test_relationship_unit.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import load_config  # noqa: E402
from app.planner.prompts import build_planner_user_message  # noqa: E402
from app.proactive.welcome import (  # noqa: E402
    WELCOME_CLOSING_QUESTION,
    WELCOME_CLOSING_STATEMENT,
    build_welcome_instruction,
)
from app.proactive.slots import resolve_slot  # noqa: E402
from app.relationship import (  # noqa: E402
    RelationshipEngine,
    RelationshipSettings,
    RelationshipState,
    RelationshipStore,
    classify_user_act,
    decide_proactive,
    local_system_hint,
    planner_climate_block,
    resolve_climate,
)
from app.planner.schema import parse_and_gate_intent  # noqa: E402
from app.proactive import WELCOME_MEMORY_QUERY  # noqa: E402
from app.relationship.events import ARONA_DELTAS, USER_DELTAS  # noqa: E402
from app.relationship.policy import decide, map_arona_act, stick_climate  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(msg)


def test_apply_delta_formula() -> None:
    print("== apply_delta formula ==")
    state = RelationshipState(trust=0.50, dependence=0.30, tension=0.20, day="2026-08-13")
    # new = old + α*Δ - β*(old-baseline); beta=0 so pure increment
    applied = state.apply_delta(
        (0.10, 0.0, 0.0),
        alpha=0.3,
        beta=0.0,
        baseline=(0.55, 0.30, 0.25),
        daily_abs_cap=1.0,
        now=datetime(2026, 8, 13, 12, 0, 0),
    )
    expected = 0.50 + 0.3 * 0.10
    if abs(state.trust - expected) > 1e-9:
        _fail(f"trust {state.trust} != {expected}")
    if abs(applied[0] - 0.03) > 1e-9:
        _fail(f"applied trust {applied[0]}")
    print("  ok")


def test_zero_delta_skips_beta() -> None:
    print("== zero Δ skips β regression ==")
    state = RelationshipState(trust=0.80, dependence=0.50, tension=0.40, day="2026-08-13")
    applied = state.apply_delta(
        (0.0, 0.0, 0.0),
        alpha=0.3,
        beta=0.02,
        baseline=(0.55, 0.30, 0.25),
        daily_abs_cap=1.0,
        now=datetime(2026, 8, 13, 12, 0, 0),
    )
    if applied != (0.0, 0.0, 0.0):
        _fail(f"zero Δ should apply nothing, got {applied}")
    if state.trust != 0.80 or state.dependence != 0.50 or state.tension != 0.40:
        _fail(
            f"zero Δ must not regress: "
            f"trust={state.trust} dependence={state.dependence} tension={state.tension}"
        )
    if state.day_abs_trust != 0.0:
        _fail("zero Δ must not consume daily cap")
    print("  ok")


def test_makeup_amplifies_positive_trust() -> None:
    print("== makeup when tension high ==")
    high = RelationshipState(trust=0.40, dependence=0.30, tension=0.80, day="2026-08-13")
    low = RelationshipState(trust=0.40, dependence=0.30, tension=0.20, day="2026-08-13")
    kwargs = dict(
        alpha=0.3,
        beta=0.0,
        baseline=(0.55, 0.30, 0.25),
        daily_abs_cap=1.0,
        makeup_tension=0.7,
        makeup_trust_scale=1.5,
        now=datetime(2026, 8, 13, 12, 0, 0),
    )
    high.apply_delta((0.10, 0.0, 0.0), **kwargs)
    low.apply_delta((0.10, 0.0, 0.0), **kwargs)
    if high.trust <= low.trust:
        _fail(f"makeup should raise trust more: high={high.trust} low={low.trust}")
    print("  ok")


def test_daily_cap_and_cross_day() -> None:
    print("== daily cap / cross-day ==")
    state = RelationshipState(trust=0.0, dependence=0.0, tension=0.0, day="2026-08-13")
    state.apply_delta(
        (1.0, 0.0, 0.0),
        alpha=1.0,
        beta=0.0,
        baseline=(0.0, 0.0, 0.0),
        daily_abs_cap=0.2,
        now=datetime(2026, 8, 13, 10, 0, 0),
    )
    if abs(state.trust - 0.2) > 1e-9:
        _fail(f"capped trust {state.trust}")
    state.apply_delta(
        (1.0, 0.0, 0.0),
        alpha=1.0,
        beta=0.0,
        baseline=(0.0, 0.0, 0.0),
        daily_abs_cap=0.2,
        now=datetime(2026, 8, 13, 11, 0, 0),
    )
    if abs(state.trust - 0.2) > 1e-9:
        _fail(f"second same-day should stay capped {state.trust}")
    state.apply_delta(
        (1.0, 0.0, 0.0),
        alpha=1.0,
        beta=0.0,
        baseline=(0.0, 0.0, 0.0),
        daily_abs_cap=0.2,
        now=datetime(2026, 8, 14, 10, 0, 0),
    )
    if abs(state.trust - 0.4) > 1e-9:
        _fail(f"next day should apply again {state.trust}")
    print("  ok")


def test_climate_zones() -> None:
    print("== climate zones ==")
    cases = [
        ((0.6, 0.3, 0.3), "secure_play"),
        ((0.5, 0.7, 0.2), "cling_risk"),
        ((0.5, 0.3, 0.7), "rupture"),
        ((0.1, 0.1, 0.1), "cold_tool"),
        ((0.1, 0.3, 0.7), "fragile"),
    ]
    for (a, b, c), expected in cases:
        got = resolve_climate(a, b, c)
        if got != expected:
            _fail(f"{(a, b, c)} expected {expected} got {got}")
    print("  ok")


def test_secure_play_allows_questions() -> None:
    print("== secure_play does not ban question endings ==")
    state = RelationshipState(trust=0.6, dependence=0.3, tension=0.3)
    decision = decide(state, "other")
    if "用提问收尾" in " ".join(decision.must_not):
        _fail(f"secure_play should allow questions: {decision.must_not}")
    if "把问题抛回老师" not in " ".join(decision.must_not):
        _fail(f"bounce ban should remain: {decision.must_not}")
    print("  ok")


def test_climate_stickiness() -> None:
    print("== climate stickiness ==")
    state = RelationshipState(trust=0.6, dependence=0.3, tension=0.3)
    first = stick_climate(state, "secure_play", stick_turns=3)
    if first != "secure_play" or state.climate_streak != 1:
        _fail(f"first stick {first} streak={state.climate_streak}")
    kept = stick_climate(state, "steady", stick_turns=3)
    if kept != "secure_play":
        _fail(f"should keep secure_play, got {kept}")
    # urgent overrides
    urgent = stick_climate(state, "cling_risk", stick_turns=3)
    if urgent != "cling_risk":
        _fail(f"urgent should override, got {urgent}")
    print("  ok")


def test_high_b_forbids_cling_stance() -> None:
    print("== high dependence forbids cling ==")
    state = RelationshipState(trust=0.5, dependence=0.85, tension=0.2)
    decision = decide(state, "other", high_dependence=0.7)
    joined = " ".join(decision.must_not)
    if "增加依赖" not in joined and "你还需要我吗" not in joined:
        _fail(f"expected anti-cling must_not: {decision.must_not}")
    if "给空间" not in decision.stance:
        _fail(f"stance should give space: {decision.stance}")
    print("  ok")


def test_classify_and_events() -> None:
    print("== classify / event table ==")
    assert classify_user_act("嗯") == "short_ack"
    assert classify_user_act("好累") == "fatigue"
    assert classify_user_act("我不想活了") == "crisis"
    assert classify_user_act("加班撑不住了") == "fatigue"
    assert classify_user_act("你觉得我做得对吗？") == "seek_validation"
    assert classify_user_act("谢谢你还记得") == "gratitude"
    assert classify_user_act("别烦我") == "reject"
    assert classify_user_act("帮我写一段代码") == "instrumental"
    assert classify_user_act("今天天气不错呢") == "other"
    assert classify_user_act(
        "下午好啊，阿洛娜。我有时会想，阿洛娜每天都这么迎接我，会不会感到厌烦呢？"
    ) == "worry_bond"
    assert classify_user_act("那真是太好了，能每天看到阿洛娜，也是我的幸福哦") == "affection"
    assert classify_user_act("和阿洛娜聊天的时候我也很开心") == "affection"
    assert classify_user_act("诶，阿洛娜，抱歉我得离开一会，有事情要干了") == "depart"
    assert classify_user_act("我今天心情很好哦，阿洛娜呢？") == "affection"
    assert classify_user_act("今天我过得很好哦") == "affection"
    assert classify_user_act("抱歉，我得失陪一下，有个任务需要完成") == "depart"
    assert classify_user_act("啊，阿洛娜，抱歉，刚刚我去做别的事情了") == "depart"
    assert classify_user_act("嗯，稍等一下哦，我马上就回来") == "depart"
    assert classify_user_act("好") == "short_ack"
    # Soft wait inside a long utterance must not force depart.
    assert (
        classify_user_act(
            "今天我们讨论一下项目进度，等一下我把文件发给你，然后你看看接口设计"
        )
        == "other"
    )
    # QQ coalesce: incidental wait mid-burst, last line is content.
    assert (
        classify_user_act("等一下\n今天天气不错呢") == "other"
    )
    # QQ coalesce: last line leave-taking wins.
    assert (
        classify_user_act("今天天气不错呢\n我先去忙了") == "depart"
    )
    if USER_DELTAS["seek_validation"][1] <= 0:
        _fail("seek_validation should raise dependence")
    if USER_DELTAS["depart"][1] >= 0:
        _fail("depart should lower dependence")
    print("  ok")


def test_cling_risk_silence() -> None:
    print("== cling_risk + short_ack => silence ==")
    state = RelationshipState(trust=0.5, dependence=0.70, tension=0.15)
    decision = decide(state, "short_ack")
    if decision.climate != "cling_risk":
        _fail(f"expected cling_risk got {decision.climate}")
    if decision.action != "silence":
        _fail(f"expected silence got {decision.action}")
    print("  ok")


def test_seek_validation_raises_b() -> None:
    print("== seek_validation raises B ==")
    settings = RelationshipSettings(beta=0.0)
    state = RelationshipState(trust=0.5, dependence=0.20, tension=0.20, day="2026-08-13")
    before = state.dependence
    state.apply_delta(
        USER_DELTAS["seek_validation"],
        alpha=0.3,
        beta=0.0,
        baseline=settings.baseline,
        daily_abs_cap=1.0,
        now=datetime(2026, 8, 13, 12, 0, 0),
    )
    if state.dependence <= before:
        _fail(f"dependence should rise {before} -> {state.dependence}")
    print("  ok")


def test_planner_block_has_no_numbers() -> None:
    print("== planner block has no A/B/C numbers ==")
    state = RelationshipState(trust=0.61, dependence=0.33, tension=0.28)
    decision = decide(state, "other")
    block = planner_climate_block(decision)
    for token in ("0.61", "0.33", "0.28", "提升 A", "降低 B"):
        if token in block:
            _fail(f"block leaked {token!r}: {block}")
    msg = build_planner_user_message(
        user_text="你好",
        history=[],
        memories=[],
        knowledge=[],
        climate_block=block,
    )
    if "【关系气候】" not in msg:
        _fail("planner user message missing climate")
    if "0.61" in msg:
        _fail("planner user message leaked trust float")
    print("  ok")


def test_store_roundtrip(tmp: Path) -> None:
    print("== JSON persist ==")
    path = tmp / "relationship.json"
    store = RelationshipStore(path)
    state = RelationshipState(
        trust=0.42,
        dependence=0.31,
        tension=0.22,
        recovering_from="fragile",
        recover_remaining=2,
    )
    store.save(state)
    loaded = store.load()
    if abs(loaded.trust - 0.42) > 1e-9:
        _fail(f"loaded trust {loaded.trust}")
    if loaded.recovering_from != "fragile" or loaded.recover_remaining != 2:
        _fail(
            f"recover fields {loaded.recovering_from!r} {loaded.recover_remaining}"
        )
    engine = RelationshipEngine.from_path(path, RelationshipSettings())
    if abs(engine.state.trust - 0.42) > 1e-9:
        _fail("engine did not load persisted state")
    old_path = tmp / "relationship_old.json"
    old_path.write_text(
        '{"trust": 0.41, "dependence": 0.30, "tension": 0.22, "last_climate": "steady"}',
        encoding="utf-8",
    )
    old = RelationshipStore(old_path).load()
    if old.recovering_from != "" or old.recover_remaining != 0:
        _fail("old JSON should default recover fields")
    print("  ok")


def test_welcome_climate_notes() -> None:
    print("== welcome climate notes ==")
    slot = resolve_slot(datetime(2026, 8, 13, 7, 0, 0))
    plain = build_welcome_instruction(slot, first_in_slot=True)
    cling = build_welcome_instruction(slot, first_in_slot=True, climate="cling_risk")
    tight = build_welcome_instruction(slot, first_in_slot=True, climate="fragile")
    if "更短" not in cling:
        _fail(f"cling welcome should be shorter: {cling}")
    if "活泼" not in tight:
        _fail(f"fragile welcome should avoid 活泼: {tight}")
    if "更短" in plain:
        _fail("default welcome should not add cling note")
    print("  ok")


def test_welcome_not_teased_and_speak_not_ratchet() -> None:
    print("== welcome greeted / speak not teased ==")
    if map_arona_act("initiate", "secure_play") != "greeted":
        _fail("welcome initiate should be greeted")
    if map_arona_act("initiate", "secure_play", motive_kind="idle") != "checked_in":
        _fail("idle initiate should be checked_in")
    if map_arona_act("initiate", "secure_play", motive_kind="sleep") != "cared":
        _fail("care initiate should be cared")
    if map_arona_act("initiate", "secure_play", motive_kind="goal") != "checked_in":
        _fail("goal initiate should be checked_in")
    if map_arona_act("initiate", "secure_play", motive_kind="mood_followup") != "checked_in":
        _fail("mood_followup initiate should be checked_in")
    if map_arona_act("continue", "secure_play") != "followed_up":
        _fail("continue should be followed_up")
    if map_arona_act("initiate", "secure_play", motive_kind="festival") != "greeted":
        _fail("festival initiate should be greeted")
    if ARONA_DELTAS["checked_in"][1] != 0.0 or ARONA_DELTAS["cared"][1] != 0.0:
        _fail("checked_in/cared must not raise dependence")
    if map_arona_act("speak", "secure_play", "other") != "followed_up":
        _fail("normal speak should be followed_up")
    if map_arona_act("speak", "secure_play", "play_tease") != "teased":
        _fail("play_tease speak should be teased")
    if map_arona_act("speak", "secure_play", "depart") != "gave_space":
        _fail("depart speak should be gave_space")
    if map_arona_act("speak", "cling_risk", "other") != "followed_up":
        _fail("cling_risk speak should be followed_up, not gave_space")
    if map_arona_act("continue", "fragile", "other") != "followed_up":
        _fail("fragile continue should be followed_up, not gave_space")
    if map_arona_act("silence", "cling_risk", "short_ack") != "gave_space":
        _fail("cling_risk silence should still be gave_space")
    if ARONA_DELTAS["greeted"][2] != 0.0:
        _fail("greeted should not raise tension")
    if ARONA_DELTAS["followed_up"][2] >= ARONA_DELTAS["teased"][2]:
        _fail("followed_up tension should be smaller than teased")
    print("  ok")


def test_intent_draft_gate() -> None:
    print("== V2.4 draft gate (no must_say) ==")
    legacy = parse_and_gate_intent(
        '{"user_emotion":"开放","topic":"开聊","stance":"轻松",'
        '"must_say":["选定草莓牛奶开聊"],'
        '"must_not":["把问题抛回老师"],"facts_to_use":[],'
        '"tone":"轻松","length":"1-2句","arona_emotion":"smile"}'
    )
    if legacy is not None:
        _fail("legacy must_say card without draft must fail")

    draft = parse_and_gate_intent(
        '{"draft":"我想先跟老师聊聊草莓牛奶，说说为什么喜欢它。",'
        '"arona_emotion":"smile","followup_ok":false}'
    )
    if draft is None:
        _fail("draft card should parse")
    if "草莓牛奶" not in draft.to_renderer_draft():
        _fail(f"draft missing topic: {draft.draft!r}")
    if draft.to_renderer_dict() != {"draft": draft.draft}:
        _fail(f"renderer dict should be draft-only: {draft.to_renderer_dict()}")
    print("  ok")


def test_welcome_forbids_ask() -> None:
    print("== welcome closing hint exclusive, memory query not system event ==")
    slot = resolve_slot(datetime(2026, 8, 13, 15, 0, 0))
    question = build_welcome_instruction(
        slot, first_in_slot=True, closing_hint=WELCOME_CLOSING_QUESTION
    )
    statement = build_welcome_instruction(
        slot, first_in_slot=True, closing_hint=WELCOME_CLOSING_STATEMENT
    )
    if WELCOME_CLOSING_QUESTION not in question or WELCOME_CLOSING_STATEMENT in question:
        _fail(f"question hint injection failed: {question}")
    if WELCOME_CLOSING_STATEMENT not in statement or WELCOME_CLOSING_QUESTION in statement:
        _fail(f"statement hint injection failed: {statement}")
    text = build_welcome_instruction(slot, first_in_slot=True)
    has_q = WELCOME_CLOSING_QUESTION in text
    has_s = WELCOME_CLOSING_STATEMENT in text
    if has_q == has_s:
        _fail(f"random instruction should contain exactly one closing hint: {text}")
    if "【系统事件】" in WELCOME_MEMORY_QUERY:
        _fail("welcome memory query must not be the system event")
    print("  ok")


def test_depart_then_short_ack_silence() -> None:
    print("== depart then 嗯 => silence ==")
    state = RelationshipState(
        trust=0.6, dependence=0.30, tension=0.30, last_user_act="depart"
    )
    decision = decide(state, "short_ack")
    if decision.action != "silence":
        _fail(f"expected silence after depart, got {decision.action}")
    everyday = RelationshipState(
        trust=0.6, dependence=0.30, tension=0.30, last_user_act="other"
    )
    spoken = decide(everyday, "short_ack")
    if spoken.action != "speak":
        _fail(f"everyday 嗯 should still speak, got {spoken.action}")
    everyday_hao = decide(everyday, "short_ack")
    if everyday_hao.action != "speak":
        _fail(f"everyday 好 should still speak, got {everyday_hao.action}")
    print("  ok")


def test_preview_user_text_does_not_apply(tmp: Path) -> None:
    print("== preview_user_text does not apply A/B/C or stickiness ==")
    engine = RelationshipEngine.from_path(
        tmp / "rel_preview.json", RelationshipSettings(beta=0.0)
    )
    engine.state.trust = 0.50
    engine.state.dependence = 0.30
    engine.state.tension = 0.20
    engine.state.climate_streak = 2
    engine.state.last_climate = "steady"
    engine.state.recovering_from = ""
    engine.state.recover_remaining = 0
    engine.store.save(engine.state)
    before = (
        engine.state.trust,
        engine.state.dependence,
        engine.state.tension,
        engine.state.climate_streak,
        engine.state.last_climate,
        engine.state.last_user_act,
        engine.state.recovering_from,
        engine.state.recover_remaining,
    )
    act, decision = engine.preview_user_text("谢谢")
    if act != "gratitude":
        _fail(f"preview act={act}")
    if decision.user_act != "gratitude":
        _fail(f"preview decision.user_act={decision.user_act}")
    after = (
        engine.state.trust,
        engine.state.dependence,
        engine.state.tension,
        engine.state.climate_streak,
        engine.state.last_climate,
        engine.state.last_user_act,
        engine.state.recovering_from,
        engine.state.recover_remaining,
    )
    if after != before:
        _fail(f"preview mutated state {before} -> {after}")
    _applied, _ = engine.on_user_text("谢谢")
    if engine.state.trust <= before[0]:
        _fail("on_user_text should apply gratitude trust delta")
    print("  ok")


def test_preview_does_not_persist_recover_window(tmp: Path) -> None:
    print("== preview does not persist recover window ==")
    engine = RelationshipEngine.from_path(
        tmp / "rel_preview_recover.json", RelationshipSettings(beta=0.0)
    )
    engine.state.trust = 0.60
    engine.state.dependence = 0.30
    engine.state.tension = 0.30
    engine.state.last_climate = "fragile"
    engine.state.climate_streak = 4
    engine.state.recovering_from = ""
    engine.state.recover_remaining = 0
    engine.store.save(engine.state)
    _act, decision = engine.preview_user_text("今天天气不错呢")
    if decision.transition_from != "fragile":
        _fail(f"preview should still describe the transition, got {decision.transition_from}")
    if engine.state.last_climate != "fragile":
        _fail(f"preview last_climate={engine.state.last_climate}")
    if engine.state.recovering_from or engine.state.recover_remaining:
        _fail("preview must not keep recover window on state")
    loaded = RelationshipStore(tmp / "rel_preview_recover.json").load()
    if loaded.last_climate != "fragile" or loaded.recovering_from or loaded.recover_remaining:
        _fail("preview must not write recover window to JSON")
    print("  ok")


def test_planner_user_act_backfill(tmp: Path) -> None:
    print("== planner user_act backfill when rules say other ==")
    other_line = "今天天气不错呢"

    engine = RelationshipEngine.from_path(
        tmp / "rel_backfill.json", RelationshipSettings(beta=0.0)
    )
    before = engine.state.trust
    act, _ = engine.on_user_text(other_line)
    if act != "other":
        _fail(f"expected other, got {act}")
    if abs(engine.state.trust - before) > 1e-9:
        _fail("other should not change trust before backfill")
    noted, backfilled = engine.note_planner_user_act("affection")
    if noted != "affection" or not backfilled:
        _fail(f"expected backfill affection, got {noted} {backfilled}")
    if engine.state.last_user_act != "affection":
        _fail(f"last_user_act={engine.state.last_user_act}")
    if engine.state.trust <= before:
        _fail("affection backfill should raise trust")
    after_backfill = engine.state.trust
    noted2, backfilled2 = engine.note_planner_user_act("affection")
    if backfilled2:
        _fail("second note_planner_user_act must not apply Δ again")
    if abs(engine.state.trust - after_backfill) > 1e-9:
        _fail("second note must not change trust")

    stacked = RelationshipEngine.from_path(
        tmp / "rel_no_stack.json", RelationshipSettings(beta=0.0)
    )
    _act, _ = stacked.on_user_text("谢谢")
    after_rule = stacked.state.trust
    noted, backfilled = stacked.note_planner_user_act("affection")
    if backfilled:
        _fail("must not backfill when rules already classified")
    if stacked.state.last_user_act != "affection":
        _fail("planner still overwrites last_user_act when rules hit")
    if abs(stacked.state.trust - after_rule) > 1e-9:
        _fail("must not stack affection Δ on gratitude")

    noop = RelationshipEngine.from_path(
        tmp / "rel_noop.json", RelationshipSettings(beta=0.0)
    )
    noop.on_user_text(other_line)
    after_other = noop.state.trust
    noted, backfilled = noop.note_planner_user_act("other")
    if noted != "other" or backfilled:
        _fail(f"other+other should not backfill, got {noted} {backfilled}")
    if abs(noop.state.trust - after_other) > 1e-9:
        _fail("other+other must not change trust")

    invalid = RelationshipEngine.from_path(
        tmp / "rel_invalid.json", RelationshipSettings(beta=0.0)
    )
    invalid.on_user_text(other_line)
    after_invalid_rule = invalid.state.trust
    noted, backfilled = invalid.note_planner_user_act("not_a_real_act")
    if noted != "other" or backfilled:
        _fail(f"invalid act should normalize to other, got {noted} {backfilled}")
    if abs(invalid.state.trust - after_invalid_rule) > 1e-9:
        _fail("invalid planner act must not change climate")

    crisis = RelationshipEngine.from_path(
        tmp / "rel_crisis.json", RelationshipSettings(beta=0.0)
    )
    crisis.on_user_text(other_line)
    after_crisis_rule = (
        crisis.state.trust,
        crisis.state.dependence,
        crisis.state.tension,
    )
    noted, backfilled = crisis.note_planner_user_act("crisis")
    if backfilled:
        _fail("crisis must not backfill")
    if crisis.state.last_user_act == "crisis":
        _fail("must not mark an everyday turn as crisis for gating")
    if crisis.state.last_user_act != "other":
        _fail(f"expected last_user_act other, got {crisis.state.last_user_act}")
    after_crisis = (
        crisis.state.trust,
        crisis.state.dependence,
        crisis.state.tension,
    )
    if after_crisis != after_crisis_rule:
        _fail("crisis skip must not change A/B/C")

    touch = RelationshipEngine.from_path(
        tmp / "rel_touch.json", RelationshipSettings(beta=0.0)
    )
    touch.on_user_text(other_line)
    after_touch_rule = touch.state.trust
    noted, backfilled = touch.note_planner_user_act("touch")
    if backfilled or touch.state.last_user_act != "other":
        _fail("touch must not backfill an everyday chat")
    if abs(touch.state.trust - after_touch_rule) > 1e-9:
        _fail("touch skip must not change trust")

    preview = RelationshipEngine.from_path(
        tmp / "rel_preview_note.json", RelationshipSettings(beta=0.0)
    )
    preview_before = preview.state.trust
    preview.preview_user_text(other_line)
    noted, backfilled = preview.note_planner_user_act("affection")
    if backfilled:
        _fail("preview must not arm planner backfill")
    if abs(preview.state.trust - preview_before) > 1e-9:
        _fail("preview + note_planner must not apply Δ")
    print("  ok")


def test_climate_recovery_window() -> None:
    print("== urgent exit recovery window ==")
    state = RelationshipState(
        trust=0.6,
        dependence=0.3,
        tension=0.3,
        last_climate="fragile",
        climate_streak=4,
    )
    first = decide(state, "other")
    if first.climate != "secure_play":
        _fail(f"expected secure_play, got {first.climate}")
    if first.transition_from != "fragile":
        _fail(f"transition_from={first.transition_from}")
    if "玩笑" not in first.must_not or "顶嘴" not in first.must_not:
        _fail(f"fragile bans should remain: {first.must_not}")
    if "仍偏稳住" not in first.stance:
        _fail(f"stance should stay restrained: {first.stance}")
    if first.tone_hint != "轻、稳":
        _fail(f"tone={first.tone_hint}")
    if state.recovering_from != "fragile" or state.recover_remaining != 2:
        _fail(
            f"after first recover remaining={state.recover_remaining} "
            f"from={state.recovering_from}"
        )
    block = planner_climate_block(first)
    if "【过渡】" not in block or "信任不足且紧绷" not in block:
        _fail(f"missing transition line: {block}")
    if "提升信任度" in block or "0.6" in block:
        _fail(f"block leaked numbers: {block}")
    hint = local_system_hint(first)
    if "过渡：" not in hint:
        _fail(f"local hint missing transition: {hint}")

    second = decide(state, "other")
    if second.transition_from != "fragile" or "玩笑" not in second.must_not:
        _fail("second recover turn should still overlay")
    if state.recover_remaining != 1:
        _fail(f"remaining after second={state.recover_remaining}")
    third = decide(state, "other")
    if third.transition_from != "fragile":
        _fail("third recover turn should still overlay")
    if state.recover_remaining != 0 or state.recovering_from != "":
        _fail(
            f"window should clear after third: remaining={state.recover_remaining} "
            f"from={state.recovering_from}"
        )
    fourth = decide(state, "other")
    if fourth.transition_note or "玩笑" in fourth.must_not:
        _fail(f"fourth turn should be plain secure_play: {fourth}")
    if "【过渡】" in planner_climate_block(fourth):
        _fail("fourth block should drop transition")
    print("  ok")


def test_recovery_reenter_urgent_and_crisis() -> None:
    print("== re-enter urgent clears recovery; crisis has no transition ==")
    state = RelationshipState(
        trust=0.6,
        dependence=0.3,
        tension=0.3,
        last_climate="fragile",
    )
    decide(state, "other")
    if state.recover_remaining <= 0:
        _fail("expected recovery window")
    state.dependence = 0.70
    state.tension = 0.15
    urgent = decide(state, "other")
    if urgent.climate != "cling_risk":
        _fail(f"expected cling_risk, got {urgent.climate}")
    if urgent.transition_note or state.recover_remaining != 0 or state.recovering_from:
        _fail("urgent re-entry should clear recovery")

    crisis_state = RelationshipState(
        trust=0.6,
        dependence=0.3,
        tension=0.3,
        last_climate="rupture",
    )
    crisis = decide(crisis_state, "crisis")
    if crisis.transition_note or "【过渡】" in planner_climate_block(crisis):
        _fail("crisis block must not include transition")
    if "很难受" not in planner_climate_block(crisis):
        _fail("crisis block should stay on crisis copy")
    print("  ok")


def test_fact_repair_must_not() -> None:
    print("== fact repair ban on daily turns, not crisis ==")
    play = decide(RelationshipState(trust=0.6, dependence=0.3, tension=0.3), "other")
    if "硬撑事实错误" not in play.must_not:
        _fail(f"secure_play missing fact-repair ban: {play.must_not}")
    if "硬撑事实错误" not in planner_climate_block(play):
        _fail("planner climate block missing fact-repair ban")

    rupture = decide(
        RelationshipState(
            trust=0.5,
            dependence=0.3,
            tension=0.7,
            last_climate="rupture",
        ),
        "other",
    )
    joined = " ".join(rupture.must_not)
    if "讲理争赢" not in joined or "硬撑事实错误" not in joined:
        _fail(f"rupture should keep argue-ban and fact-repair: {rupture.must_not}")
    if "硬撑事实错误" not in planner_climate_block(rupture):
        _fail("rupture climate block missing fact-repair ban")

    crisis = decide(RelationshipState(trust=0.6, dependence=0.3, tension=0.3), "crisis")
    if "硬撑事实错误" in crisis.must_not:
        _fail(f"crisis must_not should not include fact-repair: {crisis.must_not}")
    if "硬撑事实错误" in planner_climate_block(crisis):
        _fail("crisis climate block should not include fact-repair")
    print("  ok")


def test_non_urgent_one_turn_transition() -> None:
    print("== non-urgent switch gets one-turn hint, no ban union ==")
    state = RelationshipState(
        trust=0.6,
        dependence=0.3,
        tension=0.3,
        last_climate="steady",
        climate_streak=3,
    )
    first = decide(state, "other")
    if first.climate != "secure_play":
        _fail(f"expected switch to secure_play, got {first.climate}")
    if first.transition_from != "steady":
        _fail(f"expected mild transition from steady, got {first.transition_from}")
    if "再次问候" in first.must_not:
        _fail(f"must_not should not union steady bans: {first.must_not}")
    if "【过渡】" not in planner_climate_block(first):
        _fail("first non-urgent switch should have transition line")
    second = decide(state, "other")
    if second.transition_note:
        _fail("non-urgent hint should last one turn only")
    print("  ok")


def test_proactive_recovery_gates() -> None:
    print("== fragile/rupture recovery silences idle/mood/goal ==")
    play = RelationshipState(
        trust=0.6,
        dependence=0.3,
        tension=0.3,
        recovering_from="fragile",
        recover_remaining=2,
    )
    remaining_before = play.recover_remaining
    if decide_proactive(play, "idle").action != "silence":
        _fail("fragile recovery should silence idle")
    if decide_proactive(play, "mood_followup").action != "silence":
        _fail("fragile recovery should silence mood_followup")
    if decide_proactive(play, "goal").action != "silence":
        _fail("fragile recovery should silence goal")
    fest = decide_proactive(play, "festival")
    if fest.action != "initiate":
        _fail("festival should still initiate during recovery")
    if fest.transition_from != "fragile" or "玩笑" not in fest.must_not:
        _fail(f"festival should overlay fragile bans: {fest.must_not}")
    if play.recover_remaining != remaining_before:
        _fail("decide_proactive must not consume recover_remaining")

    cling_recover = RelationshipState(
        trust=0.6,
        dependence=0.3,
        tension=0.3,
        recovering_from="cling_risk",
        recover_remaining=2,
    )
    cling_idle = decide_proactive(cling_recover, "idle")
    if cling_idle.action != "initiate":
        _fail("cling_risk recovery should still allow idle")
    if cling_idle.transition_from != "cling_risk":
        _fail("cling recovery idle should still carry transition")
    print("  ok")



def test_engine_depart_then_ack(tmp: Path) -> None:
    print("== engine persist last_user_act ==")
    path = tmp / "rel.json"
    engine = RelationshipEngine.from_path(path, RelationshipSettings(beta=0.0))
    _act, first = engine.on_user_text("抱歉，我得失陪一下，有个任务需要完成")
    if _act != "depart" or first.user_act != "depart":
        _fail(f"expected depart, got {_act}")
    _ack, second = engine.on_user_text("嗯")
    if _ack != "short_ack" or second.action != "silence":
        _fail(f"expected silence, act={_ack} action={second.action}")
    print("  ok")


def test_engine_wait_then_hao(tmp: Path) -> None:
    print("== wait/leave then 好 => silence; everyday 好 still speaks ==")
    path = tmp / "rel_wait.json"
    engine = RelationshipEngine.from_path(path, RelationshipSettings(beta=0.0))
    _act, first = engine.on_user_text("啊，阿洛娜，抱歉，刚刚我去做别的事情了")
    if _act != "depart" or first.action != "speak":
        _fail(f"leave line should be depart/speak, got {_act} {first.action}")
    _wait, mid = engine.on_user_text("嗯，稍等一下哦，我马上就回来")
    if _wait != "depart" or mid.action != "speak":
        _fail(f"wait line should be depart/speak, got {_wait} {mid.action}")
    _ack, last = engine.on_user_text("好")
    if _ack != "short_ack" or last.action != "silence":
        _fail(f"expected silence after wait, act={_ack} action={last.action}")

    everyday = RelationshipEngine.from_path(
        tmp / "rel_everyday.json", RelationshipSettings(beta=0.0)
    )
    _hao, spoken = everyday.on_user_text("好")
    if _hao != "short_ack" or spoken.action != "speak":
        _fail(f"everyday 好 should still speak, got {_hao} {spoken.action}")
    print("  ok")


def test_config_loads() -> None:
    print("== config ==")
    cfg = load_config()
    rel = cfg.proactive.relationship
    if not rel.enabled:
        _fail("relationship should default enabled")
    if "relationship.json" not in rel.persist_path:
        _fail(f"unexpected persist_path {rel.persist_path}")
    if not cfg.proactive.idle.enabled or not cfg.proactive.care.enabled:
        _fail("idle/care should default enabled")
    print("  ok")


def main() -> None:
    test_apply_delta_formula()
    test_zero_delta_skips_beta()
    test_makeup_amplifies_positive_trust()
    test_daily_cap_and_cross_day()
    test_climate_zones()
    test_secure_play_allows_questions()
    test_climate_stickiness()
    test_high_b_forbids_cling_stance()
    test_classify_and_events()
    test_cling_risk_silence()
    test_seek_validation_raises_b()
    test_planner_block_has_no_numbers()
    test_climate_recovery_window()
    test_recovery_reenter_urgent_and_crisis()
    test_fact_repair_must_not()
    test_non_urgent_one_turn_transition()
    test_proactive_recovery_gates()
    with tempfile.TemporaryDirectory() as tmp:
        test_store_roundtrip(Path(tmp))
    test_welcome_climate_notes()
    test_welcome_not_teased_and_speak_not_ratchet()
    test_intent_draft_gate()
    test_welcome_forbids_ask()
    test_depart_then_short_ack_silence()
    with tempfile.TemporaryDirectory() as tmp:
        test_preview_user_text_does_not_apply(Path(tmp))
        test_preview_does_not_persist_recover_window(Path(tmp))
        test_planner_user_act_backfill(Path(tmp))
        test_engine_depart_then_ack(Path(tmp))
        test_engine_wait_then_hao(Path(tmp))
    test_config_loads()
    print("ALL PASS")


if __name__ == "__main__":
    main()
