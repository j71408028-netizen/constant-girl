"""内置分句器：把一次 AI 输出切成多个「显示段落」，并解析说话人标记。

AI 自身的换行与句读不稳定，分句不依赖其分段习惯，而是按确定性规则切分：
换行、句末标点、分号是断点；句中破折号与省略号保留原样、不作断点，分号归一
为句号、悬空顿逗清除。强调引号是正文的一部分，保留显示且不构成断点。

``@说话人@`` 紧跟引号构成「台词块」：块内按句末标点切成多个显示段落，每段
继承同一 speaker，首尾引号不进显示文本（原文保留引号，用于区分台词与叙述）；
未闭合的台词留作尾部，收全后自然定格。

说话人标记：方案声明 ``speaker_notation="tagged"`` 时，AI 会在对话句句首写
「@说话人@」（规则见 ``dungeon/speaker_notation.py``）。本模块在显示段落
**起点**识别完整标记，解析出结构化 ``DisplayUnit.speaker`` 并从显示文本中
剥离；标记出现在段落中间时不处理、原样保留。流式过程中未闭合的半截标记
按提示抑制显示（整体重算幂等，收全后自然解析）。
``speaker_notation="literary"`` 的方案正文无标记，显示段落的 speaker 全为
None。解析本身保持宽容，是否采用由窗口层按方案记法决定。

高亮标记：正文里的 ``==`` 是一对开合标记（:data:`HIGHLIGHT_MARK`），**以显示
段落为渲染单位**——某个显示段落只要被高亮区盖住，整段就按高亮颜色渲染，标记
本身不进显示文本。因此高亮可以写在任何进入显示层的文本里：固定文本章节的脚本
段落、插入触发器的段落、以及 AI 生成的句子（提示词见
``coupling.HIGHLIGHT_MARKER_RULE``）。未闭合的开标记一直作用到逻辑段落末尾。

逻辑段落仍是一次 AI 输出的整体（属性演化、回放、压缩都以它为单位），
显示段落只是它的 UI 呈现单位；说话人与高亮只活在显示层，不进持久化——
落盘正文用 :func:`strip_display_markers` 剥离标记。
"""

import re
from typing import NamedTuple, Optional

# 标点断点的最小单元长度：太短的句读不切分，避免产生碎片段落（换行不受限）
_MIN_UNIT_CHARS = 6

# 说话人标记：单元起点的 @说话人@（1~12 个非 @ 非 \n 字符）
_SPEAKER_MARKER_RE = re.compile(r"@([^@\n]{1,12})@")
# 正文内任意位置的标记（净化用，比显示层解析宽松）
_SPEAKER_MARKER_ANY_RE = re.compile(r"@[^@\n]{1,12}@")

_OPEN_QUOTES = "“『「《〈‘"
_CLOSE_QUOTES = "”』」》〉’"
#: 台词引号配对（开 -> 闭）；非台词引号按普通正文处理
_QUOTE_PAIR = dict(zip(_OPEN_QUOTES, _CLOSE_QUOTES))
_END_PUNCT = "。！？!?…"
# 截断处不允许出现的悬空标点，归一化时清除
_TRAILING_NOISE = "，、：:，"

#: 高亮标记：成对的 ``==``，见模块 docstring
HIGHLIGHT_MARK = "=="


class DisplayUnit(NamedTuple):
    """一个显示段落：speaker 为 None 表示叙述句，highlight 决定整段渲染色。"""

    speaker: Optional[str]
    text: str
    highlight: bool = False


def _normalize_unit_end(unit: str) -> str:
    """归一化截断处标点，避免显示段落以半截标点收尾。"""
    unit = unit.strip()
    if not unit:
        return unit
    while unit and unit[-1] in _TRAILING_NOISE:
        unit = unit[:-1]
    if unit and unit[-1] in "；;":
        unit = unit[:-1] + "。"
    return unit


def _split_leading_marker(text: str) -> tuple:
    """识别文本起点的完整说话人标记，返回 (speaker|None, 剥离后的正文)。"""
    if not text.startswith("@"):
        return None, text
    match = _SPEAKER_MARKER_RE.match(text)
    if match:
        return match.group(1), text[match.end():]
    return None, text


