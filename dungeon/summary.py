"""副本剧情压缩器。

把冗长的段落历史压缩成可注入提示词的“剧情概要”。

- ``record``：每一步结束后登记段落文本与所在章节；
- 每当 ``total_steps`` 达到 ``block_size`` 的倍数、或即将离开当前章节
  （``flush_chapter``）时，对上一块/上一章节的剩余段落做一次压缩；
- ``prompt_block``：返回给 ``DungeonPromptBuilder`` 的概要文本，包含
  全部压缩段、事实卡与关键事件。近期原文不再注入——对话历史
  （窗口大小见 ``story_recent_count`` 设置）已逐字携带最近剧情，
  重复注入只会推高 prefill 与首字延迟。

AI 压缩是三步流水线：``detach_chunk`` 在主线程切出一块（不调用 AI），
``compress_chunk`` 在后台线程完成 AI 调用与解析（纯函数，不碰实例状态），
``apply_result`` 在后台线程按块序号写回。这样 AI 等待不占主线程，AI 并发
返回时概要仍按时间顺序排列。窗口层负责调度这三步（见
``window/engine.py::_record_story_summary``）；纯逻辑测试可直接用同步的
``maybe_compress`` / ``flush_chapter``。

AI 不可用或失败时回退到内部算法（截取首末句与高频词拼接），保证提示词
始终有概要可用。

常驻记忆（不依赖 AI）：
- ``record_key_event``：代码路径直接登记的确定性关键事件（章节进出、
  选项选择、介入度/破坏性跨阈值），与事实卡一起常驻提示词；
- ``merge_facts``：压缩调用抽取的设定级事实，跨块去重合并。
"""

from __future__ import annotations

import json
import threading
import time
from typing import Iterable

from . import process_log
from .coupling import coupling_prompts

DEFAULT_BLOCK_SIZE = 20
MAX_SUMMARY_CHARS = 120
MAX_KEY_EVENTS = 12      # 常驻提示词的确定性关键事件上限
MAX_FACTS = 12           # 常驻提示词的关键事实（事实卡）上限
KEY_EVENT_CHARS = 60
FACT_CHARS = 60
MAX_PENDING_UPDATES = 4  # 未取走的搭车角色更新批数上限
WAIT_COMPRESS_TIMEOUT = 30.0  # flush 等在途压缩的最长时间（防 AI 卡死拖死换章）

#: 耦合等级缺摘要提示时的兜底（提示词缺键不应让整次压缩退回内部算法）
SUMMARY_SYSTEM_FALLBACK = (
    "你是剧情概要助手。把给定的故事段落压缩成 JSON 输出："
    '{"summary": "第三人称概要", "facts": ["关键事实", ...]}。'
    "summary 不超过100字，保留关键人物、事件与走向；"
    "facts 记录需要长期记住的设定级信息，每条不超过30字、最多6条，"
    "只记定性信息，不要数值；人物的当前状态不要写进 facts。"
    "只输出 JSON 本身，不要解释。"
)


def _clip(text: str, limit: int = MAX_SUMMARY_CHARS) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


