"""设置对话框：导航栏 ⚙️ 打开的模态窗口。

形态与主流桌面应用的设置一致：左侧分类导航，右侧滚动内容，每个控件改完
立即落盘（没有「保存 / 取消」）。唯一的例外是**界面配色**：它一旦落盘就会
被主窗口的亮暗轮询立刻应用，对话框自己也会被换成另一套颜色，所以选择只
记在内存里，关掉对话框时才提交并统一换色。
"""
import random
import threading
import tkinter as tk
import tkinter.font as tkfont
import uuid
from typing import Callable, Dict, Optional, TYPE_CHECKING

import customtkinter as ctk

from core import netproxy
from core.ai import PROVIDER_DEFAULTS, create_client, describe_ai_error, profile_labels
from core.logic import ALL_PART_NAMES, normalize_blocked_words
from persistence import DungeonSettingsRepo
import services.ui_mode as ui_mode
from ui.ctk import dialogs as ui_dialogs
from ui.ctk.dialogs import BaseDialog, ModalDialog
from ui.ctk.widgets import OptionButton
from ui.ctk import fonts as ui_fonts
from ui.ctk.theme import (
    DLG_BORDER, DLG_ERR, DLG_HOVER, DLG_TEXT, DLG_TEXT_SOFT, DLG_TITLE,
    SETTINGS_PANEL_BG, SETTINGS_HOVER, SETTINGS_CHECKBOX_HOVER, SETTINGS_INPUT_HOVER,
    SETTINGS_INPUT_BG, SETTINGS_INPUT_BORDER,
    SETTINGS_SWITCH_TRACK, SETTINGS_SWITCH_PROGRESS, SETTINGS_SWITCH_KNOB,
    SETTINGS_TEXT_SOFT, SETTINGS_LABEL, SETTINGS_OK,
)
from ui.ctk.theme import (
    DEFAULT_PALETTE, palette_display_modes, palette_display_names,
    palette_display_names_by_mode,
)

if TYPE_CHECKING:
    from persistence.settings_repo import SettingsRepo

_FONT = ui_fonts.ui_font(13)

#: 系统深色配色下拉框的「不覆盖默认」选项。
FOLLOW_DEFAULT_PALETTE = "跟随默认值"

# 信息更新覆写概率四档：显示名 → 覆写概率
INFO_UPDATE_OPTIONS = {"保守": 0.25, "中等": 0.5, "高效": 0.75, "激进": 1.0}

# 对比排序：显示名 → 值。narrative 从当前位置贪心串起地址跳转链。
ORDER_OPTIONS = {"匹配度": "match", "尺寸升序": "size_asc",
                 "尺寸降序": "size_desc", "自然叙述顺序": "narrative"}

# 体型设定：显示名 → 值
WORLD_OPTIONS = {"出现": "appear", "绝对巨大化": "abs_giant", "相对巨大化": "rel_giant"}

# 分类导航：(显示名, 右侧内容的行序号)。顺序即左侧自上而下的顺序。
_NAV_SECTIONS = (
    ("世界", 0),
    ("生成", 1),
    ("外观", 2),
    ("档案", 3),
)

# 对话框尺寸（逻辑像素）：880×600 与演示稿一致，主流桌面设置的常见比例。
_DIALOG_WIDTH = 880
_DIALOG_HEIGHT = 600
_NAV_WIDTH = 148


def _seed_text(seed):
    """种子 0 在输入框里显示为空（表示不指定）。"""
    return str(seed) if seed else ""