def _resolve_stream_tail(text: str) -> tuple:
    """流式尾部的显示净化：返回 ``(speaker|None, 显示文本)``。

    起点的完整标记解析出说话人并剥离；起点是未闭合的半截标记时暂不显示，
    避免闪现。整体重算幂等：标记一旦闭合（仍在长度上限内）就会被解析并剥离。
    """
    if not text.startswith("@"):
        return None, text
    match = _SPEAKER_MARKER_RE.match(text)
    if match:
        return match.group(1), text[match.end():]
    # 长度上限 12 + 前后两个 @：超过仍无闭合即视为普通正文
    if len(text) <= 13:
        return None, ""
    return None, text


def strip_speaker_markers(text: str) -> str:
    """剥离正文中全部说话人标记，返回纯正文（回放/概要/报告等落盘文本用）。"""
    if not text:
        return text
    return _SPEAKER_MARKER_ANY_RE.sub("", text)


def scan_highlight_markers(text: str) -> tuple:
    """剥离 ``==`` 高亮标记，返回 ``(净文本, 逐字符高亮掩码)``。

    掩码与净文本逐字符对齐，供分句器把高亮折算到显示段落上（显示段落是渲染
    单位：只要被高亮区盖住就整段高亮）。开标记之后进入高亮区，成对的收标记
    退出；**未闭合的开标记一直作用到逻辑段落末尾**——作者只写一次也能整段
    高亮，模型漏写收尾标记时也不会白写。文本里没有标记时掩码全为 ``False``。
    """
    if not text:
        return text or "", []
    if HIGHLIGHT_MARK not in text:
        return text, [False] * len(text)
    clean = []
    mask = []
    highlighted = False
    index = 0
    length = len(text)
    while index < length:
        if text.startswith(HIGHLIGHT_MARK, index):
            highlighted = not highlighted
            index += len(HIGHLIGHT_MARK)
            continue
        clean.append(text[index])
        mask.append(highlighted)
        index += 1
    return "".join(clean), mask


def strip_highlight_markers(text: str) -> str:
    """剥离正文中全部高亮标记（落盘 / 概要 / 对话历史用的净文本）。"""
    if not text:
        return text
    return text.replace(HIGHLIGHT_MARK, "")


def strip_display_markers(text: str) -> str:
    """剥离全部显示层标记（说话人 + 高亮），返回可直接落盘的净文本。"""
    return strip_highlight_markers(strip_speaker_markers(text))


def _project_display(text: str) -> tuple:
    """把正文投影为显示字符流，返回 ``(显示文本, 源下标, 每字说话人, 台词收尾位置)``。

    ``@说话人@`` 紧跟开引号构成台词块：标记与首尾引号不进显示，块内每个字符
    都带上该说话人，供切分后每段继承；闭引号位置作为**显式断点**（不受最小
    长度限制），短台词才不会被后文吞并。其余 ``@说话人@`` 原样保留，由段首
    解析（正文中间的标记因此不会被误读）；强调引号按普通正文保留。
    """
    chars = []
    src = []
    speakers = []
    ends = set()
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "@":
            match = _SPEAKER_MARKER_RE.match(text, i)
            if match and match.end() < n and text[match.end()] in _OPEN_QUOTES:
                speaker = match.group(1)
                open_char = text[match.end()]
                close_char = _QUOTE_PAIR.get(open_char, open_char)
                j = match.end() + 1
                nest = 1
                closed = False
                while j < n and nest:
                    char = text[j]
                    if char == close_char:
                        nest -= 1
                        if nest == 0:
                            j += 1
                            # 台词收尾：吞掉紧随的句末标点（引号内已有句读）
                            while j < n and text[j] in _END_PUNCT:
                                j += 1
                            ends.add(len(chars))
                            closed = True
                            break
                    elif char == open_char:
                        nest += 1
                    chars.append(char)
                    src.append(j)
                    speakers.append(speaker)
                    j += 1
                if closed:
                    i = j
                    continue
                # 未闭合（流式半截）：整段作为台词尾部，speaker 已打在字符上
                i = j
                continue
        chars.append(text[i])
        src.append(i)
        speakers.append(None)
        i += 1
    return "".join(chars), src, speakers, ends


