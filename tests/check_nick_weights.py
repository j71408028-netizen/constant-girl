# -*- coding: utf-8 -*-
"""昵称按行加权 + 轮换槽位的自检：权重与词都在姓名表里，代码只负责抽取与渲染。

用法：``python tests/check_nick_weights.py``
纯逻辑，不建窗口、不联网；只读 data/，临时表写到系统临时目录。

行为锁：
- 姓名表每一行昵称带自己的权重，按权重抽取；抽取配比按桶计：
  粗制 : 人名系列三类 : 垃圾 : 精制 = 50 : 20 : 15 : 15；
- ``{1}`` / ``{2}`` 由同行 substitute_N 轮换，缺候选的行整行跳过；
- 掷名有近距防重窗口：最近 N 次（默认 20）不重复同一**行**，按行下标而非
  渲染文本或模板文本记账，可取 0 关闭，可由行为包覆盖；
- 候选切分认中英文逗号，重复候选按一份算；``{sur}`` 由创建期单独替换；
- ``nick_note`` 是说明列：随行读入、不进渲染、不影响权重，缺列按空读；
- 随机性交给 rng：同一 seed 可复现，权重差距在足够多的抽样里看得出来；
- 内容在表里：模块里不留碎片常量，取材表不再声明 nick_fragments 成员。
"""

import csv
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.behavior_runtime import get_runtime  # noqa: E402
from core.resource_spec import spec_of  # noqa: E402
from persistence import material_tables  # noqa: E402
from persistence.name_repo import NameRepo, NickEntry, render_nick  # noqa: E402
from persistence.static_table import weighted_choice  # noqa: E402
from services.creation_service import (  # noqa: E402
    NICK_ANTI_REPEAT_WINDOW, CreationService)

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
check("每条昵称都有注释", all(n.note for n in nicks))
_NAME_SERIES = ("人名（非直接引用）", "运营账号", "事业")
_NAME_POOLS = ("纯名池", "×机构", "×头衔", "×事业尾", "×甜", "×尾巴", "窄口")


def _bucket(note):
    """抽取配比的桶：人名系列三类与其池行（家族池/纯名池/窄口）归「人名」，
    其余按注释首段三档归桶。注释本身不改，桶只是配比口径。"""
    parts = note.split("｜")
    if any(k in note for k in _NAME_POOLS) or (len(parts) > 1 and parts[1] in _NAME_SERIES):
        return "人名"
    return parts[0]


check("注释标出三档",
      {n.note.split("｜", 1)[0] for n in nicks} == {"精制", "粗制", "垃圾"})
_bucket_w = {}
for n in nicks:
    _bucket_w[_bucket(n.note)] = _bucket_w.get(_bucket(n.note), 0.0) + n.weight
check("四桶权重 500:200:150:150（总 1000）",
      abs(_bucket_w["粗制"] - 500) < 0.05 and abs(_bucket_w["人名"] - 200) < 0.05
      and abs(_bucket_w["垃圾"] - 150) < 0.05 and abs(_bucket_w["精制"] - 150) < 0.05,
      str(_bucket_w))
check("垃圾桶权重约一成半", 0.14 <= _bucket_w["垃圾"] / total_weight <= 0.16,
      f"{_bucket_w['垃圾']:.0f}/{total_weight:.0f}")

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
check("旧表没有注释列时按空注释读", all(n.note == "" for n in local))

# ---------------- 2.5 昵称注释列：只说明，不参与抽取 ----------------

path, _ = write_names([
    ["", "", "", "{1}撞南墙", "家族池：真小名×尾巴（5 名 × 32 尾）", "4", "阿梨,阿棠", ""],
    ["", "", "", "固定昵称", "原样保留：{sur} 绑定句", "1", "", ""],
], header=["surname", "ppm", "name", "nick", "nick_note", "nick_weight",
           "substitute_1", "substitute_2"], directory=tempfile.mkdtemp())
_, _, _, noted = load_path(path)
check("昵称注释随行读入",
      [n.note for n in noted] == ["家族池：真小名×尾巴（5 名 × 32 尾）",
                                 "原样保留：{sur} 绑定句"],
      str([n.note for n in noted]))
check("注释不影响权重", [n.weight for n in noted] == [4.0, 1.0],
      str([n.weight for n in noted]))
check("注释不进渲染文本",
      all("家族池" not in n.render(local_rng) for n in noted))
check("注释不改变槽位替换",
      {noted[0].render(local_rng) for _ in range(40)} == {"阿梨撞南墙", "阿棠撞南墙"})

_names_member = spec_of("materials").member("names")
check("姓名表声明了昵称注释列", "nick_note" in _names_member.field_keys())
check("昵称注释列不强制存在", "nick_note" not in _names_member.required_keys())

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

# ---------------- 4.5 掷名的近距防重窗口 ----------------