class SettingsDialog(ModalDialog):
    """应用设置的模态对话框，改动即时保存。

    ``on_world_setting_changed`` 转发给主窗口（体型设定要同步给生成器页），
    ``gui_ref`` 用于换色后整体重绘，``world_manager`` 提供世界包锁定的设置键。
    """

    def __init__(
            self,
            parent,
            settings_repo: 'SettingsRepo',
            initial_settings: Dict,
            on_world_setting_changed: Optional[Callable] = None,
            gui_ref=None,
            world_manager=None,
    ):
        super().__init__(parent)
        self.settings_repo = settings_repo
        # 副本独占设置独立成 data/user/dungeon_settings.json，见
        # persistence/dungeon_settings_repo.py。这里只放「下次进副本生效」的
        # 启动项（段落字体）与按档案生效的回放开关；音量 / 帧率 / 停靠侧能在
        # 副本窗口内即时生效的，只在副本设置面板里调。
        self.dungeon_settings_repo = DungeonSettingsRepo()
        self.dungeon_settings = self.dungeon_settings_repo.load()
        self.settings = initial_settings
        self.on_world_setting_changed = on_world_setting_changed
        self.gui_ref = gui_ref
        self.world_manager = world_manager
        self.world_state = getattr(world_manager, "world_state", None) \
            if world_manager is not None else None
        self.parts_checkboxes = {}

        # 界面配色（assets/theme/ 下的一套 token）：默认配色用于系统浅色，
        # 系统深色配色留空表示跟随默认配色。
        self._palette_names = palette_display_names()
        self._palette_options = {display: name
                                 for name, display in self._palette_names.items()}
        self.theme_palette = self.settings.get("theme_palette") or DEFAULT_PALETTE
        if self.theme_palette not in self._palette_names:
            self.theme_palette = DEFAULT_PALETTE
        self.theme_dark_palette = self.settings.get("theme_dark_palette") or ""
        if self.theme_dark_palette not in self._palette_names:
            self.theme_dark_palette = ""
        self.user_seed = self.settings.get("seed", 0)
        self.comparison_count = self.settings.get("comparison_count", 5)
        self.comparison_order = self.settings.get("comparison_order", "match")
        self.world_setting = self.settings.get("world_setting", "appear")
        self.ai_configs = self._load_ai_configs()
        self.ai_provider = self.settings.get("ai_provider", "zhipu")
        if self.ai_provider not in self.ai_configs:
            self.ai_provider = next(iter(self.ai_configs), "")
        self.enable_confusion = self.settings.get("enable_confusion", False)
        self.quip_rate_factor = self.settings.get("quip_rate_factor", 1.0)
        self.info_update_rate = self.settings.get("info_update_rate", 0.5)
        self.blocked_words = normalize_blocked_words(self.settings.get("blocked_words", []))

        self.title("设置")
        self.resizable(False, False)
        self.geometry(f"{_DIALOG_WIDTH}x{_DIALOG_HEIGHT}")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda _e: self._close())

        self._create_widgets()
        self._sync_parts_states()

        self._show_backdrop()
        self._show_modal()

    # ───────────────────── UI 构建 ─────────────────────
    def _create_widgets(self):
        self._build_header()
        self._build_footer()

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill='both', expand=True, padx=(18, 8), pady=(14, 0))
        self.body.columnconfigure(1, weight=1)
        self.body.rowconfigure(0, weight=1)

        self._build_nav(self.body)

        # 右侧内容：一页滚动区里按分类自上而下排四个区块，左侧导航滚动定位。
        self.content = ctk.CTkScrollableFrame(
            self.body, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=SETTINGS_HOVER,
            scrollbar_button_hover_color=SETTINGS_INPUT_HOVER)
        self.content.grid(row=0, column=1, sticky='nsew', padx=(12, 0))

        self._build_world_block()
        self._build_generation_block()
        self._build_display_block()
        self._build_archive_block()
        self.content.bind("<Configure>", self._sync_nav_highlight, add="+")

    def _build_header(self):
        self.header = ctk.CTkFrame(self, fg_color="transparent")
        self.header.pack(fill='x', padx=22, pady=(16, 2))

        ctk.CTkLabel(
            self.header, text="设置", anchor='w',
            font=ui_fonts.ui_font(18, "bold"), text_color=DLG_TITLE
        ).pack(side='left')

        ctk.CTkButton(
            self.header, text="✕", width=30, height=30,
            command=self._close,
            fg_color="transparent", text_color=DLG_TEXT_SOFT,
            hover_color=DLG_HOVER, corner_radius=8,
            font=ui_fonts.ui_font(14)
        ).pack(side='right')

    def _build_footer(self):
        self.footer = ctk.CTkFrame(self, fg_color="transparent")
        self.footer.pack(fill='x', padx=22, pady=(0, 14), side='bottom')
        self.footer_note = ctk.CTkLabel(
            self.footer, text="改动即时生效并保存，换配色会在关闭本窗口时套用",
            anchor='w', font=ui_fonts.ui_font(11), text_color=DLG_TEXT_SOFT)
        self.footer_note.pack(side='left')
        ctk.CTkButton(
            self.footer, text="完成", width=84, height=30,
            command=self._close,
            fg_color=DLG_TEXT, text_color=SETTINGS_PANEL_BG,
            hover_color=DLG_TITLE, corner_radius=8,
            font=ui_fonts.ui_font(13)
        ).pack(side='right')

    def _build_nav(self, parent):
        self.nav = ctk.CTkFrame(parent, fg_color=SETTINGS_PANEL_BG,
                                corner_radius=8, width=_NAV_WIDTH)
        self.nav.grid(row=0, column=0, sticky='ns')
        self.nav.grid_propagate(False)
        self.nav.columnconfigure(0, weight=1)

        self._nav_buttons = {}
        self._nav_active = None
        for idx, (caption, target) in enumerate(_NAV_SECTIONS):
            btn = ctk.CTkButton(
                self.nav, text=caption, anchor='w', height=34,
                fg_color="transparent", text_color=SETTINGS_LABEL,
                hover_color=SETTINGS_HOVER, corner_radius=6,
                font=ui_fonts.ui_font(13),
                command=lambda i=target: self._scroll_to_section(i))
            btn.grid(row=idx, column=0, sticky='ew', padx=8,
                     pady=(10, 0) if idx == 0 else (2, 0))
            self._nav_buttons[target] = btn

        self.nav_tip = ctk.CTkLabel(
            self.nav, text="", anchor='w', justify='left', wraplength=_NAV_WIDTH - 24,
            font=ui_fonts.ui_font(11), text_color=SETTINGS_TEXT_SOFT)
        self.nav_tip.grid(row=len(_NAV_SECTIONS), column=0, sticky='ew',
                          padx=10, pady=(18, 10))

    # ───────────────── 通用控件辅助 ─────────────────
    @staticmethod
    def _setup_body_grid(body, name):
        """块体内统一两列：0=标签列，1=控件列，跨行对齐。"""
        body.columnconfigure(0, weight=2, uniform=name + "_cols")
        body.columnconfigure(1, weight=3, uniform=name + "_cols")

    def _section_card(self, parent, title, grid_name):
        """一张圆角卡片 + 卡片标题，返回 (卡片, 卡片内的表单体)。"""
        card = ctk.CTkFrame(parent, fg_color=SETTINGS_PANEL_BG, corner_radius=8)
        card.pack(fill='x', pady=(0, 14))
        ctk.CTkLabel(
            card, text=title, anchor='w',
            font=ui_fonts.ui_font(14, "bold"), text_color=DLG_TITLE
        ).pack(fill='x', padx=18, pady=(14, 6))
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill='x', padx=2, pady=(0, 8))
        self._setup_body_grid(body, grid_name)
        return card, body

    def _section_label(self, parent, row, text):
        ctk.CTkLabel(
            parent, text=text,
            font=ui_fonts.ui_font(13, "bold"),
            text_color=SETTINGS_TEXT_SOFT
        ).grid(row=row, column=0, columnspan=2, sticky='w',
               padx=10, pady=6)

    def _make_row(self, parent, row, text):
        """创建一行：标签在左，控件容器在右，两列对齐。"""
        label = ctk.CTkLabel(
            parent, text=text, anchor='w',
            font=_FONT, text_color=SETTINGS_LABEL
        )
        label.grid(row=row, column=0, sticky='w', padx=(18, 12), pady=(0, 8))
        control = ctk.CTkFrame(parent, fg_color="transparent")
        control.grid(row=row, column=1, sticky='e', padx=(0, 18), pady=(0, 8))
        return label, control

    @staticmethod
    def _pack_control(control, expand=True):
        if expand:
            control.pack(fill='both', expand=True)
        else:
            control.pack(side='left')
        return control

    def _make_option_button(self, parent, values, command, variable=None,
                            expand=True, text_colors=None):
        """行内选项控件统一用 widgets.OptionButton：按钮 + 顶部锚定下拉列表。"""
        return self._pack_control(OptionButton(
            parent, values=values, command=command, variable=variable,
            text_colors=text_colors,
            width=120, height=28, corner_radius=7, font=_FONT,
            fg_color=SETTINGS_INPUT_BG, border_color=SETTINGS_INPUT_BORDER,
            hover_color=SETTINGS_INPUT_HOVER, text_color=SETTINGS_LABEL,
            text_color_disabled=SETTINGS_TEXT_SOFT,
            popup_fg_color=SETTINGS_INPUT_BG,
            popup_hover_color=SETTINGS_INPUT_HOVER,
            popup_text_color=SETTINGS_LABEL,
        ), expand)

    def _make_entry(self, parent, variable, width=120, show=None, placeholder_text=None):
        return ctk.CTkEntry(
            parent, textvariable=variable, width=width, height=28, show=show,
            placeholder_text=placeholder_text or "",
            border_width=1, border_color=SETTINGS_INPUT_BORDER,
            fg_color=SETTINGS_INPUT_BG, corner_radius=8, font=_FONT
        )

    def _make_switch(self, parent, variable, command=None):
        switch = ctk.CTkSwitch(
            parent, text="", variable=variable, width=44, height=22,
            progress_color=SETTINGS_SWITCH_PROGRESS, fg_color=SETTINGS_SWITCH_TRACK,
            button_color=SETTINGS_SWITCH_KNOB, button_hover_color=SETTINGS_SWITCH_KNOB,
            command=command
        )
        switch.pack(side='left')
        return switch

    def _make_small_button(self, parent, text, command):
        return ctk.CTkButton(
            parent, text=text, width=60, height=28,
            command=command, fg_color="transparent", text_color=SETTINGS_TEXT_SOFT,
            hover_color=SETTINGS_HOVER,
            border_width=1, border_color=SETTINGS_INPUT_BORDER,
            corner_radius=8, font=ui_fonts.ui_font(12)
        )

    # ───────────────── 各区块构建 ─────────────────
    def _build_world_block(self):
        card, body = self._section_card(self.content, "世界", "world")
        self._world_card = card
        row = 0

        self._section_label(body, row, "规则")
        row += 1

        _, ctrl = self._make_row(body, row, "体型设定")
        row += 1
        self.world_setting_var = tk.StringVar(value=self.world_setting)
        self.world_setting_button = self._make_option_button(
            ctrl, list(WORLD_OPTIONS.keys()),
            self._on_world_option_changed, self.world_setting_var
        )
        for display, value in WORLD_OPTIONS.items():
            if value == self.world_setting:
                self.world_setting_button.set(display)
                break

        _, ctrl = self._make_row(body, row, "种子")
        row += 1
        self.seed_var = tk.StringVar(value=_seed_text(self.user_seed))
        self.seed_entry = self._make_entry(ctrl, self.seed_var, width=100)
        self.seed_entry.pack(side='left')
        self.seed_entry.bind("<FocusOut>", self._commit_seed, add="+")
        self.seed_entry.bind("<Return>", lambda _e: self._commit_seed(), add="+")
        self.seed_random_btn = self._make_small_button(ctrl, "随机", self._randomize_seed)
        self.seed_random_btn.pack(side='left', padx=(8, 0))

        # 信息更新速率决定世界向玩家反馈信息的更新程度：既影响部位描述被
        # 新文案覆写的概率，也影响加载时新闻取索引条目还是异常条目。
        self._section_label(body, row, "信息")
        row += 1

        _, ctrl = self._make_row(body, row, "信息更新速率")
        self.info_update_var = tk.StringVar(value="中等")
        for display, value in INFO_UPDATE_OPTIONS.items():
            if abs(value - self.info_update_rate) < 1e-9:
                self.info_update_var.set(display)
                break
        self.info_update_button = self._make_option_button(
            ctrl, list(INFO_UPDATE_OPTIONS.keys()),
            self._on_info_update_changed, self.info_update_var
        )

        self._set_world_controls_locked()

    def _build_generation_block(self):
        card, body = self._section_card(self.content, "生成", "gen")
        self._gen_card = card
        row = 0

        self._section_label(body, row, "尺寸对比")
        row += 1

        _, ctrl = self._make_row(body, row, "对比数量")
        row += 1
        self.count_var = tk.StringVar(value=str(self.comparison_count))
        self.count_entry = self._make_entry(ctrl, self.count_var, width=80)
        self.count_entry.pack(side='left')
        self.count_entry.bind("<FocusOut>", self._commit_count, add="+")
        self.count_entry.bind("<Return>", lambda _e: self._commit_count(), add="+")

        _, ctrl = self._make_row(body, row, "排序方式")
        row += 1
        self.order_var = tk.StringVar(value=self.comparison_order)
        self.order_button = self._make_option_button(
            ctrl, list(ORDER_OPTIONS.keys()),
            self._on_order_option_changed, self.order_var
        )
        for display, value in ORDER_OPTIONS.items():
            if value == self.comparison_order:
                self.order_button.set(display)
                break

        self._section_label(body, row, "叙述优化")
        row += 1

        _, ctrl = self._make_row(body, row, "叙述速率")
        row += 1
        self.rate_factor_var = tk.StringVar(value=str(self.quip_rate_factor))
        self.rate_factor_entry = self._make_entry(ctrl, self.rate_factor_var, width=80)
        self.rate_factor_entry.pack(side='left')
        self.rate_factor_entry.bind("<FocusOut>", self._commit_rate_factor, add="+")
        self.rate_factor_entry.bind("<Return>", lambda _e: self._commit_rate_factor(), add="+")

        _, ctrl = self._make_row(body, row, "混淆描述细分词库")
        row += 1
        self.confusion_var = tk.BooleanVar(value=self.enable_confusion)
        self.confusion_switch = self._make_switch(
            ctrl, self.confusion_var,
            command=lambda: self._autosave(enable_confusion=self.confusion_var.get()))

        _, ctrl = self._make_row(body, row, "屏蔽词")
        row += 1
        self.blocked_words_var = tk.StringVar(value=", ".join(self.blocked_words))
        self.blocked_words_entry = self._make_entry(
            ctrl, self.blocked_words_var, width=190,
            placeholder_text="（逗号分隔）"
        )
        self.blocked_words_entry.pack(side='left')
        self.blocked_words_entry.bind("<FocusOut>", self._commit_blocked_words, add="+")

        self._section_label(body, row, "报告详情栏")
        row += 1

        _, ctrl = self._make_row(body, row, "测量所有尺寸")
        row += 1
        self.show_all_details_var = tk.BooleanVar(value=self.settings.get("show_all_details", False))
        self.show_all_switch = self._make_switch(
            ctrl, self.show_all_details_var,
            command=lambda: self._autosave(show_all_details=self.show_all_details_var.get()))

        _, ctrl = self._make_row(body, row, "倒序展示尺寸")
        row += 1
        self.reverse_details_var = tk.BooleanVar(value=self.settings.get("reverse_details_order", False))
        self.reverse_details_switch = self._make_switch(
            ctrl, self.reverse_details_var,
            command=lambda: self._autosave(reverse_details_order=self.reverse_details_var.get()))

        _, ctrl = self._make_row(body, row, "未上传形象时使用身材预览图")
        row += 1
        self.use_preview_avatar_var = tk.BooleanVar(value=self.settings.get("use_preview_image_as_avatar", False))
        self.use_preview_avatar_switch = self._make_switch(
            ctrl, self.use_preview_avatar_var,
            command=lambda: self._autosave(
                use_preview_image_as_avatar=self.use_preview_avatar_var.get()))

        self._section_label(body, row, "部位设置")
        row += 1
        self._build_parts_selection(body, row)
        row += 1

        self._build_ai_section(body, row)

    def _build_display_block(self):
        card, body = self._section_card(self.content, "外观", "disp")
        self._disp_card = card
        row = 0

        self._section_label(body, row, "主题")
        row += 1

        palette_choices = palette_display_names_by_mode()
        palette_modes = palette_display_modes()
        palette_text_colors = {
            display: (SETTINGS_TEXT_SOFT
                      if palette_modes.get(display) == "Light"
                      else SETTINGS_LABEL)
            for display in palette_choices
        }

        _, ctrl = self._make_row(body, row, "默认配色")
        row += 1
        self.palette_var = tk.StringVar(value=self._palette_names[self.theme_palette])
        self.palette_menu = self._make_option_button(
            ctrl, palette_choices, self._on_palette_option_changed,
            self.palette_var, text_colors=palette_text_colors
        )
        self.palette_menu.set(self._palette_names[self.theme_palette])

        _, ctrl = self._make_row(body, row, "系统深色配色")
        row += 1
        self.dark_palette_var = tk.StringVar()
        self.dark_palette_menu = self._make_option_button(
            ctrl, [FOLLOW_DEFAULT_PALETTE] + palette_choices,
            self._on_dark_palette_changed, self.dark_palette_var,
            text_colors=palette_text_colors
        )
        self._set_dark_palette_menu(self.theme_dark_palette)

        self._section_label(body, row, "界面选项")
        row += 1

        # 启动界面模式：只决定**下次启动**用哪套界面，点这里不重建窗口。
        # 「退出时模式」跟随上次退出时所在的界面
        # （见 services.ui_mode.resolve_startup_mode）。
        _, ctrl = self._make_row(body, row, "启动界面模式")
        row += 1
        pref = self.settings.get(ui_mode.STARTUP_MODE_KEY, ui_mode.STARTUP_EXIT)
        self.ui_mode_var = tk.StringVar(value=ui_mode.label_of(pref))
        self.ui_mode_button = self._make_option_button(
            ctrl, [label for label, _pref in ui_mode.STARTUP_CHOICES],
            self._on_ui_mode_changed, self.ui_mode_var)

        self._section_label(body, row, "字体设置")
        row += 1

        _, ctrl = self._make_row(body, row, "报告主体")
        row += 1
        self.report_font_var = tk.StringVar(value=self.settings.get("report_font", ui_fonts.report_font_default()))
        self.report_font_entry = self._make_entry(ctrl, self.report_font_var, width=150)
        self.report_font_entry.pack(side='left')
        self.report_font_entry.bind(
            "<FocusOut>", lambda _e: self._commit_fonts(), add="+")

        _, ctrl = self._make_row(body, row, "报告描述")
        row += 1
        self.desc_font_var = tk.StringVar(value=self.settings.get("desc_font", ui_fonts.desc_font_default()))
        self.desc_font_entry = self._make_entry(ctrl, self.desc_font_var, width=150)
        self.desc_font_entry.pack(side='left')
        self.desc_font_entry.bind(
            "<FocusOut>", lambda _e: self._commit_fonts(), add="+")

        _, ctrl = self._make_row(body, row, "副本段落")
        row += 1
        self.dungeon_font_var = tk.StringVar(
            value=self.dungeon_settings.get("dungeon_font") or ui_fonts.dungeon_font_default())
        self.dungeon_font_entry = self._make_entry(ctrl, self.dungeon_font_var, width=150)
        self.dungeon_font_entry.pack(side='left')
        self.dungeon_font_entry.bind(
            "<FocusOut>", lambda _e: self._commit_fonts(), add="+")

        # 帧率 / 音量 / 停靠侧是副本窗口内的即时运行项，这里不提供入口。
        # 玩家若在设置里找这些项，给出明确去向，免得以为不支持（见发布指南 Q1）。
        ctk.CTkLabel(
            body,
            text="帧率、音量、停靠侧在副本窗口的设置面板中即时调整",
            font=ui_fonts.ui_font(11), text_color=SETTINGS_TEXT_SOFT,
            anchor='w'
        ).grid(row=row, column=0, columnspan=2, sticky='w',
               padx=18, pady=(0, 8))

    def _build_archive_block(self):
        card, body = self._section_card(self.content, "档案", "archive")
        self._archive_card = card
        row = 0

        self._section_label(body, row, "保存")
        row += 1

        _, ctrl = self._make_row(body, row, "自动保存报告")
        row += 1
        self.auto_save_report_var = tk.BooleanVar(value=self.settings.get("auto_save_report", False))
        self.auto_save_report_switch = self._make_switch(
            ctrl, self.auto_save_report_var,
            command=lambda: self._autosave(auto_save_report=self.auto_save_report_var.get()))

        # 副本回放的自动保存放这里而不是副本设置面板：它只在「探索模式且已加载
        # 角色」时生效，是档案层的开关；摆在副本面板里会让玩家以为任何一次
        # 开局都会自动存回放。关闭它不影响手动保存——退出副本时仍会问一次。
        _, ctrl = self._make_row(body, row, "自动保存副本回放")
        row += 1
        self.auto_save_replay_var = tk.BooleanVar(
            value=bool(self.dungeon_settings.get("auto_save_replay", False)))
        self.auto_save_replay_switch = self._make_switch(
            ctrl, self.auto_save_replay_var, command=self._commit_auto_save_replay)

        _, ctrl = self._make_row(body, row, "以低分辨率保存图片")
        row += 1
        self.save_low_resolution_var = tk.BooleanVar(value=self.settings.get("save_low_resolution_image", False))
        self.save_low_resolution_switch = self._make_switch(
            ctrl, self.save_low_resolution_var,
            command=lambda: self._autosave(
                save_low_resolution_image=self.save_low_resolution_var.get()))

        # ── 展示与导出 ──
        self._section_label(body, row, "展示与导出")
        row += 1

        # 报告与档案导出里呈现哪些记录，归档案块；只裁剪展示，不改伤亡计算，
        # 也不改世界履历的写入（两处始终记录）。
        _, ctrl = self._make_row(body, row, "展示世界履历")
        row += 1
        self.world_history_var = tk.BooleanVar(value=self.settings.get("world_history_enabled", True))
        self.world_history_switch = self._make_switch(
            ctrl, self.world_history_var,
            command=lambda: self._autosave(
                world_history_enabled=self.world_history_var.get()))

        _, ctrl = self._make_row(body, row, "展示伤亡统计")
        self.show_casualties_var = tk.BooleanVar(value=self.settings.get("show_casualties", True))
        self.show_casualties_switch = self._make_switch(
            ctrl, self.show_casualties_var,
            command=lambda: self._autosave(show_casualties=self.show_casualties_var.get()))

    def _build_parts_selection(self, parent, row):
        parts_frame = ctk.CTkFrame(parent, fg_color="transparent")
        parts_frame.grid(row=row, column=0, columnspan=2, sticky='ew',
                         padx=18, pady=(0, 8))

        grid_frame = ctk.CTkFrame(parts_frame, fg_color="transparent")
        grid_frame.pack(fill='x', expand=True)

        # 空选按全部部位处理（见 _commit_parts），这里显式说明，
        # 不让玩家以为"一个都不选 = 报告不列尺寸"却得到相反结果。
        ctk.CTkLabel(
            parts_frame, text="全部取消勾选时按全部部位处理",
            font=ui_fonts.ui_font(11), text_color=SETTINGS_TEXT_SOFT,
            anchor='w'
        ).pack(fill='x', padx=2, pady=(2, 0))

        cols = 5
        selected = self.settings.get("selected_parts", ALL_PART_NAMES)
        for idx, part_name in enumerate(ALL_PART_NAMES):
            var = tk.BooleanVar(value=(part_name in selected))
            cb = ctk.CTkCheckBox(
                grid_frame, text=part_name, variable=var, width=95,
                font=ui_fonts.ui_font(12), text_color=SETTINGS_LABEL,
                fg_color=SETTINGS_TEXT_SOFT, hover_color=SETTINGS_CHECKBOX_HOVER,
                checkbox_width=18, checkbox_height=18, corner_radius=4,
                command=self._commit_parts
            )
            row_i = idx // cols
            col_i = idx % cols
            cb.grid(row=row_i, column=col_i, padx=2, pady=3, sticky='w')
            self.parts_checkboxes[part_name] = var

    def _build_ai_section(self, parent, row):
        self._section_label(parent, row, "网络与 AI")
        row += 1

        # AI 配置不再是「选一个 → 再弹对话框改」的两层结构：左侧列出全部配置，
        # 右侧是当前配置的表单，表单里的改动逐项落盘（与对话框其余部分一致）。
        ctk.CTkLabel(
            parent, text="AI 配置", anchor='nw', font=_FONT,
            text_color=SETTINGS_LABEL
        ).grid(row=row, column=0, sticky='new', padx=(10, 0), pady=(6, 0))
        self._build_ai_editor(parent, row)
        row += 1

        # 网络代理（可留空）：语音合成与 AI 文本生成**共用**同一份联网代理，见
        # core/netproxy.py。留空并非固定直连，而是按「显式设置 > 环境变量 >
        # 直连」解析：先看 DUNGEON_NET_PROXY / HTTPS_PROXY / HTTP_PROXY，都没有
        # 才直连。填了就立即对后续请求生效。VPN 的「系统代理」(WinINET) Python
        # 看不见，那种情况必须填在这里。
        _, proxy_control = self._make_row(parent, row, "网络代理")
        self.net_proxy_var = tk.StringVar(
            value=self.settings.get("net_proxy", "") or "")
        self.net_proxy_entry = self._make_entry(
            proxy_control, self.net_proxy_var, width=190,
            placeholder_text="留空：环境变量或直连")
        self.net_proxy_entry.pack(side='left')
        self.net_proxy_entry.bind("<FocusOut>", self._commit_net_proxy, add="+")
        self.net_proxy_entry.bind("<Return>", lambda _e: self._commit_net_proxy(), add="+")

    # ───────────────── 左侧导航与滚动 ─────────────────
    def _scroll_to_section(self, target):
        """滚到某个分类的卡片顶部。

        坐标一律在 canvas 内取：``canvasy(0)`` 是当前视口相对内容的纵向偏移，
        祖先控件的布局/内边距都算在两者之差里，不能自己另加 padding。
        """
        try:
            card = (self._world_card, self._gen_card,
                    self._disp_card, self._archive_card)[target]
            canvas = self.content._parent_canvas
            box = self.content._parent_frame  # canvas 的父级，滚动内容从它顶上开始
            self.update_idletasks()
            top = card.winfo_rooty() - box.winfo_rooty() + canvas.canvasy(0)
            span = max(1, self.content.winfo_reqheight())
            canvas.yview_moveto(max(0.0, min(1.0, top / span)))
        except Exception:
            return
        self._set_nav_active(target)

    def _sync_nav_highlight(self, _event=None):
        """滚动后按当前视口把导航高亮到最接近顶部的分类（不反向带动滚动）。"""
        try:
            canvas = self.content._parent_canvas
            box = self.content._parent_frame
            offset = canvas.canvasy(0)
            active = 0
            for idx, card in enumerate((self._world_card, self._gen_card,
                                        self._disp_card, self._archive_card)):
                if card.winfo_rooty() - box.winfo_rooty() + offset <= 48:
                    active = idx
            self._set_nav_active(active)
        except Exception:
            return

    def _set_nav_active(self, active):
        """高亮某一分类。只在真的变化时重绘，避免 configure → <Configure> 成环。"""
        if active == self._nav_active:
            return
        self._nav_active = active
        for idx, btn in self._nav_buttons.items():
            if idx == active:
                btn.configure(fg_color=SETTINGS_HOVER, text_color=DLG_TITLE)
            else:
                btn.configure(fg_color="transparent", text_color=SETTINGS_LABEL)

    # ───────────────── 世界包联动（规则段） ─────────────────
    def _set_world_controls_locked(self):
        """按包锁定的设置键禁用规则段控件（取材表菜单的锁在资源中心页）。"""
        locked = self.world_state.locked_keys() if self.world_state is not None else set()
        self.world_setting_button.configure(
            state="disabled" if "world_setting" in locked else "normal")
        self.seed_entry.configure(state="disabled" if "seed" in locked else "normal")
        self.seed_random_btn.configure(state="disabled" if "seed" in locked else "normal")

    def _sync_world_vars(self):
        """按 self.settings 刷新规则段控件（世界包 settings 可能改写体型/种子）。"""
        world_setting = self.settings.get("world_setting", "appear")
        for display, value in WORLD_OPTIONS.items():
            if value == world_setting:
                self.world_setting_button.set(display)
                break
        self.world_setting = world_setting

        seed = self.settings.get("seed", 0)
        self.seed_var.set(str(seed) if seed != 0 else "")
        self.user_seed = seed
        self._set_world_controls_locked()

    # ───────────────── 部位选择同步 ─────────────────
    def _sync_parts_states(self):
        """按 self.settings 刷新部位多选（风格列表的同步在资源中心页）。"""
        selected = self.settings.get("selected_parts", ALL_PART_NAMES)
        for part, var in self.parts_checkboxes.items():
            var.set(part in selected)

    # ───────────────── 即时保存 ─────────────────
    def _autosave(self, **updates):
        """把若干设置写完落盘。所有控件回调都从这里出去，避免各写各的。"""
        if not updates:
            return
        self.settings.update(updates)
        self._save_settings()

    def _save_settings(self):
        try:
            self.settings_repo.save(self.settings)
        except Exception as e:
            print(f"[Warning] 保存设置失败: {e}")

    def _autosave_dungeon(self, **patch):
        """副本独占设置走自己的文件（data/user/dungeon_settings.json）。"""
        try:
            self.dungeon_settings = self.dungeon_settings_repo.update(patch)
        except Exception as e:
            print(f"[Warning] 保存副本设置失败: {e}")

    def _commit_seed(self):
        raw = self.seed_var.get().strip()
        try:
            seed = int(float(raw)) & 0x7FFFFFFF if raw != "" else 0
        except ValueError:
            # 输入了非数字：回填当前有效值，别让输入框一直停在错的状态
            self.seed_var.set(_seed_text(self.settings.get("seed", 0)))
            return
        self.user_seed = seed
        self.seed_var.set(_seed_text(seed))
        self._autosave(seed=seed)

    def _commit_count(self):
        try:
            count = max(1, min(10, int(self.count_var.get())))
        except (ValueError, TypeError):
            count = self.settings.get("comparison_count", 5)
        self.comparison_count = count
        self.count_var.set(str(count))
        self._autosave(comparison_count=count)

    def _commit_rate_factor(self):
        try:
            rate_factor = max(0.5, min(2.0, float(self.rate_factor_var.get())))
        except (ValueError, TypeError):
            rate_factor = 1.0
        self.quip_rate_factor = rate_factor
        self.rate_factor_var.set(f"{rate_factor:g}")
        self._autosave(quip_rate_factor=rate_factor)

    def _commit_blocked_words(self):
        words = normalize_blocked_words(self.blocked_words_var.get())
        self.blocked_words = words
        self.blocked_words_var.set(", ".join(words))
        self._autosave(blocked_words=words)

    def _commit_net_proxy(self):
        value = self.net_proxy_var.get().strip()
        self.net_proxy_var.set(value)
        self._autosave(net_proxy=value)
        # 语音与 AI 共用同一份覆盖值——设一次两处都跟，改动立即作用于后续请求。
        netproxy.set_override(value)

    def _commit_fonts(self):
        """三个字体输入框共用一次提交：任一失焦时一并校验并规范化。"""
        report_font = self._validate_font(
            self.report_font_var.get().strip(), ui_fonts.report_font_default())
        desc_font = self._validate_font(
            self.desc_font_var.get().strip(), ui_fonts.desc_font_default())
        dungeon_font = self._validate_font(
            self.dungeon_font_var.get().strip(), ui_fonts.dungeon_font_default())

        self.report_font_var.set(report_font)
        self.desc_font_var.set(desc_font)
        self.dungeon_font_var.set(dungeon_font)

        self._autosave(report_font=report_font, desc_font=desc_font)
        if dungeon_font != (self.dungeon_settings.get("dungeon_font")
                            or ui_fonts.dungeon_font_default()):
            self._autosave_dungeon(dungeon_font=dungeon_font)

    @staticmethod
    def _validate_font(font_name, default):
        """字体名不落在系统字体表里就回落到默认字体。"""
        font_name = ui_fonts.font_family_for(font_name, default)
        if not font_name:
            return default
        available = [f.lower() for f in tkfont.families()]
        if font_name.lower() in available:
            return font_name
        cleaned = font_name.strip("'\"")
        if cleaned.lower() in available:
            return cleaned
        return default

    def _commit_parts(self):
        selected = [part for part, var in self.parts_checkboxes.items() if var.get()]
        if not selected:
            selected = ALL_PART_NAMES.copy()
        self._autosave(selected_parts=selected)

    def _commit_auto_save_replay(self):
        self._autosave_dungeon(
            auto_save_replay=bool(self.auto_save_replay_var.get()))

    # ───────────────── AI 配置 ─────────────────
    def _load_ai_configs(self):
        """Load named profiles from settings."""
        configs = self.settings.get("ai_configs") or {}
        return {pid: dict(cfg) for pid, cfg in configs.items()}

    def _profile_labels(self):
        return profile_labels(self.ai_configs)

    def _profile_label(self, profile_id):
        return self._profile_labels().get(profile_id, profile_id)

    def _build_ai_editor(self, parent, row):
        """AI 配置编辑器：左侧配置列表，右侧当前配置的表单。

        与「选一个配置 → 再弹一层对话框改」相比，这里没有「确定 / 取消」：
        列表点击即切换当前配置，表单逐项 ``FocusOut`` 校验后写回并落盘。
        配置标识（``provider``）由创建时随机生成，改名只影响显示，不动引用。
        """
        box = ctk.CTkFrame(parent, fg_color=SETTINGS_INPUT_BG, corner_radius=8)
        box.grid(row=row, column=0, columnspan=2, sticky='ew',
                 padx=10, pady=(0, 8))
        box.columnconfigure(1, weight=1)

        # ---- 左：配置列表 ----
        left = ctk.CTkFrame(box, fg_color="transparent")
        left.grid(row=0, column=0, sticky='ns', padx=(10, 8), pady=10)

        self._ai_list_frame = ctk.CTkFrame(left, fg_color="transparent")
        self._ai_list_frame.pack(fill='x')
        self._make_small_button(left, "新建配置", self._new_ai_config).pack(
            fill='x', pady=(8, 0))

        # ---- 右：当前配置的表单 ----
        form = ctk.CTkFrame(box, fg_color="transparent")
        form.grid(row=0, column=1, sticky='ew', pady=10, padx=(0, 10))
        form.columnconfigure(1, weight=1)

        self.ai_name_var = tk.StringVar()
        self.ai_url_var = tk.StringVar()
        self.ai_model_var = tk.StringVar()
        self.ai_key_var = tk.StringVar()

        fields = (
            ("配置名称", self.ai_name_var, None, self._commit_ai_name),
            ("接口 URL", self.ai_url_var,
             "留空使用该服务商的默认地址", self._commit_ai_url),
            ("模型名称", self.ai_model_var, None, self._commit_ai_model),
            ("API Key", self.ai_key_var, None, self._commit_ai_key),
        )
        self._ai_entries = {}
        for idx, (caption, var, placeholder, commit) in enumerate(fields):
            ctk.CTkLabel(
                form, text=caption, anchor='w', font=_FONT,
                text_color=SETTINGS_LABEL
            ).grid(row=idx, column=0, sticky='w', padx=(0, 12), pady=(0, 6))
            entry = self._make_entry(
                form, var, width=200,
                show="*" if caption == "API Key" else None,
                placeholder_text=placeholder)
            entry.grid(row=idx, column=1, sticky='ew', pady=(0, 6))
            entry.bind("<FocusOut>", commit, add="+")
            entry.bind("<Return>", lambda _e, c=commit: c(), add="+")
            self._ai_entries[caption] = entry

        # 服务商模板：一键填好 URL 与模型，Key 由用户自己填。
        ctk.CTkLabel(
            form, text="快速模板", anchor='w', font=ui_fonts.ui_font(11),
            text_color=SETTINGS_TEXT_SOFT
        ).grid(row=len(fields), column=0, sticky='w', pady=(4, 0))
        templates = ctk.CTkFrame(form, fg_color="transparent")
        templates.grid(row=len(fields), column=1, sticky='w', pady=(4, 0))
        for profile_id in PROVIDER_DEFAULTS:
            self._make_small_button(
                templates, PROVIDER_DEFAULTS[profile_id].get("name", profile_id),
                lambda pid=profile_id: self._apply_ai_template(pid)
            ).pack(side='left', padx=(0, 6))

        status_row = ctk.CTkFrame(form, fg_color="transparent")
        status_row.grid(row=len(fields) + 1, column=0, columnspan=2,
                        sticky='ew', pady=(10, 0))
        self._ai_test_btn = self._make_small_button(
            status_row, "测试连接", self._test_ai_connection)
        self._ai_test_btn.pack(side='left')
        self._make_small_button(status_row, "删除配置", self._delete_ai_config) \
            .pack(side='left', padx=(8, 0))
        self._ai_test_label = ctk.CTkLabel(
            status_row, text="", anchor='w', font=ui_fonts.ui_font(11),
            text_color=SETTINGS_TEXT_SOFT)
        self._ai_test_label.pack(side='left', padx=(12, 0))

        self._ai_buttons = {}
        self._refresh_ai_editor()

    def _refresh_ai_editor(self):
        """按 ``self.ai_configs`` 与 ``self.ai_provider`` 重建列表并回填表单。"""
        if not hasattr(self, "_ai_list_frame"):
            return
        labels = self._profile_labels()
        if self.ai_provider not in self.ai_configs:
            self.ai_provider = next(iter(self.ai_configs), "")

        for child in self._ai_list_frame.winfo_children():
            child.destroy()
        self._ai_buttons = {}
        for profile_id, label in labels.items():
            active = profile_id == self.ai_provider
            btn = ctk.CTkButton(
                self._ai_list_frame, text=f"使用中 · {label}" if active else label,
                anchor='w', width=150, height=30,
                command=lambda pid=profile_id: self._on_ai_provider_changed(pid),
                fg_color=SETTINGS_HOVER if active else "transparent",
                text_color=SETTINGS_LABEL if active else SETTINGS_TEXT_SOFT,
                hover_color=SETTINGS_HOVER, corner_radius=6,
                font=ui_fonts.ui_font(12))
            btn.pack(fill='x', pady=(0, 4))
            self._ai_buttons[profile_id] = btn

        cfg = self.ai_configs.get(self.ai_provider, {})
        defaults = PROVIDER_DEFAULTS.get(self.ai_provider, {})
        self.ai_name_var.set(cfg.get("name") or defaults.get("name", ""))
        self.ai_url_var.set(cfg.get("url") or defaults.get("url", ""))
        self.ai_model_var.set(cfg.get("model") or defaults.get("model", ""))
        self.ai_key_var.set(cfg.get("api_key") or "")

        can_delete = len(self.ai_configs) > 1
        self._ai_test_label.configure(text="", text_color=SETTINGS_TEXT_SOFT)
        self._ai_test_btn.configure(state="normal")

    def _commit_ai_configs(self):
        self._autosave(ai_provider=self.ai_provider,
                       ai_configs={pid: dict(cfg) for pid, cfg in self.ai_configs.items()})

    def _on_ai_provider_changed(self, profile_id):
        """点列表切换「当前使用」的配置。"""
        if profile_id == self.ai_provider or profile_id not in self.ai_configs:
            return
        self.ai_provider = profile_id
        self._commit_ai_configs()
        self._refresh_ai_editor()

    def _ai_field(self, key, var, label, allow_empty=False):
        """把表单某一项写回当前配置；空值按「回落到服务商默认」处理。"""
        value = var.get().strip()
        if not value and not allow_empty:
            self._ai_test_label.configure(
                text=f"{label}不能为空", text_color=DLG_ERR)
            return
        cfg = self.ai_configs.setdefault(self.ai_provider, {})
        if cfg.get(key) == value:
            return
        cfg[key] = value
        if key == "name":
            # 改名只刷新列表文字，避免重建列表打断正在编辑的输入框
            active = self.ai_provider
            btn = self._ai_buttons.get(active)
            if btn is not None:
                btn.configure(text=f"使用中 · {value}")
        self._commit_ai_configs()

    def _commit_ai_name(self):
        self._ai_field("name", self.ai_name_var, "配置名称")

    def _commit_ai_url(self):
        self._ai_field("url", self.ai_url_var, "接口 URL", allow_empty=True)

    def _commit_ai_model(self):
        self._ai_field("model", self.ai_model_var, "模型名称")

    def _commit_ai_key(self):
        self._ai_field("api_key", self.ai_key_var, "API Key", allow_empty=True)

    def _apply_ai_template(self, profile_id):
        """按服务商模板填 URL 与模型（Key 保留用户已填的值）。"""
        if self.ai_provider not in self.ai_configs:
            return
        defaults = PROVIDER_DEFAULTS.get(profile_id, {})
        self.ai_url_var.set(defaults.get("url", ""))
        self.ai_model_var.set(defaults.get("model", ""))
        self._commit_ai_url()
        self._commit_ai_model()
        self._ai_test_label.configure(
            text=f"已填入{defaults.get('name', profile_id)}的默认地址与模型",
            text_color=SETTINGS_TEXT_SOFT)

    def _new_ai_config(self):
        provider = "profile_" + uuid.uuid4().hex[:8]
        self.ai_configs[provider] = {
            "name": f"新配置 {len(self.ai_configs) + 1}",
            "url": "", "model": "", "api_key": "",
        }
        self.ai_provider = provider
        self._commit_ai_configs()
        self._refresh_ai_editor()
        entry = self._ai_entries.get("配置名称")
        if entry is not None:
            entry.focus_set()

    def _delete_ai_config(self):
        """删除当前配置；至少保留一个，否则界面就没有可用的 AI 后端了。"""
        if len(self.ai_configs) <= 1:
            self._ai_test_label.configure(
                text="至少保留一个配置", text_color=DLG_ERR)
            return
        name = self.ai_configs.get(self.ai_provider, {}).get("name") or self.ai_provider
        if not ui_dialogs.askyesno(
                "确认删除", f"确定要删除配置「{name}」吗？\n此操作不可恢复。",
                parent=self):
            return
        self.ai_configs.pop(self.ai_provider, None)
        self.ai_provider = next(iter(self.ai_configs), "")
        self._commit_ai_configs()
        self._refresh_ai_editor()

    def _test_ai_connection(self):
        """在后台线程里试连当前配置，结果回到 UI 线程显示。"""
        cfg = {
            "name": self.ai_name_var.get().strip(),
            "url": self.ai_url_var.get().strip(),
            "model": self.ai_model_var.get().strip(),
            "api_key": self.ai_key_var.get().strip(),
        }
        if not cfg["api_key"]:
            self._ai_test_label.configure(
                text="请先填写 API Key", text_color=DLG_ERR)
            return
        self._ai_test_label.configure(
            text="正在测试连接...", text_color=SETTINGS_TEXT_SOFT)
        self._ai_test_btn.configure(state="disabled")
        threading.Thread(
            target=self._run_ai_test, args=(self.ai_provider, cfg), daemon=True
        ).start()

    def _run_ai_test(self, provider, cfg):
        try:
            client = create_client(
                provider, cfg["api_key"],
                base_url=cfg["url"] or None, model=cfg["model"] or None)
            ok, msg = client.test_connection()
        except Exception as e:
            ok, msg = False, describe_ai_error(e)
        try:
            self.after(0, lambda: self._ai_test_done(ok, msg))
        except tk.TclError:
            return  # 对话框在测试期间被关掉了

    def _ai_test_done(self, ok, msg):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        self._ai_test_btn.configure(state="normal")
        if ok:
            self._ai_test_label.configure(
                text="连接成功", text_color=SETTINGS_OK)
        else:
            self._ai_test_label.configure(
                text=f"连接失败：{msg or '未知错误'}", text_color=DLG_ERR)

    # ───────────────── 回调 ─────────────────
    def _on_world_option_changed(self, choice):
        self.world_setting = WORLD_OPTIONS.get(choice, "appear")
        self._autosave(world_setting=self.world_setting)
        if self.on_world_setting_changed:
            self.on_world_setting_changed(self.world_setting)

    def _on_order_option_changed(self, choice):
        self.comparison_order = ORDER_OPTIONS.get(choice, "match")
        self._autosave(comparison_order=self.comparison_order)

    def _on_info_update_changed(self, choice):
        self.info_update_rate = INFO_UPDATE_OPTIONS.get(choice, 0.5)
        self._autosave(info_update_rate=self.info_update_rate)

    def _set_dark_palette_menu(self, name):
        """把系统深色配色名写回下拉框；空值显示「跟随默认值」。"""
        self.dark_palette_menu.set(
            self._palette_names.get(name, FOLLOW_DEFAULT_PALETTE))

    def _on_dark_palette_changed(self, choice):
        self.theme_dark_palette = self._palette_options.get(choice, "")
        self._hint_palette_pending()

    def _on_palette_option_changed(self, choice):
        """只记在内存里：配色在关闭对话框时统一提交并换色。"""
        self.theme_palette = self._palette_options.get(choice, DEFAULT_PALETTE)
        self._hint_palette_pending()

    def _hint_palette_pending(self):
        """选完配色后说明「还没生效、关窗时套用」，避免以为点了没反应。"""
        if self.theme_palette == (self.settings.get("theme_palette") or DEFAULT_PALETTE) \
                and self.theme_dark_palette == (self.settings.get("theme_dark_palette") or ""):
            self.footer_note.configure(text="改动即时生效并保存，换配色会在关闭本窗口时套用")
        else:
            self.footer_note.configure(text="配色已记录：关闭本窗口时套用")

    def _on_ui_mode_changed(self, value):
        """记录「下次启动用哪套界面」，仅此而已。

        这个选项**只影响启动**：点击只把选择写进设置，不重建窗口。界面重建会
        丢掉当前界面上的编辑状态，所以实时切换不放在设置里——那是导航栏底部
        「切换界面」的职责（见 ``MainWindowManager.prompt_switch_to_mini``）。

        「退出时模式」意味着下次启动跟随上次退出时所在的界面——实际模式由
        ``app.shell.switch_to`` 在每次切换时落盘（``ui_mode`` 键），这里不碰它。
        """
        # 词表与落盘都在共享的 services.ui_mode（ui 层不得 import 应用外壳）。
        pref = ui_mode.pref_of_label(value)
        ui_mode.save_startup_mode(pref)
        self._autosave(**{ui_mode.STARTUP_MODE_KEY: pref})

    def _randomize_seed(self):
        new_seed = random.randint(1, 2 ** 31 - 1)
        self.seed_var.set(str(new_seed))
        self._commit_seed()

    # ───────────────── 关闭 ─────────────────
    def _flush_text_entries(self, focus=None):
        """把失焦的文本输入框里的内容提交掉（值没变则不写盘）。

        调用点只有两处：关闭对话框时、以及各输入框自己的 ``<FocusOut>``。
        不再用整个窗口的 ``<FocusIn>`` 兜底——焦点在对话框内部每换一次控件都会
        触发一遍，叠加 ``tkfont.families()`` 的字体验证，会把点击变成一串
        同步的写盘。

        ``focus`` 是刚刚拿到焦点的控件；它是哪个输入框，哪个就还没「离开」，
        跳过不提交。
        """
        commits = (
            (self.seed_entry, self.seed_var, self._commit_seed, _seed_text(
                self.settings.get("seed", 0))),
            (self.count_entry, self.count_var, self._commit_count, str(
                self.settings.get("comparison_count", 5))),
            (self.rate_factor_entry, self.rate_factor_var, self._commit_rate_factor,
             f"{self.settings.get('quip_rate_factor', 1.0):g}"),
            (self.blocked_words_entry, self.blocked_words_var,
             self._commit_blocked_words,
             ", ".join(normalize_blocked_words(self.settings.get("blocked_words", [])))),
            (self.net_proxy_entry, self.net_proxy_var, self._commit_net_proxy,
             self.settings.get("net_proxy", "") or ""),
        )
        for entry, var, commit, committed in commits:
            if entry is focus:
                continue
            if var.get() != committed:
                commit()

        if focus in (self.report_font_entry, self.desc_font_entry, self.dungeon_font_entry):
            return
        fonts_dirty = (
            self.report_font_var.get() != (self.settings.get("report_font")
                                           or ui_fonts.report_font_default())
            or self.desc_font_var.get() != (self.settings.get("desc_font")
                                            or ui_fonts.desc_font_default())
            or self.dungeon_font_var.get() != (self.dungeon_settings.get("dungeon_font")
                                               or ui_fonts.dungeon_font_default()))
        if fonts_dirty:
            self._commit_fonts()

    def _close(self):
        """收尾：提交文本输入 → 提交配色 → 关窗。

        配色必须在本窗口还活着的时候交给主窗口去套用：``apply_settings()``
        会先铺加载遮罩、整批重绘主窗口，本对话框随后才销毁，否则用户会先看到
        一个旧配色的窗口再消失。
        """
        if getattr(self, '_closing', False):
            return
        self._flush_text_entries()

        palette = self.theme_palette or DEFAULT_PALETTE
        dark_palette = self.theme_dark_palette
        changed = (palette != (self.settings.get("theme_palette") or DEFAULT_PALETTE)
                   or dark_palette != (self.settings.get("theme_dark_palette") or ""))
        if changed:
            self._autosave(theme_palette=palette, theme_dark_palette=dark_palette)
        try:
            self.grab_release()
        except tk.TclError:
            pass
        # 先撤遮罩再换色：换色期间主窗口要被加载遮罩盖住，不该再压一层旧遮罩
        self._drop_backdrop()
        if changed and self.gui_ref is not None and hasattr(self.gui_ref, "apply_settings"):
            try:
                self.gui_ref.apply_settings()
            except Exception as e:
                print(f"[Warning] 应用新配色失败: {e}")
        super()._close()
