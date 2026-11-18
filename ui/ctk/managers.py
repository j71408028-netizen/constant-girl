from tkinter import ttk
import tkinter as tk

import ui.ctk.dialogs
from typing import List, Any, Optional

import customtkinter as ctk

from ui.ctk.dialogs import ResourceNameDialog
from ui.ctk.theme import (
    MGR_BG, MGR_HEADER_BG, MGR_BORDER, MGR_BORDER_STRONG,
    MGR_HOVER, MGR_TEXT, MGR_TEXT_SOFT, MGR_OK,
    MGR_OK_HOVER, MGR_ERR, MGR_ERR_HOVER, MGR_ROW_STRIPE,
    MGR_ROW_SELECTED_BG, MGR_ROW_SELECTED_TEXT, MGR_ROW_DISABLED_TEXT,
    MGR_HEADER_TEXT, MGR_TEXT_MUTED, MGR_PLACEHOLDER, MGR_RAIL_BG,
    MGR_INPUT_BG, MGR_ROW_HOVER, MGR_ROW_OPEN, MGR_PRIMARY_BG,
    MGR_PRIMARY_HOVER, MGR_PRIMARY_TEXT, MGR_PANEL_BG, MGR_PAGE_BG,
)
from ui.ctk import fonts as ui_fonts


