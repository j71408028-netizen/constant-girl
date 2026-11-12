"""自检：回放记录的解析层与回放步进（``dungeon/replay.py`` + ``_replay_*``）。

用法：``python tests/check_replay_parse.py``

无 GUI：回放宿主用「真 mixin + 少量替身」拼出来（``ReplayHost``），只守纯逻辑：

1. ``dungeon.replay``：分类 / 各形态字段归一 / 脏记录不抛异常；
2. 内嵌配置走配置侧归一器（legacy ``volume``、非法语音预设、只写在
   ``action_data.type`` 里的动作类型）；
3. 回放步进：显示前缀随记录走（结束章节 =「结局」）、状态快照还原、
   ``effect`` 覆盖按步到期（含音乐档位这一维）、带显示层标记的原文（``display_text``）
   随记录往返（说话人是回放朗读的唯一依据）；
4. 结局记录：``_record_ending`` 只记一次，回放时复现正文 + 图标并终止；
5. 同一事件的唯一写法：章节环境只由 ``kind:"chapter"`` 承载（旧格式的
   ``goto`` 平级键在解析层展开），反向 ``to_config_fragment`` 与解析成对；
6. 回放身份：``kind:"meta"`` 的写读一轮、坏形状容错、素材路径同源、不占点击、
   不进档案导出；
7. 档案导出：账本快照不画、结局记录画成结局块、meta 计数只数真步进 / 真触发。
"""

import os
import sys
import tempfile
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # tests/：兄弟模块 _trigger_host

_report_path = os.path.join(tempfile.mkdtemp(prefix="replay_parse_"), "report.txt")
_log = open(_report_path, "w", encoding="utf-8")
sys.stdout = _log
sys.stderr = _log

failures = []
total = 0


def check(name, ok, extra=""):
    global total
    total += 1
    print(("  OK   " if ok else "  FAIL ") + name + (f"  <{extra}>" if extra and not ok else ""))
    if not ok:
        failures.append(name)


from dungeon import replay  # noqa: E402
from dungeon.audio import buses  # noqa: E402
from dungeon.models import (PREFIX_ENDING, DungeonState,  # noqa: E402
                            DungeonTextType)
from dungeon.window.ending import EndingHandler  # noqa: E402
from dungeon.window.engine import DungeonStoryEngine  # noqa: E402
from dungeon.window.triggers import TriggerHandler  # noqa: E402

# ---------------- 1. 分类与容错 ----------------
check("无 kind = 步进", replay.classify({"type": "dialog"}) == replay.KIND_STEP)
check("四种显式 kind", [replay.classify({"kind": k}) for k in
                        ("chapter", "trigger", "characters", "ending")]
      == [replay.KIND_CHAPTER, replay.KIND_TRIGGER, replay.KIND_CHARACTERS,
          replay.KIND_ENDING])
check("未知 kind 不可识别（整条跳过）", replay.classify({"kind": "chatter"}) == "")
check("非字典不可识别", replay.classify(["x"]) == "" and replay.classify(None) == "")

_dirty = [
    "整套坏数据",
    None,
    42,
    {"kind": "unknown"},
    {"type": "ending"},                     # 已删的段落类型 + 没有正文
    {"step": "x", "type": None},
    {"type": "dialog"},                     # 没有正文
]
try:
    dropped = replay.parse_all(_dirty)
    crashed = None
except Exception as exc:                     # noqa: BLE001 - 这里就是要它不抛
    dropped, crashed = [], exc
check("脏记录不抛异常", crashed is None, repr(crashed))
check("非字典 / 未知 kind / 无正文整条丢弃", dropped == [],
      [type(r).__name__ for r in dropped])

_dropped_raw = []
_expanded = replay.parse_all(
    [{"kind": "trigger", "name": "跳", "action_type": "goto",
      "action_data": {"chapter": "B"}, "chapter_bgm": {"path": "b.mp3"}},
     "坏", {"type": "dialog", "text": "一段"}],
    on_drop=_dropped_raw.append)
check("on_drop 只收到真丢掉的记录（旧格式展开不算丢弃）",
      len(_dropped_raw) == 1 and len(_expanded) == 3,
      (len(_dropped_raw), len(_expanded)))

