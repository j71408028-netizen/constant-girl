import os
import re
import threading
import tkinter as tk

import customtkinter as ctk

import services.worlds.address_registry as address_registry
import ui.ctk.dialogs
from core.models import Landmark, is_valid_landmark_size
from core.logic import format_size
from persistence.landmark_repo import LandmarkRepo, DEFAULT_LANDMARK_STYLE
from services.challenges import (
    challenge_pack_titles, get_challenge_packs, import_landmark_challenge_pack,
    unique_display,
)
from ui.ctk.dialogs import BaseDialog
from ui.ctk.managers import CardManager
from ui.ctk.widgets import CTkScrollableDropdownFrame
from ui.ctk.address_dlg import AddressTextDialog
from core.address_model import format_addr_verbose
from ui.ctk.theme import (
    LM_TEXT_SOFT, LM_TEXT_MUTED, LM_LINK,
    MGR_BORDER, MGR_BORDER_STRONG, MGR_ERR, MGR_ERR_HOVER, MGR_HOVER,
    MGR_PANEL_BG, MGR_TEXT, MGR_TEXT_SOFT, MGR_TEXT_MUTED,
)
from ui.ctk import fonts as ui_fonts


class LandmarkCardManager(CardManager):
    RESOURCE_TYPE = "landmarks"
    RAIL_HEAD = "尺寸档"
    ITEM_UNIT = "个"

    SIZE_RANGES = [
        (0, 3, "0~3米"),
        (3, 10, "3~10米"),
        (10, 30, "10~30米"),
        (30, 100, "30~100米"),
        (100, 300, "100~300米"),
        (300, 1000, "300~1000米"),
        (1000, 3000, "1~3千米"),
        (3000, 10000, "3~10千米"),
        (10000, 30000, "10~30千米"),
        (30000, 100000, "30~100千米"),
        (100000, 300000, "100~300千米"),
        (300000, float("inf"), "300千米以上"),
    ]

    def __init__(self, parent, landmark_repo: LandmarkRepo, settings_repo, gui_ref):
        self.landmark_repo = landmark_repo
        self._settings_repo = settings_repo
        self.style_var = tk.StringVar()
        super().__init__(parent, gui_ref, item_name="地标")
        self.create_style_widgets(self.style_host)
        self.refresh_styles()
        self.refresh_ui()

    # ----- 实现基类抽象方法 -----
    def _get_style_list(self):
        return self.landmark_repo.get_styles()

    def _get_current_style(self):
        return self.gui.current_style

    def _set_current_style(self, style):
        self.gui.current_style = style

    def _get_default_style(self):
        return DEFAULT_LANDMARK_STYLE

    def _create_style_impl(self, style_id, title):
        self.landmark_repo.create_style(style_id, title=title)

    def _set_style_title_impl(self, style_id, title):
        self.landmark_repo.set_title(style_id, title)

    def _style_display_name(self, style_id):
        return self.landmark_repo.display_name(style_id)

    def _delete_style_impl(self, name):
        self.landmark_repo.delete_style(name)

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
        current = self.landmark_repo.load_style_address(style)
        dlg = AddressTextDialog(
            self, "地标风格注册地址",
            description=(
                "注册该地标风格所在的地址。只能选择已申领的地址"
                "（详见 docs/designs/address-system/authoring.md）。\n"
                "当前风格：" + self._style_display_name(style)
            ),
            initial=current, landmark_style=True)
        if dlg.result is not None:
            self.landmark_repo.save_style_address(style, dlg.result)
            # 风格注册地址变了 → 已解析的地标地址全部作废，重建地址索引
            self.gui.context.invalidate_addresses()
            if dlg.result:
                ui.ctk.dialogs.showinfo(
                    "已保存",
                    f"已保存风格注册地址：{format_addr_verbose(dlg.result)}。")
            else:
                ui.ctk.dialogs.showinfo(
                    "已保存", "已清除风格注册地址（该风格地标不参与地址规则）。")

    def _get_challenge_packs_with_keys(self):
        packs = get_challenge_packs(self._settings_repo)
        return packs

    def _build_combined_items(self):
        """下拉条目：显示名在前（选择回 id），挑战包导入项挂在末尾。"""
        styles = self.landmark_repo.get_styles()
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
            text_colors[display] = LM_LINK
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
                imported = import_landmark_challenge_pack(self._settings_repo, pack_name, self.landmark_repo)
            except ValueError as e:
                ui.ctk.dialogs.showerror("错误", str(e))
                self._set_combo_to_current_style()
                return
            self.refresh_styles()
            self._clear_search()
            self.refresh_ui()
            self._reset_scroll(self.rows)
            self.gui.load_combined_landmarks()
            ui.ctk.dialogs.showinfo("成功", f"已从挑战包导入 {imported} 条地标数据")
        else:
            new_style = getattr(self, "_style_display_map", {}).get(choice, choice)
            if new_style == self._get_current_style():
                return
            self._set_current_style(new_style)
            self._clear_search()
            self.refresh_ui()
            self._reset_scroll(self.rows)
            self.gui.sync_landmark_styles_state()

    def _set_combo_to_current_style(self):
        current = self._get_current_style()
        self.style_var.set(self._style_display_name(current))

    def refresh_styles(self):
        self.styles = self.landmark_repo.get_styles()
        self._rebuild_dropdown()
        if self.gui.current_style not in self.styles:
            self.gui.current_style = self.styles[0] if self.styles else DEFAULT_LANDMARK_STYLE
        self.style_var.set(self._style_display_name(self.gui.current_style))

    # ---------- 数据加载与保存 ----------
    def load_items(self):
        self.all_items = self.landmark_repo.load(self.gui.current_style)

    def save_items(self, items):
        self.gui.landmarks = items
        self.landmark_repo.save(self.gui.current_style, items)
        self.gui.load_combined_landmarks()
        self.all_items = items
        self.refresh_ui()

    # ---------- 尺寸分类 ----------
    @staticmethod
    def _size_category(size):
        for low, high, name in LandmarkCardManager.SIZE_RANGES:
            if low <= size < high:
                return name
        return "300千米以上"

    def get_category(self, item):
        return self._size_category(item.size)

    def get_card_display(self, item):
        return {
            "名称": item.name,
            "尺寸": format_size(item.size),
            "属性": f"{self._dim_text(item)} | {self._freq_text(item)}"
        }

    @staticmethod
    def _dim_text(item):
        if item.dimension == "vertical":
            return "高"
        return "长" if item.horizontal_type == "length" else "宽"

    @staticmethod
    def _freq_text(item):
        return "精确" if item.frequency == "unique" else "均值"

    # ---------- 分组 / 行内容 ----------
    def category_keys(self):
        return [name for _low, _high, name in self.SIZE_RANGES]

    def selector_note(self):
        filled = sum(1 for key in self.category_keys()
                     if self.category_count(key))
        return f"{filled} / {len(self.SIZE_RANGES)} 档"

    def empty_hint(self, key):
        return f"点「添加地标」把尺寸填进 {key} 即可"

    def build_selector(self, parent):
        groups = self._groups
        keys = self.category_keys()
        max_count = max((len(groups.get(k, ())) for k in keys), default=0)
        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill='x')
        for col in range(2):
            grid.grid_columnconfigure(col, weight=1, uniform="lmcell")
        for idx, key in enumerate(keys):
            row, col = divmod(idx, 2)
            count = len(groups.get(key, ()))
            selected = key == self.current_category
            heat = self.heat_color(count, max_count)
            chip = ctk.CTkFrame(
                grid, corner_radius=8,
                border_width=2 if selected else 1,
                border_color=(MGR_BORDER_STRONG if selected else MGR_BORDER),
                fg_color=MGR_PANEL_BG if selected else heat)
            chip.grid(row=row, column=col, sticky='nsew', padx=2, pady=2)
            name = ctk.CTkLabel(
                chip, text=str(key), font=ui_fonts.ui_font(12),
                text_color=MGR_TEXT if count else MGR_TEXT_MUTED,
                anchor='w')
            name.pack(side='left', fill='x', expand=True, padx=(8, 0),
                      pady=6)
            number = ctk.CTkLabel(
                chip, text=str(count), font=ui_fonts.ui_font(11),
                text_color=MGR_TEXT_SOFT)
            number.pack(side='right', padx=(4, 8))

            def on_enter(_event=None, f=chip, sel=selected):
                if not sel:
                    f.configure(fg_color=MGR_HOVER)

            def on_leave(_event=None, f=chip, sel=selected, fill=heat):
                if not sel:
                    f.configure(fg_color=fill)

            for widget in (chip, name, number):
                widget.configure(cursor="hand2")
                widget.bind("<Button-1>",
                            lambda _e, k=key: self._select_category(k),
                            add="+")
                widget.bind("<Enter>", on_enter, add="+")
                widget.bind("<Leave>", on_leave, add="+")

    def sort_items(self, items):
        return sorted(items, key=lambda x: x.size)

    def search_text(self, item):
        return f"{item.name} {item.address or ''} " \
               f"{self._dim_text(item)} {self._freq_text(item)}"

    def row_title(self, item):
        return item.name

    def row_preview(self, item):
        addr = (item.address or "").strip() or "未绑定地址"
        return self._clip(
            f"{self._dim_text(item)}方向 · {self._freq_text(item)} · {addr}",
            40)

    def row_meta(self, item):
        return format_size(item.size)

    def pane_subtitle(self, items):
        if not items:
            return "0 个地标"
        sizes = [item.size for item in items]
        return (f"{len(items)} 个 · {format_size(min(sizes))}–"
                f"{format_size(max(sizes))}")

    def build_row_detail(self, parent, item):
        card = ctk.CTkFrame(parent, fg_color=MGR_PANEL_BG, corner_radius=8)
        card.pack(fill='x')

        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill='x', padx=12, pady=(10, 4))
        addr = (item.address or "").strip() or "未绑定地址"
        pairs = [
            ("尺寸", format_size(item.size)),
            ("方向", self._dim_text(item)),
            ("频率", self._freq_text(item)),
            ("地址", addr),
        ]
        for idx, (label, value) in enumerate(pairs):
            row, col = divmod(idx, 2)
            ctk.CTkLabel(
                grid, text=label, font=ui_fonts.ui_font(12),
                text_color=MGR_TEXT_MUTED
            ).grid(row=row, column=col * 2, sticky='w', padx=(0, 6), pady=3)
            ctk.CTkLabel(
                grid, text=value, font=ui_fonts.ui_font(13),
                text_color=MGR_TEXT, anchor='w', justify='left',
                wraplength=200
            ).grid(row=row, column=col * 2 + 1, sticky='w',
                   padx=(0, 16), pady=3)
        grid.grid_columnconfigure(1, weight=1)
        grid.grid_columnconfigure(3, weight=1)

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
        add_action("删除", lambda: self.delete_item(item), width=46,
                   danger=True)

        ctk.CTkLabel(
            actions, text=f"分组：{self.get_category(item)}",
            font=ui_fonts.ui_font(12), text_color=MGR_TEXT_MUTED
        ).pack(side='right')

    # ---------- 增删改实现 ----------
    def _current_style_address(self) -> str:
        """当前风格的注册地址（供地标地址下拉确定子地址树范围）。"""
        style = self._get_current_style()
        if not style:
            return ""
        return self.landmark_repo.load_style_address(style)

    def add_item_in_category(self):
        dlg = LandmarkDialog(self, "添加地标", None,
                             style_address=self._current_style_address())
        if dlg.result:
            new_item = Landmark(
                name=dlg.result["name"],
                size=dlg.result["size"],
                dimension=dlg.result["dimension"],
                frequency=dlg.result["frequency"],
                horizontal_type=dlg.result.get("horizontal_type"),
                address=dlg.result.get("address", ""),
            )
            self.all_items.append(new_item)
            self.save_items(self.all_items)

    def edit_item(self, item):
        dlg = LandmarkDialog(self, "编辑地标", item,
                             style_address=self._current_style_address())
        if dlg.result:
            item.name = dlg.result["name"]
            item.size = dlg.result["size"]
            item.dimension = dlg.result["dimension"]
            item.frequency = dlg.result["frequency"]
            item.horizontal_type = dlg.result.get("horizontal_type")
            item.address = dlg.result.get("address", "")
            self.save_items(self.all_items)

    def delete_item(self, item):
        if ui.ctk.dialogs.askyesno("确认", f"确定要删除地标 '{item.name}' 吗？"):
            self.all_items.remove(item)
            self.save_items(self.all_items)

    def _on_module_switch(self, value):
        if value == "描述管理":
            if hasattr(self.gui, 'show_quip_manager'):
                self.gui.show_quip_manager()


