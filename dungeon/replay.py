"""回放记录的语法：分类、归一与容错解析（纯领域层：无 IO / UI / AI）。

回放文件是一串记录，几种形态（写在哪见 ``docs/designs/dungeon/script.md`` §9.3）：

- **步进**（无 ``kind``）：一个逻辑段落的正文与它前后的状态快照；正文存净文本，
  原文带显示层标记时另存 ``display_text``（回放要靠它还原说话人与高亮）；
- ``kind:"chapter"``：进入章节，带当时的环境（背景 / 音乐 / 语音效果）；
- ``kind:"trigger"``：触发器动作，分支动作额外带选择结果 / 小游戏返回值；
- ``kind:"characters"``：文件头部的人物账本快照（不参与步进）；
- ``kind:"ending"``：结局正文（结束章节走完后的收尾记录）；
- ``kind:"meta"``：回放身份（所属方案 / 版本 / 用到的素材），同样不参与步进。

读取方只吃本模块产出的 Record，不再各自 ``dict.get``。三条约定：

1. **内嵌配置一律复用配置侧的归一器**（``normalize_bgm`` / ``normalize_voice_fx`` /
   ``trigger_action_type``）：记录里存的是当时的环境，重新拼成配置时必须与编辑器
   写出的同形，否则「回放→配置」的回溯改写会产出另一种合法但走样的配置。
2. **容错是这里的事**：缺键给默认、类型不符给默认、整条坏记录返回 ``None`` 由调用方
   跳过。一条坏记录不该让整段回放卡死在半路。
3. **不猜**：字段缺失与「显式空值」区分开（``custom_after`` 缺失 = 不改状态，
   空字典 = 状态确实为空），显示前缀缺失时按类型现算，但记录的 ``type_prefix``
   （含空串「本段不显示前缀」）优先。

同一份语法也负责写：:func:`to_config_fragment` 把章节 / 触发器记录还原成配置
片段，供「回放 → 配置」的回溯改写使用；:func:`meta_record` 产出回放身份记录。
读入口径统一在 :func:`parse_all`（旧格式的 ``goto`` 记录会被展开成章节进入记录）。
"""

import os
from dataclasses import dataclass

from dungeon.actions import trigger_action_type
from dungeon.audio.chapters import normalize_background, normalize_bgm
from dungeon.audio.voice_fx import normalize_voice_fx
from dungeon.models import (PREFIX_ENDING, DungeonTextType)
from dungeon.splitter import strip_display_markers

#: 步进记录（无 kind）。
KIND_STEP = "step"
KIND_CHAPTER = "chapter"
KIND_TRIGGER = "trigger"
#: 人物账本快照；盘上沿用历史字面值 "characters"（旧回放文件不迁移）
KIND_CHARACTERS = "characters"
KIND_ENDING = "ending"
#: 回放身份（所属方案），见 :class:`ScenarioRecord`
KIND_META = "meta"

_KINDS = (KIND_CHAPTER, KIND_TRIGGER, KIND_CHARACTERS, KIND_ENDING, KIND_META)
_TEXT_TYPES = {text_type.value: text_type for text_type in DungeonTextType}

#: 身份记录的语法版本（写法变了才加，读取侧据此决定怎么解释）
META_VERSION = 1

#: 素材路径的采集上限（反查所属方案与写入 meta.assets 同源，取同一个数）
MATERIAL_PATH_LIMIT = 8


# ---------------- Record ----------------

