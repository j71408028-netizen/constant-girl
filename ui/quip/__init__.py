import math
import os
import tkinter as tk
from collections import Counter

import ui.ctk.dialogs

import customtkinter as ctk
import re

from core.logic import SIZE_CATEGORIES, size_level_text
from core.scale_reference import DESTRUCTION_LEVELS, INTRUSION_LEVELS
from persistence import QuipRepo
from persistence.quip_repo import DEFAULT_QUIP_STYLE
from services.challenges import (
    challenge_pack_titles, get_challenge_packs, import_quip_challenge_pack,
    unique_display,
)
from ui.ctk.managers import TreeviewManager, CardManager
from ui.ctk.widgets import OptionButton, CTkScrollableDropdownFrame
from ui.ctk.dialogs import BaseDialog
from ui.ctk.address_dlg import AddressTextDialog
from ui.quip.dialogs import QuipDialog, _TargetSelectDialog
from ui.quip.lint_dialog import QuipLintDialog
from services.exploration.quip_lint import lint_style
from core.address_model import format_addr_verbose
from ui.ctk.theme import (
    QUIP_BORDER_STRONG, QUIP_HOVER, QUIP_TEXT_SOFT,
    QUIP_PLACEHOLDER, QUIP_LINK, QUIP_ERR, QUIP_ERR_HOVER,
    QUIP_TYPEVIEW, QUIP_TYPEVIEW_HOVER, QUIP_TYPE_COLORS,
    MGR_BORDER, MGR_BORDER_STRONG, MGR_ERR, MGR_ERR_HOVER, MGR_HOVER,
    MGR_PANEL_BG, MGR_TEXT, MGR_TEXT_SOFT, MGR_TEXT_MUTED,
)
from ui.ctk import fonts as ui_fonts