_loose = replay.parse_all([
    {"kind": "trigger", "action_data": "不是字典"},
    {"kind": "chapter", "bgm": [1, 2]},
    {"kind": "characters"},
    {"text": "没有类型"},
])
check("缺字段的记录按默认补全后仍可用（不因一处缺键丢整条）",
      [type(r).__name__ for r in _loose]
      == ["TriggerRecord", "ChapterRecord", "CharactersRecord", "StepRecord"],
      [type(r).__name__ for r in _loose])

_step = replay.parse({
    "step": 3, "type": "dialog", "text": " 正文 ", "highlight": 1,
    "intrusion_before": 1, "destruction_before": 2,
    "intrusion_after": 1.5, "destruction_after": 2.5,
    "custom_before": {"好感": "3", "坏值": "x"}, "custom_after": {"好感": 4},
    "total_casualties_after": 12.5, "casualty_increase": 0.5,
})
check("步进记录归一", isinstance(_step, replay.StepRecord)
      and _step.step == 3 and _step.text_type is DungeonTextType.DIALOG
      and _step.highlight is True, _step)
check("自定义属性只留数字项", _step.custom_before == {"好感": 3.0}, _step.custom_before)
check("缺 before 时退到 after",
      replay.parse({"type": "dialog", "text": "x", "intrusion_after": 3}).intrusion_before == 3.0)
check("缺 *_after 是 None（回放不改状态）",
      replay.parse({"type": "dialog", "text": "x"}).intrusion_after is None)
check("custom_after 缺失与空字典区分开",
      replay.parse({"type": "dialog", "text": "x"}).custom_after is None
      and replay.parse({"type": "dialog", "text": "x",
                        "custom_after": {}}).custom_after == {})
check("未知段落类型回退「环境」",
      replay.parse({"type": "ending", "text": "x"}).text_type is DungeonTextType.BACKGROUND)

# ---------------- 2. 内嵌配置复用配置侧归一器 ----------------
_chapter = replay.parse({"kind": "chapter", "name": "A",
                         "background": {"image_path": "a.png", "filter_effect": "blur"},
                         "bgm": {"path": "a.mp3", "volume": 80},
                         "voice_fx": {"her": {"preset": "不存在的预设"}}})
check("章节记录：legacy volume 折算成档位",
      _chapter.bgm.get("level") == buses.step_from_level(80)
      and "volume" not in _chapter.bgm, _chapter.bgm)
check("章节记录：非法语音预设归一为「不加效果」", _chapter.voice_fx == {}, _chapter.voice_fx)
check("章节记录：非字典 bgm 归一为空（视为停播）",
      replay.parse({"kind": "chapter", "bgm": [1]}).bgm == {})

_trigger = replay.parse({"kind": "trigger", "name": "跳",
                         "action_data": {"type": "goto", "chapter": "B"}})
check("动作类型从 action_data.type 回退", _trigger.action_type == "goto")
check("缺动作类型的记录退成 none",
      replay.parse({"kind": "trigger", "name": "x"}).action_type == "none")
check("选择编号非数字视为未选择",
      replay.parse({"kind": "trigger", "name": "x",
                    "choice_index": "abc"}).choice_index is None)
check("小游戏标量结果包成 {value}", replay.parse(
    {"kind": "trigger", "name": "g", "game_result": 3}).game_result == {"value": 3})

# ---------------- 3. 回放宿主 ----------------
class _Bgm:
    def __init__(self):
        self.calls = []

    def play(self, spec):
        self.calls.append(dict(spec or {}))


class _Speech:
    def __init__(self):
        self.effects = []

    def set_effect(self, spec=None):
        self.effects.append(dict(spec or {}))


class _Frame:
    """帧时钟替身：主线程里立即执行。"""

    def call(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)