class StorySummarizer:
    """按块压缩剧情，并向提示词构建器提供“概要 + 最近段落”。

    概要、事实卡等状态可能被主线程（登记、注入提示词）与后台线程（异步
    压缩写回）同时访问，统一用 ``_lock`` 保护；``_cond`` 供 flush 等待在途
    压缩落地。锁是可重入的，内部方法可以互相调用。
    """

    def __init__(self, block_size: int = DEFAULT_BLOCK_SIZE, coupling_level: str = None):
        self.block_size = max(1, int(block_size))
        # 概要与事实卡的收集口径随耦合等级变化（见 dungeon.coupling）
        self.coupling_level = coupling_level
        # 已完成压缩的段落：[(chapter_name, summary_text), ...]
        self.summaries: list[tuple[str, str]] = []
        # 事实卡：跨块合并去重的设定级关键事实（人物、地点、伏笔、承诺）
        self.facts: list[str] = []
        # 确定性关键事件（章节进出、选项选择、阈值跨越），代码路径直接登记
        self.key_events: list[str] = []
        # 搭车抽取的角色更新：[(块内正文, [更新...]), ...]，窗口层取走喂账本
        self.pending_character_updates: list[tuple[str, list]] = []
        # 尚未压缩的缓冲：[(text_type_value, text, chapter_name), ...]（仅主线程）
        self._buffer: list[tuple[str, str, str]] = []
        # 异步压缩保序：已分配序号 [0, _next_issue)，已写回 [0, _next_write)。
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._next_issue = 0
        self._next_write = 0
        # seq -> None（压缩中）或 (label, result, chunk)（待写回）
        self._pending: dict[int, tuple | None] = {}

    # ---------------- 写入 ----------------
    def record(self, text_type_value: str, text: str, chapter_name: str = ""):
        """登记一段已展示的正文（AI 段落、插入段、回放步进共用）。"""
        text = str(text or "").strip()
        if not text:
            return
        with self._lock:
            self._buffer.append((text_type_value, text, chapter_name or ""))

    def flush_chapter(self, chapter_name: str, ai_client=None):
        """离开章节时强制压缩本章缓冲（不满一个块也压缩）。

        先等在途的异步压缩全部写回，再压缩剩余缓冲——保证结局/换章拿到的
        ``summary_only`` 是完整的，不会漏掉仍在后台的块。
        """
        self.wait_pending()
        self._compress(chapter_name=chapter_name, ai_client=ai_client,
                       allow_partial=True)

    def maybe_compress(self, total_steps: int, chapter_name: str = "",
                       ai_client=None):
        """同步压缩一个块（供回放与纯逻辑测试；实时路径走异步三段式）。"""
        if self.block_size <= 0:
            return
        with self._lock:
            ready = len(self._buffer) >= self.block_size
        if ready:
            self._compress(chapter_name=chapter_name, ai_client=ai_client,
                           allow_partial=False)

    def wait_pending(self, timeout: float = WAIT_COMPRESS_TIMEOUT):
        """等待所有已切出、尚未写回的异步压缩块落地。

        ``Condition.wait`` 会释放锁，因此即便在主线程（换章）调用，后台的
        ``apply_result`` 仍可拿到锁写回并唤醒等待，不会互相卡死。
        """
        deadline = time.monotonic() + max(0.0, timeout)
        with self._cond:
            while self._next_write < self._next_issue:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process_log.log("[Summary] 等待异步压缩超时，按现有概要继续")
                    return
                self._cond.wait(remaining)

    # ---------------- 异步三段式 ----------------
    def detach_chunk(self, chapter_name: str = "") -> tuple | None:
        """主线程：切出一个满块并从缓冲移除，返回 ``(seq, chunk, label)``。

        不满一块返回 ``None``。切出的块立刻从缓冲移除，避免并发重复压缩；
        序号在此分配，供后台返回后按序写回。
        """
        with self._lock:
            if self.block_size <= 0 or len(self._buffer) < self.block_size:
                return None
            chunk = self._buffer[:self.block_size]
            del self._buffer[:self.block_size]
            label = chapter_name or (chunk[0][2] if chunk else "")
            seq = self._next_issue
            self._next_issue += 1
            self._pending[seq] = None  # 占位：仍在压缩中
        return seq, chunk, label

    def compress_chunk(self, chunk: list, ai_client=None) -> tuple:
        """后台线程：压缩一个块，返回 ``(概要, 关键事实, 角色更新)``。

        不触碰实例状态（``coupling_level`` 只读），可安全在后台线程调用。
        """
        return self._summarize_chunk(chunk, ai_client)

    def apply_result(self, seq: int, label: str, result: tuple, chunk: list):
        """后台线程：写回一个块的压缩结果，并按序号保序。

        后台可能先返回后面的块；这里挂到 ``_pending[seq]``，只有从
        ``_next_write`` 开始的连续块才落进概要，从而保证时间顺序。
        """
        with self._cond:
            self._pending[seq] = (label, result, chunk)
            self._cond.notify_all()
            while self._next_write in self._pending \
                    and self._pending[self._next_write] is not None:
                item = self._pending.pop(self._next_write)
                lbl, res, ch = item
                self._apply_chunk(lbl, res, ch)
                self._next_write += 1
            self._cond.notify_all()

    # ---------------- 关键事件与事实卡 ----------------
    def record_key_event(self, text: str):
        """登记一条确定性关键事件，常驻提示词（有界，超出丢弃最旧）。

        只记定性里程碑（章节进出、选项选择、介入度/破坏性跨阈值），
        不记演化修正等纯数值信息。
        """
        text = _clip(text, KEY_EVENT_CHARS)
        if not text:
            return
        with self._lock:
            if self.key_events and self.key_events[-1] == text:
                return
            self.key_events.append(text)
            if len(self.key_events) > MAX_KEY_EVENTS:
                del self.key_events[:len(self.key_events) - MAX_KEY_EVENTS]

    def merge_facts(self, facts):
        """把压缩调用提取的关键事实合并进事实卡（去重、有界）。"""
        with self._lock:
            for fact in facts or []:
                fact = _clip(str(fact or ""), FACT_CHARS)
                if fact and fact not in self.facts:
                    self.facts.append(fact)
            if len(self.facts) > MAX_FACTS:
                del self.facts[:len(self.facts) - MAX_FACTS]

    # ---------------- 压缩 ----------------
    def _compress(self, chapter_name: str = "", ai_client=None,
                  allow_partial: bool = False):
        """同步压缩：切块 → 压缩 → 写回，三步一气呵成。"""
        with self._lock:
            if not self._buffer:
                return
            if not allow_partial and len(self._buffer) < self.block_size:
                return
            chunk = self._buffer if allow_partial else self._buffer[:self.block_size]
            self._buffer = [] if allow_partial else self._buffer[len(chunk):]
            label = chapter_name or (chunk[0][2] if chunk else "")
        result = self._summarize_chunk(chunk, ai_client)  # 慢调用，不持锁
        with self._lock:
            self._apply_chunk(label, result, chunk)

    def _apply_chunk(self, label: str, result: tuple, chunk: list):
        """把一块的压缩结果写进概要/事实卡/角色更新（调用方持锁）。"""
        summary, facts, updates = result
        self.summaries.append((label, summary))
        for fact in facts or []:
            fact = _clip(str(fact or ""), FACT_CHARS)
            if fact and fact not in self.facts:
                self.facts.append(fact)
        if len(self.facts) > MAX_FACTS:
            del self.facts[:len(self.facts) - MAX_FACTS]
        if updates:
            # 搭车抽取的角色更新：连同块内正文一起存（正文是合并锚点），
            # 由窗口层取走喂给角色账本；这里不解析、不判断
            anchor = "\n".join(t for _type, t, _ch in chunk if t)
            self.pending_character_updates.append((anchor, updates))
            del self.pending_character_updates[:-MAX_PENDING_UPDATES]

    def _summarize_chunk(self, chunk: list, ai_client=None) -> tuple:
        """压缩一个块，返回 (概要, 关键事实列表, 角色更新列表)。"""
        texts = [t for _type, t, _ch in chunk if t]
        if not texts:
            return "", [], []
        if ai_client is not None:
            try:
                joined = "\n".join(texts)
                pack = coupling_prompts(self.coupling_level)
                system_prompt = pack.get("summary_system") or SUMMARY_SYSTEM_FALLBACK
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content":
                        f"请概括以下 {len(texts)} 段剧情：\n{joined}"},
                ]
                raw = ai_client.generate(messages, temperature=0.3)
                summary, facts, updates = self._parse_summary_json(raw)
                if summary:
                    process_log.log(
                        f"[Summary] AI 压缩成功（{self.coupling_level or 'default'}）："
                        f"{len(texts)} 段")
                    return summary, facts, updates
            except Exception as e:
                process_log.log(
                    f"[Summary] AI 压缩失败（{self.coupling_level or 'default'}），"
                    f"改用内部算法: {e}")
        return self._fallback_summary(texts), [], []

    def drain_character_updates(self) -> list:
        """取走搭车抽取的角色更新 ``[(块内正文, [更新...]), ...]`` 并清空。"""
        with self._lock:
            pending = self.pending_character_updates
            self.pending_character_updates = []
            return pending

    @staticmethod
    def _parse_summary_json(raw) -> tuple:
        """解析压缩调用返回的 {summary, facts, character_updates}。

        旧响应没有 ``character_updates`` 时返回空列表，行为不变；
        解析失败时整体当概要。
        """
        raw = str(raw or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()
        start = raw.find("{")
        if start != -1:
            try:
                data, _ = json.JSONDecoder().raw_decode(raw[start:])
                summary = str(data.get("summary") or "").strip()
                facts = data.get("facts")
                updates = data.get("character_updates")
                if summary:
                    return (_clip(summary),
                            facts if isinstance(facts, list) else [],
                            updates if isinstance(updates, list) else [])
            except json.JSONDecodeError:
                pass
        return (_clip(raw) if raw else ""), [], []

    @staticmethod
    def _fallback_summary(texts: Iterable[str]) -> str:
        """内部算法：首句 + 末句 + 高频关键词拼成概要。"""
        texts = [t for t in texts if t]
        if not texts:
            return ""
        first = _clip(texts[0], 40)
        last = _clip(texts[-1], 40)
        keywords = StorySummarizer._keywords(texts)
        parts = []
        if first:
            parts.append(f"起：{first}")
        if keywords:
            parts.append(f"关键：{'、'.join(keywords)}")
        if last and last != first:
            parts.append(f"末：{last}")
        return _clip("；".join(parts) or f"共{len(texts)}段剧情")

    @staticmethod
    def _keywords(texts: Iterable[str], top: int = 3) -> list:
        """简单词频统计：取长度≥2 的高频连续中文词作为关键词。"""
        import re
        counter: dict[str, int] = {}
        for text in texts:
            for token in re.findall(r"[一-鿿]{2,4}", text):
                counter[token] = counter.get(token, 0) + 1
        ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        return [word for word, _count in ranked[:top]]

    # ---------------- 提示词 ----------------
    def _memory_lines(self) -> list:
        """概要之外的常驻记忆：事实卡与关键事件（紧凑注入，调用方持锁）。"""
        lines = []
        if self.facts:
            lines.append("关键事实：" + "；".join(self.facts))
        if self.key_events:
            lines.append("关键事件（按时间顺序）：")
            lines.extend(f"- {event}" for event in self.key_events)
        return lines

    def prompt_block(self) -> str:
        """注入提示词的剧情块：压缩概要 + 常驻记忆（近期原文由对话历史携带）。"""
        with self._lock:
            lines = []
            if self.summaries:
                lines.append("剧情概要（按时间顺序）：")
                for i, (chapter, summary) in enumerate(self.summaries, 1):
                    prefix = f"{i}. " + (f"【{chapter}】" if chapter else "")
                    lines.append(prefix + summary)
            lines.extend(self._memory_lines())
            return "\n".join(lines)

    def summary_only(self) -> str:
        """仅压缩概要与常驻记忆（结局生成等不需要原文的场景使用）。"""
        with self._lock:
            lines = []
            for i, (chapter, summary) in enumerate(self.summaries, 1):
                lines.append(f"{i}. 【{chapter}】{summary}" if chapter else f"{i}. {summary}")
            lines.extend(self._memory_lines())
            return "\n".join(lines)
