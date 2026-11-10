"""回放记录的语法：分类、归一与容错解析（纯领域层：无 IO / UI / AI）。

回放文件是一串记录，四种形态（写在哪见 ``docs/designs/dungeon/script.md`` §9.3）：

- **步进**（无 ``kind``）：一个逻辑段落的正文与它前后的状态快照；
- ``kind:"chapter"``：进入章节，带当时的环境（背景 / 音乐 / 语音效果）；
- ``kind:"trigger"``：触发器动作，分支动作额外带选择结果 / 小游戏返回值；
- ``kind:"characters"``：文件头部的人物账本快照（不参与步进）；
- ``kind:"ending"``：结局正文（结束章节走完后的收尾记录）。

读取方只吃本模块产出的 Record，不再各自 ``dict.get``。三条约定：

1. **内嵌配置一律复用配置侧的归一器**（``normalize_bgm`` / ``normalize_voice_fx`` /
   ``normalize_action_type``）：记录里存的是当时的环境，重新拼成配置时必须与编辑器
   写出的同形，否则「回放→配置」的回溯改写会产出另一种合法但走样的配置。
2. **容错是这里的事**：缺键给默认、类型不符给默认、整条坏记录返回 ``None`` 由调用方
   跳过。一条坏记录不该让整段回放卡死在半路。
3. **不猜**：字段缺失与「显式空值」区分开（``custom_after`` 缺失 = 不改状态，
   空字典 = 状态确实为空），显示前缀缺失时按类型现算，但记录的 ``type_prefix``
   （含空串「本段不显示前缀」）优先。
"""

from dataclasses import dataclass

from dungeon.actions import normalize_action_type
from dungeon.audio.chapters import normalize_bgm
from dungeon.audio.voice_fx import normalize_voice_fx
from dungeon.models import (PREFIX_ENDING, DungeonTextType)

#: 步进记录（无 kind）。
KIND_STEP = "step"
KIND_CHAPTER = "chapter"
KIND_TRIGGER = "trigger"
#: 人物账本快照；盘上沿用历史字面值 "characters"（旧回放文件不迁移）
KIND_CHARACTERS = "characters"
KIND_ENDING = "ending"

_KINDS = (KIND_CHAPTER, KIND_TRIGGER, KIND_CHARACTERS, KIND_ENDING)
_TEXT_TYPES = {text_type.value: text_type for text_type in DungeonTextType}


# ---------------- Record ----------------

@dataclass(frozen=True)
class StepRecord:
    """一个逻辑段落的回放记录。

    ``*_before`` 供回放起始状态还原，``*_after`` 为 ``None`` 表示该维度当时没有
    快照（旧记录），回放保持当前值不动。
    """

    step: int
    text_type: DungeonTextType
    text: str
    prefix: str
    highlight: bool
    ending_chapter: bool
    intrusion_before: float
    destruction_before: float
    depth_intrusion_before: float | None
    depth_destruction_before: float | None
    custom_before: dict
    intrusion_after: float | None
    destruction_after: float | None
    depth_intrusion_after: float | None
    depth_destruction_after: float | None
    custom_after: dict | None
    total_casualties_after: float | None
    casualty_increase: float


@dataclass(frozen=True)
class ChapterRecord:
    """进入章节：环境一律取自记录，不依赖当前加载的方案。"""

    name: str
    step: int
    background: dict
    bgm: dict
    voice_fx: dict


@dataclass(frozen=True)
class TriggerRecord:
    """触发器动作。``action_type`` 已归一（旧记录的类型可能只写在 action_data 里）。"""

    name: str
    action_type: str
    action_data: dict
    step: int
    chapter_background: dict
    chapter_bgm: dict
    chapter_voice_fx: dict
    choice_index: int | None
    choice_text: str
    option_prompt: str
    choice_value: int | None
    game_result: dict
    ending_text: str


@dataclass(frozen=True)
class CharactersRecord:
    """文件头部的人物账本快照（回放时整本还原，不参与步进）。"""

    snapshot: dict


@dataclass(frozen=True)
class EndingRecord:
    """结局正文与结局图标（回放到此为止）。"""

    name: str
    text: str
    icon_path: str
    step: int


# ---------------- 容错取数 ----------------

def _number(value, default=None):
    """数字转换；bool / 非数字 / NaN / inf 一律按缺省（bool 当 1 用是笔误来源）。"""
    if value is None or isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result != result or result in (float("inf"), float("-inf")):
        return default
    return result


def _whole(value, default=0):
    number = _number(value)
    return default if number is None else int(number)


def _optional_whole(value):
    number = _number(value)
    return None if number is None else int(number)


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _mapping(value) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _attributes(value):
    """自定义属性表：只留下能当数字用的项（脏值丢掉，不让回放中途炸）。"""
    result = {}
    for key, item in _mapping(value).items():
        number = _number(item)
        if number is not None:
            result[str(key)] = number
    return result


def _text_type(value) -> DungeonTextType:
    """记录里的段落类型；未知 / 缺失回退「环境」（旧文件里出现过已删类型）。"""
    if isinstance(value, DungeonTextType):
        return value
    return _TEXT_TYPES.get(str(value or "").strip().lower(),
                           DungeonTextType.BACKGROUND)


