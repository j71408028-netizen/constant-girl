# -*- coding: utf-8 -*-
"""昵称素材的可用符号清单：按码位范围判，不按手写清单。

判据见 `data/static/materials/default/nick_categories_forms.md`「符号池：按码位范围，不按清单」。
这里只做执行：折半 → 排除彩色 emoji 与路径字符 → 认区 → 认类。

    python developer_tools/materials_symbols_report.py --list    # 允许的范围与字面
    python developer_tools/materials_symbols_report.py --audit   # 扫 CSV，列出越界字符与条目
    python developer_tools/materials_symbols_report.py --check "春还没站稳~"
    python developer_tools/materials_symbols_report.py --md      # 生成可直接贴进 forms.md 的段落

emoji 码位段内嵌自 Unicode 15.1 的 emoji-data.txt，只取 `Emoji_Presentation`（默认彩色呈现）
属性，已合并相邻段。三类字符因此可用：

- **没有 `Emoji` 属性的排印符号**：★ ♤ ♪ ☽ ☼ ⚐
- **有 `Emoji` 属性、但默认文本呈现的单色 emoji**：☀ ☁ ☂ ☃ ☄ ✈ ✂ ❤ ♀ ♠ ♥ ☺
- 其余凡带 `Emoji_Presentation` 的一律不收：🍒 🌙 💕 ⚡ ✅

单色 emoji **只能用文本形态**：尾巴后面跟 U+FE0F 会强制彩色，U+FE0F 不在任何允许区段里，
会照常判为越界。
"""
from __future__ import annotations

import csv
import io
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data/static/materials/default/nick_categories.csv"

# ---------------------------------------------------------------- 彩色 emoji

# Unicode 15.1 `Emoji_Presentation`：不给变体选择符也默认涂成彩色的一批。
# 它比 `Emoji` 少两百多个码位，差集正是默认单色的那批（☀ ☂ ❤ ♠ ♥ ☺），本池子收。
_EPRES = (
    "231A-231B,23E9-23EC,23F0,23F3,25FD-25FE,2614-2615,2648-2653,267F,2693,26A1,26AA-26AB,26BD-26BE,26C4-26C5,26CE,26D4,26EA,26F2-26F3,26F5,26FA,26FD,2705,270A-270B,2728,274C,274E,2753-2755,2757,2795-2797,27B0,27BF,2B1B-2B1C,2B50,2B55,1F004,1F0CF,1F18E,1F191-1F19A,1F1E6-1F1FF,1F201,1F21A,1F22F,1F232-1F236,1F238-1F23A,1F250-1F251,1F300-1F320,1F32D-1F335,1F337-1F37C,1F37E-1F393,1F3A0-1F3CA,1F3CF-1F3D3,1F3E0-1F3F0,1F3F4,1F3F8-1F43E,1F440,1F442-1F4FC,1F4FF-1F53D,1F54B-1F54E,1F550-1F567,1F57A,1F595-1F596,1F5A4,1F5FB-1F64F,1F680-1F6C5,1F6CC,1F6D0-1F6D2,1F6D5-1F6D7,1F6DC-1F6DF,1F6EB-1F6EC,1F6F4-1F6FC,1F7E0-1F7EB,1F7F0,1F90C-1F93A,1F93C-1F945,1F947-1F9FF,1FA70-1FA7C,1FA80-1FA88,1FA90-1FABD,1FABF-1FAC5,1FACE-1FADB,1FAE0-1FAE8,1FAF0-1FAF8"
)

EPRES_RANGES: list[tuple[int, int]] = []
for _part in _EPRES.split(","):
    _a, _, _b = _part.partition("-")
    EPRES_RANGES.append((int(_a, 16), int(_b, 16) if _b else int(_a, 16)))


def is_color_emoji(cp: int) -> bool:
    """是否默认彩色呈现。ASCII 由白名单直接管，`#` `*` 与数字只在键帽序列里才是 emoji。"""
    if cp < 0x80:
        return False
    return any(a <= cp <= b for a, b in EPRES_RANGES)


# ---------------------------------------------------------------- 归一化

