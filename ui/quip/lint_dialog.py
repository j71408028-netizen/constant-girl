"""描述校验对话框：把 quip 语料的校验结论摆成一份可定位的清单。

「校验」按钮（``ui/quip/__init__.py::QuipCardManager.run_check``）打开本对话框。
判据全在 ``services/exploration/quip_lint.py``，这里只做三件事：

1. **按级别呈现**：错误 / 警告 / 提示逐行列出，左侧复选框过滤（提示级缺省收起，
   与命令行 ``--all`` 同口径）；
2. **一条一溯源**：位置列写 ``尺寸档 @ 坐标 · 条目#N · 偏移K``，选中后下方展开完整
   说明、池信息与「替换后」样例——组合级结论靠这一步才看得懂；
3. **一键回原文**：双击或点「定位到描述」把坐标与条目下标交回描述管理页，直接打开
   那条描述的编辑框（``on_locate`` 回调，由页面实现）。

只读：不改数据、不写盘。校验范围与命令行一致——**当前风格、当前尺寸档**；
换档请关掉对话框切观测等级再校验（全量结论读不动，两边都不提供全档）。
"""

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from services.exploration.quip_lint import LEVEL_LABELS, short_loc
from ui.ctk import fonts as ui_fonts
from ui.ctk.dialogs import BaseDialog
from ui.ctk.theme import (
    DLG_PANEL_BG, DLG_TITLE, QUIP_BORDER_STRONG, QUIP_ERR, QUIP_HOVER,
    QUIP_TEXT, QUIP_TEXT_SOFT, QUIP_WARN,
)

LEVELS = ("error", "warn", "info")
LEVEL_TEXT = {"error": "错误", "warn": "警告", "info": "提示"}


def _pick(token):
    """成对主题色 → 当前外观下的单色（原生 ttk 只吃单色）。"""
    if isinstance(token, (list, tuple)):
        idx = 1 if ctk.get_appearance_mode().lower() == "dark" else 0
        return token[min(idx, len(token) - 1)]
    return token