class TreeviewManager(ctk.CTkFrame):
    """
    通用数据库管理面板基类。
    提供 Treeview 列表、刷新、增删改按钮的标准实现。
    子类需重写部分方法以适配具体数据模型。
    """
    def __init__(self, parent, repository, columns: List[tuple],
                 title: str = "管理", item_name: str = "项目"):
        """
        :param parent: 父容器
        :param repository: 数据仓库实例
        :param columns: Treeview 列定义，格式 [(列标题, 宽度, 数据键名), ...]
        :param title: 标签页标题（未使用）
        :param item_name: 项目名称（仅用于提示，不再用于按钮文本）
        """
        super().__init__(parent, fg_color=MGR_BG)
        self.repository = repository
        self.columns = columns
        self.item_name = item_name
        self._create_ui()
        self.update_theme(ctk.get_appearance_mode())

    def update_theme(self, theme_mode: str):
        style = ttk.Style()
        if style.theme_use() != 'clam':
            style.theme_use('clam')

        if theme_mode == "Dark":
            bg_color = MGR_BG[1]
            alt_color = MGR_ROW_STRIPE[1]
            fg_color = MGR_TEXT[1]
            select_bg = MGR_ROW_SELECTED_BG[1]
            select_fg = MGR_ROW_SELECTED_TEXT[1]
            heading_bg = MGR_HEADER_BG[1]
            heading_fg = MGR_HEADER_TEXT[1]
            field_bg = MGR_BG[1]
            border_color = MGR_BORDER[1]
        else:
            bg_color = MGR_BG[0]
            alt_color = MGR_ROW_STRIPE[0]
            fg_color = MGR_TEXT[0]
            select_bg = MGR_ROW_SELECTED_BG[0]
            select_fg = MGR_ROW_SELECTED_TEXT[0]
            heading_bg = MGR_HEADER_BG[0]
            heading_fg = MGR_HEADER_TEXT[0]
            field_bg = MGR_BG[0]
            border_color = MGR_BORDER[0]

        style.configure("Custom.Treeview",
                        background=bg_color,
                        foreground=fg_color,
                        fieldbackground=field_bg,
                        # 行高随系统缩放走，175% 屏约等于原 38px 的观感
                        rowheight=int(round(22 * self._get_widget_scaling())),
                        font=ui_fonts.ui_font(13),
                        borderwidth=0,
                        bordercolor=bg_color,
                        lightcolor=bg_color,
                        darkcolor=bg_color)
        style.map("Custom.Treeview",
                  background=[('selected', select_bg)],
                  foreground=[('selected', select_fg)],
                  bordercolor=[('focus', bg_color)])

        style.layout("Custom.Treeview", [
            ("Custom.Treeview.field", {
                "sticky": "nswe",
                "children": [
                    ("Custom.Treeview.padding", {
                        "sticky": "nswe",
                        "children": [
                            ("Custom.Treeview.treearea", {"sticky": "nswe"})
                        ]
                    })
                ]
            })
        ])

        style.configure("Custom.Treeview.Heading",
                        background=heading_bg,
                        foreground=heading_fg,
                        font=ui_fonts.ui_font(13, "bold"),
                        relief="flat",
                        borderwidth=0)
        style.map("Custom.Treeview.Heading",
                  background=[('active', heading_bg)])

        # 隔行变色标签
        if hasattr(self, 'tree'):
            self.tree.configure(style="Custom.Treeview")
            self.tree.tag_configure("evenrow", background=alt_color)
            self.tree.tag_configure("disabled", foreground=MGR_ROW_DISABLED_TEXT)

    def _create_ui(self):
        """构建标准 UI 布局（使用 CTk 组件）- 探索模式风格"""
        # 顶部工具栏区域（留给子类自定义）
        self.toolbar_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.toolbar_frame.pack(fill='x', padx=5, pady=(5, 0))
        self.create_toolbar()

        # 中间列表区域 - 带圆角边框
        list_frame = ctk.CTkFrame(self, fg_color="transparent",
                                  border_width=1, corner_radius=8,
                                  border_color=MGR_BORDER)
        list_frame.pack(fill='both', expand=True, padx=9, pady=(0,9))
        self.list_frame = list_frame

        col_ids = [f"col_{i}" for i in range(len(self.columns))]
        self.tree = ttk.Treeview(list_frame, columns=col_ids, show="headings", style="Custom.Treeview")
        for i, (heading, width, _) in enumerate(self.columns):
            self.tree.heading(col_ids[i], text=heading)
            self.tree.column(col_ids[i], width=width)

        self.scrollbar = ctk.CTkScrollbar(list_frame, orientation="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.scrollbar.set)

        self.tree.pack(side='left', fill='both', expand=True, padx=(5, 2), pady=5)
        self.scrollbar.pack(side='right', fill='y', padx=(2, 5), pady=5)

        # 底部按钮栏
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.pack(fill='x', padx=5, pady=(0, 5))
        self.button_frame = button_frame

        _btn_style = dict(
            fg_color="transparent", border_width=1, corner_radius=8,
            font=ui_fonts.ui_font(13)
        )
        _btn_text = MGR_TEXT_SOFT
        _btn_hover = MGR_HOVER
        _btn_border = MGR_BORDER_STRONG

        # 左侧按钮组（添加、编辑、删除）
        left_btn_frame = ctk.CTkFrame(button_frame, fg_color="transparent")
        left_btn_frame.pack(side='left', fill='x', expand=True)

        ctk.CTkButton(left_btn_frame, text="添加",
                      command=self.add_item, width=80,
                      text_color=_btn_text, hover_color=_btn_hover,
                      border_color=_btn_border, **_btn_style).pack(side='left', padx=5)
        ctk.CTkButton(left_btn_frame, text="编辑",
                      command=self.edit_item, width=80,
                      text_color=_btn_text, hover_color=_btn_hover,
                      border_color=_btn_border, **_btn_style).pack(side='left', padx=5)
        ctk.CTkButton(left_btn_frame, text="删除",
                      command=self.delete_item, width=80,
                      fg_color="transparent", border_width=1, corner_radius=8,
                      text_color=MGR_ERR,
                      hover_color=MGR_ERR_HOVER,
                      border_color=MGR_ERR,
                      font=ui_fonts.ui_font(13)).pack(side='left', padx=5)

        # 右侧按钮组（上移、下移）
        right_btn_frame = ctk.CTkFrame(button_frame, fg_color="transparent")
        right_btn_frame.pack(side='right', fill='x', expand=True)

        ctk.CTkButton(right_btn_frame, text="上移",
                      command=self.move_up, width=80,
                      text_color=_btn_text, hover_color=_btn_hover,
                      border_color=_btn_border, **_btn_style).pack(side='right', padx=5)
        ctk.CTkButton(right_btn_frame, text="下移",
                      command=self.move_down, width=80,
                      text_color=_btn_text, hover_color=_btn_hover,
                      border_color=_btn_border, **_btn_style).pack(side='right', padx=5)

    def create_toolbar(self):
        """子类可重写此方法以添加顶部自定义控件"""
        pass

    # ---------- 需要子类实现的方法 ----------
    def get_items(self) -> List[Any]:
        """返回当前所有数据项的列表"""
        raise NotImplementedError

    def get_item_values(self, item: Any) -> tuple:
        """
        将数据对象转换为 Treeview 显示的一行值 (tuple)。
        顺序必须与 self.columns 中定义的数据键对应。
        """
        raise NotImplementedError

    def save_items(self, items: List[Any]):
        """保存数据列表到持久化存储"""
        raise NotImplementedError

    def create_item_dialog(self, item: Optional[Any] = None):
        """
        打开添加/编辑对话框，返回新数据字典（用于新建）或修改后的对象。
        若用户取消则返回 None。
        """
        raise NotImplementedError

    # ---------- 通用操作方法 ----------
    def refresh_list(self):
        self.tree.delete(*self.tree.get_children())
        for i, item in enumerate(self.get_items()):
            tags = ("evenrow",) if i % 2 == 0 else ()
            self.tree.insert("", "end", values=self.get_item_values(item), tags=tags)

    def get_selected_index(self) -> int:
        """返回当前选中项的索引，若未选中返回 -1"""
        selection = self.tree.selection()
        if not selection:
            return -1
        # 获取选中项在 Treeview 中的索引（所有子项列表中的位置）
        all_items = self.tree.get_children()
        return all_items.index(selection[0])

    def get_selected_item(self) -> Optional[Any]:
        """返回当前选中的数据对象，若未选中返回 None"""
        idx = self.get_selected_index()
        if idx == -1:
            return None
        items = self.get_items()
        if 0 <= idx < len(items):
            return items[idx]
        return None

    def add_item(self):
        """添加新项"""
        result = self.create_item_dialog()
        if result is not None:
            items = self.get_items()
            items.append(result)  # 假设 create_item_dialog 返回可直接添加的对象
            self.save_items(items)
            self.refresh_list()

    def edit_item(self):
        """编辑选中项"""
        item = self.get_selected_item()
        if item is None:
            ui.ctk.dialogs.showwarning("警告", "请先选择一个项目")
            return
        idx = self.get_selected_index()
        result = self.create_item_dialog(item)
        if result is not None:
            items = self.get_items()
            items[idx] = result  # 直接替换
            self.save_items(items)
            self.refresh_list()

    def display_name(self, item: Any) -> str:
        """条目的可读名称（删除确认等提示用）。子类可覆盖。"""
        if isinstance(item, dict):
            return str(item.get("name") or item)
        return str(getattr(item, "name", None) or item)

    def delete_item(self):
        """删除选中项"""
        item = self.get_selected_item()
        if item is None:
            return
        idx = self.get_selected_index()
        if ui.ctk.dialogs.askyesno("确认", f"确定要删除 '{self.display_name(item)}' 吗？"):
            items = self.get_items()
            del items[idx]
            self.save_items(items)
            self.refresh_list()

    def move_up(self):
        """将选中项上移一位"""
        idx = self.get_selected_index()
        if idx == -1:
            ui.ctk.dialogs.showwarning("警告", "请先选择一个项目")
            return
        if idx == 0:
            return
        items = self.get_items()
        items[idx], items[idx - 1] = items[idx - 1], items[idx]
        self.save_items(items)
        self.refresh_list()
        # 重新选中移动后的项
        children = self.tree.get_children()
        if idx - 1 < len(children):
            self.tree.selection_set(children[idx - 1])

    def move_down(self):
        """将选中项下移一位"""
        idx = self.get_selected_index()
        if idx == -1:
            ui.ctk.dialogs.showwarning("警告", "请先选择一个项目")
            return
        items = self.get_items()
        if idx == len(items) - 1:
            return
        items[idx], items[idx + 1] = items[idx + 1], items[idx]
        self.save_items(items)
        self.refresh_list()
        # 重新选中移动后的项
        children = self.tree.get_children()
        if idx + 1 < len(children):
            self.tree.selection_set(children[idx + 1])


class CardManager(ctk.CTkFrame):
    """两栏式资源管理页：左侧分组选择，右侧当前分组与条目。

    基类负责作用域（风格 / 观测等级）、选择栏骨架、搜索、条目展开与锁定遮罩；
    数据、选择器外观与分组说明由子类通过下列 hooks 提供：

    - ``load_items()`` / ``get_category(item)`` / ``sort_items(items)``
    - ``category_keys()``（含空分组）/ ``category_label(key)``
    - ``build_selector(parent)`` / ``render_rail_extra(parent)``
    - ``render_group_head(parent, key, items)``（可选，右侧标题下的补充说明）
    - ``row_title`` / ``row_preview`` / ``row_meta`` / ``build_row_detail``
    - ``pane_subtitle`` / ``selector_note`` / ``selector_hint`` / ``search_text``
    - ``create_style_widgets(parent)``

    子类用 ``RESOURCE_TYPE`` 声明资源类型（``landmarks`` / ``quips``）；
    ``SUPPORTS_SIZE`` 决定作用域行是否带观测等级。
    """

    #: 本管理器维护的资源类型 id（子类必须声明）
    RESOURCE_TYPE = ""
    #: 是否显示观测等级作用域（描述页为 True）
    SUPPORTS_SIZE = False
    #: 左栏选择器标题
    RAIL_HEAD = "分组"
    #: 条目量词（描述用「条」，地标用「个」）
    ITEM_UNIT = "条"

    #: 选择器底色梯度：向强调色混合的比例（由浅到深）
    _HEAT_RATIOS = (0.07, 0.13, 0.20, 0.28)

    def __init__(self, parent, gui_ref, item_name="条目"):
        super().__init__(parent, fg_color=MGR_PAGE_BG, corner_radius=0)
        self.gui = gui_ref
        self.item_name = item_name

        self.current_category = None
        self.search_var = tk.StringVar()
        self._groups = {}
        self._world_locked = False
        self._lock_overlay = None
        self._suppress_search = False

        self._setup_ui()
        self.search_var.trace_add("write", self._on_search_var)

    # ---------- 布局 ----------
    def _setup_ui(self):
        # 卡片外只有一行：作用域（风格 › 观测等级）+ 右侧动作。
        # 地标/描述已拆成两个独立页面，由左侧导航直接切换，不再需要模块 tab。
        self.top_row = ctk.CTkFrame(self, fg_color="transparent")
        self.top_row.pack(fill='x', padx=12, pady=(10, 0))

        self.scope_box = ctk.CTkFrame(self.top_row, fg_color="transparent")
        self.scope_box.pack(side='left')

        ctk.CTkLabel(self.scope_box, text="风格", font=ui_fonts.ui_font(13),
                     text_color=MGR_TEXT_SOFT).pack(side='left')
        self.style_host = ctk.CTkFrame(self.scope_box, fg_color="transparent")
        self.style_host.pack(side='left', padx=(8, 0))
        self.style_menu_btn = ctk.CTkButton(
            self.scope_box, text="⋯", width=30, height=30, corner_radius=7,
            fg_color="transparent", hover_color=MGR_HOVER,
            text_color=MGR_TEXT_SOFT, font=ui_fonts.ui_font(16),
            command=self._show_style_menu
        )
        self.style_menu_btn.pack(side='left', padx=(2, 0))

        if self.SUPPORTS_SIZE:
            ctk.CTkLabel(self.scope_box, text="›", font=ui_fonts.ui_font(13),
                         text_color=MGR_TEXT_MUTED).pack(side='left',
                                                         padx=(10, 4))
            ctk.CTkLabel(self.scope_box, text="观测等级",
                         font=ui_fonts.ui_font(13),
                         text_color=MGR_TEXT_SOFT).pack(side='left')
            self.size_host = ctk.CTkFrame(self.scope_box, fg_color="transparent")
            self.size_host.pack(side='left', padx=(8, 0))

        self.head_right = ctk.CTkFrame(self.top_row, fg_color="transparent",
                                      width=0, height=0)
        self.head_right.pack(side='right')

        # ---- 工作区：左栏与右栏并列成两块卡片，互不嵌套 ----
        # 左栏：分组选择器（4×4 矩阵 / 12 档网格），下方留白
        self.rail = ctk.CTkFrame(self, fg_color=MGR_RAIL_BG,
                                 corner_radius=12, width=260)
        self.rail.pack_propagate(False)

        self.rail_head = ctk.CTkFrame(self.rail, fg_color="transparent")
        self.rail_head.pack(fill='x', padx=12, pady=(12, 8))
        self.rail_head_label = ctk.CTkLabel(
            self.rail_head, text=self.RAIL_HEAD, font=ui_fonts.ui_font(12),
            text_color=MGR_TEXT_MUTED)
        self.rail_head_label.pack(side='left')
        self.rail_note_label = ctk.CTkLabel(
            self.rail_head, text="", font=ui_fonts.ui_font(12),
            text_color=MGR_TEXT_MUTED)
        self.rail_note_label.pack(side='right')

        self.selector_host = ctk.CTkFrame(self.rail, fg_color="transparent")
        self.selector_host.pack(fill='x', padx=10)

        # 描述页在这里补当前分组的两条轴定义；地标页暂不显示说明
        self.rail_extra = ctk.CTkFrame(self.rail, fg_color="transparent",
                                       height=0)
        self.rail_extra.pack(fill='x', padx=12, pady=(10, 0))

        self.legend = ctk.CTkFrame(self.rail, fg_color="transparent")
        self.legend.pack(fill='x', padx=12, pady=(10, 10))
        self._legend_swatches = []
        for ratio in self._HEAT_RATIOS:
            swatch = ctk.CTkFrame(self.legend, width=9, height=9,
                                  corner_radius=2, fg_color=self._heat(ratio))
            swatch.pack(side='left', padx=(0, 2))
            swatch.pack_propagate(False)
            self._legend_swatches.append(swatch)
        ctk.CTkLabel(self.legend, text="底色 = 条目数",
                     font=ui_fonts.ui_font(11),
                     text_color=MGR_TEXT_MUTED).pack(side='left', padx=(5, 0))

        # 右栏：当前分组名称 + 搜索 → 条目
        self.pane = ctk.CTkFrame(self, fg_color=MGR_PANEL_BG,
                                 corner_radius=12)

        self.group_head = ctk.CTkFrame(self.pane, fg_color="transparent")
        self.group_head.pack(fill='x', padx=16, pady=(14, 8))

        title_row = ctk.CTkFrame(self.group_head, fg_color="transparent")
        title_row.pack(fill='x')
        self.title_row = title_row
        self.group_title = ctk.CTkLabel(
            title_row, text="", font=ui_fonts.ui_font(17, "bold"),
            text_color=MGR_TEXT, anchor='w')
        self.group_title.pack(side='left')
        count_box = ctk.CTkFrame(title_row, fg_color=MGR_INPUT_BG,
                                 corner_radius=8)
        count_box.pack(side='left', padx=(8, 0))
        self.group_count = ctk.CTkLabel(
            count_box, text="", font=ui_fonts.ui_font(11),
            text_color=MGR_TEXT_SOFT)
        self.group_count.pack(padx=8, pady=1)

        self.group_defs = ctk.CTkFrame(self.group_head, fg_color="transparent")

        self.add_btn = ctk.CTkButton(
            self.title_row, text=f"＋ 添加{self.item_name}", width=112,
            height=30, corner_radius=8, fg_color=MGR_PRIMARY_BG,
            hover_color=MGR_PRIMARY_HOVER, text_color=MGR_PRIMARY_TEXT,
            font=ui_fonts.ui_font(13, "bold"), command=self.on_add_click
        )
        self.add_btn.pack(side='right')

        self.search_entry = ctk.CTkEntry(
            self.title_row, textvariable=self.search_var,
            placeholder_text="搜索本组…", height=30, width=230,
            corner_radius=7, border_width=0, fg_color=MGR_INPUT_BG,
            text_color=MGR_TEXT, placeholder_text_color=MGR_PLACEHOLDER,
            font=ui_fonts.ui_font(13)
        )
        self.search_entry.pack(side='right', padx=10)

        # 底部条：放校验结论等，停在右栏右下角；无内容时整条收起
        self.pane_footer = ctk.CTkFrame(self.pane, fg_color="transparent")

        self.rows = ctk.CTkScrollableFrame(
            self.pane, fg_color=MGR_PANEL_BG, corner_radius=0, border_width=0,
            scrollbar_button_color=MGR_HOVER,
            scrollbar_button_hover_color=MGR_BORDER
        )
        self.rows.pack(fill='both', expand=True, padx=6, pady=(0, 6))

        self._show_workspace()

    # ---------- 工作区显隐 ----------
    def _show_workspace(self):
        """左栏与右栏并排铺满工具栏以下的空间（左栏先进，保持在左）。"""
        self.rail.pack(side='left', fill='y', padx=(12, 0),
                       pady=(10, 12))
        self.pane.pack(side='left', fill='both', expand=True,
                       padx=(8, 12), pady=(10, 12))

    def _hide_workspace(self):
        self.rail.pack_forget()
        self.pane.pack_forget()

    # ---------- 子类 hooks ----------
    def create_style_widgets(self, parent):
        """在作用域行的风格位置创建风格下拉。"""

    def get_category(self, item):
        raise NotImplementedError

    def load_items(self):
        raise NotImplementedError

    def save_items(self, items):
        raise NotImplementedError

    def add_item_in_category(self):
        raise NotImplementedError

    def edit_item(self, item):
        raise NotImplementedError

    def delete_item(self, item):
        raise NotImplementedError

    def sort_items(self, items):
        return items

    def category_keys(self):
        """选择器要显示的完整键序列；默认只列已有数据的键。"""
        return list(self._groups.keys())

    def category_label(self, key):
        return str(key)

    def category_count(self, key):
        return len(self._groups.get(key, ()))

    def selector_title(self):
        return self.RAIL_HEAD

    def selector_note(self):
        keys = self.category_keys()
        filled = sum(1 for key in keys if self.category_count(key))
        return f"{filled} / {len(keys)} 组"

    def build_selector(self, parent):
        """在左栏选择器容器里创建控件；默认是纵向列表。"""
        for key in self.category_keys():
            selected = key == self.current_category
            ctk.CTkButton(
                parent,
                text=f"{self.category_label(key)}   "
                     f"{self.category_count(key)}",
                anchor='w', height=30, corner_radius=8,
                fg_color=MGR_PANEL_BG if selected else "transparent",
                hover_color=MGR_HOVER, border_width=1,
                border_color=MGR_BORDER_STRONG if selected else MGR_BORDER,
                text_color=MGR_TEXT, font=ui_fonts.ui_font(13),
                command=lambda k=key: self._select_category(k)
            ).pack(fill='x', pady=1)

    def render_group_head(self, parent, key, items):
        """在右栏标题下创建分组说明；子类实现。"""

    def render_rail_extra(self, parent):
        """在选择器下方补充当前分组的说明（如两条轴定义）；子类实现。"""

    def empty_hint(self, key):
        return f"点击右上角「添加{self.item_name}」开始"

    def search_text(self, item):
        try:
            return " ".join(str(v) for v in self.get_card_display(item).values())
        except Exception:
            return str(item)

    def row_title(self, item):
        return str(item)

    def row_preview(self, item):
        return ""

    def row_meta(self, item):
        return ""

    def build_row_detail(self, parent, item):
        """在展开区域里创建详情内容（卡片自行 pack）。"""
        ctk.CTkLabel(parent, text="暂无详情",
                     font=ui_fonts.ui_font(12),
                     text_color=MGR_TEXT_SOFT).pack(anchor='w')

    def pane_subtitle(self, items):
        return f"{len(items)} {self.ITEM_UNIT}{self.item_name}"

    def update_lint_summary(self):
        """描述页在数据刷新后更新校验摘要；地标页不显示。"""

    def _after_refresh(self):
        """数据刷新后的附加刷新（如类型视图）。"""

    # ---------- 选择器底色 ----------
    @staticmethod
    def _pick_color(token):
        """主题 token 可能是单色，也可能是 ``[亮, 暗]`` 双槽。"""
        if isinstance(token, (list, tuple)):
            return token[1] if ctk.get_appearance_mode() == "Dark" else token[0]
        return token

    @classmethod
    def _mix(cls, fg, bg, ratio):
        """把强调色按比例混进底色，返回 ``#RRGGBB``。"""
        fg = cls._pick_color(fg)
        bg = cls._pick_color(bg)
        try:
            fr, fgn, fb = (int(fg[i:i + 2], 16) for i in (1, 3, 5))
            br, bgn, bb = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
        except (TypeError, ValueError):
            return bg if isinstance(bg, str) else "transparent"
        ratio = max(0.0, min(1.0, ratio))
        return "#%02X%02X%02X" % (
            round(fr * ratio + br * (1 - ratio)),
            round(fgn * ratio + bgn * (1 - ratio)),
            round(fb * ratio + bb * (1 - ratio)),
        )

    def _heat(self, ratio):
        return self._mix(MGR_PRIMARY_BG, MGR_RAIL_BG, ratio)

    def heat_color(self, count, max_count):
        """条目数 → 选择器底色；0 条返回 ``transparent``。"""
        if not count:
            return "transparent"
        low, high = self._HEAT_RATIOS[0], self._HEAT_RATIOS[-1]
        ratio = low + (high - low) * min(1.0, count / max(1, max_count))
        return self._heat(ratio)

    # ---------- 数据 / 分组 ----------
    def _grouped_items(self):
        groups = {}
        for item in self.all_items:
            groups.setdefault(self.get_category(item), []).append(item)
        return groups

    def _clip(self, text, limit):
        text = " ".join(str(text or "").split())
        if len(text) <= limit:
            return text
        return text[:limit] + "…"

    def _reset_scroll(self, frame):
        canvas = getattr(frame, "_parent_canvas", None)
        if canvas is not None:
            try:
                canvas.yview_moveto(0.0)
            except Exception:
                pass

    def _ensure_category(self, keys):
        keys = list(keys)
        if self.current_category in keys:
            return
        if not keys:
            self.current_category = None
            return
        # 默认落到条目最多的分组；全空时取第一个
        self.current_category = max(
            keys, key=lambda key: len(self._groups.get(key, ())))

    def refresh_ui(self):
        """重读数据并重建选择器、分组说明与条目区。"""
        self.load_items()
        self._groups = self._grouped_items()
        self._ensure_category(self.category_keys())
        self._render_selector()
        self._render_group_head()
        self._render_pane()
        self.update_lint_summary()
        self._after_refresh()

    # ---------- 左栏渲染 ----------
    def _render_selector(self):
        self.rail_head_label.configure(text=self.selector_title())
        self.rail_note_label.configure(text=self.selector_note())
        for widget in self.selector_host.winfo_children():
            widget.destroy()
        self.build_selector(self.selector_host)
        for widget in self.rail_extra.winfo_children():
            widget.destroy()
        self.render_rail_extra(self.rail_extra)
        for swatch, ratio in zip(self._legend_swatches, self._HEAT_RATIOS):
            swatch.configure(fg_color=self._heat(ratio))

    def _render_group_head(self):
        key = self.current_category
        items = self._groups.get(key, ()) if key else ()
        self.group_title.configure(
            text=self.category_label(key) if key else f"暂无{self.item_name}")
        self.group_count.configure(text=f"{len(items)} {self.ITEM_UNIT}")
        for widget in self.group_defs.winfo_children():
            widget.destroy()
        if key:
            self.render_group_head(self.group_defs, key, items)
        if self.group_defs.winfo_children():
            self.group_defs.pack(fill='x', pady=(7, 0))
        else:
            self.group_defs.pack_forget()

    def _select_category(self, key):
        if key == self.current_category:
            return
        self.current_category = key
        self._clear_search()
        self._render_selector()
        self._render_group_head()
        self._render_pane()
        self._reset_scroll(self.rows)

    def _clear_search(self):
        if not self.search_var.get():
            return
        self._suppress_search = True
        self.search_var.set("")
        self._suppress_search = False

    def _on_search_var(self, *_args):
        if self._suppress_search:
            return
        self._render_pane()
        self._reset_scroll(self.rows)

    # ---------- 右栏渲染 ----------
    def _render_pane(self, groups=None):
        for widget in self.rows.winfo_children():
            widget.destroy()

        groups = self._groups if groups is None else groups
        key = self.current_category
        if not key:
            self._render_empty(
                f"还没有可显示的{self.item_name}",
                f"点击右上角「添加{self.item_name}」开始")
            return

        all_items = list(groups.get(key, ()))
        query = self.search_var.get().strip()
        items = all_items
        if query:
            needle = query.lower()
            items = [it for it in all_items
                     if needle in self.search_text(it).lower()]

        if not items:
            self._render_empty(
                "没有匹配的条目" if query else
                f"这个分组还没有{self.item_name}",
                "换个关键词试试" if query else self.empty_hint(key))
            return

        for item in self.sort_items(items):
            self._build_row(item)

    def _render_empty(self, title, hint):
        box = ctk.CTkFrame(self.rows, fg_color="transparent")
        box.pack(fill='x', pady=44)
        ctk.CTkLabel(box, text=title, font=ui_fonts.ui_font(14, "bold"),
                     text_color=MGR_TEXT_SOFT).pack()
        ctk.CTkLabel(box, text=hint, font=ui_fonts.ui_font(12),
                     text_color=MGR_TEXT_MUTED).pack(pady=(4, 0))

    def _build_row(self, item):
        row = ctk.CTkFrame(self.rows, fg_color="transparent", corner_radius=8)
        row.pack(fill='x', padx=2, pady=1)

        head = ctk.CTkFrame(row, fg_color="transparent")
        head.pack(fill='x', padx=10, pady=(8, 0))

        title = ctk.CTkLabel(
            head, text=self.row_title(item), font=ui_fonts.ui_font(14, "bold"),
            text_color=MGR_TEXT, anchor='w')
        title.pack(side='left', fill='x', expand=True)

        arrow = ctk.CTkLabel(
            head, text="▾", font=ui_fonts.ui_font(11),
            text_color=MGR_TEXT_MUTED, width=14)
        arrow.pack(side='right')

        meta = None
        meta_text = self.row_meta(item)
        if meta_text:
            meta = ctk.CTkLabel(
                head, text=meta_text, font=ui_fonts.ui_font(12),
                text_color=MGR_TEXT_MUTED)
            meta.pack(side='right', padx=(8, 0))

        preview = ctk.CTkLabel(
            row, text=self.row_preview(item),
            font=ui_fonts.ui_font(13), text_color=MGR_TEXT_SOFT,
            anchor='w')
        preview.pack(fill='x', padx=10, pady=(2, 8))

        detail_host = ctk.CTkFrame(row, fg_color="transparent")
        state = {"open": False, "hover": False, "built": False}

        def set_bg():
            if state["open"]:
                color = MGR_ROW_OPEN
            elif state["hover"]:
                color = MGR_ROW_HOVER
            else:
                color = "transparent"
            row.configure(fg_color=color)

        def toggle(_event=None):
            if not state["built"]:
                self.build_row_detail(detail_host, item)
                state["built"] = True
            state["open"] = not state["open"]
            if state["open"]:
                preview.pack_forget()
                detail_host.pack(fill='x', padx=10, pady=(0, 10))
                arrow.configure(text="▴")
            else:
                detail_host.pack_forget()
                preview.pack(fill='x', padx=10, pady=(2, 8), after=head)
                arrow.configure(text="▾")
            set_bg()

        def on_enter(_event=None):
            state["hover"] = True
            set_bg()

        def on_leave(_event=None):
            state["hover"] = False
            set_bg()

        targets = [row, head, title, preview, arrow]
        if meta is not None:
            targets.append(meta)
        for widget in targets:
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", toggle, add="+")
            widget.bind("<Enter>", on_enter, add="+")
            widget.bind("<Leave>", on_leave, add="+")

    # ---------- 风格管理 ----------
    def refresh_styles(self):
        styles = self._get_style_list()
        self.style_combo.configure(
            values=[self._style_display_name(s) for s in styles])
        current = self._get_current_style()
        if current not in styles:
            current = styles[0] if styles else self._get_default_style()
            self._set_current_style(current)
        self.style_var.set(self._style_display_name(current))

    def _style_menu_colors(self):
        dark = ctk.get_appearance_mode() == "Dark"

        def pick(token):
            if isinstance(token, (list, tuple)):
                return token[1] if dark else token[0]
            return token

        return pick

    def _show_style_menu(self):
        pick = self._style_menu_colors()
        menu = tk.Menu(
            self, tearoff=0, bg=pick(MGR_PANEL_BG), fg=pick(MGR_TEXT),
            activebackground=pick(MGR_HOVER), activeforeground=pick(MGR_TEXT),
            bd=0, relief='flat', font=ui_fonts.ui_font(12))
        menu.add_command(label="新建风格…", command=self.create_style)
        menu.add_command(label="重命名风格…", command=self.rename_style)
        if hasattr(self, "_edit_style_address"):
            menu.add_command(label="注册地址…", command=self._edit_style_address)
        menu.add_separator()
        menu.add_command(label="删除风格", command=self.delete_style,
                         foreground=pick(MGR_ERR))
        self._style_menu = menu
        try:
            menu.tk_popup(
                self.style_menu_btn.winfo_rootx(),
                self.style_menu_btn.winfo_rooty()
                + self.style_menu_btn.winfo_height())
        finally:
            menu.grab_release()

    def create_style(self):
        """新建风格：只问名称，id 自动分配（高级里可手填）。"""
        dlg = ResourceNameDialog(
            self, resource_type=self.RESOURCE_TYPE, title="新建风格",
            initial_name="", taken=self._get_style_list())
        if not dlg.result:
            return
        try:
            self._create_style_impl(dlg.result["id"], dlg.result["title"])
            self._set_current_style(dlg.result["id"])
            self.refresh_styles()
            self._clear_search()
            self.refresh_ui()
            self._reset_scroll(self.rows)
        except ValueError as e:
            ui.ctk.dialogs.showerror("错误", str(e))
        self._notify_style_list_changed()

    def rename_style(self):
        """改名只改显示名，id 不变——已选风格、注册地址、打包清单都照旧。"""
        old = self._get_current_style()
        if not old:
            ui.ctk.dialogs.showwarning("警告", "请先选择一个风格")
            return
        dlg = ResourceNameDialog(
            self, resource_type=self.RESOURCE_TYPE, title="重命名风格",
            mode="rename", initial_name=self._style_display_name(old),
            resource_id=old)
        if not dlg.result:
            return
        try:
            self._set_style_title_impl(old, dlg.result["title"])
            self.refresh_styles()
            self.refresh_ui()
            self._reset_scroll(self.rows)
        except ValueError as e:
            ui.ctk.dialogs.showerror("错误", str(e))
        self._notify_style_list_changed()

    def delete_style(self):
        name = self._get_current_style()
        if name == self._get_default_style():
            ui.ctk.dialogs.showwarning("警告", "不能删除默认风格")
            return
        if not ui.ctk.dialogs.askyesno(
                "确认", f"确定删除风格「{self._style_display_name(name)}」吗？"):
            return
        try:
            self._delete_style_impl(name)
            self.refresh_styles()
            self._clear_search()
            self.refresh_ui()
            self._reset_scroll(self.rows)
        except ValueError as e:
            ui.ctk.dialogs.showerror("错误", str(e))
        self._notify_style_list_changed()

    def on_add_click(self):
        self.add_item_in_category()

    def _notify_style_list_changed(self):
        callback = getattr(self.gui, 'refresh_style_listboxes', None)
        if callback is not None:
            callback()

    def _style_display_name(self, style_id):
        return str(style_id or "")

    # ---------- 世界包锁定 ----------
    def set_world_locked(self, locked: bool):
        """世界包锁定该资源管理时，屏蔽除左上角切换控件外的整个视图。"""
        if locked == self._world_locked:
            return
        self._world_locked = locked
        if locked:
            self._mask_world_locked()
        else:
            self._unmask_world_locked()

    def _mask_world_locked(self):
        self.scope_box.pack_forget()
        self._hide_workspace()
        if getattr(self, 'type_view', None) is not None:
            self.type_view.pack_forget()
        self.head_right.pack_forget()

        self._lock_overlay = ctk.CTkFrame(
            self, fg_color=MGR_PAGE_BG, corner_radius=12)
        ctk.CTkLabel(
            self._lock_overlay,
            text=f"世界包已锁定{self.item_name}资源管理，暂不可查看",
            font=ui_fonts.ui_font(14),
            text_color=MGR_TEXT_SOFT,
        ).pack(expand=True)
        self._lock_overlay.pack(fill='both', expand=True, padx=12,
                                pady=(10, 12))

    def _unmask_world_locked(self):
        if self._lock_overlay is not None:
            self._lock_overlay.pack_forget()
            self._lock_overlay.destroy()
            self._lock_overlay = None

        self.scope_box.pack(side='left', before=self.head_right)
        if getattr(self, 'type_view_active', False):
            self.type_view.pack(fill='both', expand=True, padx=12,
                                pady=(10, 12))
        else:
            self._show_workspace()
        self.head_right.pack(side='right')

    def update_theme(self, theme_mode: str):
        # CTk 控件自行响应外观变化；选择器底色与分组说明是算出来的，需要重绘。
        try:
            if not self.winfo_exists():
                return
            self._render_selector()
            self._render_group_head()
        except tk.TclError:
            return