# 全角 ASCII 变体与同形字符，一律折成半角再判。同一形状只留一个码位，
# 形态统计不再因为 `～` / `~` 各写一个而分裂。
NORMALIZE = {
    **{chr(0xFF01 + i): chr(0x21 + i) for i in range(0x5E)},  # ！ ～ ａ Ａ
    "\u301c": "~",  # WAVE DASH
    "\u02dc": "~",  # SMALL TILDE
    "\u3030": "~",  # WAVY DASH
    "\ufe4f": "~",  # WAVY LOW LINE
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
    "\u2014": "-", "\u2015": "-", "\u2212": "-",
    "\u2044": "/", "\u2215": "/",
    "\u2216": "\\",
    "\u2217": "*",
}


def norm(ch: str) -> str:
    return NORMALIZE.get(ch, ch)


# ---------------------------------------------------------------- 范围与例外

# 按语义认的中文标点：形态上算中文，不算符号。
CJK_PUNCT = set("，。、；：？！…—·・‘’“”（）《》〈〉【】「」『』〔〕　")

# 路径非法字符与引擎冲突字符，折成半角后判，整组禁用。
FORBIDDEN = set('\\/:*?"<>|,)') | set("{}[]")

# (名称, 起, 止, 收什么)
RANGES: list[tuple[str, int, int, str]] = [
    ("ASCII 排印", 0x21, 0x7E, "只收 ~ & # % + - _ = ^"),
    ("Latin-1", 0x00A1, 0x00BF, "¦ © ¬ ® ° ±"),
    ("Latin-1 运算", 0x00D7, 0x00F7, "× ÷"),
    ("箭头", 0x2190, 0x21FF, "方向、趋势、位移"),
    ("数学运算符", 0x2200, 0x22FF, "∞ ∅ √ ∴ ⊕ 一类"),
    ("几何图形", 0x25A0, 0x25FF, "■ ▲ △ ◆ ◇ ○ ●，结构符号主力"),
    ("杂项符号", 0x2600, 0x26FF, "剔掉彩色 emoji 后剩星形、棋牌、骰子、音符、天气"),
    ("装饰符号", 0x2700, 0x27BF, "✓ ✦ ❀ ❖ 一类，含单色图标"),
    ("数学符号 A", 0x27C0, 0x27EF, "⟡ ⟢ ⟣ 一类（括号形状不收）"),
    ("补充箭头 A", 0x27F0, 0x27FF, "⟵ ⟶ 一类"),
    ("大号几何", 0x2B1A, 0x2B2F, "⬡ ⬢ ⬤ ⬥ 一类"),
]

# 段内挖掉的洞：(起, 止, 理由)
HOLES: list[tuple[int, int, str]] = [
    (0x2700, 0x2701, "剪刀与信封的开头两码：字形残缺，整枚在下一段才成图"),
    (0x275B, 0x2762, "引号与感叹号的装饰变体：读作标点"),
    (0x2776, 0x2793, "圈号：是数字与字母"),
]

ASCII_ALLOW = set("~&#%+-_=^")
# 只收数学符号与其他符号：标点、字母、数字、括号形状自动出局。
CATS = {"Sm", "So"}


def allowed(ch: str) -> bool:
    """是否属于可用符号。先归一，再按半角形态判。"""
    ch = norm(ch)
    cp = ord(ch)
    if cp < 0x80:
        return ch in ASCII_ALLOW
    if ch in FORBIDDEN:
        return False
    if not any(a <= cp <= b for _, a, b, _ in RANGES):
        return False
    if any(a <= cp <= b for a, b, _ in HOLES):
        return False
    if unicodedata.category(ch) not in CATS:
        return False
    return not is_color_emoji(cp)


def classify(ch: str) -> str:
    """han / digit / letter / cjk_punct / space / symbol / forbidden / other"""
    if "\u4e00" <= ch <= "\u9fff":
        return "han"
    if ch in CJK_PUNCT:
        return "cjk_punct"
    if ch.isspace():
        return "space"
    n = norm(ch)
    cat = unicodedata.category(n)
    if cat in {"Nd", "Nl", "No"}:
        return "digit"
    if cat[0] == "L":
        return "letter"
    if n in FORBIDDEN:
        return "forbidden"
    if allowed(n):
        return "symbol"
    return "other"