def split_stream_units(text: str):
    """把（部分）正文切成 ``(完整单元列表, 未完结尾部)``。

    单元与结尾部都是 :class:`DisplayUnit`；结尾部是未完结句，``speaker`` 取自
    起点的完整标记或台词块（半截标记按显示提示被抑制）。纯函数：对同一文本
    重复调用结果一致，流式过程中每收到新数据整体重算。
    """
    units = []
    clean_text, mask = scan_highlight_markers(text)
    display, src, unit_speakers, dialogue_ends = _project_display(clean_text)
    n = len(display)
    seg_start = 0

    def highlighted(start: int, end: int) -> bool:
        """该段被高亮区盖住（显示段落是渲染单位，沾一点就整段高亮）。"""
        if end <= start:
            return False
        return any(mask[src[start]:src[end - 1] + 1])

    def trim(a: int, b: int) -> tuple:
        while a < b and display[a].isspace():
            a += 1
        while b > a and display[b - 1].isspace():
            b -= 1
        return a, b

    def try_flush(end: int, min_chars: int) -> bool:
        nonlocal seg_start
        a, b = trim(seg_start, end)
        if a >= b:
            seg_start = end
            return False
        raw = display[a:b]
        speaker, body = _split_leading_marker(raw)
        # 标记被剥离后正文起点右移，说话人从正文首字取（台词块继承）
        body_pos = a + (len(raw) - len(body))
        if speaker is None and body_pos < b:
            speaker = unit_speakers[body_pos]
        # 台词块内「内部可以断」，短句也独立成段；叙述仍按最小长度防碎片
        in_dialogue = body_pos < b and unit_speakers[body_pos] is not None
        limit = 1 if in_dialogue else min_chars
        if len(body) < limit:
            return False
        unit = _normalize_unit_end(body)
        if unit:
            units.append(DisplayUnit(speaker=speaker, text=unit,
                                     highlight=highlighted(body_pos, b)))
        seg_start = end
        return True

    i = 0
    while i < n:
        if i in dialogue_ends:
            # 台词闭合是作者显式边界，短台词也独立成段并保留说话人
            try_flush(i, 1)
            dialogue_ends.discard(i)
            continue
        ch = display[i]
        if ch == "\n":
            # 换行是作者/AI 显式分段，不受最小长度限制
            try_flush(i, 1)
            i += 1
            continue
        if ch in _END_PUNCT:
            j = i + 1
            while j < n and display[j] in _END_PUNCT:
                j += 1
            # 句中省略号（后面紧接正文）不断句
            if ch == "…" and j < n and not display[j].isspace() and display[j] != "\n":
                i = j
                continue
            if try_flush(j, _MIN_UNIT_CHARS):
                i = j
                continue
            i += 1
            continue
        if ch in "；;":
            if try_flush(i + 1, _MIN_UNIT_CHARS):
                i += 1
                continue
        # 破折号与引号都不再是断点：破折号留在正文，引号按强调引号保留显示
        i += 1

    a, b = trim(seg_start, n)
    tail_speaker, tail_text = None, ""
    if a < b:
        raw = display[a:b]
        lead_speaker, body = _resolve_stream_tail(raw)
        body_pos = a + (len(raw) - len(body))
        if lead_speaker is not None:
            tail_speaker = lead_speaker
        elif body_pos < b:
            tail_speaker = unit_speakers[body_pos]
        tail_text = body
    tail = DisplayUnit(speaker=tail_speaker, text=tail_text,
                       highlight=bool(tail_text) and highlighted(a, b))
    return units, tail


def split_full_text(text: str) -> list:
    """完整正文的最终切分：无结尾断点的尾部作为最后一个显示段落。

    返回 :class:`DisplayUnit` 列表；若尾部起点是未闭合标记则原样保留
    （落盘前的净化见 :func:`strip_display_markers`）。
    """
    if not text:
        return []
    units, tail = split_stream_units(text)
    if tail.text:
        units.append(DisplayUnit(
            speaker=tail.speaker,
            text=_normalize_unit_end(tail.text) or tail.text,
            highlight=tail.highlight))
    return [u for u in units if u.text]
