# -*- coding: utf-8 -*-
"""昵称按行加权 + 轮换槽位的自检：权重与词都在姓名表里，代码只负责抽取与渲染。

用法：``python tests/check_nick_weights.py``
纯逻辑，不建窗口、不联网；只读 data/，临时表写到系统临时目录。

行为锁：
- 姓名表每一行昵称带自己的权重，按权重抽取；
- ``{1}`` / ``{2}`` 由同行 substitute_N 轮换，缺候选的行整行跳过；
- 候选切分认中英文逗号，重复候选按一份算；``{sur}`` 由创建期单独替换；
- 随机性交给 rng：同一 seed 可复现，权重差距在足够多的抽样里看得出来；
- 内容在表里：模块里不留碎片常量，取材表不再声明 nick_fragments 成员。
"""

import csv
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.resource_spec import spec_of  # noqa: E402
from persistence import material_tables  # noqa: E402
from persistence.name_repo import NameRepo, NickEntry, render_nick  # noqa: E402
from persistence.static_table import weighted_choice  # noqa: E402
from services.creation_service import CreationService  # noqa: E402

failures = []
total = 0


def check(name, ok, extra=""):
    global total
    total += 1
    print(("  OK   " if ok else "  FAIL ") + name
          + (f"  <{extra}>" if extra and not ok else ""))
    if not ok:
        failures.append(name)


