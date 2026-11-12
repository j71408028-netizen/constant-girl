"""描述语料静态检查：meta 声明、标记格式、内容池替换与组合级语法风险。

本模块只做**判定**，不读文件、不打印、不碰 UI——同一套判据同时供
``developer_tools/quip_report.py``（命令行体检）与主程序描述管理页的「校验」
按钮使用，两处口径不会分叉。

四层检查
--------
====================  ====================================================
层                    覆盖内容
====================  ====================================================
meta                  ``_meta.custom_types`` 的名称/细分/``allow_confusion``
格式                  未知类型字母、空内容/非数字编号、游离括号、坏坐标键、
                      条目 ``style`` 字段串档、未知 ``{占位符}``
替换                  内容池可用性、混淆（邻近坐标加权改选编号）可达性
接缝                  候选与模板在标记边界上的字形冲突、同槽位形态不一致
====================  ====================================================

第 5 层「单条文本自己的排版」是纯规则层（:func:`scan_text_style`）：全半角标点
混用、标点叠置、省略号写法、虚词叠字。它判的是**一条文本自身**，与内容池无关，
所以既在正文（标记之外的部分）上跑，也在每个标记的内容上跑——标记内容就是池成员，
逐处溯源比在池上去重更好定位。

接缝层为什么不能用通用语法库
----------------------------
``[类型:编号:文本]`` 的语义是"这一格由同风格同体型下所有同类型同编号的标记文本
互换"，所以风险只出现在**接缝**上，且组合空间是 槽位 × 池内候选。通用中文语法库
（LanguageTool / pycorrector / HanLP / LTP）面向完整句子、需要模型与联网下载，
既穷举不了组合，也会把定语式片段成片误报。故本层坚持**特征比对**：只在标记边界
上比较字形分类，内容特征按字符串全局缓存，复杂度 O(槽位 × 池内候选)，不做
候选×模板 的笛卡尔展开。

数据形状
--------
输入的 ``data`` 与 ``persistence.quip_repo.read_quips_csv`` 的产物同构::

    {"small": {(1, 1): [{"text": ..., "style": ...}]}, "_meta": {...}}

``size_cat`` 给出时只检查该档（池按 (尺寸档, 风格, 字母, 编号) 分裂，只查一档在
语义上自洽）；风格或尺寸档缺省时报错由调用方负责，本模块不做猜测。
"""

import math
import re
from collections import Counter, defaultdict

from core.logic.sizing import SIZE_CATEGORIES

# 内置类型细分（与 ui/quip/dialogs.py::QuipDialog._build_type_list 一致）
BUILTIN_SUBTYPES = {
    "a": ["裙子", "制服", "夏季", "冬季"],
    "b": ["站立", "坐下", "躺下", "蹲跪"],
}
#: 内置类型的显示名（与 ui/quip/dialogs.py::QuipDialog._build_type_list 一致）
BUILTIN_LABELS = {"a": "衣着", "b": "姿势"}
CUSTOM_LETTERS = ("c", "d", "e")
KNOWN_PLACEHOLDERS = {"{name}", "{nick}"}
SIZE_CATS = list(SIZE_CATEGORIES)

# 运行时替换用的标记正则（services/exploration/quips.py::replace_quip_tags、
# detail_pools.py::build_detail_pools 同一口径）
TAG_RE = re.compile(r"\[([a-e]):(\d+):([^\]]+)\]")
# 任何成对括号组；掩掉它之后残留的 [ ] 就是游离/嵌套括号
BRACKET_GROUP_RE = re.compile(r"\[[^\[\]]*\]")
SUMMARY_RE = re.compile(r"\[summary:([^\]]*)\]")
PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")

LEVEL_ORDER = {"error": 0, "warn": 1, "info": 2}
LEVEL_LABELS = {"error": "错误", "warn": "警告", "info": "提示"}

# ===== 组合级（接缝）语法检查用的字形分类 =====
# 判定只看标记边界上的字形，不做 候选×模板 的笛卡尔展开。
DE_PARTICLES = "的地得"          # 结构助词/状语标记：叠置即"的的"
SENT_PUNCT = "。！？…"           # 句末标点：候选自带会把句子截断
CLAUSE_PUNCT = "，、；：—"        # 句中标点：与模板标点相邻即叠用
OPEN_QUOTES = "“‘「『"
CLOSE_QUOTES = "”’」』"
CONJ_CHARS = "和与及或"           # 连词
ASPECT_CHARS = "了着过"           # 体标记：叠置即"了了"
BRACKET_OPEN = "（(【["
BRACKET_CLOSE = "）)】]"

# 谓词性开头（前导副词/介词/动词）。词表刻意保守：只收语料里判定明确、且**不会**
# 与名词短语混淆的形式；命中即认为该候选是"谓词性小句"，用于发现同槽位里混进来的
# 「沦为了一场效率惊人的速通记录」这类换了结构就接不通的候选。
# 注意不含「被/让/给」——「被她无意间踏碎的繁华地段」是偏正结构的名词短语。
PREDICATE_HEAD_RE = re.compile(
    r"^(?:在|像|如|经|连同|瞬间|立刻|随即|同时|整体|彻底|完全|永久性?|逐步|持续|正|随|由"
    r"|沦为|化为|化作|变为|变成|成为|降格为|陷入|吞没|掀飞|扭曲|折断|撕裂|粉碎"
    r"|抹除|抹平|蒸发|液化|气化|塌陷|崩落|崩塌|崩断|崩裂|碾碎|挤压|剥离)")
# 动词打头但紧接着名词性后缀的是"动宾式名词"（崩裂声、崩塌感），不是谓词小句
NOUN_SUFFIX = "声感性度权质者们"
# 人称代词：排除「自我」「其他」这类含人称字的普通词
PERSON1_RE = re.compile(r"(?<!自)(?<!忘)我")
PERSON2_RE = re.compile(r"你|您")
PERSON3_OTHER_RE = re.compile(r"(?<!其)他|它")

FORM_DE = "de"        # 以「的/地/得」收尾 —— 定语式，后面接名词
FORM_PUNCT = "punct"  # 以真标点（。！？…，、；：）收尾
FORM_QUOTE = "quote"  # 以引号/括号收尾 —— 引号会跟着一起搬走
FORM_PRED = "pred"    # 谓词性小句
FORM_NOUN = "noun"    # 名词短语
FORM_LABEL = {FORM_DE: "「的」字定语式", FORM_PUNCT: "带标点收尾",
              FORM_QUOTE: "引号/括号收尾", FORM_PRED: "谓词性小句",
              FORM_NOUN: "名词短语"}