class QuipCardManager(CardManager):
    RESOURCE_TYPE = "quips"
    SUPPORTS_SIZE = True

    SIZE_CATEGORIES = SIZE_CATEGORIES
    SUMMARY_RE = re.compile(r'\s*\[summary:(.*?)\]$')
    TAG_RE = re.compile(r'\[([a-e]):(\d+):([^\]]+)\]')

    def __init__(self, parent, quip_repo: QuipRepo, settings_repo, gui_ref):
        self.quip_repo = quip_repo
        self._settings_repo = settings_repo
        self.style_var = tk.StringVar()
        self.size_var = tk.StringVar(value="small")
        super().__init__(parent, gui_ref, item_name="描述")

        self._create_size_widgets()
        self._create_type_view_button()
        self.create_style_widgets(self.style_host)
        self.refresh_styles()

        self.type_view_active = False
        self.type_view = QuipTypeViewManager(self, self)
        self.type_view.pack_forget()
        self._create_lint_widget()
        self.refresh_ui()

    # ----- 实现基类抽象方法 -----
    def _get_style_list(self):
        return self.quip_repo.get_styles()

    def _get_current_style(self):
        return self.gui.current_quip_style

    def _set_current_style(self, style):
        self.gui.current_quip_style = style

    def _get_default_style(self):
        return DEFAULT_QUIP_STYLE

    def _create_style_impl(self, style_id, title):
        self.quip_repo.create_style(style_id, title=title)

    def _set_style_title_impl(self, style_id, title):
        self.quip_repo.set_title(style_id, title)

    def _style_display_name(self, style_id):
        return self.quip_repo.display_name(style_id)

    def _delete_style_impl(self, name):
        self.quip_repo.delete_style(name)

    # ----- 风格控件 -----
    def create_style_widgets(self, parent):
        self.style_combo = ctk.CTkComboBox(
            parent, variable=self.style_var, state="readonly",
            width=160, height=32, corner_radius=7,
            fg_color=MGR_PANEL_BG,
            border_width=1, border_color=MGR_BORDER,
            button_color=MGR_PANEL_BG,
            button_hover_color=MGR_HOVER,
            dropdown_fg_color=MGR_PANEL_BG,
            dropdown_hover_color=MGR_HOVER,
            text_color=MGR_TEXT,
            font=ui_fonts.ui_font(13)
        )
        self.style_combo.pack(side='left')
        self._rebuild_dropdown()

    def _edit_style_address(self):
        style = self._get_current_style()
        if not style:
            return
        current = self.quip_repo.load_style_address(style)
        dlg = AddressTextDialog(
            self, "描述风格注册地址",
            description=(
                "注册该描述风格所在的地址（仅注册最上面的若干级，维度必填）。\n"
                "报告生成时，该风格只能用于同一 / 包含它的地标地址之后的描述。\n"
                "当前风格：" + self.quip_repo.display_name(style)
            ),
            initial=current)
        if dlg.result is not None:
            self.quip_repo.save_style_address(style, dlg.result)
            if dlg.result:
                ui.ctk.dialogs.showinfo(
                    "已保存",
                    f"已保存风格注册地址：{format_addr_verbose(dlg.result)}。")
            else:
                ui.ctk.dialogs.showinfo(
                    "已保存", "已清除风格注册地址（该风格可接任意地标后的描述）。")

    def _get_challenge_packs_with_keys(self):
        packs = get_challenge_packs(self._settings_repo)
        return packs

    def _build_combined_items(self):
        """下拉条目：显示名在前（选择回 id），挑战包导入项挂在末尾。"""
        styles = self.quip_repo.get_styles()
        packs = self._get_challenge_packs_with_keys()
        items = []
        text_colors = {}
        self._pack_display_map = {}
        self._style_display_map = {}
        used = set()
        for style in styles:
            display = self._style_display_name(style)
            if display in used:   # 显示名撞车时补 id，保证每行可区分
                display = f"{display}（{style}）"
            used.add(display)
            items.append(display)
            self._style_display_map[display] = style
        titles = challenge_pack_titles(self._settings_repo, packs)
        for pack in packs:
            display = unique_display(
                f"⚔ {titles.get(pack) or os.path.splitext(pack)[0]}", pack, used)
            items.append(display)
            text_colors[display] = QUIP_LINK
            self._pack_display_map[display] = pack
        return items, text_colors

    def _rebuild_dropdown(self):
        items, text_colors = self._build_combined_items()
        self.style_combo.configure(values=items if items else [])
        if hasattr(self, '_style_dropdown') and self._style_dropdown:
            self._style_dropdown.configure(values=items, text_colors=text_colors)
        else:
            self._style_dropdown = CTkScrollableDropdownFrame(
                attach=self.style_combo,
                values=items,
                text_colors=text_colors,
                command=self._on_dropdown_select,
                height=210, button_height=30,
                fg_color=MGR_PANEL_BG,
                hover_color=MGR_HOVER,
                scrollbar_button_color=MGR_HOVER,
                scrollbar_button_hover_color=MGR_HOVER,
                frame_border_color=MGR_BORDER,
                text_color=MGR_TEXT,
                button_color=MGR_PANEL_BG,
                frame_border_width=1,
                justify="left"
            )

    def _on_dropdown_select(self, choice):
        if choice in getattr(self, '_pack_display_map', {}):
            pack_name = self._pack_display_map[choice]
            try:
                imported = import_quip_challenge_pack(self._settings_repo, pack_name, self.quip_repo)
            except ValueError as e:
                ui.ctk.dialogs.showerror("错误", str(e))
                self._set_combo_to_current_style()
                return
            self.refresh_styles()
            self._clear_search()
            self._refresh_active_view()
            self._reset_scroll(self.rows)
            self.gui.load_combined_quips()
            ui.ctk.dialogs.showinfo("成功", f"已从挑战包导入 {imported} 条描述数据")
        else:
            style = getattr(self, "_style_display_map", {}).get(choice, choice)
            if style != self._get_current_style():
                self._set_current_style(style)
                self._clear_search()
                self._refresh_active_view()
                self._reset_scroll(self.rows)

    # ---------- 工具方法 ----------
    @classmethod
    def extract_summary(cls, quip_text: str) -> tuple:
        text = quip_text.strip()
        m = cls.SUMMARY_RE.search(text)
        if m:
            summary = m.group(1).strip()
            clean = cls.SUMMARY_RE.sub('', text).strip()
            return clean, summary
        else:
            summary = text[:7].strip()
            return text, summary if summary else "无简介"

    @classmethod
    def split_summary(cls, item: dict) -> tuple:
        """条目 → ``(正文, 简介)``：优先取 ``summary`` 字段，旧数据回落解标记。"""
        text = item.get('text', '')
        summary = (item.get('summary') or '').strip()
        if summary:
            return cls.SUMMARY_RE.sub('', text).strip(), summary
        return cls.extract_summary(text)

    def _type_color(self, letter):
        colors = QUIP_TYPE_COLORS.get(letter)
        if not colors:
            return QUIP_PLACEHOLDER
        if ctk.get_appearance_mode() == "Dark":
            return colors[1] if len(colors) > 1 else colors[0]
        return colors[0]

    def _tagged_text(self, text):
        """去掉 ``[类型:编号:内容]`` 外壳，返回 (可见文本, 着色片段)。"""
        out = []
        spans = []
        pos = 0
        cursor = 0
        for m in self.TAG_RE.finditer(text):
            out.append(text[cursor:m.start()])
            pos += m.start() - cursor
            inner = m.group(3)
            out.append(inner)
            spans.append((pos, pos + len(inner), self._type_color(m.group(1))))
            pos += len(inner)
            cursor = m.end()
        out.append(text[cursor:])
        return ''.join(out), spans

    # ---------- 风格控件 ----------
    def edit_custom_types(self, on_saved=None):
        style = self._get_current_style()
        meta = self.quip_repo.load_meta(style)
        custom = meta.get("custom_types", {})

        dialog = BaseDialog(self)
        dialog.title(f"编辑自定义类型 - {self._style_display_name(style)}")
        dialog.geometry("600x320")
        dialog.transient(self)
        # 抓取延到窗口可见之后（X11 要求 viewable，见 BaseDialog._grab_deferred）
        dialog._grab_deferred()

        main_frame = ctk.CTkFrame(dialog)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)

        entries = {}
        for i, key in enumerate(["c", "d", "e"]):
            frame = ctk.CTkFrame(main_frame, border_width=1, corner_radius=6)
            frame.pack(side='left', fill='both', expand=True, padx=5, pady=5)

            ctk.CTkLabel(frame, text=f"自定义类型 {key.upper()}", font=ui_fonts.ui_font(12, "bold")).pack(anchor='w', padx=5, pady=(5, 0))

            name_row = ctk.CTkFrame(frame, fg_color="transparent")
            name_row.pack(fill='x', padx=5, pady=(5, 0))
            ctk.CTkLabel(name_row, text="名称:  ").pack(side='left')
            name_var = tk.StringVar(value=custom.get(key, {}).get("name", f"自定义{i+1}"))
            ctk.CTkEntry(name_row, textvariable=name_var, width=120).pack(side='left', padx=(5, 0))

            sub_vars = []
            subtypes = custom.get(key, {}).get("subtypes", [])
            for j in range(4):
                sub_row = ctk.CTkFrame(frame, fg_color="transparent")
                sub_row.pack(fill='x', padx=5, pady=(2, 0))
                ctk.CTkLabel(sub_row, text=f"细分{j+1}:").pack(side='left')
                default_sub = subtypes[j] if j < len(subtypes) else f"细分{j+1}"
                var = tk.StringVar(value=default_sub)
                ctk.CTkEntry(sub_row, textvariable=var, width=120).pack(side='left', padx=(5, 0))
                sub_vars.append(var)

            allow_var = tk.BooleanVar(value=custom.get(key, {}).get("allow_confusion", True))
            ctk.CTkSwitch(frame, text="允许混淆", variable=allow_var).pack(pady=(10, 5), padx=5)

            entries[key] = (name_var, sub_vars, allow_var)

        def save():
            new_custom = {}
            for key, (name_var, sub_vars, allow_var) in entries.items():
                new_custom[key] = {
                    "name": name_var.get().strip() or f"自定义{key[1]}",
                    "subtypes": [v.get().strip() or f"细分{idx+1}" for idx, v in enumerate(sub_vars)],
                    "allow_confusion": allow_var.get()
                }
            meta["custom_types"] = new_custom
            self.quip_repo.save_meta(style, meta)
            dialog.destroy()
            if on_saved:
                on_saved()

        button_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        button_frame.pack(pady=10)
        ctk.CTkButton(button_frame, text="保存", command=save, width=80).pack(side='left', padx=10)
        ctk.CTkButton(button_frame, text="取消", command=dialog.destroy, width=80).pack(side='left', padx=10)

        dialog._center_dialog(self)

    # ---------- 观测等级选择 ----------
    def _create_size_widgets(self):
        values = [size_level_text(cat) for cat in self.SIZE_CATEGORIES]
        self._size_key_by_label = {
            label: cat for label, cat in zip(values, self.SIZE_CATEGORIES)
        }
        self.size_option = OptionButton(
            self.size_host, values=values, command=self._on_size_option,
            width=210, height=32, corner_radius=7, border_width=1,
            border_color=MGR_BORDER, fg_color=MGR_PANEL_BG,
            hover_color=MGR_HOVER, text_color=MGR_TEXT,
            font=ui_fonts.ui_font(13), anchor='w',
            popup_fg_color=MGR_PANEL_BG, popup_hover_color=MGR_HOVER,
            popup_text_color=MGR_TEXT, popup_border_color=MGR_BORDER,
            popup_height=220
        )
        self.size_option.pack(side='left')
        self.size_option.set(size_level_text(self.size_var.get()))

    def _on_size_option(self, label):
        key = self._size_key_by_label.get(label)
        if not key or key == self.size_var.get():
            return
        self.size_var.set(key)
        self.on_size_changed()

    def _create_type_view_button(self):
        self.type_view_btn = ctk.CTkButton(
            self.head_right, text="▦ 类型视图", width=104, height=32,
            corner_radius=7, fg_color="transparent",
            hover_color=QUIP_TYPEVIEW_HOVER, text_color=QUIP_TYPEVIEW,
            font=ui_fonts.ui_font(13), command=self.toggle_type_view
        )
        self.type_view_btn.pack(side='right')

    def _create_lint_widget(self):
        """校验结论：卡片视图与类型视图都停在右下角。"""
        self.lint_btn = self._make_lint_btn(self.pane_footer, side='right')
        self.type_status_host = ctk.CTkFrame(
            self.type_view, fg_color="transparent", width=0, height=0)
        self.type_status_host.place(relx=1.0, rely=1.0, anchor='se',
                                    x=-16, y=-5)
        self.type_status_host.lift()
        self.type_lint_btn = self._make_lint_btn(self.type_status_host)

    def _make_lint_btn(self, parent, side='left', padx=0):
        btn = ctk.CTkButton(
            parent, text="", width=180, height=24, corner_radius=6,
            border_width=0, fg_color=MGR_HOVER, hover_color=MGR_BORDER_STRONG,
            text_color=QUIP_TEXT_SOFT, font=ui_fonts.ui_font(12),
            command=self.run_check
        )
        btn.pack(side=side, padx=padx)
        btn.pack_forget()
        return btn

    # ---------- 类型视图切换 ----------
    def toggle_type_view(self):
        if getattr(self, 'type_view_active', False):
            self._hide_type_view()
        else:
            self._show_type_view()

    def _show_type_view(self):
        self.type_view_active = True
        self._hide_workspace()
        self.type_view.pack(fill='both', expand=True, padx=12, pady=(10, 12))
        self.type_view_btn.configure(text="↩ 返回描述")
        self.type_view.refresh_matches()

    def _hide_type_view(self):
        self.type_view_active = False
        self.type_view.pack_forget()
        self._show_workspace()
        self.type_view_btn.configure(text="▦ 类型视图")
        self.refresh_ui()

    def _refresh_active_view(self):
        self.refresh_ui()

    def _after_refresh(self):
        if getattr(self, 'type_view_active', False):
            self.type_view.refresh_matches()

    # ---------- 校验 ----------
    def _build_lint_report(self):
        """按当前风格 + 当前观测等级构造检查报告；无数据时返回 None。"""
        style = self._get_current_style()
        size = self.size_var.get()
        if not style:
            return None
        matrix = {}
        for item in self.all_items:
            matrix.setdefault((item['intrusion'], item['destruction']), []).append({
                'text': item['text'],
                'style': item.get('style', style),
                'step': item.get('step', 1.0),
                'summary': item.get('summary', ''),
            })
        if not matrix:
            return None
        data = {size: matrix, "_meta": self.quip_repo.load_meta(style)}
        return lint_style(style, data, size_cat=size)

    def _lint_color(self, letter):
        return self._type_color(letter) or MGR_TEXT_SOFT

    def update_lint_summary(self):
        """把当前档位的校验结论压成一行，停在两种视图各自的右下角。"""
        if not hasattr(self, "lint_btn"):
            return
        report = self._build_lint_report() if self.all_items else None
        if report is None:
            self.pane_footer.pack_forget()
            self.type_lint_btn.pack_forget()
            return

        counts = Counter(f.level for f in report.sorted_findings())
        errors = counts.get("error", 0)
        warns = counts.get("warn", 0)
        infos = counts.get("info", 0)
        if errors:
            text = f"校验 {errors} 错误"
            if warns:
                text += f" · {warns} 警告"
            color = self._lint_color("a")
        elif warns:
            text = f"校验 {warns} 警告"
            if infos:
                text += f" · {infos} 提示"
            color = self._lint_color("d")
        elif infos:
            text = f"校验 {infos} 提示"
            color = self._lint_color("c")
        else:
            text = "校验通过"
            color = self._lint_color("b")

        self.lint_btn.configure(text=f"● {text} ›", text_color=color)
        self.pane_footer.pack(side='bottom', fill='x', padx=16, pady=(0, 7))
        self.lint_btn.pack(side='right')
        self.type_lint_btn.configure(text=f"● {text} ›", text_color=color)
        self.type_lint_btn.pack(side='left')

    def run_check(self):
        """校验当前风格 + 当前观测等级，结论交给 ``QuipLintDialog``。

        范围与 ``python developer_tools/quip_report.py <风格> <尺寸档>`` 一致：一次只查
        一档。换档请先关掉结论窗口再切观测等级——全量结论读不动，两边都不提供全档。

        送检的是页面上此刻的数据（``all_items``）而不是再读一遍 CSV：校验看到的必须
        等于用户看到的，定位也按同一份下标反查。
        """
        style = self._get_current_style()
        size = self.size_var.get()
        if not style:
            return
        self.load_items()
        report = self._build_lint_report()
        if report is None:
            ui.ctk.dialogs.showinfo(
                "无可校验内容", f"风格 {style} 在 {size} 档下还没有描述。")
            return
        QuipLintDialog(self, report, on_locate=self.locate_finding)

    def locate_finding(self, loc):
        """校验结论 → 对应条目 → 打开编辑框（loc 由 quip_lint 溯源给出）。"""
        item = self._item_for_loc(loc)
        if item is None:
            ui.ctk.dialogs.showwarning(
                "定位失败", "这条结论对应的描述已不存在（可能刚被改动），请重新校验。")
            return
        self.edit_item(item)

    def _item_for_loc(self, loc):
        """按坐标 + 条目下标反查 ``all_items`` 里的条目。

        条目下标是**该坐标下**的序号（与扫描顺序一致），不是整页的扁平下标。
        """
        if not loc:
            return None
        try:
            intr, dest = (int(p) for p in str(loc.get("coord", "")).split("_"))
        except ValueError:
            return None
        same = [item for item in self.all_items
                if item["intrusion"] == intr and item["destruction"] == dest]
        idx = loc.get("entry_idx")
        if not same:
            return None
        if idx is None or not (0 <= idx < len(same)):
            return same[0]
        return same[idx]

    # ---------- 风格 / 体型变更 ----------
    def _display_for_style(self, style):
        for display, sid in getattr(self, "_style_display_map", {}).items():
            if sid == style:
                return display
        return style

    def _set_combo_to_current_style(self):
        self.style_var.set(self._display_for_style(self._get_current_style()))

    def refresh_styles(self):
        styles = self.quip_repo.get_styles()
        self._rebuild_dropdown()
        current = self._get_current_style()
        if current not in styles:
            current = styles[0] if styles else DEFAULT_QUIP_STYLE
            self._set_current_style(current)
        self.style_var.set(self._display_for_style(current))

    def on_size_changed(self):
        self._clear_search()
        self.refresh_ui()
        self._reset_scroll(self.rows)

    def update_theme(self, theme_mode: str):
        super().update_theme(theme_mode)
        if hasattr(self, 'type_view'):
            self.type_view.update_theme(theme_mode)
        self.update_lint_summary()

    # ---------- 数据加载与保存 ----------
    def load_items(self):
        style = self._get_current_style()
        size = self.size_var.get()
        quips = self.quip_repo.load(style)
        matrix = quips.get(size, {})
        items = []
        for (intr, dest), qlist in matrix.items():
            for q in qlist:
                step = q.get('step', 1.0)
                q_style = q.get('style', style)
                clean, summary = self.split_summary(q)
                item = {
                    'text': clean,
                    'style': q_style,
                    'step': step,
                    'intrusion': int(intr),
                    'destruction': int(dest),
                    'summary': summary
                }
                items.append(item)
        self.all_items = items

    def save_items(self, items):
        style = self._get_current_style()
        size = self.size_var.get()
        quips = self.quip_repo.load(style)
        new_matrix = {}
        for item in items:
            key = (item['intrusion'], item['destruction'])
            new_matrix.setdefault(key, []).append({
                'text': item['text'],
                'style': item.get('style', style),
                'step': item.get('step', 1.0),
                'summary': item.get('summary', ''),
            })
        quips[size] = new_matrix
        self.quip_repo.save(style, quips)
        self.gui.load_combined_quips()
        self.all_items = items
        self.refresh_ui()

    # ---------- 分类与行内容 ----------
    def get_category(self, item):
        return f"介入{item['intrusion']} 破坏{item['destruction']}"

    def get_card_display(self, item):
        return {
            "简介": item['summary'] or "无简介",
            "介入": f"{item['intrusion']}",
            "破坏": f"{item['destruction']}",
            "步进": f"{item.get('step', 1.0):.2f}"
        }

    @staticmethod
    def _parse_category(key):
        parts = str(key or "").split()
        try:
            return (int(parts[0].replace("介入", "")),
                    int(parts[1].replace("破坏", "")))
        except (IndexError, ValueError):
            return (1, 1)

    def category_label(self, key):
        i, d = self._parse_category(key)
        return f"介入 {i} · 破坏 {d}"

    def category_keys(self):
        return [f"介入{i} 破坏{d}" for d in range(1, 5) for i in range(1, 5)]

    def selector_note(self):
        filled = sum(1 for key in self.category_keys()
                     if self.category_count(key))
        return f"{filled} / 16 格"

    def empty_hint(self, key):
        i, d = self._parse_category(key)
        return f"点「添加描述」会把 介入 {i} / 破坏 {d} 预填进对话框"

    def build_selector(self, parent):
        groups = self._groups
        keys = self.category_keys()
        max_count = max((len(groups.get(k, ())) for k in keys), default=0)
        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill='x')
        for col in range(1, 5):
            grid.grid_columnconfigure(col, weight=1, uniform="qcell")
        ctk.CTkLabel(
            grid, text="条数", font=ui_fonts.ui_font(10),
            text_color=MGR_TEXT_MUTED
        ).grid(row=0, column=0, sticky='sw', padx=(2, 0), pady=(0, 3))
        for i in range(1, 5):
            ctk.CTkLabel(
                grid, text=f"介入 {i}", font=ui_fonts.ui_font(10),
                text_color=MGR_TEXT_MUTED
            ).grid(row=0, column=i, sticky='s', pady=(0, 3))
        for d in range(1, 5):
            ctk.CTkLabel(
                grid, text=f"破坏 {d}", font=ui_fonts.ui_font(10),
                text_color=MGR_TEXT_MUTED, anchor='e'
            ).grid(row=d, column=0, sticky='e', padx=(0, 3), pady=2)
            for i in range(1, 5):
                key = f"介入{i} 破坏{d}"
                count = len(groups.get(key, ()))
                selected = key == self.current_category
                cell = ctk.CTkButton(
                    grid, text=str(count), height=40, corner_radius=8,
                    font=(ui_fonts.ui_font(14, "bold") if count
                          else ui_fonts.ui_font(13)),
                    fg_color=(MGR_PANEL_BG if selected
                              else self.heat_color(count, max_count)),
                    hover_color=MGR_HOVER,
                    border_width=2 if selected else 1,
                    border_color=(MGR_BORDER_STRONG if selected
                                  else MGR_BORDER),
                    text_color=MGR_TEXT if count else MGR_TEXT_MUTED,
                    command=lambda k=key: self._select_category(k))
                cell.grid(row=d, column=i, sticky='nsew', padx=2, pady=2)

    def render_rail_extra(self, parent):
        i, d = self._parse_category(self.current_category)

        def block(eyebrow, pair):
            title, _, body = pair.partition("：")
            head = ctk.CTkFrame(parent, fg_color="transparent")
            head.pack(fill='x')
            ctk.CTkLabel(head, text=eyebrow, font=ui_fonts.ui_font(11),
                         text_color=MGR_TEXT_MUTED).pack(side='left')
            ctk.CTkLabel(head, text=title, font=ui_fonts.ui_font(13, "bold"),
                         text_color=MGR_TEXT_SOFT).pack(side='left',
                                                        padx=(6, 0))
            ctk.CTkLabel(
                parent, text=body, font=ui_fonts.ui_font(12),
                text_color=MGR_TEXT_SOFT, justify='left', anchor='w',
                wraplength=232).pack(fill='x', pady=(3, 0))

        block(f"介入度 {i}", INTRUSION_LEVELS[i])
        ctk.CTkFrame(parent, height=1, fg_color=MGR_BORDER).pack(
            fill='x', pady=9)
        block(f"破坏性 {d}", DESTRUCTION_LEVELS[d])

    def search_text(self, item):
        return f"{item.get('summary', '')} {self._strip_tags(item.get('text', ''))}"

    def row_title(self, item):
        return item.get('summary') or "无简介"

    def row_preview(self, item):
        return self._clip(self._strip_tags(item.get('text', '')), 34)

    def row_meta(self, item):
        return (f"步进 {item.get('step', 1.0):.2f} · "
                f"{self._display_len(item.get('text', ''))} 字")

    def pane_subtitle(self, items):
        if not items:
            return "0 条描述"
        steps = [float(it.get('step', 1.0)) for it in items]
        return (f"{len(items)} 条 · 步进 "
                f"{min(steps):.2f}–{max(steps):.2f}")

    def _strip_tags(self, text):
        return self.TAG_RE.sub(r'\3', text or '')

    def _display_len(self, text):
        return len(self._strip_tags(text))

    def build_row_detail(self, parent, item):
        card = ctk.CTkFrame(parent, fg_color=MGR_PANEL_BG, corner_radius=8)
        card.pack(fill='x')

        text = item.get('text', '')
        display, spans = self._tagged_text(text)
        try:
            scaling = self._get_widget_scaling()
            width = max(240, self.rows.winfo_width() / scaling - 60)
        except Exception:
            width = 420
        per_line = max(16, int(width / 13))
        lines = max(1, math.ceil(len(display) / per_line))
        height = max(56, min(240, 12 + lines * 21))

        textbox = ctk.CTkTextbox(
            card, fg_color="transparent", border_width=0, height=height,
            wrap="word", font=ui_fonts.ui_font(13),
            text_color=MGR_TEXT,
            scrollbar_button_color=MGR_HOVER,
            scrollbar_button_hover_color=MGR_BORDER
        )
        textbox.pack(fill='x', padx=9, pady=(8, 0))
        textbox.insert("0.0", display)
        for start, end, color in spans:
            tag_name = f"tag_{start}_{end}"
            textbox._textbox.tag_configure(tag_name, foreground=color)
            textbox._textbox.tag_add(
                tag_name, f"1.0+{start}c", f"1.0+{end}c")
        textbox.configure(state="disabled")

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill='x', padx=8, pady=(6, 7))

        def add_action(text, command, width=54, danger=False):
            ctk.CTkButton(
                actions, text=text, command=command, width=width, height=26,
                corner_radius=6, border_width=0, fg_color="transparent",
                hover_color=MGR_ERR_HOVER if danger else MGR_HOVER,
                text_color=MGR_ERR if danger else MGR_TEXT_SOFT,
                font=ui_fonts.ui_font(12)
            ).pack(side='left', padx=1)

        add_action("编辑", lambda: self.edit_item(item), width=46)
        add_action("复制到…", lambda: self.copy_item(item), width=68)
        add_action("移动到…", lambda: self.move_item(item), width=68)
        add_action("删除", lambda: self.delete_item(item), width=46,
                   danger=True)

        ctk.CTkLabel(
            actions,
            text=(f"介入 {item.get('intrusion')} · "
                  f"破坏 {item.get('destruction')} · "
                  f"步进 {item.get('step', 1.0):.2f}"),
            font=ui_fonts.ui_font(12), text_color=MGR_TEXT_MUTED
        ).pack(side='right')

    # ---------- 复制 / 移动 ----------
    def copy_item(self, item):
        self._copy_move_item(item, copy=True)

    def move_item(self, item):
        self._copy_move_item(item, copy=False)

    def _select_target_dialog(self, src_intr, src_dest, src_size):
        gui_select = getattr(self.gui, '_select_target_dialog', None)
        if gui_select is not None:
            return gui_select(src_intr, src_dest, src_size)
        dlg = _TargetSelectDialog(self, src_intr, src_dest, src_size)
        return dlg.result

    def _copy_move_item(self, item, copy=True):
        src_intr, src_dest = item['intrusion'], item['destruction']
        src_size = self.size_var.get()

        result = self._select_target_dialog(src_intr, src_dest, src_size)
        if not result:
            return
        target_size, target_intr, target_dest = result

        if not copy and target_size == src_size and target_intr == src_intr and target_dest == src_dest:
            ui.ctk.dialogs.showwarning("警告", "不能移动到相同位置")
            return

        style = self._get_current_style()
        quips = self.quip_repo.load(style)

        if target_size not in quips:
            quips[target_size] = {}
        key = (target_intr, target_dest)
        if key not in quips[target_size]:
            quips[target_size][key] = []
        moved = {
            'text': item['text'],
            'style': item.get('style', style),
            'step': item.get('step', 1.0),
            'summary': item.get('summary', ''),
        }
        quips[target_size][key].append(moved)

        if not copy:
            src_key = (src_intr, src_dest)
            if src_size in quips and src_key in quips[src_size]:
                lst = quips[src_size][src_key]
                to_remove = None
                for q in lst:
                    if q.get('text') == moved['text'] and q.get('step') == item.get('step', 1.0):
                        to_remove = q
                        break
                if to_remove:
                    lst.remove(to_remove)
                if not lst:
                    del quips[src_size][src_key]

        self.quip_repo.save(style, quips)
        self.refresh_ui()

        action = "复制" if copy else "移动"
        ui.ctk.dialogs.showinfo("成功", f"已{action}描述至 {target_size} {target_intr}/{target_dest}")

    # ---------- 增删改 ----------
    def add_item_in_category(self):
        default_intr, default_dest = self._parse_category(
            self.current_category)

        dlg = QuipDialog(
            self, "添加描述",
            intrusion=default_intr,
            destruction=default_dest,
            style_name=self._get_current_style(),
            quip_repo=self.quip_repo,
            step=None
        )
        if dlg.result:
            clean_text = dlg.result["quip"]
            summary = dlg.result.get("summary", "").strip()
            if not summary:
                clean_text, summary = self.extract_summary(clean_text)
            step = dlg.result.get("step", QuipRepo.default_step(default_intr, default_dest))
            new_item = {
                'text': clean_text,
                'style': self._get_current_style(),
                'step': step,
                'intrusion': int(dlg.result["intrusion"]),
                'destruction': int(dlg.result["destruction"]),
                'summary': summary
            }
            self.all_items.append(new_item)
            self.save_items(self.all_items)

    def edit_item(self, item):
        dlg = QuipDialog(
            self, "编辑描述",
            quip=item['text'],
            intrusion=item['intrusion'],
            destruction=item['destruction'],
            summary=item['summary'],
            style_name=self._get_current_style(),
            quip_repo=self.quip_repo,
            step=item.get('step', None)
        )
        if dlg.result:
            new_clean = dlg.result["quip"]
            new_summary = dlg.result.get("summary", "").strip()
            if not new_summary:
                new_clean, new_summary = self.extract_summary(new_clean)
            new_step = dlg.result.get("step", item.get('step', 1.0))
            item['text'] = new_clean
            item['summary'] = new_summary
            item['step'] = new_step
            item['intrusion'] = int(dlg.result["intrusion"])
            item['destruction'] = int(dlg.result["destruction"])
            self.save_items(self.all_items)

    def delete_item(self, item):
        if ui.ctk.dialogs.askyesno("确认", "确定要删除这条描述吗？"):
            self.all_items.remove(item)
            self.save_items(self.all_items)

    # ---------- 模块切换 ----------
    def _on_module_switch(self, value):
        if value == "地标管理" and hasattr(self.gui, 'show_landmark_manager'):
            self.gui.show_landmark_manager()

    # ---------- 排序 ----------
    def sort_items(self, items):
        return sorted(items, key=lambda x: float(x.get('step', 1.0)))


