# -*- coding: utf-8 -*-
"""描述语料校验器自检：组合级 9 类规则、排版层 4 条规则、反例零误报与界面契约。

用法：``python tests/check_quip_lint.py``
全部在内存里构造数据，不读 data/、不写盘、不联网。

这里守的是 ``services/exploration/quip_lint.py``——命令行体检（``quip_report.py``）
与主程序描述管理页的「校验」按钮都走它，所以这份自检等于同时守住了两边。
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_report_path = os.path.join(tempfile.mkdtemp(prefix="quip_lint_"), "report.txt")
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


from services.exploration.quip_lint import (  # noqa: E402
    BUILTIN_LABELS, BUILTIN_SUBTYPES, CUSTOM_LETTERS, build_feature,
    content_feature, lint_style, short_loc,
)


def _item(text, style="SelfTest"):
    return {"text": text, "style": style, "step": 0.1}


def _meta(confusion=False, subtypes=4):
    return {"custom_types": {
        lt: {"name": f"自定义{lt}", "subtypes": [str(i) for i in range(1, subtypes + 1)],
             "allow_confusion": confusion}
        for lt in CUSTOM_LETTERS}}


def _dirty_fixture():
    """每个池只暴露一类问题；样例文本即为该规则的触发点。"""
    meta = _meta()
    return {
        "small": {
            # a1：标记后紧跟「的」，同池候选自身以「的」收尾 → 的的
            "1_1": [_item("她托着[a:1:光洁的]下巴。[summary:s]")],
            "1_2": [_item("她托着[a:1:光洁]的面颊。[summary:s]")],
            # a2：候选收尾是逗号，槽位后紧跟句号 → 标点叠用
            "1_3": [_item("结构在瞬间[a:2:整体崩断]。[summary:s]")],
            "1_4": [_item("结构在瞬间[a:2:整体崩断、]。[summary:s]")],
            # a3：候选自带句末标点，槽位后还有正文 → 句子被截断
            "2_1": [_item("她注视着[a:3:那块招牌]久久不语。[summary:s]")],
            "2_2": [_item("她注视着[a:3:那块招牌。][summary:s]")],
            # a4：候选引号不成对
            "2_3": [_item("她念出[a:4:那句“咒语”]。[summary:s]")],
            "2_4": [_item("她念出[a:4:那句“咒语]。[summary:s]")],
            # c1：候选使用第一人称
            "3_1": [_item("{name}望着[c:1:远处的塔]。[summary:s]")],
            "3_2": [_item("{name}望着[c:1:我熟悉的塔]。[summary:s]")],
            # c2 + e4：相邻两个标记，左侧候选收尾是「的」、右侧候选开头是「的」→ 的的
            "3_3": [_item("她将[c:2:整排橱窗][e:4:瞬间化为齑粉]。[summary:s]")],
            "3_4": [_item("她将[c:2:成群结队的][e:4:的确如此]。[summary:s]")],
            # e1：候选直接称呼读者
            "4_1": [_item("{name}低语着[e:1:某种共鸣]。[summary:s]")],
            "4_2": [_item("{name}低语着[e:1:你听不见的共鸣]。[summary:s]")],
            # e2：候选以「他/它」指代，而上下文用「她」
            "4_3": [_item("她感到[e:2:一阵眩晕]，随即闭上了眼。[summary:s]")],
            "4_4": [_item("她感到[e:2:他们的目光]，随即闭上了眼。[summary:s]")],
        },
        # e3：同池候选"是否显式带主语她"不一致 → 池级 info
        "medium": {"1_1": [_item("她看着[e:3:废墟]。[summary:s]"),
                            _item("她看着[e:3:她脚下的废墟]。[summary:s]")]},
        "_meta": meta,
    }


def _clean_fixture():
    """与脏样本同构，但形态一致、接缝干净——任何 warn/error 都算误报。"""
    meta = _meta(subtypes=2)
    return {
        "small": {
            # b1：同一池两条都是名词短语，形态一致
            "1_1": [_item("{name}选择了[b:1:站直]。[summary:s]", "CleanTest")],
            "1_2": [_item("{name}选择了[b:1:侧身]。[summary:s]", "CleanTest")],
            # b2：同一池两条都以「的」收尾，接缝也干净
            "1_3": [_item("{name}露出[b:2:温和的]表情。[summary:s]", "CleanTest")],
            "1_4": [_item("{name}露出[b:2:柔和的]表情。[summary:s]", "CleanTest")],
        },
        "_meta": meta,
    }


EXPECTED_RULES = {
    "seam_de": "标记后紧跟「的」与候选自身的「的」叠置（含相邻标记两侧）",
    "seam_punct": "候选收尾的标点与模板标点叠用",
    "content_sent_punct": "候选自带句末标点把句子截断",
    "quote_unbalanced": "候选引号不成对",
    "pron_person1": "候选使用第一人称",
    "pron_person2": "候选直接称呼读者",
    "pron_gender": "候选用「他/它」而上下文用「她」",
    "pool_pronoun": "同池候选是否带主语「她」不一致",
    "slot_form": "同槽位候选形态不一致",
}


def case_grammar_rules():
    report = lint_style("SelfTest", _dirty_fixture())
    kinds = {f.kind for f in report.findings}
    for kind, desc in sorted(EXPECTED_RULES.items()):
        check(f"组合级规则 {kind}（{desc}）", kind in kinds,
              f"未命中；已有 {sorted(kinds)}")
    check("组合级检查统计到槽位与候选比对",
          report.stats.get("slots", 0) > 0 and report.stats.get("candidates", 0) > 0,
          repr(report.stats))
    return report


def case_no_false_positive():
    report = lint_style("CleanTest", _clean_fixture())
    noisy = [f for f in report.findings if f.level in ("error", "warn")]
    check("反例池（形态一致 / 接缝干净）零 warn/error", not noisy,
          "、".join(sorted({f.kind for f in noisy})))


def case_size_filter():
    """一次只查一档：选 small 时 medium 的池级结论不该出现。"""
    dirty = _dirty_fixture()
    full = lint_style("SelfTest", dirty)
    single = lint_style("SelfTest", dirty, size_cat="small")
    check("不限档时能看到 medium 的池级结论",
          any(f.kind == "pool_pronoun" for f in full.findings))
    check("限定 small 时 medium 的池级结论不出现",
          not any(f.kind == "pool_pronoun" for f in single.findings))
    check("限定 small 时其余结论仍在",
          any(f.kind == "seam_de" for f in single.findings))


def case_text_style():
    """排版层：只查零争议的四条，且不误报合法写法。"""
    def kinds_of(text):
        data = {"small": {"1_1": [_item(text)]}, "_meta": _meta()}
        return {f.kind for f in lint_style("StyleTest", data, size_cat="small").findings}

    check("半角标点夹在汉字旁 → punct_width", "punct_width" in kinds_of("她看见,远处有一座塔。"))
    check("小数 3.5 不算半角标点误用", "punct_width" not in kinds_of("高度约3.5米。"))
    check("停顿标点叠置 → punct_stack", "punct_stack" in kinds_of("她愣住了，。随即转身。"))
    check("三个句点当省略号 → ellipsis_style", "ellipsis_style" in kinds_of("她沉默了...然后笑了。"))
    check("省略号不重复报标点叠置",
          "punct_stack" not in kinds_of("她沉默了...然后笑了。"))
    check("虚词叠字 → func_dup", "func_dup" in kinds_of("光洁的的皮肤。"))
    check("「的的确确」是合法叠用，不报 func_dup",
          "func_dup" not in kinds_of("的的确确如此。"))
    check("标记内容里的排版问题带 content_ 前缀",
          "content_punct_width" in kinds_of("她看着[a:1:细嫩的,皮肤]。"))
    check("标记语法里的半角字符不算正文标点",
          "punct_width" not in kinds_of("她看着[a:1:光洁的]下巴。"))


def case_tuple_coords():
    """内存矩阵的坐标键是元组，与 CSV 的 "1_1" 必须等价（界面走这条路径）。"""
    data = {"small": {(1, 1): [_item("她托着[a:1:光洁的]下巴。"),
                               _item("她托着[a:1:光洁]的面颊。")]},
            "_meta": _meta()}
    report = lint_style("TupleTest", data, size_cat="small")
    check("元组坐标键不报 coord 错误",
          not any(f.kind == "coord" for f in report.findings))
    check("元组坐标键：两条文本的标记都被扫到", report.tag_total == 2,
          f"tag_total={report.tag_total}")
    coords = {f.loc.get("coord") for f in report.findings if f.loc and "coord" in f.loc}
    check("元组坐标在溯源里写成 1_1 形态", coords == {"1_1"}, repr(coords))


def case_report_contract():
    """界面契约：计数、排序、可定位性——对话框只依赖这几样。"""
    report = lint_style("SelfTest", _dirty_fixture())
    counts = report.counts
    check("counts 之和等于结论总数", sum(counts.values()) == len(report.findings))
    check("has_errors 与实际 error 数一致",
          report.has_errors == (counts["error"] > 0))
    ordered = report.sorted_findings()
    check("sorted_findings 按 error/warn/info 排序",
          [f.level for f in ordered] == sorted(
              (f.level for f in ordered),
              key=lambda lv: {"error": 0, "warn": 1, "info": 2}[lv]))
    only_warn = report.sorted_findings(levels=["warn"])
    check("按级别筛选只保留该级别",
          only_warn and all(f.level == "warn" for f in only_warn))

    locatable = [f for f in report.findings
                 if f.loc and f.loc.get("coord") and f.loc.get("entry_idx") is not None]
    check("结论带坐标与条目下标（供界面回原文）", bool(locatable))
    check("short_loc 渲染出档位/坐标/条目",
          all("@" in short_loc(f.loc) and "条目#" in short_loc(f.loc)
              for f in locatable))


def case_meta_view():
    """命令行 ``--json`` 的 meta 结构：内置名称只养一份，声明了没用的类型照旧出现。"""
    report = lint_style("SelfTest", _dirty_fixture(), size_cat="small")
    view = report.meta_view()
    check("meta_view 覆盖 a-e 五个字母", sorted(view["types"]) == list("abcde"))
    builtin = view["types"]["a"]
    check("内置类型补上显示名与细分",
          builtin["name"] == BUILTIN_LABELS["a"] and builtin["name"]
          and builtin["subtypes"] == BUILTIN_SUBTYPES["a"], repr(builtin))
    check("用到编号按数值有序", builtin["nums"] == sorted(builtin["nums"], key=int))
    custom = view["types"]["c"]
    check("自定义类型带 allow_confusion 与使用量",
          custom["name"] == "自定义c" and custom["allow_confusion"] is False
          and custom["used"] > 0, repr(custom))
    check("声明了但没用到的类型仍出现（used=0）",
          view["types"]["d"]["used"] == 0, repr(view["types"]["d"]))
    bare = lint_style("Bare", {"small": {"1_1": [_item("{name}看着[a:1:裙子]。")]},
                               "_meta": {}}, size_cat="small").meta_view()
    check("未声明的自定义类型记为 None", bare["types"]["c"] is None)
    check("tag_total 等于视图里各字母 used 之和",
          view["tag_total"] == sum(v["used"] for v in view["types"].values() if v))


def case_feature_cache():
    cache = {}
    for text in ("温和的", "温和的", "柔和的"):
        content_feature(text, cache)
    check("内容特征按字符串缓存（3 次取特征只落 2 条）", len(cache) == 2, repr(len(cache)))
    feat = build_feature("温和的")
    check("「温和的」判为「的」字定语式", feat.form == "de", feat.form)


def case_empty_data():
    report = lint_style("Empty", {"small": {}, "_meta": _meta()}, size_cat="small")
    check("空档位不报 error", not report.has_errors)
    check("空档位仍有 meta 相关结论（不是静默通过）", bool(report.findings))


for _case in (case_grammar_rules, case_no_false_positive, case_size_filter,
              case_text_style, case_tuple_coords, case_report_contract, case_meta_view,
              case_feature_cache, case_empty_data):
    print(f"-- {_case.__name__}")
    _case()

_log.flush()
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
if failures:
    print(f"[check_quip_lint] FAILED {len(failures)}/{total}: {failures}")
else:
    print(f"[check_quip_lint] PASSED {total}/{total}")
print(f"[check_quip_lint] report: {_report_path}")
raise SystemExit(1 if failures else 0)