# ===== 单条文本的排版层 =====
# 口径取自中文排版 lint 的通用条目（全半角统一、标点不叠置、省略号用「……」），
# 但只保留**零争议**的那几条：宁可漏报，也不要在语料里制造需要人工复核的噪音。
HALF_TO_FULL = {",": "，", ".": "。", "!": "！", "?": "？", ";": "；", ":": "："}
_CJK = "\u3400-\u4dbf\u4e00-\u9fff"
_CJK_BEFORE = re.compile(f"[{_CJK}]")
_CJK_AFTER = re.compile(f"[{_CJK}]")
_HALF_PUNCT_RE = re.compile(r"[,\.!\?;:]")
_ELLIPSIS_RE = re.compile(r"\.{3,}|。{3,}|．{3,}|⋯{2,}")
# 停顿标点后紧跟停顿/句末标点：叠置。不含「！？」「？！」，那是合法强调组合。
_STACK_RE = re.compile(r"([，、；：。])([，、；：。])")
_FUNC_DUP_RE = re.compile(r"的的|了了|着着|过过|和和|与与|及及")
# 「的的确确」是合法叠用，不报
_FUNC_DUP_EXCEPTIONS = ("的的确",)


class ContentFeature:
    """一条候选文本在"接缝"上看得出的全部信息。按字符串全局缓存。"""

    __slots__ = ("text", "head", "tail", "form", "head_class", "tail_class",
                 "pron1", "pron2", "pron_her", "pron_other", "quotes_ok", "length")

    def __init__(self, text, head, tail, form, head_class, tail_class,
                 pron1, pron2, pron_her, pron_other, quotes_ok, length):
        self.text = text
        self.head = head
        self.tail = tail
        self.form = form
        self.head_class = head_class
        self.tail_class = tail_class
        self.pron1 = pron1
        self.pron2 = pron2
        self.pron_her = pron_her
        self.pron_other = pron_other
        self.quotes_ok = quotes_ok
        self.length = length


def head_class(ch):
    """一个字作为"文本开头"时的类别。"""
    if not ch:
        return "none"
    if ch in DE_PARTICLES:
        return "de"
    if ch in OPEN_QUOTES or ch in BRACKET_OPEN:
        return "quote_open"
    if ch in SENT_PUNCT or ch in CLAUSE_PUNCT or ch in CLOSE_QUOTES or ch in BRACKET_CLOSE:
        return "punct"
    if ch in CONJ_CHARS:
        return "conj"
    if ch in ASPECT_CHARS:
        return "aspect"
    return "word"


def tail_class(ch):
    """一个字作为"文本结尾"时的类别。"""
    if not ch:
        return "none"
    if ch in DE_PARTICLES:
        return "de"
    if ch in SENT_PUNCT:
        return "sent_punct"
    if ch in CLAUSE_PUNCT:
        return "clause_punct"
    if ch in CLOSE_QUOTES or ch in BRACKET_CLOSE:
        return "quote_close"
    if ch in OPEN_QUOTES or ch in BRACKET_OPEN:
        return "quote_open"
    if ch in CONJ_CHARS:
        return "conj"
    if ch in ASPECT_CHARS:
        return "aspect"
    return "word"


def _is_predicate(core):
    """候选是不是"谓词性小句"（换成名词槽位就接不通）。"""
    m = PREDICATE_HEAD_RE.match(core)
    if not m:
        return False
    if m.end() < len(core) and core[m.end()] in NOUN_SUFFIX:
        return False  # 崩裂声 / 崩塌感 —— 动词打头的名词
    return True


QUOTE_PAIRS = {"“": "”", "‘": "’", "「": "」", "『": "』",
               "（": "）", "(": ")", "【": "】", "[": "]"}


def _quotes_balanced(core):
    """引号/括号是否成对且类型对得上（ASCII 双引号按出现次数判奇偶）。

    候选自带半个引号时，替换进模板会把模板里原有的引号一起带偏，所以按内容单独查。
    """
    stack = []
    for ch in core:
        if ch in QUOTE_PAIRS:
            stack.append(QUOTE_PAIRS[ch])
        elif ch in ("”", "’", "」", "』", "）", ")", "】", "]"):
            if not stack or stack.pop() != ch:
                return False
    return not stack and core.count('"') % 2 == 0


def build_feature(text):
    core = text.strip()
    if not core:
        return ContentFeature(text, None, None, FORM_PUNCT, "none", "none",
                              False, False, False, False, True, 0)
    hd, tl = core[0], core[-1]
    hc, tc = head_class(hd), tail_class(tl)
    if tc == "de":
        form = FORM_DE
    elif tc == "sent_punct" or tc == "clause_punct":
        form = FORM_PUNCT
    elif tc in ("quote_close", "quote_open"):
        form = FORM_QUOTE
    elif _is_predicate(core):
        form = FORM_PRED
    else:
        form = FORM_NOUN
    return ContentFeature(
        text, hd, tl, form, hc, tc,
        bool(PERSON1_RE.search(core)), bool(PERSON2_RE.search(core)),
        "她" in core, bool(PERSON3_OTHER_RE.search(core)),
        _quotes_balanced(core), len(core))


def content_feature(text, cache):
    """按内容字符串缓存特征——同一段文本在全库只分析一次。"""
    feat = cache.get(text)
    if feat is None:
        feat = build_feature(text)
        cache[text] = feat
    return feat


def _render(occ, cand, pad=12):
    """把候选填进槽位，给出替换后的实际片段（便于人眼直接判断通不通）。"""
    text = occ["text"]
    left = text[max(0, occ["offset"] - pad):occ["offset"]]
    right = text[occ["end"]:occ["end"] + pad]
    return f"{left}【{cand}】{right}"


def _window(occ, pad=16):
    text = occ["text"]
    return text[max(0, occ["offset"] - pad):occ["end"] + pad]


class Finding:
    """一条结论：级别 + 规则名 + 说明 + 溯源定位 + 可选附带信息。

    ``loc`` 的形状见 :func:`make_loc`：UI 靠 ``coord`` 与 ``entry_idx`` 反查条目，
    CLI 靠 ``file`` / ``offset`` / ``snippet`` 直接给人看。
    """

    __slots__ = ("level", "kind", "message", "loc", "extra")

    def __init__(self, level, kind, message, loc, extra=None):
        self.level = level
        self.kind = kind
        self.message = message
        self.loc = loc
        self.extra = extra

    def as_dict(self):
        out = {"level": self.level, "kind": self.kind,
               "message": self.message, "loc": self.loc}
        if self.extra is not None:
            out["extra"] = self.extra
        return out

    def __repr__(self):
        return f"<Finding {self.level} {self.kind} {self.message[:24]}>"


