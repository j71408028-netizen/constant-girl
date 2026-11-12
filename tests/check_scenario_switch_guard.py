"""F1 回归守卫：剧本编辑器的方案切换路径不得静默丢弃未保存的通用设置。

用法：``python tests/check_scenario_switch_guard.py``

**为什么需要**：重命名只写显示名信封，方案目录与 id 都不动，但改完曾重新
``_load_scenario()``——那会把磁盘上的配置回填进控件，提示词、准入等尚未保存
的编辑静默消失，快照也被重拍成「已保存」，连提示都不会再出现。新建方案、
从挑战包载入方案、资源页深跳同样会切换当前方案，属于同一类丢失。

本守卫用不依赖 Tk 的桩对象（只借用编辑器的真实方法）验证：

1. 改名后草稿仍在、快照仍记为「已修改」、且没有回读配置；
2. 改名后继续保存，写回的是同一方案；
3. 切换 / 新建方案前会询问，选保存则落盘，选不保存则按下一条方案加载。

退出码：0 = 通过；1 = 行为不符。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dungeon.audio.speech import normalize_voice  # noqa: E402
from dungeon.coupling import DEFAULT_COUPLING_LEVEL  # noqa: E402
from persistence.scenario_repo import ScenarioRepo  # noqa: E402
import ui.ctk.dialogs  # noqa: E402
import ui.scenario.sc_frame as sc_frame  # noqa: E402
from ui.scenario.sc_frame import ScenarioEditor  # noqa: E402

failures = []
total = 0


def check(name, ok, extra=""):
    global total
    total += 1
    print(("  OK   " if ok else "  FAIL ") + name + (f"  <{extra}>" if extra and not ok else ""))
    if not ok:
        failures.append(name)


# ---------------- 桩：只在 Tk 边界上替换 ----------------

class FakeText:
    """CTkTextbox 的最小替身：只实现 get / delete / insert。"""

    def __init__(self, text=""):
        self._text = text

    def get(self, *_args):
        return self._text

    def delete(self, *_args):
        self._text = ""

    def insert(self, _index, text):
        self._text = text


class FakeVar:
    def __init__(self, value=None):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class FakeCombo:
    def __init__(self):
        self.text = ""

    def set(self, value):
        self.text = value


class FakeCharacterPage:
    """角色页自带防抖保存，这里只记调用次数。"""

    def __init__(self):
        self.flush_count = 0

    def flush_pending(self):
        self.flush_count += 1

    def protagonist_title(self):
        return ""

    def collect_voice(self):
        return normalize_voice(None)

    def on_coupling_changed(self, _level):
        pass

    def refresh_from_config(self):
        pass


class FakeNameDialog:
    """替代 ResourceNameDialog：新建与重命名都走它。"""

    result = None
    calls = 0

    def __init__(self, *_args, **_kwargs):
        type(self).calls += 1
        self.result = type(self).result


class FakeEditor:
    """借用 ScenarioEditor 的真实方法，只替换窗口控件与导航入口。"""

    _scenario_display = ScenarioEditor._scenario_display
    _get_prompt_data_from_ui = ScenarioEditor._get_prompt_data_from_ui
    _optional_number = ScenarioEditor._optional_number
    _update_prompt_snapshot = ScenarioEditor._update_prompt_snapshot
    _is_prompt_modified = ScenarioEditor._is_prompt_modified
    _confirm_unsaved_prompts = ScenarioEditor._confirm_unsaved_prompts
    _save_prompts = ScenarioEditor._save_prompts
    _notify_validation = ScenarioEditor._notify_validation
    _rename_scenario = ScenarioEditor._rename_scenario
    _on_scenario_select = ScenarioEditor._on_scenario_select
    _new_scenario = ScenarioEditor._new_scenario

    def __init__(self, repo, scenario_id="alpha"):
        self._scenario_repo = repo
        self.current_scenario_id = scenario_id
        self.character_panel = FakeCharacterPage()
        self.scenario_combo = FakeCombo()
        self.initial_prompt_text = FakeText("")
        self.section_frames = {}
        self.section_step_vars = {}
        self.coupling_level = DEFAULT_COUPLING_LEVEL
        self.transition_matrix = None
        self.entry_address = ""
        self.entry_address_max_distance = None
        self.entry_height_min = None
        self.entry_height_max = None
        self.entry_cost_var = FakeVar("0")
        self.entry_distance_var = FakeVar("")
        self.entry_height_min_var = FakeVar("")
        self.entry_height_max_var = FakeVar("")
        # 组件选择由组件面板维护，本守卫不涉及，给默认值即可
        self.text_component = "text_card"
        self.components = []
        self.components_params = {}
        self._saved_prompt_snapshot = {}
        self.load_calls = []
        self.refresh_count = 0

    # --- 被替换的导航入口 ---
    def _load_scenario(self, scenario_id):
        self.load_calls.append(scenario_id)
        self.current_scenario_id = scenario_id

    def _refresh_scenario_list(self):
        self.refresh_count += 1


# ---------------- 打桩：对话框与方案列表 ----------------

asked = []
ask_answer = {"value": False}


def fake_askyesno(title, message, **_kwargs):
    asked.append(title)
    return ask_answer["value"]


for _name in ("askyesno", "showinfo", "showwarning", "showerror"):
    setattr(ui.ctk.dialogs, _name,
            fake_askyesno if _name == "askyesno" else (lambda *a, **k: None))
sc_frame.ResourceNameDialog = FakeNameDialog


def make_repo():
    tmp = tempfile.mkdtemp(prefix="scenario_switch_guard_")
    root = os.path.join(tmp, "packs", "scenarios")
    for scenario_id, prompt in (("alpha", "旧提示词"), ("beta", "另一个方案")):
        os.makedirs(os.path.join(root, scenario_id), exist_ok=True)
        with open(os.path.join(root, scenario_id, "config.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"initial_prompt": prompt}, f, ensure_ascii=False)
    return ScenarioRepo(data_dir=tmp), tmp


def disk_prompt(repo, scenario_id):
    return (repo.load_config(scenario_id) or {}).get("initial_prompt")


def load_saved_state(editor, repo, scenario_id, draft=None):
    """模拟「已保存到盘 → 又改了草稿」的界面状态。"""
    saved = disk_prompt(repo, scenario_id)
    editor.current_scenario_id = scenario_id
    editor.initial_prompt_text = FakeText(saved)
    editor._update_prompt_snapshot()
    if draft is not None:
        editor.initial_prompt_text = FakeText(draft)
    return editor


# ---------------- 1. 重命名不动草稿 ----------------
repo, _tmp = make_repo()
editor = load_saved_state(FakeEditor(repo), repo, "alpha", draft="改了一半的草稿")
FakeNameDialog.result = {"id": "alpha", "title": "新名字"}
asked.clear()
editor._rename_scenario()

check("改名写入了显示名", repo.display_name("alpha") == "新名字", repo.display_name("alpha"))
check("改名后没回读配置", editor.load_calls == [], editor.load_calls)
check("草稿仍在输入框里", editor.initial_prompt_text.get("1.0", "end-1c") == "改了一半的草稿",
      editor.initial_prompt_text.get("1.0", "end-1c"))
check("快照没被重拍成已保存", editor._is_prompt_modified() is True)
check("下拉显示新名字", editor.scenario_combo.text == "新名字", editor.scenario_combo.text)
check("改名不动载荷", disk_prompt(repo, "alpha") == "旧提示词", disk_prompt(repo, "alpha"))
check("改名不需要再问是否保存", asked == [], asked)

# ---------------- 2. 改名后继续保存仍写回同一方案 ----------------
editor._save_prompts()
check("改名后保存写回原方案", disk_prompt(repo, "alpha") == "改了一半的草稿",
      disk_prompt(repo, "alpha"))
check("保存后快照复位", editor._is_prompt_modified() is False)

# ---------------- 3. 切换方案：选保存则先落盘 ----------------
repo, _tmp = make_repo()
editor = load_saved_state(FakeEditor(repo), repo, "alpha", draft="切走前的草稿")
ask_answer["value"] = True
asked.clear()
editor._on_scenario_select("beta")
check("切换前询问过", asked == ["通用设置未保存"], asked)
check("选保存后旧方案已落盘", disk_prompt(repo, "alpha") == "切走前的草稿",
      disk_prompt(repo, "alpha"))
check("随后加载新方案", editor.load_calls == ["beta"], editor.load_calls)

# ---------------- 4. 切换方案：选不保存则明确放弃 ----------------
repo, _tmp = make_repo()
editor = load_saved_state(FakeEditor(repo), repo, "alpha", draft="不想保留的草稿")
ask_answer["value"] = False
asked.clear()
editor._on_scenario_select("beta")
check("不保存时仍会询问", asked == ["通用设置未保存"], asked)
check("选不保存不写盘", disk_prompt(repo, "alpha") == "旧提示词", disk_prompt(repo, "alpha"))
check("选不保存照样切换", editor.load_calls == ["beta"], editor.load_calls)

# ---------------- 5. 新建方案前也询问 ----------------
repo, _tmp = make_repo()
editor = load_saved_state(FakeEditor(repo), repo, "alpha", draft="新建前的草稿")
ask_answer["value"] = False
asked.clear()
FakeNameDialog.result = {"id": "gamma", "title": "新方案"}
editor._new_scenario()
check("新建前询问过", asked == ["通用设置未保存"], asked)
check("新建后切到新方案", editor.load_calls == ["gamma"], editor.load_calls)

# 没有改动时不该多问一句
repo, _tmp = make_repo()
editor = load_saved_state(FakeEditor(repo), repo, "alpha")
asked.clear()
FakeNameDialog.result = {"id": "delta", "title": "另一个新方案"}
editor._new_scenario()
check("无改动时新建不打扰", asked == [], asked)

# ---------------- 结论 ----------------
print()
if failures:
    print(f"[check_scenario_switch_guard] FAILED {len(failures)}/{total}: "
          + "; ".join(failures))
    sys.exit(1)
print(f"[check_scenario_switch_guard] PASSED {total}/{total}")