def write_names(rows, header=None, directory=None):
    """把二维列表写成一张临时姓名表，返回 (路径, 目录)。"""
    header = header or ["surname", "ppm", "name", "nick", "nick_weight",
                        "substitute_1", "substitute_2", "substitute_3"]
    folder = directory or tempfile.mkdtemp()
    path = os.path.join(folder, "names.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\r\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path, folder


def load_path(path):
    """绕过 member_path 的回落，直接读指定路径的一张表。"""
    original = NameRepo.resolve
    NameRepo.resolve = lambda self, group=None: path
    try:
        return NameRepo().load("anything")
    finally:
        NameRepo.resolve = original


# ---------------- 1. 随仓库发出去的那张表 ----------------

surnames, weights, names, nicks = NameRepo().load("default")
check("内置表能读出来", bool(surnames) and bool(names) and bool(nicks))
check("昵称都是 NickEntry 且权重为正",
      all(isinstance(n, NickEntry) and n.weight > 0 for n in nicks))
check("精修条目没有未填的数字槽位",
      all("{" not in n.text or not any(c.isdigit() for c in n.text) for n in nicks
          if not n.substitutes))
check("带槽位的行都有候选",
      all(all(i in n.substitutes for i in range(1, max(n.substitutes) + 1))
          for n in nicks if n.substitutes))

rng = random.Random(7)
rendered = [n.render(rng) for n in nicks]
check("渲染后不留数字槽位",
      not any("{" in s and any(c.isdigit() for c in s) for s in rendered))
check("渲染结果无首尾空白",
      all(s and s == s.strip() for s in rendered))
check("拼出来的候选确实进了池子",
      any("啊啊啊啊" in s or "今天天气真好" in s or "困困ing" in s for s in rendered))

total_weight = sum(n.weight for n in nicks)
_junk_texts = {"{1}", "{1}...", "{1}{2}", "{1}_{2}"}
junk_weight = sum(n.weight for n in nicks if n.text in _junk_texts)
check("模板占比在 18~22%", 0.18 <= junk_weight / total_weight <= 0.22,
      f"{junk_weight}/{total_weight}")

# ---------------- 2. 表结构：逐行权重与槽位 ----------------

folder = tempfile.mkdtemp()
path, _ = write_names([
    ["王", "1", "静", "固定昵称", "", "", "", ""],
    ["", "", "", "{sur}的{1}", "3", "猫，狗", "", ""],
    ["", "", "", "{1}{2}", "1", "甲,乙,甲", "一,二", ""],
    ["", "", "", "{1}缺候选", "9", "", "", ""],
    ["", "", "", "零权重", "0", "", "", ""],
    ["", "", "", "负权重", "-2", "", "", ""],
    ["", "", "", "坏权重", "abc", "", "", ""],
], directory=folder)
_, _, _, local = load_path(path)
texts = [n.text for n in local]
check("缺候选 / 非正权重行跳过，坏权重按 1 收",
      texts == ["固定昵称", "{sur}的{1}", "{1}{2}", "坏权重"], str(texts))
check("权重按列解析", [n.weight for n in local] == [1.0, 3.0, 1.0, 1.0],
      str([n.weight for n in local]))
check("全角逗号也切得开且去重保序",
      local[1].substitutes[1] == ("猫", "狗"), str(local[1].substitutes))
check("重复候选按一份算",
      local[2].substitutes[1] == ("甲", "乙"), str(local[2].substitutes[1]))

local_rng = random.Random(3)
variants = {local[2].render(local_rng) for _ in range(60)}
check("双槽按位组合出多种串",
      variants == {"甲一", "甲二", "乙一", "乙二"}, str(sorted(variants)))
check("单遍替换：{sur} 留给创建期",
      "{sur}的猫" in {local[1].render(local_rng) for _ in range(20)})

# ---------------- 3. 按权重抽取 ----------------

_, _, _, two = load_path(write_names([
    ["", "", "", "常出现", "9", "", "", ""],
    ["", "", "", "少见", "1", "", "", ""],
])[0])
pick_rng = random.Random(11)
picks = [weighted_choice(two, rng=pick_rng).text for _ in range(1000)]
check("权重差在抽样里看得出来（约 9:1）",
      850 <= picks.count("常出现") <= 950, str(picks.count("常出现")))

# ---------------- 4. 掷姓名昵称时同轮渲染 ----------------

class FakeNameRepo:
    def __init__(self, entries):
        self.entries = entries

    def load(self, group=None):
        return (["王"], [1.0], ["静"], self.entries)


def roll(entries):
    return CreationService(name_repo=FakeNameRepo(entries)).generate_random_name_nick()


name, nick = roll([NickEntry("{sur}家小{given}", 1), NickEntry("固定昵称", 1)])
check("占位符与权重路径并存", name == "王静" and nick in ("王家小静", "固定昵称"),
      f"{name} / {nick}")

name, nick = roll([NickEntry("{given}和{1}", 1, {1: ("猫", "狗")})])
check("槽位与占位符一次掷出即渲染完成",
      name == "王静" and nick in ("静和猫", "静和狗"), f"{name} / {nick}")

name, nick = roll(["{sur}{given}"])
check("兼容直接传字符串的旧调用方", name == "王静" and nick == "王静")

# ---------------- 5. 内置表的配比与合并模板 ----------------

_builtin = NameRepo().load("default")[3]
_junk_keys = {"{1}", "{1}...", "{1}{2}", "{1}_{2}"}
_junk_w = sum(e.weight for e in _builtin if e.text in _junk_keys)
_refined_w = sum(e.weight for e in _builtin if e.text not in _junk_keys)
_ratio = _junk_w / (_junk_w + _refined_w)
check("内置表垃圾权重约两成", 0.18 <= _ratio <= 0.22,
      f"{_junk_w:.0f}/{_junk_w + _refined_w:.0f}={_ratio:.3f}")
check("精修权重守恒（合并不改配比基数）",
      abs(_refined_w - 1341) < 1e-6, f"{_refined_w:.0f}")

# 合并模板的产出必须覆盖原来的每一条
_merged = {
    "今天也{1}": ("很困", "想sleep", "要喝奶茶_00"),
    "mom{1}": ("o", "o_"),
    "晚安{1}": ("档案", "延迟发送", "goodnight", "ovo"),
    "隔着{1}的{2}": (("时间", "玻璃"), ("偏爱", "拥抱")),
    "月亮{1}进{2}": (("掉", "落"), ("水里了", "天蝎座")),
    "qw{1}_{2}": (("er", "q"), ("092", "ovo", "owo")),
}
for text, cands in _merged.items():
    entry = next((e for e in _builtin if e.text == text), None)
    expected = {1: tuple(cands)} if all(isinstance(v, str) for v in cands) else \
               {i + 1: tuple(v) for i, v in enumerate(cands)}
    check(f"合并模板 {text} 在表内且候选齐全",
          entry is not None and entry.substitutes == expected,
          str(entry.substitutes) if entry else "缺行")

# ---------------- 6. 不再有第五个成员 / 组合器模块 ----------------

check("取材表成员回到四个",
      tuple(m.key for m in spec_of("materials").members) ==
      ("names", "presets", "personalities", "news"))
check("nick_fragments 不再是合法成员",
      "nick_fragments" not in material_tables.MEMBER_KEYS)
check("nick_composer 模块已移除",
      not os.path.exists(os.path.join(os.path.dirname(os.path.dirname(
          os.path.abspath(__file__))), "services", "nick_composer.py")))
check("内置组已无 nick_fragments.csv",
      not os.path.exists(os.path.join(os.path.dirname(os.path.dirname(
          os.path.abspath(__file__))), "data", "static", "materials", "default",
          "nick_fragments.csv")))

print()
if failures:
    print(f"[check_nick_weights] FAILED {len(failures)}/{total}: " + "; ".join(failures))
    sys.exit(1)
print(f"[check_nick_weights] PASSED {total}/{total}")