def make_loc(file, size_cat=None, coord=None, entry_idx=None, offset=None, snippet=None):
    loc = {"file": file}
    for key, val in (("size_cat", size_cat), ("coord", coord),
                     ("entry_idx", entry_idx), ("offset", offset), ("snippet", snippet)):
        if val is not None:
            loc[key] = val
    return loc


def format_loc(loc):
    """把溯源定位渲染成一行：文件 [体型 @ 坐标] 条目#N 偏移K。"""
    if not loc:
        return "(无定位)"
    out = loc.get("file", "")
    if "size_cat" in loc:
        out += f" [{loc['size_cat']}"
        if "coord" in loc:
            out += f" @ {loc['coord']}"
        out += "]"
    if "entry_idx" in loc:
        out += f" 条目#{loc['entry_idx']}"
    if "offset" in loc:
        out += f" 偏移{loc['offset']}"
    return out


def short_loc(loc):
    """面向界面的短定位：``small @ 1_1 · 条目#0 · 偏移12``（不含文件名）。"""
    if not loc:
        return "(无定位)"
    parts = []
    if "size_cat" in loc:
        parts.append(str(loc["size_cat"]))
    if "coord" in loc:
        parts.append(f"@ {loc['coord']}")
    if "entry_idx" in loc:
        parts.append(f"条目#{loc['entry_idx']}")
    if "offset" in loc:
        parts.append(f"偏移{loc['offset']}")
    return " · ".join(parts) if parts else loc.get("file", "")


def format_extra(extra):
    """把组合级问题的双向溯源渲染成缩进行。"""
    if not extra:
        return []
    lines = [f"      ↳ 池 {extra.get('pool', '?')}；本类组合命中 {extra.get('count', '?')} 组"
             f"（涉事候选 {extra.get('distinct_candidates', '?')} 条）"]
    if extra.get("her_candidates"):
        lines.append("        自带主语「她」的候选：" + "、".join(
            f"『{c}』" for c in extra["her_candidates"]))
    for s in extra.get("samples", []):
        lines.append(f"        样例·候选『{s['candidate']}』"
                     f"（来自 {format_loc(s.get('origin'))}）")
        lines.append(f"        　　　填入槽位 {format_loc(s.get('slot'))}")
        lines.append(f"        　　　替换后 → 「{s.get('rendered', '')}」")
    return lines


# ---------------------------------------------------------------------------
# 单条文本的排版层
# ---------------------------------------------------------------------------

def scan_text_style(segment, offset, add, kind_prefix=""):
    """检查一段**纯正文**（不含标记语法）的排版问题，结论按绝对偏移溯源。

    ``add`` 是 ``add(level, kind, message, offset, snippet)`` 回调，由调用方决定
    如何构造 Finding；``offset`` 是 segment 在整条文本里的起始偏移。

    只查四条零争议规则：全半角标点混用、停顿标点叠置、省略号写法、虚词叠字。
    英文标点夹在数字/英文之间（``3.5``、``v1.2``）不算问题——判据是**相邻有汉字**。
    """
    if not segment:
        return
    work = segment

    # 省略号先认掉并掩掉，否则「。。。」会同时命中"标点叠置"，同一处报两遍
    for m in _ELLIPSIS_RE.finditer(segment):
        add("info", kind_prefix + "ellipsis_style",
            f"省略号写成「{m.group()}」：中文正文统一用「……」（两个省略号字符）",
            offset + m.start(), m.group())
        work = work[:m.start()] + "\x00" * (m.end() - m.start()) + work[m.end():]

    for m in _HALF_PUNCT_RE.finditer(work):
        ch = m.group()
        before = work[m.start() - 1] if m.start() > 0 else ""
        after = work[m.end()] if m.end() < len(work) else ""
        if not (_CJK_BEFORE.match(before or "") or _CJK_AFTER.match(after or "")):
            continue  # 纯英文/数字语境（3.5、v1.2），半角标点是正确写法
        add("warn", kind_prefix + "punct_width",
            f"汉字旁边用了半角标点「{ch}」，中文正文应为全角「{HALF_TO_FULL[ch]}」",
            offset + m.start(), segment[max(0, m.start() - 8):m.start() + 8])

    for m in _STACK_RE.finditer(work):
        add("warn", kind_prefix + "punct_stack",
            f"标点叠置「{m.group()}」：替换/接缝之外的正文里也不该出现连续两个停顿或句末标点",
            offset + m.start(), segment[max(0, m.start() - 8):m.end() + 8])

    for m in _FUNC_DUP_RE.finditer(segment):
        if any(token in segment[max(0, m.start() - 1):m.end() + 1]
               for token in _FUNC_DUP_EXCEPTIONS):
            continue
        add("warn", kind_prefix + "func_dup",
            f"虚词叠字「{m.group()}」：多半是复制或拼接时多写了一个字",
            offset + m.start(), segment[max(0, m.start() - 8):m.end() + 8])


# ---------------------------------------------------------------------------
# meta / 格式
# ---------------------------------------------------------------------------

def check_meta(file, meta, findings):
    """读取并校验 _meta.custom_types，返回 {letter: info_dict}。"""
    types_info = {}
    custom_types = {}
    if isinstance(meta, dict):
        custom_types = meta.get("custom_types") or {}
        if not isinstance(custom_types, dict):
            findings.append(Finding(
                "error", "meta", "_meta.custom_types 不是对象，运行时会按无自定义类型处理",
                make_loc(file)))
            custom_types = {}
    else:
        findings.append(Finding(
            "error", "meta", "_meta 不是对象，运行时会按默认 meta 处理", make_loc(file)))

    for letter in CUSTOM_LETTERS:
        info = custom_types.get(letter)
        if info is None:
            types_info[letter] = None
            continue
        if not isinstance(info, dict):
            findings.append(Finding(
                "error", "meta", f"custom_types.{letter} 不是对象", make_loc(file)))
            types_info[letter] = None
            continue
        subtypes = info.get("subtypes")
        if not isinstance(subtypes, list) or not subtypes:
            findings.append(Finding(
                "error", "meta",
                f"custom_types.{letter}({info.get('name', '?')}) 缺少非空 subtypes 列表，"
                f"编辑器与混淆权重都无法按细分工作", make_loc(file)))
            subtypes = []
        entry = {
            "name": info.get("name", ""),
            "subtypes": subtypes,
            "allow_confusion": info.get("allow_confusion"),
        }
        if "allow_confusion" not in info:
            findings.append(Finding(
                "warn", "meta",
                f"custom_types.{letter}({entry['name'] or '?'}) 未声明 allow_confusion："
                f"repo 运行时按 False（永不混淆），quip 编辑器却按 True 显示——建议显式声明",
                make_loc(file)))
        elif not isinstance(info["allow_confusion"], bool):
            findings.append(Finding(
                "error", "meta",
                f"custom_types.{letter} 的 allow_confusion 不是布尔值：{info['allow_confusion']!r}",
                make_loc(file)))
            entry["allow_confusion"] = None
        types_info[letter] = entry
    return types_info


