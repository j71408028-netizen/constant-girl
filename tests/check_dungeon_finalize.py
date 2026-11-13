"""副本 S1 收尾路径与原子写自检（无 GUI，不触碰真实 data/ 目录）。

用法：``python tests/check_dungeon_finalize.py``
输出：控制台一行 ASCII 结论 + UTF-8 报告文件路径（报告在临时目录，含全部明细）。

覆盖：
1. ``persistence/json_store``：原子写、覆盖前留 .bak、损坏回退、无残留 .tmp；
2. ``persistence/scenario_repo``：正常读写 + 主文件损坏时自愈读 .bak；
3. ``DungeonPersistence._finalize``：完成路径（结算 + 结局索引 + 自动保存）
   与未完成路径（什么都不落盘、不建角色、幂等、退出前确认一次放弃）；
4. 回放身份记录（写侧）：头部 meta 取方案信封的 id / 版本 / 内容哈希，
   ``assets`` 只记记录里用到的文件与字节数。
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_report_path = os.path.join(tempfile.mkdtemp(prefix="dungeon_finalize_check_"), "report.txt")
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


# ---------------- 1. 原子写 + .bak ----------------
from persistence.json_store import (  # noqa: E402
    load_json_with_backup, write_json_atomic, write_text_atomic)

tmp = tempfile.mkdtemp(prefix="dungeon_finalize_")
p = os.path.join(tmp, "config.json")
write_json_atomic(p, {"a": 1})
check("首次写入内容正确", json.load(open(p, encoding="utf-8")) == {"a": 1})
check("无残留 .tmp", not os.path.exists(p + ".tmp"))
write_json_atomic(p, {"a": 2})
check("覆盖后主文件为新内容", json.load(open(p, encoding="utf-8")) == {"a": 2})
check("覆盖前留了一份 .bak", json.load(open(p + ".bak", encoding="utf-8")) == {"a": 1})

with open(p, "w", encoding="utf-8") as f:
    f.write("{\u534a\u622a\u574f\u6587\u4ef6")
check("主文件损坏时回退到 .bak", load_json_with_backup(p) == {"a": 1})
check("两者都不可用时返回 None",
      load_json_with_backup(os.path.join(tmp, "\u4e0d\u5b58\u5728.json")) is None)

tp = os.path.join(tmp, "report.txt")
write_text_atomic(tp, "\u4f60\u597d")
check("文本原子写", open(tp, encoding="utf-8").read() == "\u4f60\u597d")

# ---------------- 2. scenario_repo 读写 ----------------
from persistence.scenario_repo import ScenarioRepo  # noqa: E402

repo_dir = os.path.join(tmp, "data")
repo = ScenarioRepo(data_dir=repo_dir)
repo.save_config("default", {"initial_prompt": "v1"})
repo.save_config("default", {"initial_prompt": "v2"})
check("repo 正常读取新内容", repo.load_config("default")["initial_prompt"] == "v2")
config_path = os.path.join(repo_dir, "packs", "scenarios", "default", "config.json")
with open(config_path, "w", encoding="utf-8") as f:
    f.write("{\u5199\u574f\u4e86")
check("repo 自愈读取 .bak", repo.load_config("default")["initial_prompt"] == "v1")

# ---------------- 3. _finalize 三态 ----------------
import dungeon.window.persistence as persp  # noqa: E402
from dungeon.window.ending import EndingHandler  # noqa: E402
from dungeon.window.host import DIALOG_ASK, HostPort  # noqa: E402


class RecordingHost(HostPort):
    """记录收尾弹框；询问类按 ``answer`` 回答（默认「否」）。

    L2 之后 window 层只经宿主端口弹框（``dungeon/window/host.py``），
    自检因此改为注入一个记录宿主，不再打桩 ``ui.ctk.dialogs`` 模块。
    """

    def __init__(self, answer=False):
        self.calls = []   # [(kind, title, message), ...]
        self.answer = answer

    def dialog(self, kind, title, message):
        self.calls.append((kind, title, message))
        return self.answer if kind == DIALOG_ASK else None


HOST = RecordingHost()
dialog_calls = HOST.calls

# 所有落盘都改到临时目录，绝不碰真实 data/
session_root = os.path.join(tmp, "session_data")
persp.data_dir = lambda: session_root


class FakeCharacter:
    giantess_id = "测试角色_unit"
    name = "测试角色"


class FakeState:
    intrusion = 1.5
    destruction = 2.0
    custom_attrs = {"测试属性": 3.0}
    total_steps = 7
    total_casualties = 1234.0


class StubSession(persp.DungeonPersistence, EndingHandler):
    """最小会话替身：只补齐 _finalize 依赖的状态字段。"""

    def __init__(self, with_character=True, mode="explore", errors=()):
        self.host = HOST
        self.is_replay = False
        self.mode = mode
        self.scenario_id = "unit_test"
        self.name = "测试角色"
        self.nick = ""
        self.original_height = 1.6
        self.body_parts = {}
        self.personality = {}
        self.greed = 0
        self.tags = []
        self.intro_hidden = ""
        self.intro_visible = ""
        self.settings = {}
        self.dungeon_settings = {}
        self.height = 100.0
        self.ending_text = ""
        self.ending_effects = {}
        self.ending_icon_path = ""
        self._ending_trigger_index = -1
        self._achievement_record = None
        self._replay_saved = False
        self._finalized = False
        self._session_errors = list(errors)
        self._last_ending_record = None
        self._ending_thread = None
        self.pending_ending = None
        self.dungeon_ended = False
        self.character = FakeCharacter() if with_character else None
        self.character_repo = None
        self.dungeon_state = FakeState()
        self.story_history = [{"type_str": "【对话】", "text": "你好"}]
        self.replay_data = [{"step": 1, "type": "dialog", "text": "你好"}]


# 3.1 未完成退出：不落盘任何回放 / 报告（本版没有中途存档与接续）
replay_dir = os.path.join(session_root, "archives", "测试角色_unit", "回放")
report_dir = os.path.join(session_root, "archives", "测试角色_unit", "报告")
user_replays = os.path.join(session_root, "user", "replays")
user_reports = os.path.join(session_root, "user", "reports")

stub = StubSession()
stub._finalize(completed=False, reason="未触发结局就退出")
check("未完成不写角色档案回放",
      not os.path.exists(replay_dir) or not os.listdir(replay_dir))
check("未完成不写角色档案报告",
      not os.path.exists(report_dir) or not os.listdir(report_dir))
check("未完成不写 data/user 回放",
      not os.path.exists(user_replays) or not os.listdir(user_replays))
check("未完成不写 data/user 报告",
      not os.path.exists(user_reports) or not os.listdir(user_reports))
check("未完成不写 endings.json",
      not os.path.exists(os.path.join(session_root, "user", "endings.json")))
check("未完成不记结局索引", stub._achievement_record is None)
check("未完成不标成已保存", stub._replay_saved is False)
check("未完成仍置收尾标记", stub._finalized is True)

# 3.2 未完成 + 无角色：同样什么都不写，也不会顺手建角色
stub2 = StubSession(with_character=False)
stub2._finalize(completed=False, reason="未触发结局就退出")
check("无角色未完成不创建角色", stub2.character is None)
check("无角色未完成不写 data/user 回放",
      not os.path.exists(user_replays) or not os.listdir(user_replays))

# 3.3 放弃确认：有内容才问，空会话不打断
dialog_calls.clear()
stub3 = StubSession()
check("有内容时退出要确认", stub3._confirm_abandon() is False)  # 宿主默认答「否」
check("确认框说明不可接续",
      any(c[0] == "ask" and "无法接续" in c[2] for c in dialog_calls), dialog_calls)

dialog_calls.clear()
stub4 = StubSession()
stub4.replay_data = []
stub4.story_history = []
check("空会话不弹确认", stub4._confirm_abandon() is True)
check("空会话不产生询问弹框",
      not any(c[0] == "ask" for c in dialog_calls), dialog_calls)

# ---------------- 4. 回放身份记录（写侧） ----------------
from paths import APP_VERSION  # noqa: E402

scenario_root = os.path.join(tmp, "scenarios")
scenario_dir = os.path.join(scenario_root, "unit_scenario")
os.makedirs(os.path.join(scenario_dir, "images"), exist_ok=True)
with open(os.path.join(scenario_dir, "images", "a.png"), "wb") as f:
    f.write(b"0123456789")
write_json_atomic(os.path.join(scenario_dir, "unit_scenario.meta.json"), {
    "schema": "gg.scenarios/1", "id": "unit_scenario",
    "version": "1.3.0", "content_hash": "sha256:abc"})


class FakeScenarioRepo:
    """只实现回放身份需要的两个方法。"""

    def scenario_dir(self, scenario_id):
        return scenario_dir if scenario_id == "unit_scenario" else ""


meta_stub = StubSession(with_character=False)
meta_stub.scenario_id = "unit_scenario"
meta_stub.scenario_repo = FakeScenarioRepo()
meta_stub.replay_data = [
    {"kind": "chapter", "name": "A",
     "background": {"image_path": "images/a.png"}},
    {"step": 1, "type": "dialog", "text": "你好"},
]
meta_path = meta_stub._write_user_replay_file()
meta_payload = json.load(open(meta_path, encoding="utf-8"))
meta_head = meta_payload[0]
check("回放头部第一条是身份记录", meta_head.get("kind") == "meta", meta_head)
check("身份记录取自方案信封（id / 版本 / 内容哈希）",
      meta_head.get("scenario", {}).get("id") == "unit_scenario"
      and meta_head["scenario"].get("version_tag") == "1.3.0"
      and meta_head["scenario"].get("content_hash") == "sha256:abc",
      meta_head)
check("身份记录带应用版本与保存时间",
      meta_head.get("app") == APP_VERSION and bool(meta_head.get("saved_at")),
      meta_head)
check("素材清单只记用到的文件与其字节数",
      meta_head["scenario"].get("assets") == [{"path": "images/a.png", "size": 10}],
      meta_head["scenario"].get("assets"))
check("身份记录之后是记录本体",
      meta_payload[1:] == meta_stub.replay_data, meta_payload[1:])

# 3.5 会话异常不再进「未完成报告」——未完成路径本身已不产生报告
err_stub = StubSession(errors=["ValueError: 模型返回空", "TimeoutError: 超时"])
err_stub._finalize(completed=False, reason="未触发结局就退出")
check("会话异常不再产生未完成报告",
      not os.path.exists(report_dir) or not os.listdir(report_dir))

# 3.6 正常结局：结算 + 结局索引 + 不自动存回放（开关关闭）
stub5 = StubSession(mode="challenge")
calls = []
stub5._apply_ending_effects = lambda: calls.append("effects")
stub5._record_ending_achievement = lambda: calls.append("achievement")
stub5._finalize(completed=True, reason="触发结局")
check("完成路径执行结算与结局索引", calls == ["effects", "achievement"], calls)
check("完成路径置 dungeon_ended", stub5.dungeon_ended is True)
check("自动保存关闭时不写回放", stub5._replay_saved is False)

# 3.7 完成路径幂等
stub5._finalize(completed=True)
check("完成路径幂等", calls == ["effects", "achievement"], calls)

# 3.8 自动保存打开 + 无角色：仍要询问，玩家不同意就不创建角色、不保存
dialog_calls.clear()
auto_declined = StubSession(with_character=False)
auto_declined.dungeon_settings = {"auto_save_replay": True}
auto_declined._apply_ending_effects = lambda: None
auto_declined._record_ending_achievement = lambda: None
auto_declined._finalize(completed=True, reason="触发结局")
check("自动保存遇到无角色也先询问",
      any(c[0] == "ask" and "创建角色" in c[1] for c in dialog_calls), dialog_calls)
check("自动保存被拒绝后不创建角色", auto_declined.character is None)
check("自动保存被拒绝后不写回放", auto_declined._replay_saved is False)

# 3.9 自动保存打开 + 玩家同意建角色：保存成功，且不弹「保存成功」打扰
dialog_calls.clear()
HOST.answer = True
auto_accepted = StubSession(with_character=False)
auto_accepted.dungeon_settings = {"auto_save_replay": True}
auto_accepted._apply_ending_effects = lambda: None
auto_accepted._record_ending_achievement = lambda: None
auto_accepted._finalize(completed=True, reason="触发结局")
HOST.answer = False
check("自动保存同意后创建角色并保存",
      auto_accepted.character is not None and auto_accepted._replay_saved, dialog_calls)
check("自动保存成功后不弹提示框",
      not any(c[0] == "info" for c in dialog_calls), dialog_calls)

# 3.6 _handle_exit 分流（不真正落盘：只记录 _finalize 的调用参数）
class ExitStub(StubSession):
    def _finalize(self, completed, reason=""):
        self.finalize_calls.append((completed, reason))
        self._finalized = True

    def _confirm_abandon(self):
        self.confirm_count += 1
        return self.confirm_answer


def exit_stub(dungeon_ended=False, pending_ending=None, is_replay=False,
              replay_saved=False, confirm_answer=True):
    stub = ExitStub()
    stub.dungeon_ended = dungeon_ended
    stub.pending_ending = pending_ending
    stub.is_replay = is_replay
    stub._replay_saved = replay_saved
    stub.confirm_answer = confirm_answer
    stub.finalize_calls = []
    stub.confirm_count = 0
    return stub


ex = exit_stub(pending_ending=None)
ex._handle_exit()
check("退出：未触发结局 → completed=False 收尾",
      ex.finalize_calls == [(False, "未触发结局就退出")], ex.finalize_calls)
check("退出：未触发结局先确认一次放弃", ex.confirm_count == 1, ex.confirm_count)

# 玩家在「确定放弃吗」里点「否」：窗口已经销毁，不能再回到游戏里，但也不能
# 什么都不说——提示一句「这一局没有保留」。
dialog_calls.clear()
ex = exit_stub(pending_ending=None, confirm_answer=False)
ex._handle_exit()
check("退出：点否也按未完成收尾", ex.finalize_calls == [(False, "未触发结局就退出")],
      ex.finalize_calls)
check("退出：点否时明确告知没有保留",
      any(c[0] == "info" and "没有保留" in c[2] for c in dialog_calls), dialog_calls)

ex = exit_stub(pending_ending={"name": "真结局"})
ex._handle_exit()
check("退出：结局生成中 → 按 completed=True 收尾",
      len(ex.finalize_calls) == 1 and ex.finalize_calls[0][0] is True, ex.finalize_calls)
check("退出：结局生成中补兜底结局文本", ex.ending_text == "结局：真结局", ex.ending_text)

ex = exit_stub(dungeon_ended=True)
ex._handle_exit()
check("退出：已达成结局不重复收尾", ex.finalize_calls == [], ex.finalize_calls)

ex = exit_stub(dungeon_ended=True, replay_saved=True)
ex._handle_exit()
check("退出：自动保存已存过就不再问",
      ex.finalize_calls == [] and ex.confirm_count == 0,
      (ex.finalize_calls, ex.confirm_count))

ex = exit_stub(pending_ending=None, is_replay=True)
ex._handle_exit()
check("退出：回放模式跳过收尾", ex.finalize_calls == [], ex.finalize_calls)

# ---------------- 结论 ----------------
_log.flush()
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
if failures:
    print(f"[check_dungeon_finalize] FAILED {len(failures)}/{total}: {failures}")
else:
    print(f"[check_dungeon_finalize] PASSED {total}/{total}")
print(f"[check_dungeon_finalize] report: {_report_path}")
sys.exit(1 if failures else 0)