@dataclass(frozen=True)
class StepRecord:
    """一个逻辑段落的回放记录。

    ``*_before`` 供回放起始状态还原，``*_after`` 为 ``None`` 表示该维度当时没有
    快照（旧记录），回放保持当前值不动。

    ``text`` 是剥离显示层标记的净文本（落盘 / 概要 / 对话历史一律用它）。
    ``display_text`` 只在原文带 ``@说话人@`` / ``==`` 时才写，供回放重新切出
    显示段落——说话人决定这一句念不念、念谁的声音，净文本里没有。
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
    #: 带显示层标记的原文；空串 = 与 ``text`` 相同（旧记录一律如此）
    display_text: str = ""


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


@dataclass(frozen=True)
class ScenarioRecord:
    """回放身份：这份回放属于哪个方案、当时的版本、用到了哪些素材。

    只记身份，不记素材清单的副本——背景 / 音乐 / 图标仍然只有记录里那一份，
    这里只多一个「这些路径在当时有多大」，用来发现同名文件被重新导入
    （路径还在、内容已换，是唯一不能靠存在性发现的失效）。``content_hash``
    是整方案摘要，只回答「是不是同一版方案」。
    """

    scenario_id: str
    content_hash: str
    version_tag: str
    app: str
    saved_at: str
    #: ``({"path", "size"}, …)``；``size`` 为 ``None`` 表示记录里没写
    assets: tuple


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
    # 带标记的原文只在「剥完标记正好是本段净文本」时采信：对不上说明记录被改过，
    # 按净文本播比播一段与实际内容不符的文本安全
    display_text = _text(raw.get("display_text"))
    if display_text and strip_display_markers(display_text) != text:
        display_text = ""
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
        display_text=display_text,
    )


def _parse_chapter(raw: dict) -> ChapterRecord:
    return ChapterRecord(
        name=_text(raw.get("name")),
        step=_whole(raw.get("step")),
        background=normalize_background(raw.get("background")),
        bgm=normalize_bgm(raw.get("bgm")),
        voice_fx=normalize_voice_fx(raw.get("voice_fx")),
    )


def _parse_trigger(raw: dict) -> TriggerRecord:
    action_data = _mapping(raw.get("action_data"))
    # 与配置侧同一个读法：旧记录可能把动作类型写在 action 或 action_data["type"] 里
    action_type = trigger_action_type(raw)
    result = raw.get("game_result")
    return TriggerRecord(
        name=_text(raw.get("name")),
        action_type=str(action_type or "none").strip(),
        action_data=action_data,
        step=_whole(raw.get("step")),
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


def _assets(value) -> tuple:
    """素材清单：只留路径非空的条目，超出上限的部分丢掉（写侧同样限这么多）。"""
    if not isinstance(value, (list, tuple)):
        return ()
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        path = _text(item.get("path")).strip().lstrip("/\\")
        if not path:
            continue
        result.append({"path": path, "size": _optional_whole(item.get("size"))})
        if len(result) >= MATERIAL_PATH_LIMIT:
            break
    return tuple(result)


def _parse_meta(raw: dict) -> ScenarioRecord:
    scenario = _mapping(raw.get("scenario"))
    return ScenarioRecord(
        scenario_id=_text(scenario.get("id")).strip(),
        content_hash=_text(scenario.get("content_hash")),
        version_tag=_text(scenario.get("version_tag")),
        app=_text(raw.get("app")),
        saved_at=_text(raw.get("saved_at")),
        assets=_assets(scenario.get("assets")),
    )


_PARSERS = {
    KIND_STEP: _parse_step,
    KIND_CHAPTER: _parse_chapter,
    KIND_TRIGGER: _parse_trigger,
    KIND_CHARACTERS: _parse_characters,
    KIND_ENDING: _parse_ending,
    KIND_META: _parse_meta,
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


#: 旧记录把跳转目标章节的环境塞在 ``goto`` 触发器记录的三个平级键里，
#: 与 ``kind:"chapter"`` 是同一事件的两套写法；读入时统一展开成章节记录。
_LEGACY_ENV_KEYS = ("chapter_background", "chapter_bgm", "chapter_voice_fx")


def _expand(raw, record) -> list:
    """一条记录 → 一串 Record（旧格式的 ``goto`` 拆成「章节进入 + 触发器」两条）。"""
    if not isinstance(record, TriggerRecord) or record.action_type != "goto":
        return [record]
    if not any(key in raw for key in _LEGACY_ENV_KEYS):
        return [record]
    return [
        ChapterRecord(
            name=str(record.action_data.get("chapter") or "").strip(),
            step=record.step,
            background=normalize_background(raw.get("chapter_background")),
            bgm=normalize_bgm(raw.get("chapter_bgm")),
            voice_fx=normalize_voice_fx(raw.get("chapter_voice_fx")),
        ),
        record,
    ]


def parse_all(raws, on_drop=None) -> list:
    """整份回放 → Record 列表（逐条容错，坏记录直接丢弃）。

    ``on_drop`` 可选，收到每一条无法解析的原始记录（调用方用来记日志）。

    旧格式在这里收敛：``goto`` 触发器记录曾把目标章节的 ``background`` /
    ``bgm`` / ``voice_fx`` 写在三个平级键上，现在一律展开成一条
    :class:`ChapterRecord` 加原来的 :class:`TriggerRecord`，读取方只认一种形态。
    """
    if not isinstance(raws, (list, tuple)):
        return []
    records = []
    for raw in raws:
        record = parse(raw)
        if record is None:
            if on_drop is not None:
                on_drop(raw)
            continue
        records.extend(_expand(raw, record))
    return records


# ---------------- 素材路径（身份与反查同源） ----------------

def material_paths(records, limit: int = MATERIAL_PATH_LIMIT) -> list:
    """记录里引用的方案素材相对路径（去重保序，最多 ``limit`` 条）。

    回放里真正来自方案文件的只有三处：章节背景 / 音乐、结局图标、旧版 ``ending``
    动作的图标。绝对路径不参与（它本来就不依赖方案目录）。写入侧的
    ``meta.assets`` 与读取侧的方案反查都从这里取，两边不会各列一份。
    """
    paths = []
    for record in records:
        if isinstance(record, ChapterRecord):
            candidates = ((record.background or {}).get("image_path"),
                          (record.bgm or {}).get("path"))
        elif isinstance(record, EndingRecord):
            candidates = (record.icon_path,)
        elif isinstance(record, TriggerRecord) and record.action_type == "ending":
            candidates = (record.action_data.get("icon_path"),)
        else:
            continue
        for candidate in candidates:
            path = str(candidate or "").strip().lstrip("/\\")
            if not path or os.path.isabs(path) or path in paths:
                continue
            paths.append(path)
            if len(paths) >= limit:
                return paths
    return paths


# ---------------- 反向：记录 → 配置片段 ----------------

def _chapter_fragment(record: ChapterRecord) -> dict:
    fragment = {"name": record.name} if record.name else {}
    # 没配的维度不写空字典（与配置侧「没配就不摊默认值」同一套约定）
    for key in ("background", "bgm", "voice_fx"):
        value = getattr(record, key)
        if value:
            fragment[key] = dict(value)
    return fragment


def _trigger_fragment(record: TriggerRecord) -> dict:
    # 只写规范键：``action`` 已由 scenario_repo._migrate 单向并入 ``action_type``，
    # 同一语义不再写两份（见 docs/designs/dungeon/script.md §4）
    return {
        "name": record.name,
        "action_type": record.action_type,
        "action_data": dict(record.action_data),
    }


def to_config_fragment(record):
    """Record → 配置侧的片段；没有配置对应物的记录返回 ``None``。

    「回放 → 配置」的回溯改写走这里：章节记录还原成 ``{name, background, bgm,
    voice_fx}``，触发器记录还原成 ``{name, action_type, action_data}``，两者的
    内嵌配置都已经是归一后的形态，并回方案配置后与编辑器写出的同形。

    步进记录是正文（配置里没有对应字段），账本快照是当时的运行态（不是方案
    的人物表），结局正文是生成结果（配置里只有 ``icon_path`` 这类章节字段，
    无法确定归属章节），身份记录说的是「这份文件属于哪个目录」：这四种返回
    ``None``。
    """
    if isinstance(record, ChapterRecord):
        return _chapter_fragment(record)
    if isinstance(record, TriggerRecord):
        return _trigger_fragment(record)
    return None


# ---------------- 正向：步进记录字段 ----------------

def display_text_field(raw: str) -> str:
    """写侧：步进记录的 ``display_text`` 值。

    原文不带显示层标记（没有说话人也没有高亮）时返回空串，调用方据此不写这个
    字段——绝大多数段落都是这样，回放文件因此不会整体翻倍。
    """
    text = raw if isinstance(raw, str) else ""
    return text if strip_display_markers(text) != text else ""


# ---------------- 正向：身份记录 ----------------

def meta_record(*, scenario=None, app: str = "", saved_at: str = "") -> dict:
    """回放身份记录（:data:`KIND_META`）。

    ``scenario`` 认 ``id`` / ``content_hash`` / ``version_tag`` / ``assets``，
    与读取侧的 :class:`ScenarioRecord` 一一对应：没值的键不写（空串与
    「不知道」是两回事，不在这里混）。``assets`` 超过
    :data:`MATERIAL_PATH_LIMIT` 条的部分丢掉——它只用于发现同名素材被替换，
    不是素材清单的副本。
    """
    source = dict(scenario or {})
    payload = {}
    scenario_id = _text(source.get("id")).strip()
    if scenario_id:
        payload["id"] = scenario_id
    for key in ("content_hash", "version_tag"):
        value = _text(source.get(key)).strip()
        if value:
            payload[key] = value
    assets = _assets(source.get("assets"))
    if assets:
        payload["assets"] = [dict(item) for item in assets]
    record = {"kind": KIND_META, "version": META_VERSION}
    if payload:
        record["scenario"] = payload
    if app:
        record["app"] = app
    if saved_at:
        record["saved_at"] = saved_at
    return record
