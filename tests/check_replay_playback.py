"""自检：回放的播放机制（限速上屏 / 逐句点击 / 跳过不可见记录 / 停留登记）。

用法：``python tests/check_replay_playback.py``

无 GUI：把 ``DungeonStoryEngine`` / ``TriggerHandler`` / ``EndingHandler`` 与
``DungeonWindowUI`` 的游标三件套挂到一支最小宿主上，用真 ``FrameScheduler``
的 ``tick(now=...)`` 显式推时钟——回放与实时共用同一条游标，所以这里断言的是
「回放接上了同一条上屏管线」，而不是另造一套节奏。

1. **限速上屏**：步进记录不再整段直出，1 秒约 30 字；
2. **逐句点击**：一个逻辑段落切成多个显示段落，点一下补满、再点才切下一句；
3. **跳过不可见记录**：章节进入 / 效果覆盖与正文共用一次点击，不空耗点击；
4. **停留登记**：段落走完登记 ``_advance_due``（自动播放不再 0.2 秒一条空转）；
5. **结局**：正文同样限速上屏，上屏走完才关窗。
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_report_path = os.path.join(tempfile.mkdtemp(prefix="replay_playback_"), "report.txt")
_log = open(_report_path, "w", encoding="utf-8")
sys.stdout = _log
sys.stderr = _log

failures = []
total = 0


def check(name, ok, extra=""):
    global total
    total += 1
    print(("  OK   " if ok else "  FAIL ") + name
          + (f"  <{extra}>" if extra and not ok else ""))
    if not ok:
        failures.append(name)


import time  # noqa: E402
from collections import deque  # noqa: E402

from dungeon import replay  # noqa: E402
from dungeon.models import DungeonState, PREFIX_ENDING  # noqa: E402
from dungeon.window.ending import EndingHandler  # noqa: E402
from dungeon.window.engine import DungeonStoryEngine  # noqa: E402
from dungeon.window.frame import FrameScheduler  # noqa: E402
from dungeon.window.triggers import TriggerHandler  # noqa: E402
from dungeon.window.ui import (  # noqa: E402
    DungeonWindowUI,
    _REVEAL_CHARS_PER_SECOND,
    _REVEAL_TICK_SECONDS,
)


class _Bgm:
    def __init__(self):
        self.calls = []

    def play(self, spec):
        self.calls.append(dict(spec or {}))


class _Speech:
    def __init__(self):
        self.effects = []
        self.spoken = []

    def set_effect(self, spec=None):
        self.effects.append(dict(spec or {}))

    def speak(self, speaker, text):
        self.spoken.append((speaker, text))


class _PlaybackHost(DungeonStoryEngine, TriggerHandler, EndingHandler,
                    DungeonWindowUI):
    """回放宿主：真 mixin + 少量替身（无窗口、无音频设备、无 AI）。

    只装配回放路径真正触到的成员；音频 / 背景 / 终止动作全部记在列表里。
    """

    def __init__(self, records=None):
        self.is_replay = True
        self.loaded_replay = replay.parse_all(records or [])
        self.current_replay_index = 0
        self.dungeon_state = DungeonState(intrusion=0.0, destruction=0.0,
                                          custom_attrs={})
        self.chapters = []
        self.current_chapter = None
        self.chapter_sensitivity_effects = []
        self.chapter_filter = ""
        self.chapter_bgm = {}
        self.effect_overrides = []
        self._applied_visual_filter = None
        self._applied_bgm_level = None
        self.current_background_path = ""
        self.chapter_voice_fx = {}
        self.current_voice_fx = {}
        self._applied_voice_fx = {}
        self._bgm = _Bgm()
        self._speech = _Speech()
        self._frame = FrameScheduler()
        self._window_fx = self
        self._script = None
        self._script_key = None
        self._script_index = 0
        self._script_exhausted = False
        self._pregen = None
        self.personality = None
        self.character = None
        self.story_summary = None
        self.story_history = []
        self.triggers = []
        self.triggered_names = set()
        self._round_fired = set()
        self.trigger_choices = {}
        self.pending_insertions = deque()
        self.pending_option = None
        self.pending_mini_game = None
        self.pending_ending = None
        self.dungeon_ended = False
        self.ending_text = ""
        self.ending_icon_path = ""
        self._ending_name = ""
        self._ending_recorded = False
        self.replay_data = []
        # 上屏游标与自动播放停留
        self._reveal = None
        self._pending_units = []
        self._advance_due = 0.0
        self._last_click_time = None
        self._closing = False
        self.closed = False

    # ---------- 替身 ----------
    def overlay_open(self):
        return False

    def change_background(self, image_path, smooth, filter_effect):
        self.current_background_path = image_path
        self.chapter_filter = filter_effect

    def start(self, fx_key, duration, intensity):
        pass

    def _current_action_points(self):
        return None

    def _update_text_display(self):
        pass

    def _update_ending_icon(self):
        pass

    def _request_close(self):
        self.closed = True


def _clock_base():
    return time.monotonic()


def _advance(host, seconds, start=None):
    """按 ``_REVEAL_TICK_SECONDS`` 步进推帧时钟（累加式，与 due_at 同一条浮点路径）。"""
    t = _clock_base() if start is None else start
    for _ in range(int(round(seconds / _REVEAL_TICK_SECONDS))):
        t += _REVEAL_TICK_SECONDS
        host._frame.tick(now=t)
    return t


# 首段 34 字（句末才断），第二段 12 字：1 秒只够走完首段的一部分
TEXT = ("她站在城市中央，抬头看着那些摇晃的玻璃幕墙，脚下的柏油路正一点点裂开。"
        "整条街的人都在往后退。")
FIRST = "她站在城市中央，抬头看着那些摇晃的玻璃幕墙，脚下的柏油路正一点点裂开。"

# ---------------- 1. 限速仿流式上屏 ----------------
host = _PlaybackHost([{"type": "dialog", "text": TEXT, "type_prefix": "【对话】"}])
host._replay_next_step()
item = host.story_history[-1]
check("步进记录不再整段直出（首段起游标，从零开始）",
      item["text"] == "" and host._reveal_active(), item)
check("其余显示段落排队等点击", len(host._pending_units) == 1,
      [u.text for u in host._pending_units])

_t1 = _advance(host, 1.0)
pos_1s = len(item["text"])
check("回放 1 秒后推进约 30 字（与实时同一条限速）",
      28 <= pos_1s <= 31, f"chars={pos_1s}")
check("已上屏是首段的前缀", item["text"] == FIRST[:pos_1s], item["text"])

# ---------------- 2. 三态点击机 ----------------
pos_before = len(item["text"])
consumed = host._try_advance_paragraph()
check("② 未上完：点击补满当前段、不切句",
      consumed and item["text"] == FIRST and len(host._pending_units) == 1,
      (pos_before, item["text"]))
consumed = host._try_advance_paragraph()
check("③ 已补满：再点才切下一句",
      consumed and len(host.story_history) == 2
      and host.story_history[-1]["text"] == "", host.story_history[-1])
check("① 新段不足 5 字：紧随的点击被吞掉",
      host._try_advance_paragraph() and len(host.story_history) == 2)

_t2 = _advance(host, 0.6)
check("第二句走完：游标注销、队列见底",
      host._reveal is None and not host._pending_units,
      (host._reveal, host._pending_units))
check("段落走完登记了停留（自动播放不再 0.2 秒一条空转）",
      host._advance_due > _clock_base(), host._advance_due)

# 队列见底后的点击才去取下一条记录；0.4 秒内的连点被防抖吞掉
host._last_click_time = time.time()
before = len(host.story_history)
host._on_next_step()
check("连点防抖：0.4 秒内的第二次推进被吞掉", len(host.story_history) == before)

host2 = _PlaybackHost([{"type": "dialog", "text": "第一段正文。"},
                       {"type": "dialog", "text": "第二段正文。"}])
host2._replay_next_step()
host2._reveal_snap()
host2._last_click_time = None
host2._on_next_step()
check("队列见底后点击落到下一条记录",
      [i["text"] for i in host2.story_history] == ["第一段正文。", ""],
      host2.story_history)

# ---------------- 3. 不可见记录不占点击 ----------------
_skip = _PlaybackHost([
    {"kind": "chapter", "name": "A",
     "background": {"image_path": "a.png", "filter_effect": "smooth"},
     "bgm": {"path": "a.mp3", "level": 3}},
    {"kind": "trigger", "name": "覆盖", "action_type": "effect",
     "action_data": {"filter": "blur", "bgm_level": 1, "duration": 2}},
    {"type": "dialog", "text": "第一段正文。"},
])
_skip._replay_next_step()
check("章节进入 / 效果覆盖随同一次点击落地（不空耗点击）",
      _skip.current_background_path == "a.png"
      and _skip._applied_visual_filter == "blur"
      and len(_skip.story_history) == 1 and _skip._reveal_active(),
      (_skip.current_background_path, _skip._applied_visual_filter,
       _skip.story_history))

# ---------------- 4. 结局 ----------------
ENDING = "城市在她脚下安静地碎成一片灰白"
_end = _PlaybackHost([{"kind": "ending", "name": "真结局", "text": ENDING,
                       "icon_path": "i.png", "step": 7}])
_end._replay_next_step()
check("结局正文同样限速上屏（不是整段直出）",
      _end.story_history[-1]["text"] == "" and _end._reveal_active()
      and _end.story_history[-1]["type_str"] == PREFIX_ENDING,
      _end.story_history[-1])
check("结局记录仍立即终止副本、但不关窗",
      _end.dungeon_ended is True and _end.closed is False)
_t3 = _advance(_end, 1.0)
check("结局上屏走完", _end.story_history[-1]["text"] == ENDING,
      _end.story_history[-1]["text"])
_end._last_click_time = None
_end._on_next_step()
check("结局上屏后才关窗（再点一次）", _end.closed is True)

# ---------------- 5. 朗读拿的是整句，不是已上屏前缀 ----------------
# 记录里的净文本没有说话人，朗读靠 display_text 还原（12.2）；游标把 item 文本
# 清空后，朗读必须仍拿到整句。
QUOTED = "“桥还没塌，先别过去。”"
_sp = _PlaybackHost([{"type": "dialog", "text": QUOTED,
                      "display_text": f"@李队长@{QUOTED}"}])
_sp._replay_next_step()
check("带说话人的回放段落进语音导演（念整句，不是空串 / 不是前缀）",
      _sp._speech.spoken == [("李队长", QUOTED)], _sp._speech.spoken)
check("说话人也在显示层还原（上屏条目带 speaker）",
      _sp.story_history[-1].get("speaker") == "李队长", _sp.story_history[-1])

_quiet = _PlaybackHost([{"type": "dialog", "text": "没有标记的叙述。"}])
_quiet._replay_next_step()
check("旧记录（无 display_text）不念：逐句渐显照旧",
      _quiet._speech.spoken == [] and _quiet._reveal_active(),
      _quiet._speech.spoken)

_sp2 = _PlaybackHost()
_sp2._present_paragraph("桥还没塌，", prefix="【对话】",
                        display_text="@李队长@“桥还没塌，")
check("同一段落的后续句走队列时也带说话人（_present_paragraph 直调）",
      _sp2._speech.spoken == [("李队长", "“桥还没塌")], _sp2._speech.spoken)

# ---------------- 6. 常量契约 ----------------
check("回放复用 30 字/秒的上屏速率（未另造一套节奏）",
      _REVEAL_CHARS_PER_SECOND == 30.0)

# ---------------- 收尾 ----------------
_log.flush()
print("\n[check_replay_playback] %s %d/%d"
      % ("PASSED" if not failures else "FAILED", total - len(failures), total))
print("[check_replay_playback] report: %s" % _report_path)
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
if failures:
    print("FAILURES: %s" % ", ".join(failures))
    sys.exit(1)
print("check_replay_playback.py OK")