def scan_text(text, file, size_cat, coord, entry_idx, findings):
    """单遍扫描一条 quip 文本，返回合法标记 [(letter, num, span, content, prev, next)]。

    prev/next 是标记左右紧邻的一个字符（无则为 None），供组合级接缝检查使用。

    同时检测：未知字母、空内容、非数字编号、游离/嵌套括号、空 summary、
    未知 {占位符}，以及标记之外正文与标记内容各自的排版问题。全部溯源到字符偏移。
    """
    tags = []
    consumed = []

    def loc(off, frag):
        return make_loc(file, size_cat, coord, entry_idx, off, frag)

    def add_style(level, kind, message, off, frag):
        findings.append(Finding(level, kind, message, loc(off, frag)))

    def consume(m):
        consumed.append(m.span())
        return "\x00" * (m.end() - m.start())

    for m in BRACKET_GROUP_RE.finditer(text):
        inner = m.group()[1:-1]

        if inner.startswith("summary:"):
            if not inner[len("summary:"):].strip():
                findings.append(Finding(
                    "warn", "summary", "summary 标记内容为空", loc(m.start(), m.group())))
            consumed.append(m.span())
            continue

        tm = re.fullmatch(r"([a-e]):(\d+):([^\]]*)", inner)
        if tm:
            letter, num, content = tm.group(1), tm.group(2), tm.group(3)
            if not content.strip():
                # 运行时正则要求 [^\]]+，空内容不会被替换也不会被剥离，原样漏进报告
                findings.append(Finding(
                    "error", "tag_empty",
                    f"标记 [{inner}] 内容为空：replace_quip_tags 的正则匹配不到它，"
                    f"会原样漏进报告正文", loc(m.start(), m.group())))
            else:
                prev_ch = text[m.start() - 1] if m.start() > 0 else None
                next_ch = text[m.end()] if m.end() < len(text) else None
                tags.append((letter, num, m.span(), content, prev_ch, next_ch))
                # 标记内容就是池成员：逐处查它自己的排版问题，溯源回到这一处标记
                scan_text_style(content, m.start() + len(letter) + len(num) + 3,
                                add_style, kind_prefix="content_")
            consumed.append(m.span())
            continue

        tm_bad = re.fullmatch(r"([a-zA-Z]):(\d*):(.*)", inner)
        if tm_bad:
            letter = tm_bad.group(1)
            if letter not in "abcde":
                findings.append(Finding(
                    "error", "tag_letter",
                    f"未知类型字母 '{letter}'（合法为 a-e）：运行时全链路静默忽略，"
                    f"标记原文会漏进报告", loc(m.start(), m.group())))
            elif not tm_bad.group(2):
                findings.append(Finding(
                    "error", "tag_num", f"标记 [{inner}] 缺少数字编号",
                    loc(m.start(), m.group())))
            else:
                findings.append(Finding(
                    "error", "tag_format",
                    f"标记 [{inner}] 无法被运行时正则解析（含空格/嵌套等）",
                    loc(m.start(), m.group())))
            consumed.append(m.span())
            continue

        # 既非标记也非 summary 的括号组：可能是手写错标记
        if re.fullmatch(r"[a-z]:\d+:[^\]]*", inner) or re.fullmatch(r"[A-Z]:\d+:[^\]]*", inner):
            findings.append(Finding(
                "error", "tag_letter", f"未知类型标记 [{inner}]（类型字母须为 a-e）",
                loc(m.start(), m.group())))
        else:
            findings.append(Finding(
                "warn", "bracket", f"无法识别的括号组 [{inner}]：既不是类型标记也不是 summary",
                loc(m.start(), m.group())))
        consumed.append(m.span())
        continue

    masked = BRACKET_GROUP_RE.sub(consume, text)
    for m in re.finditer(r"[\[\]]", masked):
        findings.append(Finding(
            "error", "bracket_stray",
            f"游离括号 '{m.group()}'（不成对或嵌套，如 [a:1:[x]]）：运行时不会替换其内部内容",
            make_loc(file, size_cat, coord, entry_idx, m.start(),
                     text[max(0, m.start() - 10):m.start() + 10])))

    for m in PLACEHOLDER_RE.finditer(text):
        if m.group() not in KNOWN_PLACEHOLDERS:
            findings.append(Finding(
                "warn", "placeholder",
                f"未知占位符 {m.group()}（运行时只替换 {{name}}/{{nick}}）",
                make_loc(file, size_cat, coord, entry_idx, m.start(), m.group())))

    # 标记之外仍是原文的部分（掩掉的括号组是 \x00 占位，偏移不变）
    scan_text_style(masked, 0, add_style)
    return tags


def _read_coord(coord_key):
    """坐标键 → ``((介入度, 破坏性) 或 None, 显示文本, 错误类型)``。

    接受两种键：CSV 读出来的 ``"1_1"`` 与 ``QuipRepo.load`` 内存矩阵的 ``(1, 1)``。
    错误类型：``"shape"`` 形状不对（缺 ``_`` / 不是二元组）、``"range"`` 值域不对。
    """
    if isinstance(coord_key, (tuple, list)):
        if len(coord_key) != 2:
            return None, repr(coord_key), "shape"
        try:
            i, d = int(coord_key[0]), int(coord_key[1])
        except (TypeError, ValueError):
            return None, repr(coord_key), "range"
        if not (1 <= i <= 4 and 1 <= d <= 4):
            return None, f"{i}_{d}", "range"
        return (i, d), f"{i}_{d}", ""
    if not isinstance(coord_key, str) or "_" not in coord_key:
        return None, repr(coord_key), "shape"
    try:
        i, d = (int(p) for p in coord_key.split("_"))
    except ValueError:
        return None, coord_key, "range"
    if not (1 <= i <= 4 and 1 <= d <= 4):
        return None, coord_key, "range"
    return (i, d), coord_key, ""