def roll_many(entries, count):
    """在同一张表上连续掷 count 次；起手清窗口，避免上一段留下旧下标。"""
    CreationService.reset_nick_window()
    service = CreationService(name_repo=FakeNameRepo(entries))
    return [service.generate_random_name_nick()[1] for _ in range(count)]


def use_window(value):
    """把窗口常量临时覆盖成 value（先复位，避免告警）；None = 用默认值。"""
    _runtime = get_runtime()
    _runtime.reset()
    if value is not None:
        _runtime.override("CreationService.nick.anti_repeat_window", value)


check("防重窗口默认 20 条", NICK_ANTI_REPEAT_WINDOW == 20,
      str(NICK_ANTI_REPEAT_WINDOW))

use_window(2)
_seq = roll_many([NickEntry("甲行", 1), NickEntry("乙行", 1), NickEntry("丙行", 1)], 60)
check("窗口内不重复同一行",
      not [i for i in range(len(_seq)) if _seq[i] in _seq[max(0, i - 2):i]],
      str(_seq[:9]))
check("窗口会强迫走遍整张表", len(set(_seq)) == 3, str(sorted(set(_seq))))

use_window(1)
_twins = roll_many([NickEntry("{1}", 1, {1: ("阿一", "阿二")}),
                    NickEntry("{1}", 1, {1: ("贝一", "贝二")})], 40)
_sides = [text[0] for text in _twins]
check("按行不按模板文本：同模板的两行仍能交替",
      _sides.count("阿") == 20 and _sides.count("贝") == 20, "".join(_sides))
check("按行不按渲染文本：换槽位内容不放行同一行",
      all(a != b for a, b in zip(_sides, _sides[1:])), "".join(_sides))

use_window(30)
_seq = roll_many([NickEntry("甲行", 1), NickEntry("乙行", 1)], 40)
check("窗口大于表内行数时退回整池，不掷空",
      len(_seq) == 40 and all(_seq), str(_seq[:4]))

use_window(0)
_seq = roll_many([NickEntry("甲行", 1), NickEntry("乙行", 1)], 40)
check("覆盖成 0 即关闭：一条不记", not CreationService._recent_nicks and all(_seq),
      str(list(CreationService._recent_nicks)))

use_window(None)
CreationService.reset_nick_window()
CreationService(name_repo=FakeNameRepo([NickEntry("甲行", 1)])).generate_random_name_nick()
check("默认窗口会记账", len(CreationService._recent_nicks) == 1,
      str(list(CreationService._recent_nicks)))
CreationService(name_repo=FakeNameRepo([NickEntry("甲行", 1)]),
                material_table="switch-away").generate_random_name_nick()
check("换取材表即清空旧窗口",
      list(CreationService._recent_nicks) == [0]
      and CreationService._recent_nicks_group == "switch-away",
      f"{list(CreationService._recent_nicks)} / {CreationService._recent_nicks_group}")
CreationService.reset_nick_window()

# ---------------- 5. 内置表的配比与合并模板 ----------------

_builtin = NameRepo().load("default")[3]
_pooled = [e for e in _builtin if "×" in e.note or "纯名池" in e.note or "窄口" in e.note]
check("家族池已落进内置表", len(_pooled) >= 40, f"{len(_pooled)} 行")
check("池行注释写明家族与覆盖数",
      all(("×" in e.note or "窄口" in e.note or "纯名池" in e.note)
          and e.substitutes for e in _pooled))
_combos = 0
for e in _builtin:
    variants = 1
    for values in e.substitutes.values():
        variants *= max(1, len(values))
    _combos += variants
check("内置表组合数超过 3000", _combos > 3000, f"{_combos}")
check("姓与名的库存没被替换行带走",
      len(NameRepo().load("default")[0]) == 448
      and len(NameRepo().load("default")[2]) == 670)

# 语义绑定、句末标点、实义外文的尾饰都不进通用池。
_kept_tail = (
    "摆烂の浮云 ☁", "风铃♫", "拒绝营业的云☁", "绒耳Rabbit.☁",
    "小圆别跑！", "间歇性摆烂中…", "你说的都对.",
    "泛黄速写本.zip", "今年不宜动土.txt", "深夜网抑云VIP", "枫林Pilot",
    "盐渍琥珀·Nori", "推子推到+12dB",
)
for _text in _kept_tail:
    check(f"不进池尾饰 {_text} 原样保留",
          any(e.text == _text and not e.substitutes and "尾饰不进通用池" in e.note
              for e in _builtin))
check("不进池尾饰不出现在任何池候选里",
      not any(part in value
              for e in _builtin for values in e.substitutes.values()
              for value in values for part in _kept_tail))
check("纯表音尾饰仍按形式池化",
      not any(e.text == "发呆ing" and not e.substitutes for e in _builtin))

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
