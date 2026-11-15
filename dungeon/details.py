"""细节探究：AI 在后台提出「对象 + 方面」的查询，下次生成前检索参考。

流式输出完成后（``engine._generate_next_text`` 尾部），立即用刚生成的
段落、长期概要与章节意图组装提问，后台线程询问 AI 还想了解哪些会影响
后续走向的线索（最多 2 组）。方面取自本模块的白名单，对象必须逐字来自
提问时给 AI 的文本。下一次生成前，``build_turn`` 用对象在回放与长期记忆
里召回、用方面信号词排序，把「原文参考 / 仅提及 / 未记载」三档结果注入
提示词。``commit_turn`` 在回合成功后消费这一批查询，来源步不匹配的
过期查询直接丢弃。
"""

import json
import math
import re
from dataclasses import dataclass
from typing import NamedTuple

from .cast import clean_name

MAX_QUERIES = 2
QUERY_CHARS = 30
OBJECT_CHARS = 12
MATCH_CLIP_CHARS = 120
DETAIL_MEMORY_CHARS = 2000
# 二元组含这些字时区分度过低，不作为检索关键词（旧格式降级路径用）
_STOP_CHARS = "的了是在吗呢吧么啊"
# 疑问词/泛词几乎每段都有，会把真正的主体词稀释掉
_STOP_WORDS = {"什么", "为什", "怎么", "多少", "哪里", "哪个", "如何",
               "是否", "为何", "么会", "么样", "这个", "那个", "一下"}
#: 不能充当检索对象的代词与泛词
_PRONOUN_OBJECTS = {"她", "他", "它", "自己", "主角", "这个", "那个",
                    "这里", "那里", "人们", "众人", "大家", "所有人",
                    "东西", "事情", "对方", "他们", "她们", "它们"}
#: 单字虚词与泛词，不能充当检索对象
_STOP_SINGLE = set("的了是在吗呢吧啊和与对把被从向在为有这那其之者也")
#: 角色抽取搭车：不增加调用次数，只扩展同一次细节提问的返回格式
CHARACTER_UPDATE_HINT = (
    "另外，如果本段出现了值得继续追踪的角色，把它们放进 characters 数组："
    '[{"handle": "正文里实际出现的称呼", "true_name": "", "pronoun": "他/她/空", '
    '"traits": ["特征", "近况"], "relation": "与她的关系", '
    '"status": "temporary"}]。真名尚未揭示时 true_name 留空；正文明确揭示真名时'
    ' status 写 "revealed" 并填 true_name。没有可登记的角色就输出空数组。'
)
#: 角色抽取的有界字段（与 CharacterLedger 的上限保持一致）
CHARACTER_HANDLE_CHARS = 16
CHARACTER_TRAIT_CHARS = 40
CHARACTER_RELATION_CHARS = 60
MAX_CHARACTER_TRAITS = 4


@dataclass(frozen=True)
class AspectSpec:
    """一个方面的检索偏好：信号词、长期记忆偏置、时间偏好与补写许可。"""

    signals: tuple = ()
    memory_bias: float = 0.0
    recency: float = 0.5
    allow_invent: bool = True


#: 三档耦合等级共用的方面白名单。提示词、解析校验与检索打分都读这一张表。
ASPECTS = {
    "目的": AspectSpec(("为了", "打算", "意在", "准备", "要求", "目标", "想要", "好让"),
                       0.0, 0.6),
    "后果": AspectSpec(("于是", "因此", "结果", "导致", "从此", "没能", "留下",
                        "再也", "造成", "代价"), 0.0, 0.8),
    "背景": AspectSpec(("原来", "原是", "曾是", "此前", "当初", "曾经",
                        "自那以后", "身世", "来历", "早在", "当时", "约定"),
                       1.5, -0.6),
    "形态": AspectSpec(("看上去", "显得", "像是", "约莫", "足有", "轮廓",
                        "泛着", "垂下", "遮住"), 0.0, 0.7, False),
    "关系": AspectSpec(("信任", "害怕", "怨恨", "答应", "并肩", "疏远",
                        "对她", "对他", "关系", "态度"), 0.5, 0.4),
    "位置": AspectSpec(("朝", "向", "往", "抵达", "离开", "回到", "位于",
                        "远处", "身后", "脚下"), 0.0, 0.6),
    "进展": AspectSpec(("已经", "还没", "正在", "下一步", "仍未", "终于",
                        "刚刚", "接着"), 1.0, 0.7),
    "条件": AspectSpec(("无法", "只能", "除非", "必须先", "碍于", "缺少",
                        "来不及", "受阻"), 0.5, 0.6),
}