def scan_style(style_name, data, findings, size_filter=None):
    """扫描一个风格（或其单个尺寸档），返回索引结构。

    size_filter 给出时只扫该尺寸档，其余档整档略过（池按 (尺寸档, 风格, 字母, 编号)
    分裂，所以"只看一档"语义上是自洽的：该档的池天然不含别档内容）。

    pools: {(size_cat, letter, num): set(content)} —— 与 build_detail_pools 同构
           （池按条目自报的 style 字段归属，与运行时一致）。
    numset: {(size_cat, coord_i, coord_d, letter): set(num)} —— 混淆可达编号预计算用。
    origins: {(size_cat, style, letter, num): {content: loc}} —— 候选出处（溯源用）。
    occurrences: 标记出现处，带池键与左右邻字（组合级接缝检查用）。
    """
    pools = defaultdict(set)
    numset = {}
    used_letters = defaultdict(int)
    origins = {}
    occurrences = []
    source = f"{style_name}/quips.csv"

    if not isinstance(data, dict):
        findings.append(Finding("error", "structure", "风格数据顶层不是对象",
                                make_loc(source)))
        return pools, numset, used_letters, origins, occurrences

    for key, matrix in data.items():
        if key == "_meta":
            continue
        if size_filter is not None and key != size_filter:
            continue  # 本次只检查选定尺寸档，别档的池/坐标一律不进索引
        if key not in SIZE_CATS:
            findings.append(Finding(
                "warn", "structure",
                f"未知体型档 '{key}'（合法为 {','.join(SIZE_CATS)}），运行时会整档忽略",
                make_loc(source)))
        if not isinstance(matrix, dict):
            findings.append(Finding(
                "error", "structure", f"体型档 '{key}' 不是坐标到条目列表的映射",
                make_loc(source, key)))
            continue
        for coord_key, quip_list in matrix.items():
            coord, coord_text, coord_err = _read_coord(coord_key)
            if coord_err == "shape":
                findings.append(Finding(
                    "error", "coord",
                    f"坐标键 {coord_text} 缺少 '_'：QuipRepo.load 会在 split('_') 处"
                    f"直接抛异常，导致整个风格加载失败", make_loc(source, key)))
            elif coord_err:
                findings.append(Finding(
                    "error", "coord",
                    f"坐标键 '{coord_text}' 不是 1-4 范围的 整数_整数："
                    f"QuipRepo.load 会在 int() 处抛异常，导致整个风格加载失败",
                    make_loc(source, key)))
            if not isinstance(quip_list, list):
                findings.append(Finding(
                    "error", "structure", f"坐标 '{coord_text}' 下的条目不是列表",
                    make_loc(source, key, coord_text)))
                continue
            for idx, item in enumerate(quip_list):
                if isinstance(item, str):
                    text, item_style = item, style_name
                elif isinstance(item, dict):
                    text = item.get("text")
                    item_style = item.get("style")
                    if not isinstance(text, str):
                        findings.append(Finding(
                            "error", "structure",
                            f"条目缺少 text 字段或 text 不是字符串",
                            make_loc(source, key, coord_text, idx)))
                        continue
                    if item_style != style_name:
                        findings.append(Finding(
                            "warn", "style_field",
                            f"条目 style 字段为 {item_style!r}，与所属文件 '{style_name}' 不符："
                            f"选句后 replace_quip_tags 会按该字段取内容池，会串风格/取空池",
                            make_loc(source, key, coord_text, idx)))
                        if not item_style:
                            findings.append(Finding(
                                "error", "style_field",
                                f"条目缺少 style 字段：select_quip_with_budget 返回空风格名，"
                                f"replace_quip_tags 取不到内容池，所有标记原样漏进报告",
                                make_loc(source, key, coord_text, idx)))
                else:
                    findings.append(Finding(
                        "warn", "structure",
                        f"条目类型为 {type(item).__name__}，运行时会被静默丢弃",
                        make_loc(source, key, coord_text, idx)))
                    continue
                pool_key_style = item_style if item_style else style_name
                tags = scan_text(text, source, key, coord_text, idx, findings)
                for letter, num, span, content, prev_ch, next_ch in tags:
                    used_letters[letter] += 1
                    if content.strip().upper() == "MARK":
                        continue  # 与 build_detail_pools 一致：MARK 不入池
                    pk = (key, pool_key_style, letter, num)
                    pools[pk].add(content)
                    origins.setdefault(pk, {}).setdefault(
                        content, make_loc(source, key, coord_text, idx,
                                          span[0], content[:24]))
                    occurrences.append({
                        "file": source, "style": style_name,
                        "size_cat": key, "coord": coord_text, "entry_idx": idx,
                        "letter": letter, "num": num,
                        "offset": span[0], "end": span[1],
                        "inline": content, "prev": prev_ch, "next": next_ch,
                        "pool_key": pk, "text": text,
                    })
                    if coord is not None:
                        numset.setdefault((key, coord[0], coord[1], letter), set()).add(num)
    return pools, numset, used_letters, origins, occurrences


def check_replacement(style_name, pools, numset, types_info, findings):
    """类型替换静态检查：非混淆候选可用性 + 混淆可达性（组合级）。

    池由标记自身贡献，正常恒非空；编号越界的告警在 check_usage 里按声明数报。
    混淆可达性对 allow_confusion 的类型按运行时规则（同风格、距离≤2.0、
    exp(-dist) 加权）预计算每个格子的可达编号集，定位"开了混淆却空转"的组合。
    """
    declared = {}
    for letter in "abcde":
        if letter in BUILTIN_SUBTYPES:
            declared[letter] = len(BUILTIN_SUBTYPES[letter])
        elif types_info.get(letter):
            declared[letter] = len(types_info[letter]["subtypes"])

    used_nums = defaultdict(set)
    for (_size, _st, letter, num) in pools:
        used_nums[letter].add(num)

    source = f"{style_name}/quips.csv"
    confusing = [lt for lt in CUSTOM_LETTERS
                 if types_info.get(lt) and types_info[lt]["allow_confusion"] is True]
    for (size, i, d, letter), own_nums in sorted(numset.items()):
        if letter not in confusing:
            continue
        reachable = set(own_nums)
        for (s2, i2, d2, lt2), nums2 in numset.items():
            if s2 == size and lt2 == letter and math.hypot(i2 - i, d2 - d) <= 2.0:
                reachable |= nums2
        if len(reachable) <= 1:
            findings.append(Finding(
                "info", "confusion_noop",
                f"类型 {letter} 已允许混淆，但格 ({i},{d}) 周边距离≤2.0 内只有编号 "
                f"{sorted(reachable)}：混淆在该格是空转（改选编号只会命中自己）",
                make_loc(source, size, f"{i}_{d}")))
    return confusing, used_nums, declared


