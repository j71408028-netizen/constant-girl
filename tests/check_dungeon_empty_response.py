"""F7 回归守卫：连续空 AI 响应不得推进副本。

用法：``python tests/check_dungeon_empty_response.py``

**为什么需要**：``_generate_next_text`` 对空响应只重试一次，之后不管有没有
正文都继续往下走——凭空段落占位、把空文本写进对话历史、调 ``evolve_attributes``
推进一步、向 ``replay_data`` 追加记录、跑 ``check_triggers``。于是两次空响应
就能让副本在没有正文的情况下消耗进度，甚至走进结局。

本守卫直接驱动真实的 ``_generate_next_text``（线程改成同步执行），用桩对象
替代窗口其余部分，验证两条路径：

1. 连续空响应：不提交历史、不推进步数、不写回放、不跑触发、不留空气泡，
   并在 ``_session_errors`` 里留下可读原因；
2. 正常响应依旧照常推进（防止本修复把正常链路一起挡死）。

退出码：0 = 通过；1 = 行为不符。
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dungeon.models import DungeonTextType  # noqa: E402
from dungeon.window import engine as engine_mod  # noqa: E402
from dungeon.window.engine import DungeonStoryEngine  # noqa: E402

failures = []
total = 0


def check(name, ok, extra=""):
    global total
    total += 1
    print(("  OK   " if ok else "  FAIL ") + name + (f"  <{extra}>" if extra and not ok else ""))
    if not ok:
        failures.append(name)


class _FakeState:
    def __init__(self, total_steps=0):
        self.total_steps = total_steps
        self.intrusion = 1.0
        self.destruction = 1.0
        self.depth_intrusion = 0.1
        self.depth_destruction = 0.1
        self.custom_attrs = {}
        self.total_casualties = 0.0
        self.casualty_evolution = []


class _Turn:
    def __init__(self):
        self.text = "本轮请求"
        self.canonical = "本轮稳定上下文"
        self.effects = types.SimpleNamespace(prompted_parts=set())


class _PromptBuilder:
    def __init__(self):
        self.committed = 0

    def build_turn(self, text_type):
        return _Turn()

    def commit_turn(self, effects):
        self.committed += 1


class _Logic:
    """``dungeon_logic`` 里本路径只用到类型选择与属性演化。"""

    step_overrides = {}

    def __init__(self):
        self.evolve_calls = []

    def get_next_text_type(self, current):
        return DungeonTextType.BACKGROUND

    def evolve_attributes(self, before, text_type, direction, personality, **kwargs):
        self.evolve_calls.append((text_type, direction))
        return _FakeState(before.total_steps + 1)


class _EmptyClient:
    """连续两次返回空 / 纯空白内容。"""

    def __init__(self):
        self.calls = 0

    def generate_stream(self, messages, temperature=0.8):
        self.calls += 1
        yield ""
        yield "   "


class _TextClient:
    def __init__(self, text):
        self.calls = 0
        self.text = text

    def generate_stream(self, messages, temperature=0.8):
        self.calls += 1
        yield '{"text": "%s", "direction": 1}' % self.text


class _InlineThread:
    """把生成任务从后台线程改成同步执行，测试才能断言执行结果。"""

    def __init__(self, target=None, daemon=None, **_kwargs):
        self._target = target

    def start(self):
        if self._target is not None:
            self._target()


class _Window(DungeonStoryEngine):
    """绕过窗口初始化，只装配 ``_generate_next_text`` 依赖的会话字段。"""

    def __init__(self, client):
        self.ai_client = client
        self._closing = False
        self._generating = False
        self.messages = [{"role": "system", "content": "系统提示"}]
        self.story_history = []
        self.pending_insertions = []
        self.pending_option = None
        self.pending_ending = None
        self.pending_mini_game = None
        self.dungeon_ended = False
        self.is_replay = False
        self.chapters = None
        self.current_chapter = ""
        self.current_text_type = DungeonTextType.BACKGROUND
        self.personality = types.SimpleNamespace(sensitivity=1.0, gravity=0.5)
        self.evolution_attrs = []
        self.replay_data = []
        self._pending_units = []
        self._pregen = None
        self._pregen_inflight = False
        self.dungeon_state = _FakeState()
        self.step_num = 0
        self.characters = None
        self.prompt_builder = _PromptBuilder()
        self.dungeon_logic = _Logic()
        self._frame = types.SimpleNamespace(call=lambda fn: fn())
        self.prefgen_calls = 0
        self.finish_calls = []
        self.text_updates = 0

    # ---- 窗口其余部分：本路径不需要，一律桩掉并记录 ----
    def _schedule_text_update(self):
        self.text_updates += 1

    def _update_text_display(self):
        self.text_updates += 1

    def _display_type_prefix(self, text_type):
        return text_type.display_prefix

    def _message_window_size(self):
        return 20

    def _current_action_points(self):
        return 100

    def _apply_sensitivity_mods(self):
        return {}

    def _take_pregen_for_next(self):
        return None

    def _maybe_pregen_next(self):
        self.prefgen_calls += 1

    def _in_terminating_chapter(self):
        return False

    def _observe_characters(self, *_args, **_kwargs):
        pass

    def _apply_prompted_unlocks(self, *_args, **_kwargs):
        pass

    def _speak_item(self, *_args, **_kwargs):
        pass

    def _start_detail_query(self, *_args, **_kwargs):
        pass

    def _reveal_active(self):
        return False

    def _reveal_start(self, *_args):
        pass

    def _reveal_snap(self, *_args, **_kwargs):
        pass

    def _update_stream_units(self, *_args):
        pass

    def _finish_step(self, text_type, text, step_info, check_unlock=False):
        self.finish_calls.append((text_type, text, step_info))

    # ---- 驱动 ----
    def run_once(self):
        real_thread = engine_mod.threading.Thread
        engine_mod.threading.Thread = _InlineThread
        try:
            self._generate_next_text()
        finally:
            engine_mod.threading.Thread = real_thread


# ---------------- 1. 连续空响应：不得推进 ----------------
print("[1] 连续两次空响应")
_empty = _EmptyClient()
_win = _Window(_empty)
_win.run_once()

check("确实重试了一次（共两次请求）", _empty.calls == 2, _empty.calls)
check("没有提交对话历史", len(_win.messages) == 1, _win.messages)
check("没有推进步数", _win.step_num == 0 and not _win.dungeon_logic.evolve_calls,
      (_win.step_num, _win.dungeon_logic.evolve_calls))
check("没有写回放", _win.replay_data == [], _win.replay_data)
check("没有跑步进收尾 / 触发判断", _win.finish_calls == [], _win.finish_calls)
check("没有发起下一次预生成", _win.prefgen_calls == 0, _win.prefgen_calls)
check("没有留下空的段落占位",
      all(item.get("text") for item in _win.story_history),
      _win.story_history)
check("故事区给出可读原因",
      len(_win.story_history) == 1
      and _win.story_history[0]["type_str"] == "【错误】"
      and "空内容" in _win.story_history[0]["text"],
      _win.story_history)
check("错误写进会话错误清单",
      len(getattr(_win, "_session_errors", [])) == 1
      and "空内容" in _win._session_errors[0],
      getattr(_win, "_session_errors", None))
check("句队列已清空", _win._pending_units == [], _win._pending_units)
check("生成锁已释放，玩家可再点一次", _win._generating is False)

# ---------------- 2. 正常响应：照常推进 ----------------
print("[2] 正常响应仍照常推进")
_text_client = _TextClient("她走过长街。")
_win2 = _Window(_text_client)
_win2.run_once()

check("只请求一次", _text_client.calls == 1, _text_client.calls)
check("对话历史补上 user / assistant 两轮",
      len(_win2.messages) == 3
      and _win2.messages[-2]["role"] == "user"
      and _win2.messages[-1]["role"] == "assistant",
      _win2.messages)
check("回合效果已提交", _win2.prompt_builder.committed == 1,
      _win2.prompt_builder.committed)
check("步数推进了一次",
      _win2.step_num == 1 and len(_win2.dungeon_logic.evolve_calls) == 1,
      (_win2.step_num, _win2.dungeon_logic.evolve_calls))
check("步进收尾执行了一次",
      len(_win2.finish_calls) == 1 and _win2.finish_calls[0][1] == "她走过长街。",
      _win2.finish_calls)
check("故事区留下正文段落",
      len(_win2.story_history) == 1
      and _win2.story_history[0]["text"] == "她走过长街。",
      _win2.story_history)
check("正常路径仍会预生成下一段", _win2.prefgen_calls == 1, _win2.prefgen_calls)
check("正常路径不写会话错误清单",
      not getattr(_win2, "_session_errors", []),
      getattr(_win2, "_session_errors", None))

# ---------------- 汇总 ----------------
print()
if failures:
    print(f"FAILED {len(failures)}/{total}: " + "; ".join(failures))
    sys.exit(1)
print(f"PASSED {total}/{total}")