def why_not(ch: str) -> str:
    n = norm(ch)
    cp = ord(n)
    if n in FORBIDDEN:
        return "路径/引擎冲突"
    if is_color_emoji(cp):
        return "彩色 emoji"
    cat = unicodedata.category(n)
    if cat in {"Nd", "Nl", "No"}:
        return "数字"
    if cat[0] == "P":
        return "标点"
    if cat[0] == "M":
        return "组合符"
    if cp >= 0x1F000:
        return "SMP 图形"
    if any(a <= cp <= b for a, b, _ in HOLES):
        return "段内排除"
    if not any(a <= cp <= b for _, a, b, _ in RANGES):
        return "不在允许范围"
    return f"类别 {cat}"


def glyphs(a: int, b: int) -> list[str]:
    """清单只列规范形：同形异码（－ ／ ∗ ﹨）折成半角后不重复出现。"""
    return [
        chr(cp)
        for cp in range(a, b + 1)
        if norm(chr(cp)) == chr(cp) and allowed(chr(cp))
    ]


# ---------------------------------------------------------------- 命令行

def dump_list() -> None:
    total = 0
    for name, a, b, note in RANGES:
        g = glyphs(a, b)
        total += len(g)
        print(f"{name:10s} U+{a:04X}–U+{b:04X}  {len(g):3d} 枚   {note}")
        print("   " + "".join(g))
    print("合计", total)


def md_section() -> None:
    print("| 区 | 码位 | 枚数 | 收什么 |")
    print("|-|-|-|-|")
    total = 0
    for name, a, b, note in RANGES:
        g = glyphs(a, b)
        total += len(g)
        print(f"| {name} | U+{a:04X}–U+{b:04X} | {len(g)} | {note} |")
    print(f"\n合计 {total} 枚\n")
    for name, a, b, _ in RANGES:
        print(name + "：")
        print("".join(glyphs(a, b)))
        print()


def audit() -> None:
    import re

    rows = list(csv.reader(io.StringIO(CSV_PATH.read_text(encoding="utf-8-sig"))))
    tok = re.compile(r"\{sur\}|\{given\}")
    bad: dict[str, list[tuple[int, str]]] = {}
    used: dict[str, int] = {}
    for ri, row in enumerate(rows[1:], start=2):
        for ci, cell in enumerate(row):
            for ch in tok.sub("", cell):
                cat = classify(ch)
                if cat == "symbol":
                    used[ch] = used.get(ch, 0) + 1
                elif cat in ("forbidden", "other"):
                    if unicodedata.category(norm(ch))[0] == "P" and ch not in "{}[]":
                        continue  # 标点另论，不进符号池
                    bad.setdefault(ch, []).append((ri, rows[0][ci].split("/")[0]))
    print("已用符号：", " ".join(f"{c}×{n}" for c, n in sorted(used.items(), key=lambda kv: -kv[1])))
    print()
    if not bad:
        print("越界：无")
        return
    print("越界字符：")
    for ch, where in sorted(bad.items(), key=lambda kv: -len(kv[1])):
        print(f"  {ch} U+{ord(ch):04X} {why_not(ch):8s} {len(where):2d} 处  " + "/".join(sorted({c for _, c in where})))
    entries = {(r, c) for v in bad.values() for r, c in v}
    print(f"\n越界条目 {len(entries)} 条")


def check(text: str) -> None:
    bad = [(ch, why_not(ch)) for ch in text if classify(ch) in ("forbidden", "other")]
    if not bad:
        print("可用（无越界字符）")
        return
    for ch, why in bad:
        print(f"  {ch} U+{ord(ch):04X}  {why}")


if __name__ == "__main__":
    if "--list" in sys.argv:
        dump_list()
    elif "--md" in sys.argv:
        md_section()
    elif "--audit" in sys.argv:
        audit()
    elif "--check" in sys.argv:
        check(sys.argv[sys.argv.index("--check") + 1])
    else:
        print(__doc__)
