"""按现行口径数素材表的形态，并核「带符号的条目」占比。

口径见 `data/static/materials/default/nick_categories_forms.md`「三形态配比」。

判据只有一句：**把这些非中文成分去掉，句意会不会损失。**

   会损失 → 混合
     1. 句中、句首的外文（后面还有汉字，是句子成分）——`记录赤壁Wind的周公瑾`、`Misty雨巷`
     2. 与数字或字母紧贴、构成一个值的符号（单位、参数、时间、文件后缀）——
        `星轨偏航0.1°`、`+12dB`、`00:00`、`.zip`、`Alt+Tab`
     3. 颜文字（含组合符、修饰符的连写）——`道理我都懂 ˘͈ᵕ˘͈`
      句末外文要看它是不是一个词：`亚历山大东征路上的Moon` 的 `Moon` 有实义，摘了句子不成立，
   算混合；`柏林墙倒塌那夜k` 的 `k` 只是一个字母，摘了不影响，算装饰。

不会损失 → 尾注，条目仍是纯中文
     1. 句末外文的**单字符**——`柏林墙倒塌那夜k`、`深渊观测者ξ`
     2. 句末阿拉伯数字——`码头候船室04`、`反正也追不7`
     3. 中段连接符与句末孤立的符号——`白桃-乌龙` 的 `-`、`天台风向标_` 的 `_`、`风铃♫` 的 `♫`
     4. 纯装饰的符号连写——`澈正在输入中...`、`__亡骸__`

用法：
    python developer_tools/materials_form_report.py            # 分组汇总
    python developer_tools/materials_form_report.py --by-col   # 逐列
    python developer_tools/materials_form_report.py --check "星轨偏航0.1°"
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import unicodedata
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(ROOT, "data", "static", "materials", "default", "nick_categories.csv")

HAN = re.compile(r"[\u4e00-\u9fff]")
CJK_PUNCT = set("，。、；：？！…—·・‘’“”（）《》〈〉【】「」『』〔〕　")
DECIMAL = {".", ",", "．", "，"}
SEPARATORS = {"_", "-", "－", "—", "~", "～"}
# 组合符、修饰符：中文语境里成串出现就是颜文字，不是正文外文
KAOMOJI_CATS = {"Mn", "Me", "Sk"}

GROUPS = {
    "前三类": ["历史典故", "影剧", "文学"],
    "后三类": ["游戏", "其他虚拟角色情节舞台", "文娱"],
    "七列": ["城市空间", "物件本体", "现实日常", "野生动物", "音乐", "抽象概念", "天文地理"],
    "意象+情感": ["意象·夜空", "意象·气象", "意象·其他自然", "意象·情绪",
                "意象·人格化动物与智能", "意象·器物", "情感"],
    "人名系列": ["人名（非直接引用）", "运营账号", "事业"],
    "meme/网感": ["网络meme", "自造意象短语", "短小网感"],
    "造词与符号": ["造词与符号"],
}

# 验收区间（百分比，闭区间）：某一形态里，带符号的条目占多少。
# 分母是现行口径下的条数，不是旧口径（一枚符号也算混合）那版的条数。
ACCEPT = {"混合": (15.0, 25.0), "纯中文": (8.0, 15.0)}


def mark(hit: int, total: int, form: str) -> str:
    """区间标记：↑ 超上限，↓ 低于下限，空白即在区间内（或分母为零）。"""
    if not total:
        return " "
    pct = hit * 100 / total
    lo, hi = ACCEPT[form]
    return "↓" if pct < lo else "↑" if pct > hi else " "


def is_letter(ch: str) -> bool:
    if not ch.isalpha():
        return False
    if unicodedata.category(ch) == "Lm":  # 修饰字母（ᵕ ᵔ 等）是颜文字的零件，不是外文词
        return False
    name = unicodedata.name(ch, "")
    return any(k in name for k in ("LATIN", "GREEK", "CYRILLIC", "HIRAGANA",
                                   "KATAKANA", "HANGUL", "ARMENIAN", "HEBREW", "THAI"))


def is_symbol(ch: str) -> bool:
    if ch.isspace() or HAN.match(ch) or (ch.isascii() and ch.isalnum()):
        return False
    if is_letter(ch) or ch.isdigit() or ch in CJK_PUNCT:
        return False
    cat = unicodedata.category(ch)
    return cat[0] in ("S", "P", "M", "Z") or ch.isascii()


def scan(s: str) -> dict:
    t = s.replace("{sur}", "").replace("{given}", "")
    last_han = max((i for i, c in enumerate(t) if HAN.match(c)), default=-1)

    # 外文段：按位置分成句中的与句末尾注的。
    # 字母之间夹的点算段内字符，`Q.E.D.`、`O.o` 各自是一个记号，不拆成单字母。
    inline, tail, deco = [], [], []
    i, n = 0, len(t)

    def _letterish(k: int) -> bool:
        return 0 <= k < n and is_letter(t[k])

    while i < n:
        if not is_letter(t[i]):
            i += 1
            continue
        j = i
        while j < n and (is_letter(t[j]) or (t[j] == "." and _letterish(j - 1) and _letterish(j + 1))):
            j += 1
        seg = t[i:j]
        # 单个「の」是日式滤镜：摘了「博览群书の猫」还是那句话，算装饰不算外文成分。
        # 它和外文词连写（`青空のTree`）时先把「の」剥出来，剩下的词照常算句末外文。
        while len(seg) > 1 and seg[0] == "の":
            deco.append("の")
            seg = seg[1:]
        while len(seg) > 1 and seg[-1] == "の":
            deco.append("の")
            seg = seg[:-1]
        if seg == "の":
            deco.append(seg)
        else:
            (tail if i > last_han else inline).append(seg)
        i = j

    # 句末尾注里哪些是词、哪些只是装饰用的单字符
    tail_word, tail_lone = [], []
    for seg in tail:
        key = seg.rstrip(".")
        (tail_word if len(key) >= 2 else tail_lone).append(key)

    # 符号段
    runs, measure, lone = [], [], []
    i = 0
    while i < n:
        if not is_symbol(t[i]):
            i += 1
            continue
        # 字母之后的点是缩写点（`Q.E.D.` 的收尾点也算），已并入上面那个外文记号
        if t[i] == "." and i > 0 and is_letter(t[i - 1]):
            i += 1
            continue
        j = i
        while j < n and is_symbol(t[j]):
            j += 1
        run = t[i:j]
        prev = t[i - 1] if i > 0 else ""
        nxt = t[j] if j < n else ""
        if len(run) >= 2:
            runs.append(run)
        elif run in DECIMAL and prev.isdigit() and nxt.isdigit():
            pass
        elif run in SEPARATORS:
            lone.append(run)
        elif prev.isdigit() or nxt.isdigit() or is_letter(prev) or is_letter(nxt):
            measure.append(run)  # 单位、参数、时间、后缀：去掉就不是那个值了
        else:
            lone.append(run)
        i = j

    kaomoji = sum(1 for c in t if unicodedata.category(c) in KAOMOJI_CATS) >= 2

    return {
        "inline": inline,
        "tail": tail,
        "tail_word": [w for w in tail_word if w],
        "tail_lone": [w for w in tail_lone if w],
        "deco": deco,
        "runs": runs,
        "measure": measure,
        "lone": lone,
        "kaomoji": kaomoji,
        "tail_digit": bool(re.search(r"\d$", t)),
    }


def classify(s: str) -> tuple[str, str]:
    has_han = bool(HAN.search(s))
    ev = scan(s)
    if not has_han:
        return "纯外文", ""
    parts = []
    if ev["inline"]:
        parts.append("句中外文")
    if ev["tail_word"]:
        parts.append("句末实义外文")
    if ev["measure"]:
        parts.append("度量")
    if ev["kaomoji"]:
        parts.append("颜文字")
    if parts:
        return "混合", "+".join(parts)
    return "纯中文", ""


def has_symbol(s: str) -> bool:
    ev = scan(s)
    return bool(ev["runs"] or ev["measure"] or ev["lone"])


def load() -> list[list[str]]:
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def report(rows: list[list[str]], by_col: bool) -> None:
    head = rows[0]
    idx = {h.split("/")[0]: i for i, h in enumerate(head)}
    if by_col:
        print(f'{"列":<14}{"n":>5}{"中文":>6}{"混合":>6}{"外文":>6}   带符(混)       带符(中)')
        for name, i in idx.items():
            vals = [r[i].strip() for r in rows[1:] if i < len(r) and r[i].strip()]
            f, m, c = Counter(), 0, 0
            for v in vals:
                form, _ = classify(v)
                f[form] += 1
                if has_symbol(v):
                    if form == "混合":
                        m += 1
                    elif form == "纯中文":
                        c += 1
            n = len(vals)
            pm = m * 100 / max(f["混合"], 1)
            pc = c * 100 / max(f["纯中文"], 1)
            # 逐列只报数不打区间标记：单列分母小，且运营账号这类列自带 `_` 署名形态
            print(f'{name:<14}{n:>5}{f["纯中文"]:>6}{f["混合"]:>6}{f["纯外文"]:>6}   '
                  f'{m:>3}/{f["混合"]:<3}({pm:>4.1f}%)  '
                  f'{c:>3}/{f["纯中文"]:<3}({pc:>4.1f}%)')
        return

    print(f'{"组":<12}{"n":>5}{"中文":>6}{"混合":>6}{"外文":>6}  混合占比   带符(混)       带符(中)')
    tot = Counter()
    tm = tc = 0
    off = []
    for g, cols in GROUPS.items():
        vals = []
        for cname in cols:
            i = next((i for k, i in idx.items() if k.startswith(cname.split("（")[0])), None)
            if i is None:
                continue
            vals += [r[i].strip() for r in rows[1:] if i < len(r) and r[i].strip()]
        if not vals:
            continue
        f, m, c = Counter(), 0, 0
        for v in vals:
            form, _ = classify(v)
            f[form] += 1
            if has_symbol(v):
                if form == "混合":
                    m += 1
                elif form == "纯中文":
                    c += 1
        n = len(vals)
        tot.update(f)
        tm += m
        tc += c
        pm = m * 100 / max(f["混合"], 1)
        pc = c * 100 / max(f["纯中文"], 1)
        for form, p in (("混合", pm), ("纯中文", pc)):
            if mark(m if form == "混合" else c, f[form], form) != " ":
                off.append(f'{g}{form}{mark(m if form == "混合" else c, f[form], form)}{p:.1f}%')
        print(f'{g:<12}{n:>5}{f["纯中文"]:>6}{f["混合"]:>6}{f["纯外文"]:>6}  '
              f'{f["混合"]*100/n:5.1f}%   {m:>3}/{f["混合"]:<3}({pm:>4.1f}%{mark(m, f["混合"], "混合")})  '
              f'{c:>3}/{f["纯中文"]:<3}({pc:>4.1f}%{mark(c, f["纯中文"], "纯中文")})')
    n = sum(tot.values())
    pm = tm * 100 / tot["混合"]
    pc = tc * 100 / tot["纯中文"]
    print(f'\n合计 n={n}  纯中文 {tot["纯中文"]}（{tot["纯中文"]*100/n:.1f}%）  '
          f'混合 {tot["混合"]}（{tot["混合"]*100/n:.1f}%）  纯外文 {tot["纯外文"]}（{tot["纯外文"]*100/n:.1f}%）')
    lo, hi = ACCEPT["混合"]
    print(f'带符号：混合 {tm}/{tot["混合"]} = {pm:.1f}%{mark(tm, tot["混合"], "混合")}（区间 {lo:.0f}–{hi:.0f}%）'
          f'   纯中文 {tc}/{tot["纯中文"]} = {pc:.1f}%{mark(tc, tot["纯中文"], "纯中文")}'
          f'（区间 {ACCEPT["纯中文"][0]:.0f}–{ACCEPT["纯中文"][1]:.0f}%）')
    print(f'越界分组：{"、".join(off) if off else "无"}（↑ 超上限 / ↓ 低于下限）')


def check(s: str) -> None:
    ev = scan(s)
    form, sub = classify(s)
    print(f'{s}\n  形态 {form}（{sub or "—"}）')
    print(f'  句中外文 {ev["inline"] or "—"}   句末实义 {ev["tail_word"] or "—"}   '
          f'句末单字符 {ev["tail_lone"] or "—"}   装饰外文 {ev["deco"] or "—"}')
    print(f'  度量 {ev["measure"] or "—"}   颜文字 {"是" if ev["kaomoji"] else "否"}')
    print(f'  装饰连写 {ev["runs"] or "—"}   孤立/中段 {ev["lone"] or "—"}   '
          f'句末数字 {"是" if ev["tail_digit"] else "否"}')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--by-col", action="store_true")
    ap.add_argument("--check")
    a = ap.parse_args()
    if a.check:
        check(a.check)
        return 0
    report(load(), a.by_col)
    return 0


if __name__ == "__main__":
    sys.exit(main())