def check_usage(style_name, used_letters, used_nums, types_info, declared, findings,
                scope="本风格"):
    """meta 声明与实际用量的交叉检查。

    scope 是本次检查的范围（如"尺寸档 small"），只影响提示措辞——这些结论按选中的
    尺寸档统计，写"本风格"会误导。
    """
    source = f"{style_name}/quips.csv"
    for letter in "abcde":
        if letter in CUSTOM_LETTERS and used_letters[letter] and not types_info.get(letter):
            findings.append(Finding(
                "warn", "meta",
                f"{scope}内文本使用了自定义类型 {letter}（{used_letters[letter]} 处），"
                f"但 _meta.custom_types 未声明：编辑器无名称/细分可显示，"
                f"allow_confusion_map 也不会包含它（永不混淆）",
                make_loc(source)))
        src = "内置" if letter in BUILTIN_SUBTYPES else "自定义"
        name = (BUILTIN_SUBTYPES.get(letter) and ",".join(BUILTIN_SUBTYPES[letter])) or (
            types_info.get(letter) and types_info[letter]["name"]) or "?"
        if used_letters[letter] == 0:
            if letter in CUSTOM_LETTERS and types_info.get(letter):
                findings.append(Finding(
                    "info", "usage",
                    f"自定义类型 {letter}({types_info[letter]['name']}) 在{scope}内从未使用",
                    make_loc(source)))
            continue
        limit = declared.get(letter)
        if limit:
            for num in sorted(used_nums[letter], key=int):
                if int(num) > limit:
                    findings.append(Finding(
                        "warn", "tag_range",
                        f"{src}类型 {letter}({name}) 出现编号 {num}，超出声明的 {limit} 个细分："
                        f"编辑器无法显示该细分，混淆后编辑器归类为未知",
                        make_loc(source)))
        # 声明了细分但整档无人用（对自定义类型才有意义；内置类型仅提示缺口）
        if letter in CUSTOM_LETTERS and types_info.get(letter):
            missing = [str(n + 1) for n in range(limit or 0)
                       if str(n + 1) not in used_nums[letter]]
            if missing and used_nums[letter]:
                findings.append(Finding(
                    "info", "usage",
                    f"类型 {letter}({types_info[letter]['name']}) 的细分 "
                    f"{','.join(missing)} 在{scope}内没有任何标记使用",
                    make_loc(source)))


def _classify_combo(occ, feat, req, next_occ, prev_occ, pool_head_classes, pool_tail_classes):
    """给一对「槽位 × 候选」下判定，返回 (kind, level, detail, prefix) 或 None。

    优先级：硬接缝（虚词/标点叠置）> 标点截断 > 引号 > 人称代词 > 槽内形态。
    一对组合只报首要的一类，避免同一对组合在多个规则里重复刷屏；被抑制的判定
    不影响结论口径（它们在别的组合上仍会各自出现）。
    """
    prev_ch, next_ch = occ["prev"], occ["next"]
    prev_cls = tail_class(prev_ch)
    next_cls = head_class(next_ch)

    if next_occ is not None:
        # 相邻的两个标记（如 [c:1:…][e:2:…]）：接缝在"左侧候选的收尾 × 右侧池的开头"上
        nheads = pool_head_classes.get(next_occ["pool_key"], {})
        other = f"{next_occ['letter']}:{next_occ['num']}"
        if feat.tail_class == "de" and nheads.get("de"):
            return ("seam_de", "warn", f"|tag:{other}+de",
                    f"标记右侧紧邻另一个类型标记 [{other}]，其候选池里有以「的」开头的文本，"
                    f"而本候选以「{feat.tail}」收尾：两者同时命中会叠成「…的的…」")
        if feat.tail_class in ("sent_punct", "clause_punct") and (
                nheads.get("punct") or nheads.get("quote_open")):
            return ("seam_punct", "warn", f"|tag:{other}+punct",
                    f"标记右侧紧邻另一个类型标记 [{other}]，两侧候选都可能带标点："
                    f"同时命中会标点叠用")
        next_cls = "none"  # 右边是标记而非正文，正文接缝不再适用
    if prev_occ is not None:
        otails = pool_tail_classes.get(prev_occ["pool_key"], {})
        other = f"{prev_occ['letter']}:{prev_occ['num']}"
        if feat.head_class == "de" and otails.get("de"):
            return ("seam_de", "warn", f"tag:{other}|de+de",
                    f"标记左侧紧邻另一个类型标记 [{other}]，其候选池里有以「的」收尾的文本，"
                    f"而本候选以「的」开头：两者同时命中会叠成「…的的…」")
        if feat.head_class in ("punct", "quote_open") and (
                otails.get("sent_punct") or otails.get("clause_punct")):
            return ("seam_punct", "warn", f"tag:{other}|tail+{feat.head}",
                    f"标记左侧紧邻另一个类型标记 [{other}]，两侧候选都可能带标点："
                    f"同时命中会标点叠用")
        prev_cls = "none"

    if feat.tail_class == "de" and next_cls == "de":
        return ("seam_de", "warn", f"de+{next_ch}",
                f"本标记后面紧跟「{next_ch}」，而本候选以「{feat.tail}」收尾："
                f"替换后叠成「{feat.tail}{next_ch}」")
    if prev_cls == "de" and feat.head_class == "de":
        return ("seam_de", "warn", f"{prev_ch}+de",
                f"本标记前面是「{prev_ch}」，而本候选以「{feat.head}」开头："
                f"替换后叠成「{prev_ch}{feat.head}」")
    if feat.tail_class in ("sent_punct", "clause_punct") and next_cls in ("punct", "quote_close"):
        return ("seam_punct", "warn", f"tail{feat.tail}+{next_ch}",
                f"本候选以标点「{feat.tail}」收尾，标记后又是「{next_ch}」：替换后标点叠用")
    if prev_cls in ("sent_punct", "clause_punct") and feat.head_class in ("punct", "quote_open"):
        return ("seam_punct", "warn", f"{prev_ch}+head{feat.head}",
                f"本标记前面是标点「{prev_ch}」，而本候选以「{feat.head}」开头：替换后标点叠用")
    if feat.tail_class == "sent_punct" and next_cls == "word":
        return ("content_sent_punct", "warn", "sent_punct",
                "本候选自带句末标点，而标记后还有正文：替换后句子会在标记处提前结束")
    if prev_cls == "conj" and feat.head_class == "conj":
        return ("seam_conj", "warn", f"{prev_ch}+conj{feat.head}",
                f"本标记前面是连词「{prev_ch}」，而本候选以「{feat.head}」开头：替换后连词叠用")
    if prev_cls == "aspect" and feat.tail_class == "aspect" and next_cls == "aspect":
        return ("seam_aspect", "warn", f"aspect+{feat.tail}",
                f"标记前是「{prev_ch}」，本候选以体标记「{feat.tail}」收尾，后面又是「{next_ch}」："
                f"替换后叠成「{prev_ch}{feat.tail}{next_ch}」")
    if not feat.quotes_ok:
        return ("quote_unbalanced", "warn", "quotes",
                "本候选的引号/括号不成对：替换后与模板里的引号错配，整句引号归属会乱")
    if feat.pron2:
        return ("pron_person2", "warn", "p2",
                "本候选直接称呼读者（第二人称）：与全文第三人称叙述冲突")
    if feat.pron1:
        return ("pron_person1", "info", "p1",
                "本候选使用第一人称：叙述视角会从第三人称跳到第一人称")
    if feat.pron_other and "她" in _window(occ):
        return ("pron_gender", "warn", "p3o",
                "本候选用「他/它」指代，而本处上下文以「她」指代主角："
                "替换后同句出现两种性别/范畴的指代")
    if feat.form != req.form:
        # 只差"引号收尾 vs 裸名词"属于信息级（引号跟着搬走而已）；
        # 「的」字定语式/名词短语/谓词性小句之间的差别会让句子接不通，算告警。
        level = "info" if FORM_QUOTE in (req.form, feat.form) else "warn"
        return ("slot_form", level, f"{req.form}->{feat.form}",
                f"同一槽位的候选形态不一致：本处标记自称{FORM_LABEL[req.form]}"
                f"（原文『{occ['inline']}』），而池内候选是{FORM_LABEL[feat.form]}")
    return None


