"""剧本编辑器的诊断展示口径（``ui/scenario/diagnostics.py``）。

顶栏校验条是跨页签的：任何一处保存后，作者不看当前页签也该知道「哪里出了问题」。
这里守住那条口径——诊断按 ``path`` 的根键落到哪个页签、摘要挑哪一条当门面、
只剩提示时不报警。不依赖 Tk，纯函数。

用法：``python tests/check_scenario_editor_diagnostics.py``
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dungeon.validate import Diagnostic, validate_scenario_config  # noqa: E402
from ui.scenario import diagnostics  # noqa: E402

failures = []
total = 0


def check(name, ok, extra=""):
    global total
    total += 1
    print(("  OK   " if ok else "  FAIL ") + name + (f"  <{extra}>" if extra and not ok else ""))
    if not ok:
        failures.append(name)


# ---------------- 1. 根键与页签归属 ----------------

check("根键去掉下标", diagnostics.root_key("triggers[2].action_data.chapter") == "triggers",
      diagnostics.root_key("triggers[2].action_data.chapter"))
check("根键原样返回顶层键", diagnostics.root_key("initial_prompt") == "initial_prompt")
check("空路径的根键为空串", diagnostics.root_key("") == "")

CASES = [
    ("initial_prompt", diagnostics.TAB_GENERAL),
    ("section_prompts.dialog", diagnostics.TAB_GENERAL),
    ("entry_address", diagnostics.TAB_GENERAL),
    ("cast[0].name", diagnostics.TAB_CHARACTER),
    ("voice.rate", diagnostics.TAB_CHARACTER),
    ("evolution_attrs[1]", diagnostics.TAB_CHARACTER),
    ("components[0]", diagnostics.TAB_COMPONENT),
    ("chapters[0].bgm.level", diagnostics.TAB_STORY),
    ("triggers[3].action_data", diagnostics.TAB_STORY),
    # 结构级图校验用虚路径，同样要落到剧情页
    ("chapters@坠入城内", diagnostics.TAB_STORY),
    ("triggers@钟声响起", diagnostics.TAB_STORY),
]
for path, expected in CASES:
    check(f"{path} → {expected}", diagnostics.tab_of(path) == expected,
          diagnostics.tab_of(path))

check("空路径归通用", diagnostics.tab_of("") == diagnostics.TAB_GENERAL)
check("未知根键归通用（宁可多指一次也不漏）",
      diagnostics.tab_of("some_future_field") == diagnostics.TAB_GENERAL)

# ---------------- 2. 摘要：计数、门面、安静 ----------------

diags = [
    Diagnostic("info", "ending_policy", "本方案没有结局路径"),
    Diagnostic("warning", "triggers[1].precondition_names", "前置触发器不可达"),
    Diagnostic("error", "chapters@坠入城内", "章节走不到"),
    Diagnostic("error", "initial_prompt", "故事基调必须是字符串"),
]
summary = diagnostics.summarize(diags)

check("总数", summary.total == 4, summary.total)
check("错误数", summary.errors == 2, summary.errors)
check("警告数", summary.warnings == 1, summary.warnings)
check("不安静", summary.quiet is False)
check("错误在前、同级按路径排序",
      summary.diagnostics[0].level == "error"
      and summary.diagnostics[0].path == "chapters@坠入城内"
      and summary.diagnostics[1].path == "initial_prompt",
      [d.path for d in summary.diagnostics])
check("门面取最严重的一条", "章节走不到" in summary.headline(), summary.headline())
check("门面带级别",
      summary.headline().startswith("错误"), summary.headline())
check("分页签计数：通用", summary.tab_counts(diagnostics.TAB_GENERAL) == (1, 0),
      summary.tab_counts(diagnostics.TAB_GENERAL))
check("分页签计数：剧情", summary.tab_counts(diagnostics.TAB_STORY) == (1, 1),
      summary.tab_counts(diagnostics.TAB_STORY))
check("没有问题的页签返回零", summary.tab_counts(diagnostics.TAB_COMPONENT) == (0, 0))
check("tabs 与 diagnostics 一一对应",
      len(summary.tabs) == len(summary.diagnostics) == 4)

only_info = diagnostics.summarize([Diagnostic("info", "ending_policy", "无结局路径")])
check("只剩提示时算安静", only_info.quiet is True)
check("安静时门面报「未发现问题」",
      diagnostics.summarize([]).headline() == "未发现问题。",
      diagnostics.summarize([]).headline())

# ---------------- 3. 与真实校验器对齐 ----------------

BAD_CONFIG = {
    "coupling_level": 42,                      # 通用：类型错
    "triggers": [{"name": "钟声响起", "action_type": "goto",
                  "action_data": {"chapter": "不存在的章节"}}],
    "chapters": [],
}
real = validate_scenario_config(BAD_CONFIG)
real_summary = diagnostics.summarize(real)
check("真实诊断能全部归页",
      all(t in diagnostics.TABS for t in real_summary.tabs), real_summary.tabs)
check("真实诊断里剧情页有线",
      sum(real_summary.tab_counts(t)[0] + real_summary.tab_counts(t)[1]
          for t in real_summary.tabs if t == diagnostics.TAB_STORY) > 0,
      real_summary.by_tab)
check("悬空 goto 归剧情页",
      any(d.path.startswith("triggers") and diagnostics.tab_of(d.path) == diagnostics.TAB_STORY
          for d in real),
      [d.path for d in real])

print()
print(f"未通过 {len(failures)}/{total}" if failures else f"PASSED {total}/{total}")
sys.exit(1 if failures else 0)