class ReplayHost(DungeonStoryEngine, TriggerHandler, EndingHandler):
    """回放宿主：真 mixin + 少量替身（无窗口、无音频设备、无 AI）。

    ``_present_paragraph`` 在这里是整段直出的替身：本文件断言的是解析、前缀与
    状态，上屏节奏（限速 / 逐句 / 跳过不可见记录）由
    ``check_replay_playback.py`` 用真实现覆盖。
    """

    def __init__(self, records=None):
        self.loaded_replay = replay.parse_all(records or [])
        self.current_replay_index = 0
        self.dungeon_state = DungeonState(intrusion=0.0, destruction=0.0, custom_attrs={})
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
        self._frame = _Frame()
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
        self.fired_triggers = set()
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
        self.bg_calls = []
        self.fx_calls = []
        self.icon_calls = []
        self.closed = False
        self._closing = False

    # ---------- 替身 ----------
    def change_background(self, image_path, smooth, filter_effect):
        self.bg_calls.append((image_path, smooth, filter_effect))

    def start(self, fx_key, duration, intensity):
        self.fx_calls.append((fx_key, duration, intensity))

    def _current_action_points(self):
        return None

    def _update_text_display(self):
        pass

    def _update_ending_icon(self):
        self.icon_calls.append(self.ending_icon_path)

    def _request_close(self):
        self.closed = True

    def _present_paragraph(self, text, *, prefix, highlight=False, display_text=None):
        self.story_history.append({"type_str": prefix, "text": text,
                                   "highlight": highlight, "speaker": None,
                                   "display_text": display_text})


# ---------- 3.1 显示前缀随记录走 ----------
def _play(records, steps=1):
    host = ReplayHost(records)
    for _ in range(steps):
        host._replay_next_step()
    return host


_old = _play([{"type": "background", "text": "结束前", "ending_chapter": True,
               "intrusion_after": 1, "destruction_after": 1}])
check("旧记录（无 type_prefix）在结束章节显示「结局」",
      _old.story_history[-1]["type_str"] == PREFIX_ENDING, _old.story_history[-1])

_new = _play([{"type": "background", "text": "结束前", "ending_chapter": True,
               "type_prefix": PREFIX_ENDING, "intrusion_after": 1,
               "destruction_after": 1}])
check("新记录直接取 type_prefix", _new.story_history[-1]["type_str"] == PREFIX_ENDING)

_plain = _play([{"type": "dialog", "text": "你好"}])
check("无前缀记录按类型现算", _plain.story_history[-1]["type_str"] == "【对话】")
_blank = _play([{"type": "dialog", "text": "留白", "type_prefix": ""}])
check("空串前缀 = 本段不显示前缀（固定文本的纯叙述段）",
      _blank.story_history[-1]["type_str"] == "")

# ---------- 3.2 状态快照 ----------
_state = _play([{"type": "dialog", "text": "一段", "intrusion_after": 3.5,
                 "destruction_after": 1.5, "custom_after": {"好感": 2},
                 "total_casualties_after": 99, "casualty_increase": 4}])
check("回放按记录还原状态", _state.dungeon_state.intrusion == 3.5
      and _state.dungeon_state.destruction == 1.5
      and _state.dungeon_state.custom_attrs == {"好感": 2.0}
      and _state.dungeon_state.total_casualties == 99
      and _state.dungeon_state.casualty_evolution == [4.0],
      _state.dungeon_state)
_keep = ReplayHost([{"type": "dialog", "text": "一段"}])
_keep.dungeon_state.intrusion = 2.0
_keep._replay_next_step()
check("缺快照的旧记录不动状态", _keep.dungeon_state.intrusion == 2.0)

_steps = _play([{"type": "dialog", "text": "第 5 步", "step": 5}])
check("步数随记录还原（回放不走 evolve_attributes，否则恒为 0）",
      _steps.dungeon_state.total_steps == 5 and _steps.step_num == 5,
      (_steps.dungeon_state.total_steps, _steps.step_num))
check("记录没写步数时按 0（与不回填等价）",
      _play([{"type": "dialog", "text": "无步数"}]).dungeon_state.total_steps == 0)

# ---------- 3.3 覆盖按步到期 ----------
_CHAPTER_A = [{"kind": "chapter", "name": "A",
               "background": {"image_path": "a.png", "filter_effect": "smooth"},
               "bgm": {"path": "a.mp3", "level": 3}}]
_effect_records = _CHAPTER_A + [
    {"kind": "trigger", "name": "覆盖", "action_type": "effect",
     "action_data": {"filter": "blur", "bgm_level": 1, "duration": 2}},
    {"type": "dialog", "text": "一步", "type_prefix": "【对话】"},
    {"type": "dialog", "text": "两步", "type_prefix": "【对话】"},
    {"type": "dialog", "text": "三步", "type_prefix": "【对话】"},
]
host = ReplayHost(_effect_records)
host._replay_next_step()                       # 章节 + 覆盖 + 第 1 步
check("回放进入章节：音乐按记录复现（legacy 也能取到档位）",
      host.chapter_bgm.get("level") == 3 and host.current_background_path == "a.png",
      host.chapter_bgm)