def check_grammar(style_name, occurrences, pools, origins, findings, max_samples=3):
    """类型替换的组合级语法检查：在每个标记出现处，把它和整池候选在边界上比对。

    只在标记边界上比较特征，不做 候选×模板 的笛卡尔展开；内容特征按字符串全局缓存，
    相同的 (池, 槽位上下文, 候选形态) 判定天然合并。复杂度 O(槽位 × 池内候选)。
    返回统计信息，供报告里体现"实际比对了多少次、缓存省了多少"。
    """
    stats = {"slots": 0, "candidates": 0, "feature_cache": 0, "rules": Counter()}
    if not occurrences:
        return stats

    cache = {}
    pool_forms = {}
    pool_heads = {}
    pool_tails = {}
    for pk, contents in pools.items():
        forms, heads, tails = Counter(), Counter(), Counter()
        for c in contents:
            feat = content_feature(c, cache)
            forms[feat.form] += 1
            heads[feat.head_class] += 1
            tails[feat.tail_class] += 1
        pool_forms[pk], pool_heads[pk], pool_tails[pk] = forms, heads, tails
    stats["feature_cache"] = len(cache)

    # 相邻标记：右侧是标记时，接缝落在右侧池的首字分布上
    by_entry = defaultdict(list)
    for occ in occurrences:
        by_entry[(occ["file"], occ["size_cat"], occ["coord"], occ["entry_idx"])].append(occ)
    for grp in by_entry.values():
        grp.sort(key=lambda o: o["offset"])
        for left, right in zip(grp, grp[1:]):
            if left["end"] == right["offset"]:
                left["next_tag"] = right
                right["prev_tag"] = left

    groups = {}

    def agg(kind, level, pk, detail, prefix, sample):
        key = (kind, pk, detail)
        g = groups.get(key)
        if g is None:
            g = {"kind": kind, "level": level, "pk": pk, "prefix": prefix,
                 "count": 0, "samples": [], "seen": set(), "loc": sample["slot"]}
            groups[key] = g
        g["count"] += 1
        # 同一条候选在多个槽位上犯同样的错只留一条溯源样例，样例按候选去重后限条
        if sample["candidate"] not in g["seen"]:
            g["seen"].add(sample["candidate"])
            if len(g["samples"]) < max_samples:
                g["samples"].append(sample)
        stats["rules"][kind] += 1

    ordered = sorted(occurrences, key=lambda o: (
        o["file"], o["size_cat"], o["coord"], o["entry_idx"], o["offset"]))
    for occ in ordered:
        pk = occ["pool_key"]
        pool = pools.get(pk) or ()
        stats["slots"] += 1
        if len(pool) < 2:
            continue  # 池里只有自己，替换无从发生（运行时只会回退原文）
        req = content_feature(occ["inline"], cache)
        slot_loc = make_loc(occ["file"], occ["size_cat"], occ["coord"], occ["entry_idx"],
                            occ["offset"], f"[{occ['letter']}:{occ['num']}:{occ['inline'][:24]}]")
        for cand in sorted(pool):
            if cand == occ["inline"]:
                continue
            stats["candidates"] += 1
            feat = content_feature(cand, cache)
            verdict = _classify_combo(occ, feat, req, occ.get("next_tag"),
                                      occ.get("prev_tag"), pool_heads, pool_tails)
            if verdict is None:
                continue
            kind, level, detail, prefix = verdict
            agg(kind, level, pk, detail, prefix, {
                "candidate": cand,
                "origin": origins.get(pk, {}).get(cand),
                "slot": slot_loc,
                "rendered": _render(occ, cand),
            })

    for g in groups.values():
        pk = g["pk"]
        pool_name = f"({pk[2]},{pk[3]}) @ {pk[0]}"
        forms = pool_forms.get(pk) or {}
        form_desc = " / ".join(f"{FORM_LABEL[k]}{v}条"
                              for k, v in sorted(forms.items(), key=lambda kv: -kv[1]))
        n_cand = len(g["seen"])
        names = "、".join(f"『{s['candidate']}』" for s in g["samples"])
        # max_samples 0 时不列候选名，别留下空括号
        if not names:
            cand_desc = f"涉事候选 {n_cand} 条"
        else:
            more = "" if n_cand <= len(g["samples"]) else f" 等 {n_cand} 条"
            cand_desc = f"涉事候选 {n_cand} 条（{names}{more}）"
        extra = {
            "count": g["count"],
            "distinct_candidates": n_cand,
            "pool": pool_name,
            "pool_size": len(pools.get(pk) or ()),
            "pool_forms": form_desc,
            "candidates": [s["candidate"] for s in g["samples"]],
            "samples": [
                {"candidate": s["candidate"],
                 "origin": s["origin"],
                 "slot": s["slot"],
                 "rendered": s["rendered"]}
                for s in g["samples"]],
        }
        findings.append(Finding(
            g["level"], g["kind"],
            f"{g['prefix']}；池 {pool_name} 共 {extra['pool_size']} 条候选（{form_desc}），"
            f"{cand_desc}，共命中 {g['count']} 组组合",
            g["loc"], extra))

    # 池级：候选"是否显式带主语「她」"不一致 —— 替换后同句主语的显隐会跳
    for pk, contents in sorted(pools.items()):
        if len(contents) < 2:
            continue
        hers = sorted(c for c in contents if content_feature(c, cache).pron_her)
        if not hers or len(hers) == len(contents):
            continue
        sample_loc = (origins.get(pk, {}).get(hers[0]) or
                      make_loc(f"{style_name}/quips.csv", pk[0]))
        findings.append(Finding(
            "info", "pool_pronoun",
            f"池 ({pk[2]},{pk[3]}) @ {pk[0]} 的 {len(contents)} 条候选里，"
            f"{len(hers)} 条显式写出主语「她」（{len(contents) - len(hers)} 条不带人称代词）："
            f"替换后同一槽位的主语有时显、有时隐，指代表达不统一",
            sample_loc,
            {"count": len(hers), "distinct_candidates": len(hers),
             "pool": f"({pk[2]},{pk[3]}) @ {pk[0]}",
             "pool_size": len(contents),
             "her_candidates": hers[:6]}))
    return stats