class QuipLintDialog(BaseDialog):
    """校验结论清单 + 定位回原文。``on_locate(loc)`` 由调用方实现。"""

    def __init__(self, parent, report, on_locate=None):
        super().__init__(parent)
        self.report = report
        self.on_locate = on_locate
        self._rows = {}
        self._level_vars = {level: tk.BooleanVar(value=level != "info")
                            for level in LEVELS}

        self.title(f"描述校验 - {report.style}" + (
            f" / {report.size_cat}" if report.size_cat else ""))
        self.geometry("920x640")
        self.minsize(760, 480)
        self.resizable(True, True)
        self.transient(parent.winfo_toplevel())
        # 抓取延到窗口可见之后（X11 要求 viewable，见 BaseDialog._grab_deferred）
        self._grab_deferred()
        self._build_ui()
        self._refresh()
        self._center_dialog(parent)
        self.wait_window()

    # ---------- 构建 ----------

    def _build_ui(self):
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 4))

        scope = self.report.size_cat or "全部尺寸档"
        ctk.CTkLabel(head, text=f"风格 {self.report.style} · 尺寸档 {scope}",
                     font=ui_fonts.ui_font(15, "bold"),
                     text_color=DLG_TITLE).pack(anchor="w")

        counts = self.report.counts
        row = ctk.CTkFrame(head, fg_color="transparent")
        row.pack(anchor="w", pady=(4, 0))
        for level in LEVELS:
            ctk.CTkLabel(row, text=f"{LEVEL_TEXT[level]} {counts.get(level, 0)}",
                         font=ui_fonts.ui_font(13, "bold"),
                         text_color=self._level_color(level)).pack(side="left", padx=(0, 14))

        if self.report.with_grammar and self.report.stats:
            stats = self.report.stats
            line = (f"槽位 {stats.get('slots', 0)} 处 · 候选比对 {stats.get('candidates', 0)} 次"
                    f" · 特征缓存 {stats.get('feature_cache', 0)} 条")
            hits = self.report.rules_hit()
            if hits:
                line += " · 命中 " + "；".join(f"{k}×{v}" for k, v in hits.items())
            ctk.CTkLabel(head, text=line, font=ui_fonts.ui_font(12),
                         text_color=QUIP_TEXT_SOFT, justify="left").pack(anchor="w", pady=(2, 0))
        elif not self.report.with_grammar:
            ctk.CTkLabel(head, text="已跳过组合级语法检查（只看格式与 meta）",
                         font=ui_fonts.ui_font(12),
                         text_color=QUIP_TEXT_SOFT).pack(anchor="w", pady=(2, 0))

        filters = ctk.CTkFrame(self, fg_color="transparent")
        filters.pack(fill="x", padx=14, pady=(6, 2))
        ctk.CTkLabel(filters, text="显示", font=ui_fonts.ui_font(12),
                     text_color=QUIP_TEXT_SOFT).pack(side="left", padx=(0, 8))
        for level in LEVELS:
            ctk.CTkCheckBox(
                filters, text=LEVEL_TEXT[level], font=ui_fonts.ui_font(12),
                variable=self._level_vars[level], command=self._refresh,
                checkbox_width=16, checkbox_height=16,
                border_color=QUIP_BORDER_STRONG, hover_color=QUIP_HOVER,
                text_color=self._level_color(level)).pack(side="left", padx=(0, 12))
        self.count_label = ctk.CTkLabel(filters, text="", font=ui_fonts.ui_font(12),
                                        text_color=QUIP_TEXT_SOFT)
        self.count_label.pack(side="right")

        # 清单
        list_frame = ctk.CTkFrame(self, fg_color="transparent", border_width=1,
                                  corner_radius=8, border_color=QUIP_BORDER_STRONG)
        list_frame.pack(fill="both", expand=True, padx=14, pady=4)
        columns = (("level", "级别", 60), ("kind", "规则", 140),
                   ("loc", "位置", 210), ("message", "说明", 440))
        self.tree = ttk.Treeview(list_frame, style="Custom.Treeview", show="headings",
                                 columns=[c[0] for c in columns])
        for key, label, width in columns:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w",
                             stretch=key in ("loc", "message"))
        scrollbar = ctk.CTkScrollbar(list_frame, orientation="vertical",
                                     command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(4, 2), pady=4)
        scrollbar.pack(side="right", fill="y", padx=(2, 4), pady=4)
        for level in LEVELS:
            self.tree.tag_configure(level, foreground=_pick(self._level_color(level)))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda _e: self._locate())

        # 详情
        self.detail = ctk.CTkTextbox(self, height=132, fg_color=DLG_PANEL_BG,
                                     border_width=1, border_color=QUIP_BORDER_STRONG,
                                     font=ui_fonts.ui_font(12), wrap="word",
                                     text_color=QUIP_TEXT)
        self.detail.pack(fill="x", padx=14, pady=(2, 6))
        self._set_detail("选一条结论看它的完整说明与替换后样例；双击可直接定位到那条描述。")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=14, pady=(0, 12))
        self.locate_btn = ctk.CTkButton(
            buttons, text="定位到描述", width=120, command=self._locate,
            fg_color="transparent", border_width=1, corner_radius=8,
            text_color=QUIP_TEXT, hover_color=QUIP_HOVER,
            border_color=QUIP_BORDER_STRONG, state="disabled")
        self.locate_btn.pack(side="right", padx=(8, 0))
        ctk.CTkButton(buttons, text="关闭", width=90, command=self.destroy,
                      fg_color="transparent", border_width=1, corner_radius=8,
                      text_color=QUIP_TEXT_SOFT, hover_color=QUIP_HOVER,
                      border_color=QUIP_BORDER_STRONG).pack(side="right")

    @staticmethod
    def _level_color(level):
        return {"error": QUIP_ERR, "warn": QUIP_WARN}.get(level, QUIP_TEXT_SOFT)

    # ---------- 数据 ----------

    def _visible_findings(self):
        levels = [level for level in LEVELS if self._level_vars[level].get()]
        return self.report.sorted_findings(levels=levels)

    def _refresh(self):
        findings = self._visible_findings()
        self.tree.delete(*self.tree.get_children())
        self._rows = {}
        for finding in findings:
            row = self.tree.insert("", "end", values=(
                LEVEL_TEXT.get(finding.level, finding.level),
                finding.kind,
                short_loc(finding.loc),
                _one_line(finding.message),
            ), tags=(finding.level,))
            self._rows[row] = finding
        self.count_label.configure(text=f"当前显示 {len(findings)} 条")
        if not findings:
            self._set_detail("当前筛选下没有问题。"
                             + ("（提示级缺省收起，勾上「提示」可展开）"
                                if not self._level_vars["info"].get() else ""))
        self.locate_btn.configure(state="disabled")

    def _on_select(self, _event=None):
        finding = self._selected()
        if finding is None:
            return
        lines = [f"[{LEVEL_LABELS.get(finding.level, finding.level)}] {finding.kind}",
                 finding.message]
        loc = finding.loc or {}
        if loc.get("snippet"):
            lines.append(f"片段：{loc['snippet']}")
        extra = finding.extra or {}
        for sample in extra.get("samples", []):
            lines.append(f"· 候选『{sample.get('candidate', '')}』填入该槽位后 → "
                         f"「{sample.get('rendered', '')}」")
        if extra.get("her_candidates"):
            lines.append("· 自带主语「她」的候选：" +
                         "、".join(f"『{c}』" for c in extra["her_candidates"]))
        self._set_detail("\n".join(lines))
        self.locate_btn.configure(
            state="normal" if _locatable(finding) else "disabled")

    def _selected(self):
        selection = self.tree.selection()
        return self._rows.get(selection[0]) if selection else None

    def _set_detail(self, text):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    # ---------- 定位 ----------

    def _locate(self):
        finding = self._selected()
        if finding is None or not _locatable(finding) or self.on_locate is None:
            return
        loc = dict(finding.loc)
        self.destroy()
        self.on_locate(loc)


def _locatable(finding):
    """这条结论能否反查到具体条目：需要坐标与条目下标（文件级结论不跳）。"""
    loc = finding.loc or {}
    return loc.get("coord") is not None and loc.get("entry_idx") is not None


def _one_line(text, limit=160):
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit] + "…"