check("回放复现覆盖（滤镜 + 档位）",
      host._applied_visual_filter == "blur" and host._applied_bgm_level == 1,
      (host._applied_visual_filter, host._applied_bgm_level))
check("不可见记录不占点击：一次点击落在第 1 步正文上",
      [item.get("text") for item in host.story_history] == ["一步"],
      host.story_history)
check("覆盖第 1 步后仍生效",
      bool(host.effect_overrides) and host._applied_visual_filter == "blur"
      and host._applied_bgm_level == 1,
      (host.effect_overrides, host._applied_visual_filter))
host._replay_next_step()                       # 第 2 步：到期
check("走过 duration 步后覆盖到期", host.effect_overrides == [])
check("到期后滤镜回章节默认（来自记录，不查方案配置）",
      host._applied_visual_filter == "smooth" and host.bg_calls[-1][2] == "smooth",
      host.bg_calls[-1])
check("到期后音乐档位回章节默认",
      host._applied_bgm_level == 3 and host._bgm.calls[-1].get("level") == 3,
      host._bgm.calls[-1])
host._replay_next_step()                       # 第 3 步：不该再回退一次
check("到期后再走一步不重复刷新",
      host._applied_visual_filter == "smooth"
      and host.bg_calls.count(("a.png", False, "smooth")) == 1,
      host.bg_calls)

# ---------- 3.4 旧格式的章节跳转记录 ----------
_jump = ReplayHost(_CHAPTER_A + [
    {"kind": "trigger", "name": "跳", "action_type": "goto",
     "action_data": {"chapter": "B"},
     "chapter_background": {"image_path": "b.png", "filter_effect": "emboss"},
     "chapter_bgm": {"path": "b.mp3", "volume": 40}}])
_jump._replay_next_step()                       # 章节 + 跳转：都是不可见记录
check("旧格式跳转记录（环境在平级键里）仍复现目标章节环境（bgm 同样归一）",
      _jump.current_chapter == "B" and _jump.current_background_path == "b.png"
      and _jump.chapter_filter == "emboss"
      and _jump.chapter_bgm.get("level") == buses.step_from_level(40),
      (_jump.current_chapter, _jump.chapter_bgm))

# ---------- 3.5 显示层原文（朗读与高亮的来源） ----------
check("写侧：原文带显示层标记才写 display_text",
      replay.display_text_field("@李队长@“桥还没塌，”") == "@李队长@“桥还没塌，”"
      and replay.display_text_field("没有标记的叙述") == ""
      and replay.display_text_field(None) == "")
_marked = replay.parse({"type": "dialog", "text": "“走。”",
                        "display_text": "@甲@“走。”"})
check("解析：display_text 随净文本一起还原",
      _marked.text == "“走。”" and _marked.display_text == "@甲@“走。”",
      (_marked.text, _marked.display_text))
check("旧记录没有 display_text（照旧逐句渐显、只是不念）",
      replay.parse({"type": "dialog", "text": "一段"}).display_text == "")
check("对不上的 display_text 不采信（按净文本播）",
      replay.parse({"type": "dialog", "text": "另一段",
                    "display_text": "@甲@“走。”"}).display_text == "")
_play_marked = _play([{"type": "dialog", "text": "“走。”",
                       "display_text": "@甲@“走。”"}])
check("回放把带标记的原文交给显示管线（说话人来源）",
      _play_marked.story_history[-1]["display_text"] == "@甲@“走。”",
      _play_marked.story_history[-1])
check("没有该字段的记录把空串交给显示管线（回退净文本）",
      _plain.story_history[-1]["display_text"] == "")

# ---------------- 4. 结局记录 ----------------
class _EndingState:
    total_steps = 7