def analyze_style(style_name, data, findings, with_grammar=True, size_filter=None,
                  max_samples=3):
    """对一个已解析的风格数据跑全部检查（可限定单个尺寸档）。

    返回 (types_info, used_letters, used_nums, confusing, grammar_stats)。
    调用方通常用 :func:`lint_style`，它把这几样一起装进 :class:`LintReport`。
    """
    meta = data.get("_meta") if isinstance(data, dict) else None
    types_info = check_meta(f"{style_name}/quips.csv", meta, findings)
    pools, numset, used_letters, origins, occurrences = scan_style(
        style_name, data, findings, size_filter=size_filter)
    confusing, used_nums, declared = check_replacement(
        style_name, pools, numset, types_info, findings)
    scope = f"尺寸档 {size_filter}" if size_filter else "本风格"
    check_usage(style_name, used_letters, used_nums, types_info, declared, findings,
                scope=scope)
    stats = (check_grammar(style_name, occurrences, pools, origins, findings,
                           max_samples=max_samples)
             if with_grammar else Counter())
    return types_info, used_letters, used_nums, confusing, stats


class LintReport:
    """一次校验的全部结果。界面与命令行都只认这一个对象。

    ``findings`` 保持产出顺序（未排序），``sorted_findings()`` 给出稳定顺序：
    级别 → 规则名 → 定位，便于两处呈现一致。
    """

    def __init__(self, style, size_cat, findings, types_info, used_letters,
                 used_nums, confusing, stats, with_grammar):
        self.style = style
        self.size_cat = size_cat
        self.findings = findings
        self.types_info = types_info
        self.used_letters = used_letters
        self.used_nums = used_nums
        self.confusing = confusing
        self.stats = stats
        self.with_grammar = with_grammar

    @property
    def counts(self):
        counts = {"error": 0, "warn": 0, "info": 0}
        for f in self.findings:
            counts[f.level] = counts.get(f.level, 0) + 1
        return counts

    @property
    def has_errors(self):
        return any(f.level == "error" for f in self.findings)

    @property
    def tag_total(self):
        return sum(self.used_letters.values())

    def rules_hit(self):
        """命中规则 → 组合数（聚合前），按次数降序。"""
        rules = self.stats.get("rules") if self.stats else None
        return dict(sorted(rules.items(), key=lambda kv: -kv[1])) if rules else {}

    def sorted_findings(self, levels=None):
        if levels is not None:
            allowed = set(levels)
            items = [f for f in self.findings if f.level in allowed]
        else:
            items = list(self.findings)
        return sorted(items, key=lambda f: (
            LEVEL_ORDER.get(f.level, 9), f.kind,
            format_loc(f.loc)))

    def meta_view(self):
        """meta 的展示视图：``{类型: 名称/细分/混淆开关/用到编号}`` + 混淆类型 + 标记总数。

        命令行 ``--json`` 的 ``meta`` 即此结构。内置类型（a/b）的细分与名称取自
        :data:`BUILTIN_SUBTYPES` / :data:`BUILTIN_LABELS`，本档没用到的类型记为 None。
        """
        types = {}
        for letter in "abcde":
            info = self.types_info.get(letter)
            nums = sorted(self.used_nums[letter], key=int)
            if info:
                view = dict(info, used=self.used_letters[letter], nums=nums)
            elif letter in BUILTIN_SUBTYPES and self.used_letters[letter]:
                view = {"name": BUILTIN_LABELS[letter],
                        "subtypes": BUILTIN_SUBTYPES[letter],
                        "allow_confusion": False,
                        "used": self.used_letters[letter],
                        "nums": nums}
            else:
                view = None
            types[letter] = view
        return {"types": types, "confusing_types": self.confusing,
                "tag_total": self.tag_total}


def lint_style(style_name, data, size_cat=None, with_grammar=True, max_samples=3):
    """校验一个风格的（或其中一个尺寸档的）描述语料，返回 :class:`LintReport`。

    ``data`` 的形状见模块说明；``size_cat`` 为 None 表示检查全部档（界面上不提供，
    全量结论读不动，命令行也只在你明确要求时才用到）。
    """
    findings = []
    types_info, used_letters, used_nums, confusing, stats = analyze_style(
        style_name, data, findings, with_grammar=with_grammar,
        size_filter=size_cat, max_samples=max_samples)
    return LintReport(style_name, size_cat, findings, types_info, used_letters,
                      used_nums, confusing, stats, with_grammar)