class QuipTypeViewManager(TreeviewManager):
    """类型视图：以 Treeview 列出当前风格/体型下全部类型标记，行按类型着色。
    底部按钮：重命名(编辑自定义类型) / 编辑(源描述) / 删除(剥离标记外壳保留内容)，无上移下移。"""

    def __init__(self, parent, quip_mgr: 'QuipCardManager'):
        self.quip_mgr = quip_mgr
        self.quip_repo = quip_mgr.quip_repo
        self._matches = []
        super().__init__(
            parent, repository=None,
            columns=[("类型", 60, "type"), ("细分", 60, "subtype"),
                     ("内容", 220, "content"), ("上下文片段", 450, "snippet")],
            item_name="类型标记"
        )
        self.toolbar_frame.pack_forget()
        self._rearrange_buttons()

    # ---------- UI ----------

    def _rearrange_buttons(self):
        for child in self.button_frame.winfo_children():
            child.destroy()

        _btn_style = dict(fg_color="transparent", border_width=1, corner_radius=8,
                          font=ui_fonts.ui_font(13))
        _btn_text = QUIP_TEXT_SOFT
        _btn_hover = QUIP_HOVER
        _btn_border = QUIP_BORDER_STRONG

        left_frame = ctk.CTkFrame(self.button_frame, fg_color="transparent")
        left_frame.pack(side='left', fill='x', expand=True)

        ctk.CTkButton(left_frame, text="重命名", command=self.rename_types, width=90,
                      text_color=_btn_text, hover_color=_btn_hover,
                      border_color=_btn_border, **_btn_style).pack(side='left', padx=5)
        ctk.CTkButton(left_frame, text="编辑", command=self.edit_item, width=90,
                      text_color=_btn_text, hover_color=_btn_hover,
                      border_color=_btn_border, **_btn_style).pack(side='left', padx=5)
        ctk.CTkButton(left_frame, text="删除", command=self.delete_item, width=90,
                      fg_color="transparent", border_width=1, corner_radius=8,
text_color=QUIP_ERR,
                hover_color=QUIP_ERR_HOVER,
                border_color=QUIP_ERR,
                      font=ui_fonts.ui_font(13)).pack(side='left', padx=5)

    def update_theme(self, theme_mode: str):
        super().update_theme(theme_mode)
        for letter, colors in QUIP_TYPE_COLORS.items():
            color = colors[1] if theme_mode == "Dark" else colors[0]
            self.tree.tag_configure(f"type_{letter}", foreground=color)

    # ---------- 数据 ----------
    def refresh_matches(self):
        self.load_matches()
        self.refresh_list()

    def load_matches(self):
        self.quip_mgr.load_items()
        items = self.quip_mgr.all_items

        style = self.quip_mgr._get_current_style()
        meta = self.quip_repo.load_meta(style)
        custom_types = meta.get("custom_types", {})
        builtin_type_names = {'a': '衣着', 'b': '姿势'}
        builtin_subtypes = {
            'a': ["裙子", "制服", "夏季", "冬季"],
            'b': ["站立", "坐下", "躺下", "蹲跪"]
        }

        matches = []
        pattern = re.compile(r'\[([a-e]):(\d+):([^\]]*)\]')
        for idx_in_items, item in enumerate(items):
            clean_text = item['text']
            for m in pattern.finditer(clean_text):
                letter = m.group(1)
                idx = int(m.group(2))
                content = m.group(3)
                start, end = m.span()

                if letter in builtin_subtypes:
                    type_name = builtin_type_names.get(letter, letter.upper())
                    subtypes = builtin_subtypes[letter]
                    subtype_name = subtypes[idx - 1] if 1 <= idx <= len(subtypes) else f"未知{idx}"
                elif letter in custom_types:
                    info = custom_types[letter]
                    type_name = info.get("name", f"自定义{letter.upper()}")
                    subtypes = info.get("subtypes", [])
                    subtype_name = subtypes[idx - 1] if 1 <= idx <= len(subtypes) else f"细分{idx}"
                else:
                    type_name = f"未知类型{letter}"
                    subtype_name = f"索引{idx}"

                ctx_start = max(0, start - 5)
                ctx_end = min(len(clean_text), end + 5)
                snippet = clean_text[ctx_start:ctx_end]
                matches.append((letter, idx, type_name, subtype_name, content,
                                snippet, idx_in_items, start))

        letter_order = {'a': 0, 'b': 1, 'c': 2, 'd': 3, 'e': 4}
        matches.sort(key=lambda x: (letter_order.get(x[0], 99), x[1]))
        self._matches = matches

    def get_items(self):
        return self._matches

    def get_item_values(self, item):
        letter, idx, tname, sname, cont, snippet, item_idx, start = item
        return (tname, sname, cont, snippet)

    def refresh_list(self):
        self.tree.delete(*self.tree.get_children())
        for i, match in enumerate(self._matches):
            tags = [f"type_{match[0]}"]
            if i % 2 == 0:
                tags.append("evenrow")
            self.tree.insert("", "end", values=self.get_item_values(match), tags=tuple(tags))

    # ---------- 操作 ----------
    def rename_types(self):
        self.quip_mgr.edit_custom_types(on_saved=self.refresh_matches)

    def edit_item(self):
        match = self.get_selected_item()
        if match is None:
            ui.ctk.dialogs.showwarning("警告", "请先选择一个类型标记")
            return
        item_idx = match[6]
        items = self.quip_mgr.all_items
        if not (0 <= item_idx < len(items)):
            ui.ctk.dialogs.showwarning("警告", "源描述已失效，请刷新")
            return
        self.quip_mgr.edit_item(items[item_idx])
        self.refresh_matches()

    def delete_item(self):
        match = self.get_selected_item()
        if match is None:
            ui.ctk.dialogs.showwarning("警告", "请先选择一个类型标记")
            return
        letter, idx, tname, sname, cont, snippet, item_idx, start = match
        items = self.quip_mgr.all_items
        if not (0 <= item_idx < len(items)):
            ui.ctk.dialogs.showwarning("警告", "源描述已失效，请刷新")
            return
        target_item = items[item_idx]
        text = target_item['text']
        m = re.match(rf'\[{letter}:{idx}:([^\]]*)\]', text[start:])
        if not m:
            ui.ctk.dialogs.showwarning("警告", "未找到对应类型标记，可能已被修改")
            return
        inner = m.group(1)
        target_item['text'] = text[:start] + inner + text[start + len(m.group(0)):]
        self.quip_mgr.save_items(items)
        self.refresh_matches()

    def create_item_dialog(self, item=None):
        return None

    def save_items(self, items):
        pass


