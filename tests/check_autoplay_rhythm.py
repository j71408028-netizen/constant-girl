"""自检：自动播放的推进节奏（实时与回放共用一条）。

用法：``python tests/check_autoplay_rhythm.py``

无 GUI：把 ``DungeonStoryEngine`` 的推进机、``ComponentHandler`` 的会话判定、
``DungeonWindowUI`` 的游标与自动播放挂到最小宿主上。帧时钟用真
``FrameScheduler.tick(now=)`` 显式推进，会话时钟（``_advance_due`` /
``_last_click_time`` 读的那个）换成可控替身，于是节奏可以逐刻断言：

1. **队列不是阻塞项**：分句队列里还有没上屏的显示段落时
   ``session_waiting_for_input`` 为假（继续指示不闪），但自动播放必须接着播——
   这是「每段只播首句就停」的回归位；
2. **按节奏推进**：一句走完 → 停留 → 下一句，既不是 0.2 秒硬翻，也不是停住；
3. **段落之间不断档**：队列播完 → 生成下一段 → 继续按节奏播；
4. **阻塞项照旧**：生成中 / 选项弹窗 / 结局达成时停手；
5. **补满同权**：点击补满（``_reveal_snap``）与自然走完一样登记停留到期时刻。
"""

import os
import sys
import tempfile
import time as _real_time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_report_path = os.path.join(tempfile.mkdtemp(prefix="autoplay_rhythm_"), "report.txt")
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


import dungeon.window.engine as _engine_mod  # noqa: E402
import dungeon.window.ui as _ui_mod  # noqa: E402
from dungeon.window.components import ComponentHandler  # noqa: E402
from dungeon.window.engine import DungeonStoryEngine  # noqa: E402
from dungeon.window.frame import FrameScheduler  # noqa: E402
from dungeon.window.ui import (  # noqa: E402
    DungeonWindowUI,
    _AUTOPLAY_DWELL,
    _AUTOPLAY_DWELL_PER_CHAR,
    _AUTOPLAY_INTERVAL,
    _AUTOPLAY_TASK,
    _REVEAL_CHARS_PER_SECOND,
    _REVEAL_TICK_SECONDS,
)


class _Clock:
    """可控会话时钟：替掉两个模块里的 ``time``。

    ``_advance_due`` 与 ``_last_click_time`` 都读它，测试才能把「停留期」与
    「0.4 秒防抖」当确定量断言，而不是靠真实睡眠。
    """

    def __init__(self):
        self.now = _real_time.monotonic()

    def monotonic(self):
        return self.now

    def time(self):
        return self.now

    def __getattr__(self, name):
        return getattr(_real_time, name)


_clock = _Clock()
_ui_mod.time = _clock
_engine_mod.time = _clock


class _AutoplayHost(DungeonStoryEngine, ComponentHandler, DungeonWindowUI):
    """自动播放宿主：真推进机 + 真游标 + 少量替身（无窗口 / 无 AI）。"""

    def __init__(self):
        self._frame = FrameScheduler()
        self.is_replay = False
        self.story_history = []
        self._pending_units = []
        self._reveal = None
        self._advance_due = 0.0
        self._last_click_time = None
        self._closing = False
        self._generating = False
        self._autoplay = False
        self._components = []
        self._is_entry_phase = False
        self._script = None
        self.dungeon_ended = False
        self.pending_option = None
        self.pending_mini_game = None
        self.pending_ending = None
        self.paragraphs_queue = []
        self.paragraphs = 0
        self._spoken = []
        self._text_updates = 0
        self.notices = []

    # ---------- 替身 ----------
    def overlay_open(self):
        return False

    def _schedule_text_update(self):
        self._text_updates += 1

    def _update_text_display(self):
        pass

    def _speak_item(self, item):
        if item.get("speaker"):
            self._spoken.append((item.get("speaker"), item.get("text")))

    def _notify(self, text):
        self.notices.append(text)

    def _refresh_components(self):
        pass

    def _peek_pending_insertion(self):
        return None

    def _in_fixed_text_chapter(self):
        return False

    def _generate_next_text(self):
        """模拟一次生成：立刻把下一段上屏（预生成路径的形态）。

        素材用尽时停在 ``_generating``，与真实链路「等 AI 回包」一致——否则
        替身每 tick 都空转一次，测出来的推进次数没有意义。
        """
        self.paragraphs += 1
        self._generating = True
        if not self.paragraphs_queue:
            return
        self._present_paragraph(self.paragraphs_queue.pop(0), prefix="【环境】")
        self._generating = False

    # ---------- 断言辅助 ----------
    def texts(self):
        return [item["text"] for item in self.story_history]

    def finished_units(self):
        return len(self.texts())

    def autoplay_tasks(self):
        return [t for t in self._frame._tasks if t.key == _AUTOPLAY_TASK]


def _tick(host, seconds):
    """推进 ``seconds`` 秒：会话时钟与帧时钟同步前进。"""
    t = _clock.now
    for _ in range(int(round(seconds / _REVEAL_TICK_SECONDS))):
        t += _REVEAL_TICK_SECONDS
        _clock.now = t
        host._frame.tick(now=t)