_writer = ReplayHost()
_writer.dungeon_state = _EndingState()
_writer._ending_name = "真结局"
_writer.ending_text = "正文"
_writer.ending_icon_path = "icon.png"
_writer._record_ending()
_writer._record_ending()
check("结局记录只写一次", len(_writer.replay_data) == 1, _writer.replay_data)
check("结局记录字段", _writer.replay_data[0] == {
    "kind": "ending", "name": "真结局", "text": "正文",
    "icon_path": "icon.png", "step": 7}, _writer.replay_data[0])
check("结局记录能被解析回原样",
      replay.parse(_writer.replay_data[0]).text == "正文")

_ending = ReplayHost([{"kind": "ending", "name": "真结局", "text": "正文",
                       "icon_path": "icon.png", "step": 7}])
_ending._replay_next_step()
check("回放复现结局：正文 + 标记 + 终止",
      _ending.story_history[-1] == {"type_str": PREFIX_ENDING, "text": "正文",
                                    "highlight": True, "speaker": None,
                                    "display_text": None}
      and _ending.ending_text == "正文" and _ending.dungeon_ended is True,
      _ending.story_history[-1])
check("回放复现结局图标", _ending.icon_calls == ["icon.png"], _ending.icon_calls)
_ending._replay_next_step()
check("结局之后再点一次 = 关窗", _ending.closed is True)

_old_ending = ReplayHost([{"kind": "trigger", "name": "旧结局",
                           "action_type": "ending",
                           "action_data": {"type": "ending", "icon_path": "old.png"},
                           "ending_text": "旧正文"}])
_old_ending._replay_next_step()
check("旧版 ending 触发记录仍能复现结局（含图标）",
      _old_ending.ending_text == "旧正文" and _old_ending.icon_calls == ["old.png"]
      and _old_ending.dungeon_ended is True, _old_ending.story_history)

# ---------------- 5. 同一事件唯一写法 + 反向片段 ----------------
from _trigger_host import TriggerHost  # noqa: E402
from dungeon.audio.chapters import normalize_chapter  # noqa: E402
from dungeon.validate import validate_scenario_config  # noqa: E402

# 旧格式：章节环境塞在 goto 触发器记录的三个平级键里
_legacy_goto = replay.parse_all([{
    "kind": "trigger", "name": "跳", "action_type": "goto",
    "action_data": {"chapter": "B"},
    "chapter_background": {"image_path": "b.png", "filter_effect": "blur"},
    "chapter_bgm": {"path": "b.mp3", "volume": 40}}])
check("旧格式 goto 在解析层展开成「章节进入 + 触发器」",
      [type(r).__name__ for r in _legacy_goto] == ["ChapterRecord", "TriggerRecord"]
      and _legacy_goto[0].name == "B"
      and _legacy_goto[0].bgm.get("level") == buses.step_from_level(40),
      [type(r).__name__ for r in _legacy_goto])

# 新格式：写侧只留一条章节记录（环境）+ 一条触发器记录（谁触发的）
_CH_A = {"name": "A", "background": {"image_path": "a.png"},
         "bgm": {"path": "a.mp3", "level": 2}}
_CH_B = {"name": "B",
         "background": {"image_path": "b.png", "filter_effect": "emboss"},
         "bgm": {"path": "b.mp3", "volume": 40},
         "voice_fx": {"her": {"preset": "giant_boom", "intensity": 60}}}
_writer_goto = TriggerHost(
    [{"name": "跳", "chapter": "", "action_type": "goto",
      "action_data": {"chapter": "B"}, "repeatable": True}],
    chapters=[_CH_A, _CH_B], current_chapter="A")
_writer_goto._begin_trigger_round()
_writer_goto.check_triggers()
check("写侧：跳转只写「章节进入 + 触发器」两条",
      [entry.get("kind") for entry in _writer_goto.replay_data]
      == ["chapter", "trigger"], _writer_goto.replay_data)
check("写侧：环境只出现在章节记录里（触发器记录不再带平级键）",
      _writer_goto.replay_data[0]["background"] == _CH_B["background"]
      and all(key not in _writer_goto.replay_data[1]
              for key in ("chapter_background", "chapter_bgm", "chapter_voice_fx")),
      _writer_goto.replay_data)