class DetailQuery(NamedTuple):
    """一组结构化查询。``aspect`` 为空串表示模型给了白名单外的值。"""

    object: str
    aspect: str


class DetailMatch(NamedTuple):
    """一条查询结果：可注入标签、命中原文、判定档位。"""

    label: str
    text: str
    state: str  # answered / mentioned / missing


def _clip(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def _clip_block(text, limit):
    """保留首尾的块状文本截断（长期记忆按时间顺序，去尾会丢掉最近状态）。"""
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    half = max(1, limit // 2)
    return text[:half] + "\n…\n" + text[-half:]


def aspect_names() -> str:
    """白名单的可注入写法（提示词与校验共用）。"""
    return "、".join(ASPECTS)


def format_detail_label(query) -> str:
    """把查询转成提示词里可读的标签；旧字符串查询原样返回。"""
    if isinstance(query, DetailQuery):
        return (f"【{query.object}】的【{query.aspect}】" if query.aspect
                else f"【{query.object}】")
    return str(query)


def build_detail_query_prompt(paragraph_text, recent_texts=(), chapter_name="",
                              coupling_level=None, memory_block="", chapter_note=""):
    """组装细节提问调用：刚生成的段落 + 近期上下文 + 长期记忆。

    提问的系统提示按耦合等级取用：Velum 收集叙事线索、Solea 收集任务缺口、
    Bulla 收集她的动机与关系变化。方面白名单与输出格式统一写在用户提示里，
    避免三档系统提示各维护一份字段约定。
    """
    from .coupling import coupling_prompts, normalize_coupling_level
    pack = coupling_prompts(normalize_coupling_level(coupling_level))
    lines = []
    if chapter_name:
        note = str(chapter_note or "").strip()
        lines.append(f"当前章节：{chapter_name}" + (f"（{note}）" if note else ""))
    memory = _clip_block(memory_block, DETAIL_MEMORY_CHARS)
    if memory:
        lines.append("长期记忆：")
        lines.append(memory)
    recent = [str(t) for t in recent_texts if t][-3:]
    if recent:
        lines.append("近期剧情：")
        lines.extend(f"- {_clip(t, 100)}" for t in recent)
    lines.append("刚生成的段落：")
    lines.append(_clip(paragraph_text, 200))
    lines.append("请只提出真正会影响后续多段或跨章节走向、且正文尚未交代清楚的线索；"
                 "不要问刚刚写明的信息，也不要把问题问成对具体物件或路人的考据。")
    lines.append(f"每条线索写成「对象 + 方面」，最多 {MAX_QUERIES} 组。"
                 f"方面只能从这个白名单里选：{aspect_names()}。"
                 f"对象必须是上面文本里逐字出现过的实体或称呼（1-{OBJECT_CHARS} 字），"
                 "不要写代词、问句或自造词。")
    lines.append('只输出 JSON：{"queries": [{"object": "撤离令", "aspect": "背景"}]}；'
                 '没有需要追踪的线索就输出 {"queries": []}。不要解释。')
    lines.append(CHARACTER_UPDATE_HINT)
    return [
        {"role": "system", "content": pack["detail_system"]},
        {"role": "user", "content": "\n".join(lines)},
    ]


def _json_object(raw):
    """取返回文本里的第一个 JSON 对象；不是 JSON 时返回 ``None``。"""
    raw = str(raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").lstrip("json").strip()
    start = raw.find("{")
    if start == -1:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _clean_object(value) -> str:
    """清洗对象字段：去空白、说话人标记与句读，限长但不加省略号。"""
    text = " ".join(str(value or "").split()).strip().strip("@＠")
    text = re.sub(r"[?？!！。，,、；;：:…\"'“”‘’（）()【】\[\]]", "", text)
    return text[:OBJECT_CHARS]


def _object_in_corpus(obj, corpus) -> bool:
    """对象是否逐字出现在提问时给 AI 的文本里（忽略说话人标记）。"""
    if not isinstance(corpus, str):
        corpus = "\n".join(str(x) for x in corpus or ())
    return obj in corpus or obj in corpus.replace("@", "")


def parse_detail_queries(raw, corpus="") -> list:
    """解析提问调用的返回：结构化查询用 ``DetailQuery``，旧格式保留字符串。

    ``corpus`` 是提问时给模型的文本；结构化查询的对象必须逐字出现在其中，
    否则丢弃。字符串项与非 JSON 行按旧格式保留，由检索侧走兼容路径。
    """
    data = _json_object(raw)
    if data is None:
        return _clean_queries(str(raw or "").strip().splitlines(), corpus)
    items = data.get("queries")
    return _clean_queries(items, corpus) if isinstance(items, list) else []


def _clean_queries(items, corpus="") -> list:
    out, seen = [], set()
    for item in items:
        if isinstance(item, dict):
            obj = _clean_object(item.get("object"))
            aspect = str(item.get("aspect") or "").strip()
            if (not obj or obj in _PRONOUN_OBJECTS or obj in _STOP_SINGLE
                    or (corpus and not _object_in_corpus(obj, corpus))):
                continue
            query = DetailQuery(obj, aspect if aspect in ASPECTS else "")
            key = (query.object, query.aspect)
        else:
            query = _clip(item, QUERY_CHARS)
            query = re.sub(r"^[\d]+[.、)）]\s*", "", query).strip("-• ")
            if not query:
                continue
            key = query
        if key in seen:
            continue
        seen.add(key)
        out.append(query)
        if len(out) >= MAX_QUERIES:
            break
    return out


def parse_character_updates(raw) -> list:
    """解析搭车返回的角色更新；旧格式没有 ``characters`` 时返回空列表。

    解析失败、条目不是对象、没有可用称呼都直接跳过——这条通道是后台增益，
    不能影响主生成流程。
    """
    data = _json_object(raw)
    if data is None:
        return []
    items = data.get("characters")
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        handle = _clip(clean_name(item.get("handle")), CHARACTER_HANDLE_CHARS)
        true_name = _clip(clean_name(item.get("true_name")), CHARACTER_HANDLE_CHARS)
        if not handle and not true_name:
            continue
        entry = {
            "handle": handle,
            "true_name": true_name,
            "pronoun": (item.get("pronoun")
                        if item.get("pronoun") in ("他", "她") else ""),
            "status": ("revealed" if str(item.get("status") or "").strip().lower()
                       == "revealed" else "temporary"),
        }
        traits = item.get("traits")
        if isinstance(traits, (list, tuple)):
            cleaned = []
            for value in traits:
                trait = _clip(value, CHARACTER_TRAIT_CHARS)
                if trait and trait not in cleaned:
                    cleaned.append(trait)
            entry["traits"] = cleaned[-MAX_CHARACTER_TRAITS:]
        relation = item.get("relation")
        if relation is not None:
            entry["relation"] = _clip(relation, CHARACTER_RELATION_CHARS)
        out.append(entry)
    return out


def _keywords(query: str) -> set:
    cleaned = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", query)
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    out = set()
    for i in range(len(cleaned) - 1):
        token = cleaned[i:i + 2]
        if token in _STOP_WORDS:
            continue
        if any(ch in _STOP_CHARS for ch in token):
            continue
        out.add(token)
    return out


def _resolve_legacy(queries, entries) -> list:
    """旧格式字符串查询的原检索路径：二元组 + 文档频率加权 + 命中阈值。"""
    pairs = [(str(q), _keywords(q)) for q in queries if str(q).strip()]
    if not entries:
        return [(q, "") for q, _kws in pairs]
    df = {}
    for _query, kws in pairs:
        for kw in kws:
            if kw not in df:
                df[kw] = sum(1 for text in entries if kw in text)
    total_entries = len(entries)
    weights = {kw: 1.0 + math.log((total_entries + 1) / (count + 1))
               for kw, count in df.items()}
    out = []
    for query, kws in pairs:
        active = [kw for kw in kws if df.get(kw, 0) > 0]
        if not active:
            out.append((query, ""))
            continue
        total_weight = sum(
            weights[kw] if df.get(kw, 0) > 0 else 1.0 for kw in kws)
        min_hits = max(1, math.ceil(len(kws) * 0.35))
        best_text, best_key = "", (-1.0, -1, -1)
        for index, text in enumerate(entries):
            matched = [kw for kw in active if kw in text]
            if len(matched) < min_hits:
                continue
            score = sum(weights[kw] for kw in matched)
            key = (score, len(matched), index)
            if key > best_key:
                best_text, best_key = text, key
        if best_text and best_key[0] >= max(1.0, total_weight * 0.4):
            out.append((query, _clip(best_text, MATCH_CLIP_CHARS)))
        else:
            out.append((query, ""))
    return out


def _candidate_entries(replay_data, memory_lines) -> list:
    """检索语料：回放原文（带步号与时间位置）+ 长期记忆行。"""
    raw = [e for e in (replay_data or [])
           if isinstance(e, dict) and e.get("text")]
    total = max(1, len(raw) - 1)
    out = [(str(e.get("text") or ""), e.get("step"), False, i / total)
           for i, e in enumerate(raw)]
    for line in memory_lines or ():
        text = str(line or "").strip()
        if text:
            out.append((text, None, True, 0.5))
    return out


def _resolve_structured(query, candidates, source_step) -> tuple:
    """对象字面召回 + 方面信号词加权；返回 ``(命中原文, 判定档位)``。"""
    spec = ASPECTS.get(query.aspect)
    best_key, best_text, has_signal = None, "", False
    for text, step, is_memory, pos in candidates:
        if query.object not in text:
            continue
        hits = sum(1 for signal in spec.signals if signal in text) if spec else 0
        score = 1.0 + 1.2 * hits
        if spec:
            score += spec.memory_bias if is_memory else 0.0
            score += (spec.recency * pos if spec.recency >= 0
                      else -spec.recency * (1.0 - pos))
        if source_step is not None and step is not None and step == source_step:
            score -= 1.5
        key = (score, hits, pos)
        if best_key is None or key > best_key:
            best_key, best_text, has_signal = key, text, hits > 0
    if not best_text:
        return "", "missing"
    return _clip(best_text, MATCH_CLIP_CHARS), ("answered" if has_signal
                                                else "mentioned")


def resolve_detail_queries(queries, replay_data, memory_lines=(),
                           source_step=None) -> list:
    """为每条查询检索最相关原文，返回 ``[DetailMatch]``。

    结构化查询以对象为唯一硬条件；方面只通过信号词、长期记忆与时间位置
    加权，不设字面门槛。判定分三档：回答了该方面 / 仅提及对象 / 无记载。
    字符串查询走旧路径，保持既有调用方的行为。
    """
    items = list(queries or [])
    replay_texts = [str(e.get("text") or "") for e in (replay_data or [])
                    if isinstance(e, dict) and e.get("text")]
    legacy = dict(_resolve_legacy([q for q in items if isinstance(q, str)],
                                  replay_texts))
    candidates = _candidate_entries(replay_data, memory_lines)
    out = []
    for query in items:
        if isinstance(query, str):
            text = legacy.get(query, "")
            out.append(DetailMatch(query, text,
                                   "answered" if text else "missing"))
        else:
            text, state = _resolve_structured(query, candidates, source_step)
            out.append(DetailMatch(format_detail_label(query), text, state))
    return out


def detail_injection_line(query, match) -> str:
    """按判定档位生成「细节补充」块里的一行；形态类不允许模型补写设定。"""
    label, text, state = match
    spec = ASPECTS.get(query.aspect) if isinstance(query, DetailQuery) else None
    no_invent = spec is not None and not spec.allow_invent
    if state == "answered":
        return f"- {label}——原文参考：{text}"
    if no_invent:
        return (f"- {label}——正文未明确记载；以既有尺度信息为准，"
                "不要补写尺寸与外形")
    if state == "mentioned":
        return (f"- {label}——正文只提到该对象，未说明这方面；"
                "若与当前段落相关，可结合长期记忆自然补全或保留悬念，"
                "不要凭空编造设定")
    return (f"- {label}——正文未找到明确记载；若与当前段落相关，"
            "可结合长期记忆自然补全或保留悬念，不要凭空编造设定")


def search_replay_details(queries, replay_data) -> list:
    """在回放缓存中为每条查询检索最相关段落，返回命中的解释行。"""
    return [f"{m.label}——{m.text}"
            for m in resolve_detail_queries(queries, replay_data) if m.text]
