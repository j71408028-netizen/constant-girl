"""演化修正与结局生成。"""

import threading

from dungeon import process_log
from dungeon.models import PREFIX_ENDING
from dungeon.splitter import strip_highlight_markers


class EndingHandler:
    # ------------------ 演化修正汇总 ------------------
    def _apply_sensitivity_mods(self) -> dict:
        """汇总当前生效的持续演化修正（属性名 -> 倍率改变量）。

        归属章节的默认效果，被「章节效果短暂覆盖」改写时以覆盖为准（见
        ``window/triggers.py::_effective_sensitivity_effects``）；离开章节即失效。
        """
        mods = {}
        for effect in self._effective_sensitivity_effects():
            mods[effect["attr"]] = mods.get(effect["attr"], 0.0) + effect["amount"]
        return mods

    # ------------------ 结局触发器 ------------------
    def _start_ending_generation(self):
        if self._ending_generating:
            return
        self._ending_generating = True
        pending = self.pending_ending or {}
        self._ending_trigger_index = pending.get("trigger_index", -1)
        self._ending_name = pending.get("name", "")
        # 结局图标：配置了图标才算重要结局，结局生成时一起显示
        self.ending_icon_path = (pending.get("action_data") or {}).get("icon_path", "") or ""
        if self.ending_icon_path:
            self._frame.call(self._update_ending_icon)
        self._ending_thread = threading.Thread(target=self._generate_ending, daemon=True)
        self._ending_thread.start()

    def _build_story_summary(self, limit=12, text_limit=80):
        """收集当前故事状态与最近的过往片段，供结局生成参考。"""
        parts = [f"介入度 {self.dungeon_state.intrusion:.2f} / 破坏性 {self.dungeon_state.destruction:.2f}"
                 f" / 总伤亡 {int(self.dungeon_state.total_casualties):,}"]
        if self.dungeon_state.custom_attrs:
            custom = "，".join(f"{k} {v:.2f}" for k, v in self.dungeon_state.custom_attrs.items())
            parts.append(f"自定义属性：{custom}")
        # 优先使用剧情压缩器产出的完整概要，缺失时回退到最近片段
        summarizer = getattr(self, "story_summary", None)
        summary = summarizer.summary_only() if summarizer is not None else ""
        if summary:
            parts.append("剧情概要：\n" + summary)
        else:
            snippets = []
            for info in self.replay_data[-limit:]:
                # 只取步进记录：章节 / 触发器 / 结局记录不是故事片段
                if "type" not in info or not info.get("text"):
                    continue
                t = str(info["text"])
                if len(t) > text_limit:
                    t = t[:text_limit] + "..."
                snippets.append(f"[{info.get('type', '?')}] {t}")
            if snippets:
                parts.append("过往故事片段：\n" + "\n".join(snippets))
        return "\n".join(parts)

    def _generate_ending(self):
        try:
            pending = self.pending_ending
            if not pending:
                return
            name = pending["name"]
            client = getattr(self, "ai_client", None)
            self.ending_effects = pending.get("action_data", {}) or {}

            current_item = {"type_str": PREFIX_ENDING, "text": "", "highlight": True,
                            "speaker": None}
            self.story_history.append(current_item)

            if client is None:
                current_item["text"] = f"结局：{name}"
                self.ending_text = current_item["text"]
                self._schedule_text_update()
                process_log.log("[Ending] AI 客户端不可用，仅显示结局名称")
                return

            personality_desc = getattr(self.personality, "description", "") if self.personality else ""
            # 结局生成前把尚未压缩的剩余段落全部压缩，保证概要完整
            summarizer = getattr(self, "story_summary", None)
            if summarizer is not None:
                summarizer.flush_chapter(getattr(self, "current_chapter", "") or "",
                                         ai_client=client)
            # 结局提示同样按耦合等级取用：旅程收束 / 任务收尾 / 关系结局
            pack = coupling_prompts(normalize_coupling_level(
                getattr(self, "coupling_level", None)))
            system_prompt = pack["ending_system"].format(
                name=self.name, nick=self.nick,
                personality=personality_desc or '她有着独特的性格。')
            user_prompt = pack["ending_user"].format(
                ending_name=name, initial_prompt=self.initial_prompt,
                summary=self._build_story_summary())
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            buffer = ""
            for chunk in client.generate_stream(messages, temperature=0.9):
                if self._closing:
                    return
                buffer += chunk
                current_item["text"] = buffer.strip()
                self._schedule_text_update()
            current_item["text"] = strip_highlight_markers(buffer.strip())
            self.ending_text = current_item["text"]
            self._schedule_text_update()
            process_log.log(f"[Ending] 结局已生成：{name}")
        except Exception as e:
            process_log.log(f"结局生成异常: {e}")
        finally:
            self.pending_ending = None
            self.dungeon_ended = True
            self._ending_generating = False
            if 'name' in locals() and not self.ending_text:
                self.ending_text = f"结局：{name}"
            # 结局正文进回放记录，否则回放到最后一段就关窗（没有正文、没有图标）
            self._record_ending()
            # 统一收尾（见 window/persistence.py::_finalize）：
            # 结算结局增量 → 记录重要结局索引 → 按设置自动保存回放
            self._finalize(completed=True, reason="触发结局")

    def _record_ending(self):
        """把结局正文写进回放（``kind:"ending"``，只记一次）。

        结局文本是收尾线程的产物，回放没有任何别的途径拿到它；``ending_icon_path``
        同理（只有配了图标的结局才算重要结局，回放也要照着显示）。
        """
        if getattr(self, "_ending_recorded", False):
            return
        self._ending_recorded = True
        name = str(getattr(self, "_ending_name", "") or "")
        text = str(getattr(self, "ending_text", "") or "")
        self.replay_data.append({
            "kind": "ending",
            "name": name,
            "text": text or (f"结局：{name}" if name else ""),
            "icon_path": str(getattr(self, "ending_icon_path", "") or ""),
            "step": int(getattr(self.dungeon_state, "total_steps", 0) or 0),
        })

    # ------------------ 回放：结局正文 ------------------
    def _replay_ending(self, record):
        """复现结局：图标 + 正文 + 终止标记，与实时结局同一套展示。

        旧回放没有这条记录，回放到末段就关窗（不凭空补一段正文）。
        """
        self._ending_name = record.name or "结局"
        if record.icon_path:
            self.ending_icon_path = record.icon_path
            self._frame.call(self._update_ending_icon)
        if record.text:
            self.ending_text = record.text
            self.story_history.append({"type_str": PREFIX_ENDING, "text": record.text,
                                       "highlight": True, "speaker": None})
            self._update_text_display()
        self.pending_ending = None
        self.dungeon_ended = True
        process_log.log(f"[Replay] 复现结局: {record.name or '结局'}")