_written = ReplayHost(_writer_goto.replay_data)
_written._replay_next_step()
_written._replay_next_step()
check("写出的两条记录回放后落在同一环境（goto 不重复进入）",
      _written.current_chapter == "B" and _written.current_background_path == "b.png"
      and _written.chapter_bgm.get("level") == buses.step_from_level(40)
      and _written.bg_calls.count(("b.png", True, "emboss")) == 1,
      (_written.current_chapter, _written.chapter_bgm, _written.bg_calls))

# 反向：记录 → 配置片段（回溯改写的出口）
_cfg_chapter = normalize_chapter(dict(_CH_B))
_chapter_rec = replay.parse({"kind": "chapter", "name": "B",
                             "background": _cfg_chapter["background"],
                             "bgm": _cfg_chapter["bgm"],
                             "voice_fx": _cfg_chapter["voice_fx"]})
_fragment = replay.to_config_fragment(_chapter_rec)
check("章节记录 → 片段：并回章节后与配置侧归一结果同形",
      normalize_chapter(dict(_cfg_chapter, **_fragment)) == _cfg_chapter, _fragment)
check("片段不写没配的维度（不摊空字典）",
      set(replay.to_config_fragment(replay.parse(
          {"kind": "chapter", "name": "A"}))) == {"name"})

_trig_rec = replay.parse({"kind": "trigger", "name": "窗", "action_type": "fx",
                          "action_data": {"fx": "invert", "duration": 2,
                                          "intensity": 50}})
_trig_fragment = replay.to_config_fragment(_trig_rec)
check("触发器记录 → 片段：只写规范动作键（不再拼 action / action_data.type）",
      set(_trig_fragment) == {"name", "action_type", "action_data"}, _trig_fragment)
check("片段并回方案后校验零 error",
      not [d for d in validate_scenario_config(
          {"chapters": [{"name": "A", "start": True}],
           "triggers": [dict(_trig_fragment, chapter="")]})
          if d.level == "error"],
      _trig_fragment)
check("步进 / 账本 / 结局记录没有配置对应物",
      replay.to_config_fragment(replay.parse({"type": "dialog", "text": "x"})) is None
      and replay.to_config_fragment(replay.parse({"kind": "characters"})) is None
      and replay.to_config_fragment(replay.parse({"kind": "ending", "name": "E"})) is None)

# ---------------- 6. 回放身份（kind:"meta"） ----------------
check("身份记录是一种独立 kind",
      replay.classify({"kind": "meta"}) == replay.KIND_META)

_meta_raw = {
    "kind": "meta", "version": 1,
    "scenario": {"id": "juying_lincheng", "content_hash": "sha256:abc",
                 "version_tag": "1.2.0",
                 "assets": [{"path": "/images/01.jpg", "size": 2048},
                            {"path": "", "size": 1},
                            "坏条目",
                            {"path": "music/theme.mp3", "size": "x"}]},
    "app": "2.0.0", "saved_at": "2026-11-10T10:51:13"}
_meta = replay.parse(_meta_raw)
check("身份记录解析出方案 / 版本 / 时间",
      _meta.scenario_id == "juying_lincheng" and _meta.content_hash == "sha256:abc"
      and _meta.version_tag == "1.2.0" and _meta.app == "2.0.0"
      and _meta.saved_at == "2026-11-10T10:51:13", _meta)
check("素材清单去掉空路径 / 坏条目，路径去前导斜杠，算不出的尺寸留空",
      _meta.assets == ({"path": "images/01.jpg", "size": 2048},
                       {"path": "music/theme.mp3", "size": None}), _meta.assets)

_meta_loose = replay.parse_all([
    {"kind": "meta"},
    {"kind": "meta", "scenario": "不是字典"},
    {"kind": "meta", "scenario": {"id": "x", "assets": "不是列表"}},
])
check("身份记录的缺键 / 坏形状不抛异常（退化成空值）",
      [r.scenario_id for r in _meta_loose] == ["", "", "x"]
      and all(r.assets == () for r in _meta_loose),
      _meta_loose)
check("旧版本读到 meta 只是多一条可识别记录（不丢别的记录）",
      len(replay.parse_all([_meta_raw, {"type": "dialog", "text": "旧"}]) ) == 2)

_built = replay.meta_record(
    scenario={"id": "abc", "content_hash": "sha256:ff", "version_tag": "0.9",
              "assets": [{"path": "images/a.png", "size": 10}]},
    app="2.0.0", saved_at="2026-11-10T10:51:13")
