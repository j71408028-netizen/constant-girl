"""副本方案诊断的展示口径：按编辑器页签分组、挑选要显示的第一条。

顶栏的校验条要在任何页签都给出「哪里有问题」，因此诊断必须能归到某个页签上。
归属只按 ``Diagnostic.path`` 的**根键**（含结构级图的虚路径 ``chapters@名字`` /
``triggers@名字``）判定，不解析下标——这样新增字段只要落在已有根键下就自动归位。

纯函数、无界面依赖，便于离线自检（``tests/check_scenario_editor_diagnostics.py``）。
"""
from dataclasses import dataclass, field

from dungeon.validate import LEVEL_LABELS

#: 编辑器页签（与 ``ui/scenario/sc_frame.py`` 的页签名一致）。
TAB_GENERAL = "通用"
TAB_CHARACTER = "角色"
TAB_STORY = "剧情"
TAB_COMPONENT = "组件"
TABS = (TAB_GENERAL, TAB_CHARACTER, TAB_STORY, TAB_COMPONENT)

#: 根键 → 页签。根键为空串（整份配置层面的问题）归「通用」。
_ROOT_TABS = {
    "initial_prompt": TAB_GENERAL,
    "coupling_level": TAB_GENERAL,
    "speaker_notation": TAB_GENERAL,
    "section_prompts": TAB_GENERAL,
    "section_steps": TAB_GENERAL,
    "transition_matrix": TAB_GENERAL,
    "entry_action_cost": TAB_GENERAL,
    "entry_address": TAB_GENERAL,
    "entry_address_max_distance_m": TAB_GENERAL,
    "entry_height_min_m": TAB_GENERAL,
    "entry_height_max_m": TAB_GENERAL,
    "initial_intrusion": TAB_GENERAL,
    "initial_destruction": TAB_GENERAL,
    "ending_policy": TAB_GENERAL,
    "protagonist_title": TAB_CHARACTER,
    "protagonist_background": TAB_CHARACTER,
    "cast": TAB_CHARACTER,
    "voice": TAB_CHARACTER,
    "evolution_attrs": TAB_CHARACTER,
    "components": TAB_COMPONENT,
    "components_params": TAB_COMPONENT,
    "text_component": TAB_COMPONENT,
    # 章节 / 触发器本身及其结构（goto、overflow、条件引用……）都在剧情页
    "chapters": TAB_STORY,
    "triggers": TAB_STORY,
}

_LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2}


def root_key(path: str) -> str:
    """诊断路径的根键。

    ``triggers[2].action_data.chapter`` → ``triggers``；
    结构级图校验的虚路径 ``chapters@坠入城内`` → ``chapters``。
    """
    text = (path or "").strip()
    for separator in ("[", ".", "@"):
        index = text.find(separator)
        if index >= 0:
            text = text[:index]
    return text


def tab_of(path: str) -> str:
    """诊断路径 → 页签。未知根键归「通用」，宁可多指一次也不漏。"""
    return _ROOT_TABS.get(root_key(path), TAB_GENERAL)


def _order(diagnostic):
    return (_LEVEL_ORDER.get(diagnostic.level, 9), diagnostic.path)


@dataclass
class DiagnosticSummary:
    """顶栏校验条要的全部信息。"""

    diagnostics: list = field(default_factory=list)
    #: {level: 条数}
    counts: dict = field(default_factory=dict)
    #: {页签: {level: 条数}}
    by_tab: dict = field(default_factory=dict)
    #: 每条诊断归属的页签，与 ``diagnostics`` 一一对应
    tabs: list = field(default_factory=list)

    @property
    def total(self):
        return len(self.diagnostics)

    @property
    def errors(self):
        return self.counts.get("error", 0)

    @property
    def warnings(self):
        return self.counts.get("warning", 0)

    @property
    def quiet(self):
        """只剩提示（或完全没有）——不值得在顶栏报警。"""
        return self.errors == 0 and self.warnings == 0

    def headline(self):
        """一行摘要：最严重的那条，前面带级别。"""
        for diagnostic in sorted(self.diagnostics, key=_order):
            if diagnostic.level == "info" and not self.quiet:
                continue
            level = LEVEL_LABELS.get(diagnostic.level, diagnostic.level)
            where = f"{diagnostic.path}：" if diagnostic.path else ""
            return f"{level} · {where}{diagnostic.message}"
        return "未发现问题。"

    def tab_counts(self, tab):
        counts = self.by_tab.get(tab, {})
        return counts.get("error", 0), counts.get("warning", 0)


def summarize(diagnostics) -> DiagnosticSummary:
    """把诊断列表整理成顶栏要用的形状（错误在前，同级按路径排序）。"""
    ordered = sorted((d for d in (diagnostics or [])), key=_order)
    summary = DiagnosticSummary(diagnostics=ordered)
    for diagnostic in ordered:
        tab = tab_of(diagnostic.path)
        summary.tabs.append(tab)
        summary.counts[diagnostic.level] = summary.counts.get(diagnostic.level, 0) + 1
        per_tab = summary.by_tab.setdefault(tab, {})
        per_tab[diagnostic.level] = per_tab.get(diagnostic.level, 0) + 1
    return summary
