"""Quick unit smoke for dual-model pieces (V2.4 draft schema)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import AppConfig, ConversationConfig, PlannerConfig, load_config
from app.conversation import ConversationManager
from app.planner import EMOTION_WHITELIST, normalize_emotion, parse_and_gate_intent, resolve_life_action
from app.planner.client import PlannerClient
from app.planner.prompts import (
    PLANNER_PREFIX_DIRECT,
    PLANNER_PREFIX_RENDERER,
    PLANNER_SYSTEM,
    PLANNER_SYSTEM_BASE,
    PLANNER_SYSTEM_CRISIS,
    PLANNER_SYSTEM_DIRECT,
    build_planner_user_message,
    select_planner_system,
)
from app.prompt import (
    LOCAL_MAX_HISTORY_TURNS,
    RENDERER_USER_TAIL,
    build_messages,
    build_renderer_messages,
    clip_inject_chunks,
)
from app.protocol import msg_chat_response
from app.relationship.events import USER_ACT_WHITELIST, USER_ACT_WHITELIST_CSV, USER_DELTAS


def main() -> None:
    frozen = datetime(2026, 8, 24, 10, 14)
    timed_hist = [
        {
            "role": "user",
            "content": "早上好",
            "time": "2026-08-24T10:14:05",
        },
        {
            "role": "assistant",
            "content": "老师早上好。",
            "time": "2026-08-24T10:14:07",
        },
    ]
    timed_msg = build_planner_user_message(
        user_text="还没睡",
        history=timed_hist,
        memories=[],
        knowledge=[],
        now=frozen,
    )
    assert "[2026年8月24日 10:14:05 面对面交流] 老师：早上好" in timed_msg
    assert "[2026年8月24日 10:14:07 面对面交流] 阿洛娜：老师早上好。" in timed_msg
    assert "内部时序依据" in PLANNER_SYSTEM
    assert "内部时序依据" in PLANNER_SYSTEM_CRISIS

    untimed_msg = build_planner_user_message(
        user_text="还没睡",
        history=[
            {"role": "user", "content": "早上好"},
            {"role": "assistant", "content": "老师早上好。"},
        ],
        memories=[],
        knowledge=[],
        now=frozen,
    )
    assert "老师：早上好" in untimed_msg
    assert "[2026年8月24日" not in untimed_msg.split("【近期对话】", 1)[1].split(
        "【老师本轮消息】", 1
    )[0]

    conv = ConversationManager()
    conv.append("s1", "user", "早上好", at=datetime(2026, 8, 24, 10, 14, 5))
    conv.append("s1", "assistant", "老师早上好。", at=datetime(2026, 8, 24, 10, 14, 7))
    stored = conv.get_history("s1")
    assert stored[0]["time"] == "2026-08-24T10:14:05"
    assert stored[1]["time"] == "2026-08-24T10:14:07"
    from_store = build_planner_user_message(
        user_text="还没睡",
        history=stored,
        memories=[],
        knowledge=[],
        now=frozen,
    )
    assert "[2026年8月24日 10:14:05 面对面交流] 老师：早上好" in from_store
    assert "[2026年8月24日 10:14:07 面对面交流] 阿洛娜：老师早上好。" in from_store

    now = datetime(2026, 8, 24, 18, 0, 0)
    # 6h 内已超过 2N：返回全部 6h 内消息（可超 2N）
    over = ConversationManager(max_history_turns=2, planner_history_hours=6.0)
    for i in range(5):
        over.append(
            "s1",
            "user",
            f"近窗老师{i}",
            at=now - timedelta(hours=1, minutes=50 - i),
        )
        over.append(
            "s1",
            "assistant",
            f"近窗阿洛娜{i}",
            at=now - timedelta(hours=1, minutes=49 - i),
        )
    over_hist = over.get_planner_history("s1", now=now)
    assert len(over_hist) == 10
    assert over_hist[0]["content"] == "近窗老师0"
    assert over_hist[-1]["content"] == "近窗阿洛娜4"
    assert len(over.get_history("s1")) == 4

    # 6h 内不足：向前补足到恰好 2N，顺序正确
    pad = ConversationManager(max_history_turns=2, planner_history_hours=6.0)
    pad.append("s1", "user", "旧老师A", at=now - timedelta(hours=10))
    pad.append("s1", "assistant", "旧阿洛娜A", at=now - timedelta(hours=9, minutes=59))
    pad.append("s1", "user", "旧老师B", at=now - timedelta(hours=8))
    pad.append("s1", "assistant", "旧阿洛娜B", at=now - timedelta(hours=7, minutes=59))
    pad.append("s1", "user", "近老师", at=now - timedelta(hours=1))
    pad.append("s1", "assistant", "近阿洛娜", at=now - timedelta(minutes=50))
    pad_hist = pad.get_planner_history("s1", now=now)
    assert [m["content"] for m in pad_hist] == [
        "旧老师B",
        "旧阿洛娜B",
        "近老师",
        "近阿洛娜",
    ]

    # 总库存不足 2N：返回全部可得消息
    short = ConversationManager(max_history_turns=3, planner_history_hours=6.0)
    short.append("s1", "user", "唯一老师", at=now - timedelta(hours=1))
    short.append("s1", "assistant", "唯一阿洛娜", at=now - timedelta(minutes=50))
    short_hist = short.get_planner_history("s1", now=now)
    assert [m["content"] for m in short_hist] == ["唯一老师", "唯一阿洛娜"]

    # 无时间戳/坏时间戳：不进 6h 窗，仅作补足候选
    bad = ConversationManager(max_history_turns=2, planner_history_hours=6.0)
    bad.append("s1", "user", "坏时间老师", at=now - timedelta(hours=1))
    bad.append("s1", "assistant", "坏时间阿洛娜", at=now - timedelta(minutes=50))
    assert bad._store is not None
    bad._store.entries[0].time = "not-a-time"
    bad._store.entries[1].time = ""
    bad.append("s1", "user", "近老师2", at=now - timedelta(minutes=30))
    bad.append("s1", "assistant", "近阿洛娜2", at=now - timedelta(minutes=20))
    bad_hist = bad.get_planner_history("s1", now=now)
    assert [m["content"] for m in bad_hist] == [
        "坏时间老师",
        "坏时间阿洛娜",
        "近老师2",
        "近阿洛娜2",
    ]
    assert ConversationConfig().planner_history_hours == 6.0
    assert AppConfig().conversation.planner_history_hours == 6.0

    assert normalize_emotion("SMILE") == "smile"
    assert normalize_emotion("nope") == "normal"

    legacy = parse_and_gate_intent(
        '{"user_emotion":"沮丧","topic":"考试","stance":"共情",'
        '"must_say":["安慰"],"must_not":[],"facts_to_use":[],'
        '"tone":"温柔","length":"1-2句","arona_emotion":"smile"}'
    )
    assert legacy is None

    raw = (
        '{"draft":"考试让老师很沮丧，我陪在老师身边。",'
        '"arona_emotion":"smile","followup_ok":false}'
    )
    card = parse_and_gate_intent(raw)
    assert card is not None
    assert card.draft.startswith("考试")
    assert card.arona_emotion == "smile"
    assert card.followup_ok is False
    assert card.reply_ok is True
    assert card.user_act == "other"
    assert card.to_renderer_dict() == {"draft": card.draft}
    assert "arona_emotion" not in card.to_renderer_dict()
    assert "followup_ok" not in card.to_renderer_dict()
    assert "reply_ok" not in card.to_renderer_dict()
    assert "user_act" not in card.to_renderer_dict()

    cfg = load_config()
    assert cfg.planner.vision_model == "deepseek-flash"
    hist = [
        {"role": "user", "content": "上一轮老师"},
        {"role": "assistant", "content": "上一轮阿洛娜"},
    ]
    msgs = build_renderer_messages(
        cfg,
        draft=card.to_renderer_draft(),
        history=hist,
        max_history_turns=2,
    )
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "上一轮老师" not in msgs[1]["content"]
    assert "【意图草稿】" in msgs[-1]["content"]
    assert "【老师原话】" not in msgs[-1]["content"]
    assert "【系统事件】" not in msgs[-1]["content"]
    assert "【回复意图卡】" not in msgs[-1]["content"]
    assert card.draft in msgs[-1]["content"]
    assert "意图草稿" in msgs[0]["content"] or "【意图草稿】" in msgs[-1]["content"]

    hist_local = []
    for i in range(6):
        hist_local.append({"role": "user", "content": f"老师第{i + 1}轮"})
        hist_local.append({"role": "assistant", "content": f"阿洛娜第{i + 1}轮"})
    local_msgs = build_messages(
        cfg,
        user_text="本轮",
        history=hist_local,
        memories=[],
        knowledge=[],
    )
    hist_in_prompt = local_msgs[1:-1]
    assert len(hist_in_prompt) == LOCAL_MAX_HISTORY_TURNS * 2
    assert hist_in_prompt[0]["content"] == "[面对面交流] 老师第3轮"
    assert hist_in_prompt[-1]["content"] == "[面对面交流] 阿洛娜第6轮"
    assert local_msgs[-1]["content"] == "本轮"

    follow = parse_and_gate_intent(
        '{"draft":"光环是阿洛娜身份的一部分，我可以慢慢讲给老师听。",'
        '"arona_emotion":"smile","followup_ok":true}'
    )
    assert follow is not None and follow.followup_ok is True
    assert follow.reply_ok is True

    silent = parse_and_gate_intent(
        '{"draft":"","arona_emotion":"smile","followup_ok":true,'
        '"reply_ok":false,"user_act":"depart"}'
    )
    assert silent is not None
    assert silent.reply_ok is False
    assert silent.draft == ""
    assert silent.user_act == "depart"
    assert silent.followup_ok is False
    assert silent.arona_emotion == "smile"
    assert resolve_life_action(silent) == "emotion_only"
    assert resolve_life_action(silent, suggested_silence=True) == "continue_activity"
    derived = parse_and_gate_intent(
        '{"draft":"","arona_emotion":"normal","followup_ok":false,"reply_ok":false}'
    )
    assert derived is not None
    assert resolve_life_action(derived) == "continue_activity"
    glance = parse_and_gate_intent(
        '{"draft":"","arona_emotion":"curious","followup_ok":false,'
        '"reply_ok":false,"life_action":"glance"}'
    )
    assert glance is not None
    assert resolve_life_action(glance) == "emotion_only"

    assert parse_and_gate_intent(
        '{"draft":"","arona_emotion":"normal","followup_ok":false,"reply_ok":true}'
    ) is None

    bad_act = parse_and_gate_intent(
        '{"draft":"好的老师。","arona_emotion":"smile","followup_ok":false,'
        '"reply_ok":true,"user_act":"not_a_real_act"}'
    )
    assert bad_act is not None
    assert bad_act.user_act == "other"

    m = msg_chat_response("ok", emotion="shy")
    assert m["emotion"] == "shy"

    assert "【阿洛娜主要人设】" in PLANNER_SYSTEM_CRISIS
    assert "什亭之匣" in PLANNER_SYSTEM
    assert "温柔活泼" in PLANNER_SYSTEM
    assert "规划参谋" in PLANNER_SYSTEM
    assert '"draft"' in PLANNER_SYSTEM or "draft：" in PLANNER_SYSTEM
    assert "reply_ok" in PLANNER_SYSTEM
    assert "默认 true" in PLANNER_SYSTEM
    assert "打电话" in PLANNER_SYSTEM
    assert "屏幕互动" in PLANNER_SYSTEM
    assert "touch" in PLANNER_SYSTEM
    assert "user_act" in PLANNER_SYSTEM
    assert "【当前时间】" in PLANNER_SYSTEM
    assert "非必要时不把完整公历年月日念出来" in PLANNER_SYSTEM
    assert set(USER_ACT_WHITELIST) == set(USER_DELTAS)
    for act in USER_ACT_WHITELIST:
        assert act in PLANNER_SYSTEM
    assert USER_ACT_WHITELIST_CSV
    assert PLANNER_SYSTEM == PLANNER_PREFIX_RENDERER + PLANNER_SYSTEM_BASE
    assert PLANNER_SYSTEM_DIRECT == PLANNER_PREFIX_DIRECT + PLANNER_SYSTEM_BASE
    assert PLANNER_SYSTEM_BASE in PLANNER_SYSTEM
    assert PLANNER_SYSTEM_BASE in PLANNER_SYSTEM_DIRECT
    assert select_planner_system(renderer_enabled=True) == PLANNER_SYSTEM
    assert select_planner_system(renderer_enabled=False) == PLANNER_SYSTEM_DIRECT
    assert "亲密语境下害羞、撒娇" in select_planner_system(renderer_enabled=True)
    assert "## 个性化补丁" in select_planner_system(renderer_enabled=True)
    assert "服从气候" in select_planner_system(renderer_enabled=True)
    friend = select_planner_system(renderer_enabled=True, stage="朋友")
    lover = select_planner_system(renderer_enabled=True, stage="恋人")
    assert "助手与朋友" in friend
    assert "助手与恋人" in lover
    assert "不要自造昵称" in friend
    patched = select_planner_system(
        renderer_enabled=True, stage="挚友", patch="老师希望被叫小老师。"
    )
    assert "老师希望被叫小老师。" in patched
    assert "reply_ok 必须为 true" in PLANNER_SYSTEM_CRISIS
    assert "crisis" in PLANNER_SYSTEM_CRISIS
    assert "热线告示" in PLANNER_SYSTEM_CRISIS
    assert "明确的自伤" in PLANNER_SYSTEM
    assert "明确的自伤" in PLANNER_SYSTEM_DIRECT
    assert "心情与共同经历不是稳定档案" in PLANNER_SYSTEM
    assert "心情与共同经历不是稳定档案" in PLANNER_SYSTEM_DIRECT
    assert "先认错再纠正" in PLANNER_SYSTEM_BASE
    assert "硬撑" in PLANNER_SYSTEM_BASE
    assert "禁止编造更正" in PLANNER_SYSTEM_BASE
    assert "先认错再纠正" in PLANNER_SYSTEM
    assert "先认错再纠正" in PLANNER_SYSTEM_DIRECT
    frozen = datetime(2026, 8, 24, 10, 14)
    user_msg = build_planner_user_message(
        user_text="谢谢你，阿洛娜。",
        history=[],
        memories=[],
        knowledge=[],
        now=frozen,
    )
    assert "【当前时间】2026年8月24日 星期一 10:14" in user_msg
    assert user_msg.index("【当前时间】") < user_msg.index("【长期记忆】")
    assert "【老师本轮消息】" in user_msg
    assert "【阿洛娜主要人设】" not in user_msg
    assert "must_say" not in user_msg
    assert "先判断 reply_ok" in user_msg
    assert "电脑屏幕截图" not in user_msg
    assert "life_action" in PLANNER_SYSTEM
    assert "禁止把【阿洛娜此刻】或【未出口的心事】写进 draft" in PLANNER_SYSTEM
    life_msg = build_planner_user_message(
        user_text="老师回来了",
        history=[],
        memories=[],
        knowledge=[],
        now=frozen,
        life_block="【阿洛娜此刻】正在教室发呆",
    )
    assert "【阿洛娜此刻】正在教室发呆" in life_msg
    assert life_msg.index("【阿洛娜此刻】") < life_msg.index("【老师本轮消息】")
    assert "突然加入的事件" in life_msg
    assert "禁止把【阿洛娜此刻】或【未出口的心事】写进 draft" in life_msg

    vision_msg = build_planner_user_message(
        user_text="屏幕上是什么？",
        history=[],
        memories=[],
        knowledge=[],
        now=frozen,
        has_screenshot=True,
    )
    assert "电脑屏幕截图" in vision_msg
    assert "仅在回答需要截图上的信息时" in vision_msg
    assert "先判断 reply_ok" in vision_msg
    assert "请输出唯一 JSON 对象。" in vision_msg

    from app.proactive.care import build_care_instruction

    lunch_ins = build_care_instruction("lunch")
    assert "已吃午饭" in lunch_ins
    assert "reply_ok 必须 false" in lunch_ins
    assert "正在聊" in lunch_ins
    assert "还在想" in lunch_ins
    breakfast_ins = build_care_instruction("breakfast")
    assert "已吃早饭" in breakfast_ins
    assert "reply_ok 必须 false" in breakfast_ins
    assert "正在聊" in breakfast_ins
    assert "还在想" in breakfast_ins
    dinner_ins = build_care_instruction("dinner")
    assert "已吃晚饭" in dinner_ins
    assert "reply_ok 必须 false" in dinner_ins
    assert "正在聊" in dinner_ins
    assert "还在想" in dinner_ins
    sleep_ins = build_care_instruction("sleep")
    assert "待会再睡" in sleep_ins
    assert "晚安收束" in sleep_ins
    assert "正在聊" in sleep_ins
    assert "还在想" in sleep_ins

    long_a = "设定甲" * 10
    long_b = "设定乙" * 10
    first_line = f"- {long_a}"
    clipped = clip_inject_chunks([long_a, long_b], len(first_line) + 5)
    assert clipped == [long_a]
    clipped_msg = build_planner_user_message(
        user_text="光环是什么颜色？",
        history=[],
        memories=[],
        knowledge=clipped,
    )
    assert "设定甲" in clipped_msg
    assert "设定乙" not in clipped_msg

    from typing import get_args

    from app.orchestrator import should_record_history_marker
    from app.prompt import format_memory_inject
    from app.taxonomy import MemoryCategory

    assert "arona" not in get_args(MemoryCategory)
    injected = format_memory_inject(
        [{"key": "k1", "content": "老师喜欢蓝色", "category": "preference"}],
        arona_lines=["在教室休息过"],
        max_chars=400,
    )
    assert "【长期记忆】" in injected.block
    assert "【阿洛娜的记忆】" in injected.block
    assert injected.block.index("【长期记忆】") < injected.block.index("【阿洛娜的记忆】")
    assert "在教室休息过" not in injected.contents
    assert not should_record_history_marker("【提醒】")
    assert should_record_history_marker("【摸头】")
    thought_marker = "她想提起：轻轻问一句老师在不在忙"
    assert not should_record_history_marker(thought_marker)
    hidden = build_planner_user_message(
        user_text="帮我打开记事本",
        history=[
            {"role": "user", "content": thought_marker},
            {"role": "assistant", "content": "老师，您现在忙吗？"},
        ],
        memories=[],
        knowledge=[],
    )
    assert thought_marker not in hidden
    assert "阿洛娜：老师，您现在忙吗？" in hidden
    day_msg = build_planner_user_message(
        user_text="你刚才在做什么",
        history=[{"role": "assistant", "content": "该休息了"}],
        memories=[],
        knowledge=[],
        memory_block=injected.block,
        day_block="【阿洛娜的记忆】\n- 从在教室发呆换成在休息",
        now=frozen,
    )
    assert "【提醒】" not in day_msg
    assert "【阿洛娜的一天】" not in day_msg
    head, _, note = day_msg.partition("【阿洛娜的记忆】是她自己的近期摘要")
    assert head.count("【阿洛娜的记忆】") == 1
    assert note.startswith("，可以提起")
    assert "在教室休息过" in day_msg
    assert "从在教室发呆换成在休息" in day_msg
    assert day_msg.index("【近期对话】") < day_msg.index("【阿洛娜的记忆】")

    from app.model_loader import ModelLoader

    warmup_messages = build_renderer_messages(cfg, draft="老师好。")
    assert warmup_messages[0]["role"] == "system"
    assert "意图草稿" in warmup_messages[1]["content"]
    assert RENDERER_USER_TAIL in warmup_messages[1]["content"]

    class _FakeChatLLM:
        def create_chat_completion(self, messages, cache_prompt=False, **kwargs):
            return {"choices": [{"message": {"content": ""}}]}

    loader = ModelLoader()
    loader._llm = _FakeChatLLM()
    loader._configure_prompt_cache()
    assert loader._extra_completion_kwargs.get("cache_prompt") is True

    _ = EMOTION_WHITELIST
    print("ok")


def test_planner_thinking_config() -> None:
    default_cfg = PlannerConfig()
    assert default_cfg.thinking is False
    off = PlannerClient(PlannerConfig(thinking=False, max_tokens=512))
    assert off._thinking_body() == {"type": "disabled"}
    assert off._plan_max_tokens() == 512
    on = PlannerClient(PlannerConfig(thinking=True, max_tokens=512))
    assert on._thinking_body() == {"type": "enabled"}
    assert on._plan_max_tokens() == 8192
    high = PlannerClient(PlannerConfig(thinking=True, max_tokens=16384))
    assert high._plan_max_tokens() == 16384


if __name__ == "__main__":
    main()
    test_planner_thinking_config()