check("写出的身份记录是文档里的形状",
      _built == {"kind": "meta", "version": replay.META_VERSION,
                 "scenario": {"id": "abc", "content_hash": "sha256:ff",
                              "version_tag": "0.9",
                              "assets": [{"path": "images/a.png", "size": 10}]},
                 "app": "2.0.0", "saved_at": "2026-11-10T10:51:13"}, _built)
_round = replay.parse(_built)
check("写→读一轮不丢字段",
      (_round.scenario_id, _round.content_hash, _round.version_tag,
       _round.app, _round.saved_at, _round.assets)
      == ("abc", "sha256:ff", "0.9", "2.0.0", "2026-11-10T10:51:13",
          ({"path": "images/a.png", "size": 10},)), _round)
check("没有方案信息的身份记录不写空 scenario 键",
      replay.meta_record(app="2.0.0") == {"kind": "meta",
                                          "version": replay.META_VERSION,
                                          "app": "2.0.0"})

# 素材路径：反查方案与写 meta.assets 同源
_material = replay.material_paths(replay.parse_all([
    {"kind": "chapter", "name": "A",
     "background": {"image_path": "/images/a.png"}, "bgm": {"path": "music/a.mp3"}},
    {"kind": "ending", "name": "E", "icon_path": "icons/e.png"},
    {"kind": "trigger", "name": "旧结局", "action_type": "ending",
     "action_data": {"icon_path": "icons/old.png"}},
    {"type": "dialog", "text": "正文不参与"},
]))
check("素材路径来自章节环境 / 结局图标 / 旧版 ending 动作的图标",
      _material == ["images/a.png", "music/a.mp3", "icons/e.png", "icons/old.png"],
      _material)
check("绝对路径不参与、重复只留一条",
      replay.material_paths(replay.parse_all([
          {"kind": "chapter", "background": {"image_path": os.path.abspath("a.png")}},
          {"kind": "chapter", "background": {"image_path": "images/a.png"}},
          {"kind": "chapter", "background": {"image_path": "images/a.png"}},
      ])) == ["images/a.png"])
check("素材路径最多 8 条（与反查上限同一处定义）",
      len(replay.material_paths(replay.parse_all([
          {"kind": "chapter", "background": {"image_path": f"images/{i}.png"}}
          for i in range(20)]))) == replay.MATERIAL_PATH_LIMIT)

# 身份记录不参与步进：不占点击、不进档案导出
_host_meta = _play([
    _meta_raw,
    {"type": "dialog", "text": "第一段"},
    {"kind": "meta", "scenario": {"id": "另一个方案"}},
    {"type": "dialog", "text": "第二段"},
])
check("身份记录不占点击（一次点击落在正文上）",
      [item.get("text") for item in _host_meta.story_history] == ["第一段"],
      _host_meta.story_history)
_host_meta._replay_next_step()
check("中间的身份记录同样跳过",
      [item.get("text") for item in _host_meta.story_history] == ["第一段", "第二段"],
      _host_meta.story_history)

# ---------------- 7. 档案导出 ----------------
from services.character.archive_export import (_render_replay_entries,  # noqa: E402
                                               _replay_counts)

_entries = [
    {"kind": "meta", "version": 1, "scenario": {"id": "x"}},
    {"kind": "characters", "snapshot": {"members": []}},
    {"type": "dialog", "text": "第一段", "step": 1},
    {"kind": "trigger", "name": "跳", "action_type": "goto", "action_data": {}},
    {"kind": "chapter", "name": "A"},
    {"kind": "ending", "name": "真结局", "text": "END"},
]
_html = _render_replay_entries(_entries)
check("账本快照与身份记录不画成空块",
      "text-unknown" not in _html and "【未知】" not in _html, _html)
check("结局记录画成结局块", "真结局" in _html and "END" in _html)
check("meta 计数只数真步进与真触发", _replay_counts(_entries) == (1, 1),
      _replay_counts(_entries))

# ---------------- 汇总 ----------------
_log.flush()
sys.stdout = sys.__stdout__
print(f"[check_replay_parse] {'PASSED' if not failures else 'FAILED'} "
      f"{total - len(failures)}/{total}")
print(f"[check_replay_parse] report: {_report_path}")
sys.exit(1 if failures else 0)