# 分句器的最小单元长度是 6 字，例句都写够长，确保一段切成 3 个显示段落
_P1 = "开头一句写得够长一点。第二句也要够长才行。第三句同样得够长。"
_P2 = "下一段甲句也够长。下一段乙句也够长。"

# ---------------- 1. 队列不是阻塞项，且不断档 ----------------

host = _AutoplayHost()
host.paragraphs_queue = [_P2]
host._present_paragraph(_P1, prefix="【环境】")
host.toggle_autoplay()

check("开启自动播放：登记了采样任务", len(host.autoplay_tasks()) == 1,
      len(host.autoplay_tasks()))
check("一段切成 3 个显示段落", len(host._pending_units) == 2,
      [u.text for u in host._pending_units])

elapsed = 0.0
_tick(host, 0.5)
elapsed += 0.5
check("首句上屏中/刚上完时不动（只有 1 段正文）",
      host.finished_units() == 1, host.texts())
check("首句已走完但仍在停留期", host._reveal is None and host._advance_due > _clock.now,
      (host._reveal, host._advance_due - _clock.now))
check("队列非空时 session_waiting_for_input 为假（继续指示不闪）",
      host.session_waiting_for_input() is False)

_tick(host, 0.7)
elapsed += 0.7
check("首句停留期满后自动揭开第二句（不是停住）",
      host.finished_units() == 2, host.texts())

_tick(host, 1.0)
elapsed += 1.0
check("继续按停留节奏推进到第三句（不是 0.2 秒一句）",
      host.finished_units() == 3, host.texts())

_tick(host, 1.0)
elapsed += 1.0
check("队列播完能继续生成下一段（不断档）",
      host.paragraphs == 1, (host.paragraphs, host.texts()))
check("下一段正文已上屏", host.finished_units() >= 4, host.texts())

_tick(host, 2.4)
elapsed += 2.4
check("全程按节奏播完：本段 3 句 + 下一段 2 句",
      host.finished_units() == 5, (host.texts(), host._pending_units))
check("素材用尽后停在「生成中」，不再空转推进",
      host.paragraphs == 2 and host._generating is True,
      (host.paragraphs, host._generating))
check("每句都等了停留期（5 句耗时 > 3 秒）", elapsed > 3.0, elapsed)

# ---------------- 2. 停留：补满与自然走完同权 ----------------

host2 = _AutoplayHost()
host2._present_paragraph("短句。", prefix="【环境】")
host2.toggle_autoplay()
host2._advance_due = 0.0              # 假装停留期已过
host2._reveal_snap()                  # 点击补满
check("点击补满同样登记停留到期时刻",
      host2._advance_due - _clock.now >= _AUTOPLAY_DWELL - 1e-6,
      host2._advance_due - _clock.now)
check("停留随句长微增",
      abs((host2._advance_due - _clock.now)
          - (_AUTOPLAY_DWELL + _AUTOPLAY_DWELL_PER_CHAR * len("短句。"))) < 1e-6,
      host2._advance_due - _clock.now)

# ---------------- 3. 阻塞项照旧 ----------------

host3 = _AutoplayHost()
host3.paragraphs_queue = ["不该出现的段落。"]
host3._present_paragraph("开头一句写得够长一点。后面还有一句够长的。", prefix="【环境】")
host3.toggle_autoplay()
host3._reveal_snap()                  # 首句定稿，队列里留着第二句

before = host3.finished_units()


def _tick_blocked(host, **flags):
    for key, value in flags.items():
        setattr(host, key, value)
    host._advance_due = 0.0
    host._last_click_time = None
    _tick(host, _AUTOPLAY_INTERVAL * 2)


_tick_blocked(host3, _generating=True)
host3._generating = False
check("生成中不推进", before == host3.finished_units(), host3.texts())

_tick_blocked(host3, pending_option={"name": "x"})
host3.pending_option = None
check("选项弹窗未定时不推进", before == host3.finished_units(), host3.texts())

_tick_blocked(host3, dungeon_ended=True)
host3.dungeon_ended = False
check("结局达成后不推进", before == host3.finished_units(), host3.texts())
check("阻塞期间生成也没被触发", host3.paragraphs == 0, host3.paragraphs)

host3._advance_due = 0.0
_tick(host3, 0.2)
check("解除阻塞后立刻恢复推进", host3.finished_units() == before + 1, host3.texts())

# ---------------- 4. 常量契约 ----------------

check("采样频率快于停留（否则节奏被采样拖慢）",
      _AUTOPLAY_INTERVAL < _AUTOPLAY_DWELL, _AUTOPLAY_INTERVAL)
check("上屏仍限速 30 字/秒", _REVEAL_CHARS_PER_SECOND == 30.0,
      _REVEAL_CHARS_PER_SECOND)

print()
print(f"共 {total} 项，失败 {len(failures)} 项")
if failures:
    for name in failures:
        print("  - " + name)
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
print(f"report: {_report_path}")
sys.exit(1 if failures else 0)