class LandmarkDialog(BaseDialog):
    """地标编辑对话框"""

    def __init__(self, parent, title, landmark=None, style_address: str = ""):
        super().__init__(parent.winfo_toplevel())
        self.title(title)
        self.landmark = landmark
        self.result = None
        self._parent = parent.winfo_toplevel()   # 保存顶层父窗口引用
        self.style_address = (style_address or "").strip()

        # 在线注册表子地址下拉所需状态
        self._entries = []
        self._child_options = []
        self._display_map = {}
        self._addr_dropdown = None
        self._pending_fetch = None

        # 模态设置：抓取要等窗口在窗口系统里可见（X11 上先 grab 会报
        # "window not viewable"，见 ui/ctk/dialogs.BaseDialog._grab_deferred）
        self.transient(self._parent)
        self._grab_deferred()

        self._create_widgets()
        self.geometry("368x360")
        self._center_dialog(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._fetch_registry_async()

        # 等待窗口关闭后再返回
        self.wait_window()

    def _create_widgets(self):
        # 名称
        ctk.CTkLabel(self, text="名称:", font=self.UI_FONT_BOLD).grid(row=0, column=0, sticky='w', pady=(10,4), padx=(20,5))
        self.name_var = tk.StringVar(value=self.landmark.name if self.landmark else "")
        ctk.CTkEntry(self, textvariable=self.name_var, width=210, height=28,
                     font=self.UI_FONT).grid(row=0, column=1, pady=(10,4), padx=5)

        # 尺寸(米)
        ctk.CTkLabel(self, text="尺寸(米):", font=self.UI_FONT).grid(row=1, column=0, sticky='w', pady=(4,6), padx=(20,5))
        self.size_var = tk.StringVar(value=str(self.landmark.size) if self.landmark else "")
        ctk.CTkEntry(self, textvariable=self.size_var, width=210, height=28,
                     font=self.UI_FONT).grid(row=1, column=1, pady=(4,6), padx=5)

        # 地标方向：长、宽、高
        ctk.CTkLabel(self, text="方向:", font=self.UI_FONT).grid(row=2, column=0, sticky='w', pady=(6,4), padx=20)
        self.type_var = tk.StringVar()
        if self.landmark:
            if self.landmark.dimension == "vertical":
                self.type_var.set("vertical")
            elif self.landmark.dimension == "horizontal":
                self.type_var.set("width" if self.landmark.horizontal_type == "width" else "length")
            else:
                self.type_var.set("vertical")
        else:
            self.type_var.set("vertical")

        type_frame = ctk.CTkFrame(self, fg_color="transparent")
        type_frame.grid(row=2, column=1, sticky='w', pady=(6,4))
        ctk.CTkRadioButton(type_frame, text="长", variable=self.type_var, value="length",
                           font=self.UI_FONT).pack(side='left', padx=5)
        ctk.CTkRadioButton(type_frame, text="宽", variable=self.type_var, value="width",
                           font=self.UI_FONT).pack(side='left', padx=5)
        ctk.CTkRadioButton(type_frame, text="高", variable=self.type_var, value="vertical",
                           font=self.UI_FONT).pack(side='left', padx=5)

        # 类型选择
        ctk.CTkLabel(self, text="类型:", font=self.UI_FONT).grid(row=3, column=0, sticky='w', pady=4, padx=20)
        self.frequency_var = tk.StringVar(value=self.landmark.frequency if self.landmark else "unique")
        freq_frame = ctk.CTkFrame(self, fg_color="transparent")
        freq_frame.grid(row=3, column=1, sticky='w', pady=4)
        ctk.CTkRadioButton(freq_frame, text="精确", variable=self.frequency_var, value="unique",
                           font=self.UI_FONT).pack(side='left', padx=5)
        ctk.CTkRadioButton(freq_frame, text="均值", variable=self.frequency_var, value="common",
                           font=self.UI_FONT).pack(side='left', padx=5)

        # 独特地标注册地址（补在风格注册级别之下的剩余级别，可选）
        self.address_var = tk.StringVar(value=self.landmark.address if self.landmark else "")
        addr_hint = "地址(可选):"
        ctk.CTkLabel(self, text=addr_hint, font=self.UI_FONT).grid(
            row=4, column=0, sticky='w', pady=(4, 6), padx=(20, 5))
        addr_entry = ctk.CTkEntry(self, textvariable=self.address_var, width=210, height=28,
                                  font=self.UI_FONT)
        addr_entry.grid(row=4, column=1, pady=(4, 6), padx=5)
        ctk.CTkLabel(self, text="风格已注册时填剩余级（如 12-0），未注册时填完整地址（含维度）；"
                               "双击地址框可从注册表已申领的子地址中选择",
                     font=ui_fonts.ui_font(9), text_color=LM_TEXT_SOFT, wraplength=210,
                     justify='left').grid(
            row=5, column=1, sticky='w', pady=(0, 4), padx=5)

        # 已申领子地址下拉：双击地址框弹出（后台联网刷新，含尺度过滤）
        if self.style_address:
            self._addr_dropdown = CTkScrollableDropdownFrame(
                attach=addr_entry, values=[], command=self._on_pick_child,
                height=220, width=300, button_height=24, justify="left")
            self.size_var.trace_add("write", self._update_address_options)

        # 注册表加载状态（row=6）
        self.registry_status_var = tk.StringVar(value="")
        ctk.CTkLabel(self, textvariable=self.registry_status_var,
                     font=ui_fonts.ui_font(9), text_color=LM_TEXT_MUTED,
                     wraplength=210, justify='left', anchor='w').grid(
            row=6, column=1, sticky='w', pady=(0, 2), padx=5)

        # 确定/取消按钮
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=7, column=0, columnspan=2, pady=(8, 15))
        ctk.CTkButton(btn_frame, text="确定", command=self.ok, width=80,
                      height=28, font=self.UI_FONT).pack(side='left', padx=(0,7))
        ctk.CTkButton(btn_frame, text="取消", command=self._on_close, width=80,
                      height=28, font=self.UI_FONT).pack(side='left', padx=7)

    # ---------- 已申领子地址下拉（在线注册表） ----------

    def _fetch_registry_async(self):
        if not self.style_address:
            return
        self.registry_status_var.set("正在从注册表仓库获取已申领地址……")
        self._pending_fetch = None
        threading.Thread(target=self._fetch_worker, daemon=True).start()
        self.after(80, self._poll_fetch)

    def _fetch_worker(self):
        # 工作线程只写普通属性，不触碰 tkinter；由主线程轮询取结果。
        offline = False
        try:
            data, _updated = address_registry.download_registry()
            address_registry.save_cache(data, _updated)
        except address_registry.RegistryOfflineError:
            data = address_registry.load_cache().get("data") or {}
            offline = True
        self._pending_fetch = (address_registry.parse_entries(data), offline)

    def _poll_fetch(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        if self._pending_fetch is None:
            self.after(80, self._poll_fetch)
            return
        entries, offline = self._pending_fetch
        self._pending_fetch = None
        self._on_entries_loaded(entries, offline)

    def _on_entries_loaded(self, entries, offline):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._entries = entries
        self._update_address_options()
        if offline:
            self.registry_status_var.set(
                "⚠ 离线：显示本地缓存的已申领地址")
        elif not self._child_options:
            self.registry_status_var.set("注册表中没有该风格地址的已申领子地址")
        else:
            self.registry_status_var.set(
                f"已载入 {len(self._child_options)} 个已申领子地址，双击地址框选择")

    def _update_address_options(self, *_args):
        """按当前地标尺寸重建子地址候选（尺度小于地标的不推荐）。"""
        if self._addr_dropdown is None:
            return
        try:
            size = float(self.size_var.get())
        except (TypeError, ValueError):
            size = None
        opts = address_registry.child_options(
            self.style_address, self._entries, landmark_size=size)
        self._child_options = opts
        self._display_map = {o["display"]: o for o in opts}
        self._addr_dropdown.configure(
            values=[o["display"] for o in opts],
            disabled_values=[o["display"] for o in opts if not o["recommended"]])

    def _on_pick_child(self, display: str):
        opt = self._display_map.get(display)
        if opt is None:
            return
        if not opt["recommended"]:
            try:
                size = float(self.size_var.get())
            except (TypeError, ValueError):
                size = 0.0
            ui.ctk.dialogs.showinfo(
                "不推荐",
                f"子地址 {opt['value']} 的最细单元尺度小于地标尺寸"
                f"（{size:.4g} 米），已置为不推荐；如仍需使用请手动填写地址。")
            return
        self.address_var.set(opt["value"])

    def validate(self):
        if not self.name_var.get().strip():
            ui.ctk.dialogs.showwarning("警告", "请输入地标名称")
            return False
        # 除了正负，还要挡住 nan / inf：它们能通过除法，却会让对比结果失去意义
        if not is_valid_landmark_size(self.size_var.get()):
            ui.ctk.dialogs.showwarning("警告", "请输入有效的正数尺寸")
            return False
        return True

    def ok(self):
        if not self.validate():
            return
        type_choice = self.type_var.get()
        if type_choice == "vertical":
            dimension = "vertical"
            horizontal_type = None
        elif type_choice == "length":
            dimension = "horizontal"
            horizontal_type = "length"
        elif type_choice == "width":
            dimension = "horizontal"
            horizontal_type = "width"
        else:
            dimension = "vertical"
            horizontal_type = None

        self.result = {
            "name": self.name_var.get().strip(),
            "size": float(self.size_var.get()),
            "dimension": dimension,
            "frequency": self.frequency_var.get(),
            "horizontal_type": horizontal_type,
            "address": self.address_var.get().strip(),
        }
        self._on_close()

    def _on_close(self):
        """安全关闭对话框，释放抓取并销毁窗口"""
        try:
            self.grab_release()          # 释放模态抓取
        except Exception:
            pass
        self.withdraw()                 # 先隐藏，避免 CTk 缩放追踪器报错
        self.destroy()
        # 强制父窗口重获焦点并刷新，解决透明/冻结问题
        try:
            self._parent.focus_force()
            self._parent.update_idletasks()
        except Exception:
            pass