def _prefix(raw: dict, text_type: DungeonTextType, ending_chapter: bool) -> str:
    """显示前缀：记录里写了就用它（空串 = 本段不显示前缀），否则按类型现算。"""
    prefix = raw.get("type_prefix")
    if isinstance(prefix, str):
        return prefix
    if ending_chapter:
        return PREFIX_ENDING
    return text_type.display_prefix


# ---------------- 各形态 ----------------

def _parse_step(raw: dict) -> StepRecord:
    text_type = _text_type(raw.get("type"))
    text = _text(raw.get("text"))
    if not text.strip():
        # 没有正文的步进记录无处可显示（实时不会写出这种记录）：整条丢掉，
        # 否则回放会空耗一次点击，看起来像卡住
        return None
    ending_chapter = bool(raw.get("ending_chapter"))
    intrusion_after = _number(raw.get("intrusion_after"))
    destruction_after = _number(raw.get("destruction_after"))
    return StepRecord(
        step=_whole(raw.get("step")),
        text_type=text_type,
        text=text,
        prefix=_prefix(raw, text_type, ending_chapter),
        highlight=bool(raw.get("highlight")),
        ending_chapter=ending_chapter,
        # 起始状态：缺 before 时退到 after，再退到 0（脏记录也能起播）
        intrusion_before=_number(raw.get("intrusion_before"),
                                 intrusion_after if intrusion_after is not None else 0.0),
        destruction_before=_number(raw.get("destruction_before"),
                                   destruction_after if destruction_after is not None else 0.0),
        depth_intrusion_before=_number(raw.get("depth_intrusion_before")),
        depth_destruction_before=_number(raw.get("depth_destruction_before")),
        custom_before=_attributes(raw.get("custom_before")),
        intrusion_after=intrusion_after,
        destruction_after=destruction_after,
        depth_intrusion_after=_number(raw.get("depth_intrusion_after")),
        depth_destruction_after=_number(raw.get("depth_destruction_after")),
        custom_after=(_attributes(raw["custom_after"])
                      if "custom_after" in raw else None),
        total_casualties_after=_number(raw.get("total_casualties_after")),
        casualty_increase=_number(raw.get("casualty_increase"), 0.0),
    )


def _parse_chapter(raw: dict) -> ChapterRecord:
    return ChapterRecord(
        name=_text(raw.get("name")),
        step=_whole(raw.get("step")),
        background=_mapping(raw.get("background")),
        bgm=normalize_bgm(raw.get("bgm")),
        voice_fx=normalize_voice_fx(raw.get("voice_fx")),
    )


def _parse_trigger(raw: dict) -> TriggerRecord:
    action_data = _mapping(raw.get("action_data"))
    # 旧记录可能只把动作类型写在 action_data["type"] 里
    action_type = normalize_action_type(raw.get("action_type"), action_data)
    result = raw.get("game_result")
    return TriggerRecord(
        name=_text(raw.get("name")),
        action_type=str(action_type or "none").strip(),
        action_data=action_data,
        step=_whole(raw.get("step")),
        chapter_background=_mapping(raw.get("chapter_background")),
        chapter_bgm=normalize_bgm(raw.get("chapter_bgm")),
        chapter_voice_fx=normalize_voice_fx(raw.get("chapter_voice_fx")),
        choice_index=_optional_whole(raw.get("choice_index")),
        choice_text=_text(raw.get("choice_text")),
        option_prompt=_text(raw.get("option_prompt")),
        choice_value=_optional_whole(raw.get("choice_value")),
        game_result=(dict(result) if isinstance(result, dict)
                     else ({} if result is None else {"value": result})),
        ending_text=_text(raw.get("ending_text")),
    )


def _parse_characters(raw: dict) -> CharactersRecord:
    return CharactersRecord(snapshot=_mapping(raw.get("snapshot")))


def _parse_ending(raw: dict) -> EndingRecord:
    name = _text(raw.get("name"))
    return EndingRecord(
        name=name,
        text=_text(raw.get("text")) or (f"结局：{name}" if name else ""),
        icon_path=_text(raw.get("icon_path")),
        step=_whole(raw.get("step")),
    )


_PARSERS = {
    KIND_STEP: _parse_step,
    KIND_CHAPTER: _parse_chapter,
    KIND_TRIGGER: _parse_trigger,
    KIND_CHARACTERS: _parse_characters,
    KIND_ENDING: _parse_ending,
}


# ---------------- 入口 ----------------

def classify(raw) -> str:
    """记录形态；无法识别返回空串（未知 kind / 不是字典）。"""
    if not isinstance(raw, dict):
        return ""
    kind = raw.get("kind")
    if kind is None or kind == "":
        return KIND_STEP
    kind = str(kind).strip()
    return kind if kind in _KINDS else ""


def parse(raw):
    """单条记录 → Record；坏记录返回 ``None``（调用方跳过，不中断回放）。"""
    kind = classify(raw)
    if not kind:
        return None
    return _PARSERS[kind](raw)


def parse_all(raws) -> list:
    """整份回放 → Record 列表（逐条容错，坏记录直接丢弃）。"""
    if not isinstance(raws, (list, tuple)):
        return []
    records = []
    for raw in raws:
        record = parse(raw)
        if record is not None:
            records.append(record)
    return records
