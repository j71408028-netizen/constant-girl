import ui.ctk.dialogs
import customtkinter as ctk
import copy
import os
from dungeon.audio.chapters import normalize_chapters
from dungeon.admission import (FIELD_ADDRESS, FIELD_HEIGHT_MAX, FIELD_HEIGHT_MIN,
                               FIELD_MAX_DISTANCE, coerce_distance,
                               normalize_fields as normalize_admission_fields)
from dungeon.coupling import (COUPLING_LEVELS, DEFAULT_COUPLING_LEVEL,
                              coupling_initial_prompt,
                              coupling_label, normalize_coupling_level)
from dungeon.rules import EvolutionRules
from dungeon.cast import normalize_cast
from dungeon.schema import (DEFAULT_TEXT_COMPONENT, normalize_initial_coord,
                            normalize_text_component)
from dungeon.speaker_notation import (
    DEFAULT_SPEAKER_NOTATION, SPEAKER_NOTATIONS, SPEAKER_NOTATION_LABELS,
    normalize_speaker_notation)
from dungeon.audio.speech import normalize_voice
from ui.ctk.widgets import (CTkScrollableDropdownFrame, CTkToggleButtons,
                               OptionButton)
from ui.ctk.address_dlg import AddressTextDialog
from ui.ctk.dialogs import BaseDialog, ResourceNameDialog
from ui.scenario import diagnostics as tab
from ui.scenario.diagnostics import root_key as diag_root_key
from ui.scenario.diagnostics import summarize as diag_summarize
from ui.scenario.chapter_trigger_mgr import ChapterTriggerManager
from ui.scenario.graph_view import (VIEW_CHAPTERS, VIEW_TRIGGERS,
                                    ScenarioGraphPanel)
from ui.ctk.widgets import CTkSegmentedControl
#: 剧情页的三个标签：章节触发器列表 / 章节编排图 / 触发器依赖图。
#: 后两者的文案直接复用 graph_view 的视图名，传入 set_data(view=...) 即可选图。
STORY_VIEW_ROWS = "章节与触发器"
STORY_VIEWS = (STORY_VIEW_ROWS, VIEW_CHAPTERS, VIEW_TRIGGERS)
from dungeon.terms import DEFAULT_SCENARIO_ID, scenario_config_of, scenario_id_of
from dungeon.validate import (LEVEL_LABELS, format_diagnostics, has_errors,
                              validate_scenario_config)
from ui.scenario.character_page import CharacterPage
from ui.scenario.component_mgr import ComponentManager
from services.challenges import unique_display
from ui.ctk.theme import (
    SC_BG, SC_PANEL_BG, SC_BORDER, SC_BORDER_STRONG,
    SC_HOVER, SC_MENU_HOVER, SC_CARD_HOVER, SC_TEXT,
    SC_TEXT_SOFT, SC_TITLE, SC_LINK, SC_OK,
    SC_OK_HOVER, SC_ERR, SC_ERR_HOVER,
    SEG_TRACK_BG, SEG_TRACK_BORDER,
)
from ui.ctk import fonts as ui_fonts


def _format_optional_number(value):
    """准入输入框显示：None → 空串，数字去掉多余小数位。"""
    if value is None:
        return ""
    return f"{float(value):g}"


# ==================== 剧本编辑器 ====================
class ScenarioEditor(ctk.CTkFrame):
    """剧本编辑器：通用区域 + 两个 TreeviewManager 子面板（属性/触发器）"""

    def __init__(self, parent, scenario_repo, gui_ref, challenge_mgr=None):
        super().__init__(parent, fg_color="transparent")
        self._scenario_repo = scenario_repo
        self._challenge_mgr = challenge_mgr
        self.gui = gui_ref
        self.current_scenario_id = None
        self.initial_prompt = ""
        self.section_prompts = {}
        self.coupling_level = DEFAULT_COUPLING_LEVEL
        self.speaker_notation = DEFAULT_SPEAKER_NOTATION  # 说话人写法：方案级二选一
        self.protagonist_title = ""
        self.protagonist_background = ""  # 主角身份背景（故事开始时的样子）
        self.cast = []  # 人物表：重要角色（key）与群像（extra）
        # 对话语音（带结构化说话人的台词朗读）：未配置时按默认值走
        self.voice = normalize_voice(None)
        self.text_component = DEFAULT_TEXT_COMPONENT  # 文本主组件三选一
        self.evolution_attrs = []  # 统一演化量列表
        self.chapters = []  # 章节列表（不含条件，只描述背景与持续演化修正）
        self.triggers = []
        self.components = []  # 显示组件 id 列表（不含文本主组件）
        self.components_params = {}  # {组件id: {参数: 值}}
        self._modified = False
        self._saved_prompt_snapshot = {}  # 用于检测提示词是否被修改
        self._prompt_modified = False  # 辅助标志（实际用快照对比更准确）
        # 顶栏校验条的状态：最近一次校验的汇总（None = 还没校验过）
        self._diag_summary = None
        # 抽屉展开状态自己记：CTkScrollableFrame.winfo_manager() 恒为 'canvas'，
        # pack 与否只看内部 _parent_frame，不能拿它当展开依据（见 _toggle_diag_panel）
        self._diag_panel_open = False
        self.story_view_switch = None

        # --- 新增：自定义步进值与转移矩阵 ---
        self.section_steps = {}
        self.transition_matrix = None

        # 进入副本所需行动点数（0 表示免费）
        self.entry_action_cost = 0
        # 进入准入：入口地址（主世界锚点）/ 距离上限（None=不限）/ 身高区间（None=不限）
        self.entry_address = ""
        self.entry_address_max_distance = None
        self.entry_height_min = None
        self.entry_height_max = None
        # 起始坐标（限制带入）：None = 低区间随机、不继承角色当前坐标
        self.initial_intrusion = None
        self.initial_destruction = None

        self._build_ui()
        self._refresh_scenario_list()
        self._load_scenario(DEFAULT_SCENARIO_ID)

    def _build_ui(self):
        toolbar = ctk.CTkFrame(self, fg_color=SC_BG)
        toolbar.pack(fill='x', padx=10, pady=6)

        # 右侧：页签收进带底色的轨道，选中项铺浅底——与校验条的分段同一套语言
        tabs_track = ctk.CTkFrame(toolbar, fg_color=SEG_TRACK_BG,
                                  border_width=1, border_color=SEG_TRACK_BORDER,
                                  corner_radius=9)
        tabs_track.pack(side='right', padx=(6, 2), pady=(3, 1))
        self.dungeon_switch_btn = CTkToggleButtons(
            tabs_track,
            values=["通用", "角色", tab.TAB_STORY, "组件"],
            command=self._on_scenario_tab_switch,
            button_width=80, height=28, font=ui_fonts.ui_font(13)
        )
        self.dungeon_switch_btn.pack(padx=2, pady=2)
        # 初始化即选中“通用”
        self.dungeon_switch_btn.set("通用")

        # 左侧：方案身份收进描边胶囊——标签 + 下拉 + 紧凑图标动作成一块
        picker = ctk.CTkFrame(toolbar, fg_color=SC_PANEL_BG,
                              border_width=1, border_color=SC_BORDER_STRONG,
                              corner_radius=8)
        picker.pack(side='left', padx=5, pady=(3, 1))
        ctk.CTkLabel(picker, text="方案", font=ui_fonts.ui_font(11),
                     text_color=SC_TEXT_SOFT).pack(side='left', padx=(11, 2))
        # ---- CTkComboBox + CTkScrollableDropdownFrame ----
        self.scenario_combo = ctk.CTkComboBox(
            picker,
            values=[],
            state="readonly",
            width=148,
            fg_color=SC_PANEL_BG,
            border_color=SC_BORDER,
            button_color=SC_BORDER_STRONG,
            button_hover_color=SC_MENU_HOVER,
            dropdown_fg_color=SC_PANEL_BG,
            dropdown_hover_color=SC_HOVER
        )
        self.scenario_combo.pack(side='left', padx=4, pady=4)
        self._rebuild_dropdown()

        _icon = dict(fg_color="transparent", border_width=0, corner_radius=6,
                     width=28, font=ui_fonts.ui_font(14))
        ctk.CTkButton(picker, text="＋", command=self._new_scenario,
                      text_color=SC_OK, hover_color=SC_OK_HOVER,
                      **_icon).pack(side='left', padx=(0, 1))
        ctk.CTkButton(picker, text="✎", command=self._rename_scenario,
                      text_color=SC_TEXT_SOFT, hover_color=SC_HOVER,
                      **_icon).pack(side='left', padx=1)
        ctk.CTkButton(picker, text="🗑", command=self._delete_scenario,
                      text_color=SC_ERR, hover_color=SC_ERR_HOVER,
                      **_icon).pack(side='left', padx=(1, 9))

        # 第二层：校验结果条——跨页签常驻，保存后即给出「哪里有问题」，点开看全文
        self._build_diag_bar()

        # 内容容器
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # 创建各面板
        self.prompt_panel = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self._build_prompt_ui(self.prompt_panel)  # 重写 UI 构建

        self.character_panel = CharacterPage(
            self.content_frame, self._scenario_repo, self)
        # 主题切换由 window_manager 调 evolution_panel.update_theme，保持旧入口可用
        self.evolution_panel = self.character_panel.evolution_panel
        self.chapter_trigger_panel = ChapterTriggerManager(
            self.content_frame, self._scenario_repo, self)
        # 剧情页三标签：章节与触发器 / 章节编排 / 触发器依赖
        self.story_view_switch = CTkSegmentedControl(
            self.content_frame, values=list(STORY_VIEWS),
            command=self._on_story_view_switch,
            font=ui_fonts.ui_font(12), width=340)
        self.graph_panel = ScenarioGraphPanel(
            self.content_frame, scenario_dir=None)
        self._story_view = STORY_VIEW_ROWS
        self.component_panel = ComponentManager(self.content_frame, self._scenario_repo, self)

        # 默认显示通用面板
        self.character_panel.pack_forget()
        self.chapter_trigger_panel.pack_forget()
        self.story_view_switch.pack_forget()
        self.graph_panel.pack_forget()
        self.component_panel.pack_forget()
        self.prompt_panel.pack(fill='both', padx=9, expand=True)

    # ==================== 顶栏校验条 ====================

    def _build_diag_bar(self):
        """校验结果条：错误 / 警告 / 提示计数 + 第一条问题 + 各页签的问题数。

        点条子展开一份完整诊断，点其中一行跳到对应页签并高亮位置；点页签计数
        只切页。安静时（无错误无警告）只留一行浅色状态，不抢视线。
        """
        self.diag_bar = ctk.CTkFrame(self, fg_color=SC_PANEL_BG, corner_radius=0,
                                     border_width=0, height=28)
        self.diag_bar.pack(fill='x', padx=0, pady=(0, 2))
        inner = ctk.CTkFrame(self.diag_bar, fg_color="transparent")
        inner.pack(fill='x', padx=14, pady=3)

        self.diag_pills = {}
        for level, text in (("error", "● 0 错误"), ("warning", "▲ 0 警告")):
            label = ctk.CTkLabel(inner, text=text, font=ui_fonts.ui_font(12, "bold"),
                                 cursor="hand2")
            label.pack(side='left', padx=(0, 8))
            label.bind("<Button-1>", lambda _e: self._toggle_diag_panel())
            self.diag_pills[level] = label

        self.diag_headline = ctk.CTkLabel(
            inner, text="", anchor='w', justify='left',
            font=ui_fonts.ui_font(12), text_color=SC_TEXT_SOFT, cursor="hand2")
        self.diag_headline.pack(side='left', fill='x', expand=True, padx=(2, 8))
        self.diag_headline.bind("<Button-1>", lambda _e: self._toggle_diag_panel())

        self.diag_caret = ctk.CTkLabel(inner, text="▾", font=ui_fonts.ui_font(12),
                                       text_color=SC_TEXT_SOFT, cursor="hand2")
        self.diag_caret.pack(side='right', padx=(8, 0))
        self.diag_caret.bind("<Button-1>", lambda _e: self._toggle_diag_panel())

        # 各页签的问题数（点击只切页，不展开）
        self.tab_chips = {}
        for tab_name in reversed(tab.TABS):
            chip = ctk.CTkLabel(inner, text="", font=ui_fonts.ui_font(11),
                                text_color=SC_TEXT_SOFT, cursor="hand2",
                                fg_color=SC_PANEL_BG, corner_radius=9, padx=6)
            chip.bind("<Button-1>",
                      lambda _e, name=tab_name: self._switch_to_tab(name, expand=False))
            self.tab_chips[tab_name] = chip

        # 抽屉：默认收起，展开时列出全部诊断（每条可点，定位到页签）
        self.diag_panel = ctk.CTkScrollableFrame(self, fg_color=SC_PANEL_BG,
                                                 height=190, corner_radius=0)

    def _toggle_diag_panel(self, open_=None):
        # CTkScrollableFrame 的 pack() 转发给内部 _parent_frame，
        # 而 winfo_manager() 恒返回 'canvas'，据此判展开会永远当成已展开、
        # 每次点击都走收起分支——抽屉因此打不开。改用自己维护的状态。
        visible = self._diag_panel_open
        want = (not visible) if open_ is None else bool(open_)
        if want == visible:
            return
        if want:
            self._fill_diag_panel()
            self.diag_panel.pack(fill='x', padx=0, pady=(0, 4),
                                 before=self.content_frame)
            self.diag_caret.configure(text="▴")
        else:
            self.diag_panel.pack_forget()
            self.diag_caret.configure(text="▾")
        self._diag_panel_open = want

    def _fill_diag_panel(self):
        for child in self.diag_panel.winfo_children():
            child.destroy()
        summary = self._diag_summary
        if summary is None or not summary.total:
            ctk.CTkLabel(self.diag_panel, text="未发现问题。",
                         font=ui_fonts.ui_font(12), text_color=SC_OK).pack(anchor='w')
            return
        for diagnostic, tab_name in zip(summary.diagnostics, summary.tabs):
            color = (SC_ERR if diagnostic.level == "error"
                     else SC_TEXT_SOFT if diagnostic.level == "info" else SC_TEXT)
            row = ctk.CTkFrame(self.diag_panel, fg_color="transparent")
            row.pack(fill='x', pady=1)
            left = ctk.CTkLabel(row, text="", anchor='w', justify='left')
            text = (f"{LEVEL_LABELS.get(diagnostic.level, diagnostic.level)} · "
                    f"{diagnostic.path + '：' if diagnostic.path else ''}"
                    f"{diagnostic.message}")
            left.configure(text=text, font=ui_fonts.ui_font(12), text_color=color,
                           wraplength=620)
            left.pack(side='left', fill='x', expand=True)
            where = ctk.CTkLabel(row, text=f"{tab_name} ▸", font=ui_fonts.ui_font(11),
                                 text_color=SC_LINK, cursor="hand2")
            where.pack(side='right', padx=(8, 0))
            handler = lambda _e, d=diagnostic, t=tab_name: self._jump_to_diagnostic(d, t)
            left.bind("<Button-1>", handler)
            where.bind("<Button-1>", handler)

    def _jump_to_diagnostic(self, diagnostic, tab_name):
        """诊断行 → 切到页签、尽量定位到具体行/节点、收起抽屉。"""
        self._switch_to_tab(tab_name, expand=False)
        self._toggle_diag_panel(False)
        self._locate_path(diagnostic.path)

    def _switch_to_tab(self, tab_name, expand=False):
        self.dungeon_switch_btn.set(tab_name)
        self._on_scenario_tab_switch(tab_name)
        if expand:
            self._toggle_diag_panel(True)

    def _locate_path(self, path):
        """按字段路径把作者带到大致位置；定位不了就只切页（不弹窗、不打断）。"""
        root = diag_root_key(path)
        if root in ("chapters", "triggers"):
            # 剧情页：章节走「章节编排」，触发器走「触发器依赖」，再选中节点
            view = VIEW_CHAPTERS if root == "chapters" else VIEW_TRIGGERS
            self._on_story_view_switch(view, switch_widget=True)
            self.graph_panel.focus_path(path)
        elif root in ("components", "components_params", "text_component"):
            refresh = getattr(self.component_panel, "refresh_list", None)
            if callable(refresh):
                refresh()

    def _validate_config(self, scenario_id, config):
        """校验一份配置，按方案目录解析素材路径；整份编辑器只认这一处口径。"""
        scenario_dir = None
        if scenario_id:
            try:
                scenario_dir = self._scenario_repo.scenario_dir(scenario_id)
            except Exception:      # 目录算不出来不该挡着校验
                scenario_dir = None
        return validate_scenario_config(config, scenario_dir=scenario_dir)

    def _apply_diagnostics(self, diagnostics):
        self._diag_summary = diag_summarize(diagnostics)
        self._render_diag_bar()

    def _render_diag_bar(self):
        summary = self._diag_summary
        if summary is None:
            return
        quiet = summary.quiet
        self.diag_pills["error"].configure(
            text=f"● {summary.errors} 错误",
            text_color=SC_ERR if summary.errors else SC_TEXT_SOFT)
        self.diag_pills["warning"].configure(
            text=f"▲ {summary.warnings} 警告",
            text_color=(SC_TEXT if summary.warnings else SC_TEXT_SOFT))
        if quiet:
            self.diag_headline.configure(
                text=("未发现问题。" if not summary.total
                      else f"{summary.counts.get('info', 0)} 条提示"),
                text_color=SC_OK if not summary.total else SC_TEXT_SOFT)
        else:
            self.diag_headline.configure(text=summary.headline(),
                                         text_color=SC_TEXT_SOFT)
        for tab_name, chip in self.tab_chips.items():
            errors, warnings = summary.tab_counts(tab_name)
            if errors or warnings:
                chip.configure(text=f"{tab_name} {errors + warnings}",
                               text_color=SC_ERR if errors else SC_TEXT,
                               fg_color=SC_PANEL_BG)
                if not chip.winfo_manager():
                    chip.pack(side='right', padx=2)
            elif chip.winfo_manager():
                # 没问题的页签不占位，免得顶栏右侧挂一串空方块
                chip.pack_forget()
        if self._diag_panel_open:
            self._fill_diag_panel()

    def _scenario_display(self, scenario_id):
        """方案 id → 界面显示名（未命名时回落成 id）。"""
        return self._scenario_repo.display_name(scenario_id)

    def _build_combined_items(self):
        """下拉条目：显示名在前（选择回 id），挑战包项挂在末尾。"""
        schemes = self._scenario_repo.list_all()
        items = []
        text_colors = {}
        self._pack_display_map = {}
        self._scenario_display_map = {}
        used = set()
        for scenario_id in schemes:
            display = self._scenario_display(scenario_id)
            if display in used:   # 显示名撞车时补 id，保证每行可区分
                display = f"{display}（{scenario_id}）"
            used.add(display)
            items.append(display)
            self._scenario_display_map[display] = scenario_id
        if self._challenge_mgr and self._challenge_mgr.has_any_valid_key():
            packs = self._challenge_mgr.get_available_packs()
            for pack in packs:
                base = os.path.splitext(pack)[0]
                display = unique_display(
                    f"⚔ {self._challenge_mgr.pack_title(pack) or base}", pack, used)
                items.append(display)
                text_colors[display] = SC_LINK
                self._pack_display_map[display] = pack
        return items, text_colors

    def _rebuild_dropdown(self):
        items, text_colors = self._build_combined_items()
        self.scenario_combo.configure(values=items if items else [])
        if hasattr(self, '_scenario_dropdown') and self._scenario_dropdown:
            self._scenario_dropdown.configure(values=items, text_colors=text_colors)
        else:
            _FG = SC_PANEL_BG
            _BD = SC_BORDER_STRONG
            _HOVER = SC_HOVER
            self._scenario_dropdown = CTkScrollableDropdownFrame(
                attach=self.scenario_combo,
                values=items,
                text_colors=text_colors,
                command=self._on_dropdown_select,
                height=200, button_height=28,
                fg_color=_FG,
                hover_color=SC_CARD_HOVER,
                scrollbar_button_color=_HOVER,
                scrollbar_button_hover_color=_HOVER,
                frame_border_color=_BD,
                text_color=SC_TEXT,
                button_color=_FG,
                frame_border_width=1,
                justify="left"
            )

    def _on_dropdown_select(self, choice):
        if choice in getattr(self, '_pack_display_map', {}):
            pack_name = self._pack_display_map[choice]
            self._on_scenario_challenge_pack_select(pack_name)
        else:
            # 下拉里是显示名，方案切换一律按 id 走
            self._on_scenario_select(
                getattr(self, '_scenario_display_map', {}).get(choice, choice))

    def _on_scenario_challenge_pack_select(self, choice):
        if not choice:
            return
        # 切走前先落盘角色页挂起的防抖保存
        self.character_panel.flush_pending()
        file_path = self._challenge_mgr.resolve_pack_path(choice)
        if file_path is None:
            ui.ctk.dialogs.showerror("错误", f"无法读取挑战包 '{choice}'，未找到对应秘钥")
            return
        result = self._challenge_mgr.try_open_with_keys(file_path)
        if result is None:
            ui.ctk.dialogs.showerror("错误", f"无法读取挑战包 '{choice}'，未找到对应秘钥")
            return
        data, _, _ = result
        if not data:
            return
        scenario_config = scenario_config_of(data)
        scenario_id = scenario_id_of(data)
        if not scenario_config:
            ui.ctk.dialogs.showinfo("提示", "该挑战包中没有副本方案")
            return

        # 下面会覆盖/新建方案并重新加载：切到别的方案前，先把当前方案未保存的
        # 通用设置问一次（目标就是当前方案时，它本来会被包内配置整体替换）
        if scenario_id != self.current_scenario_id:
            self._confirm_unsaved_prompts()
        if self._scenario_repo.exists(scenario_id):
            self._scenario_repo.save_config(scenario_id, scenario_config)
        else:
            self._scenario_repo.create(scenario_id, scenario_config)

        self._refresh_scenario_list()
        self._load_scenario(scenario_id)
        self._notify_validation()
        ui.ctk.dialogs.showinfo(
            "成功", f"已从挑战包加载剧本「{self._scenario_repo.display_name(scenario_id)}」")

    def _on_scenario_tab_switch(self, value):
        tab_name = value.strip()
        # 角色页有防抖保存：换页前先落盘，剧情页的章节多选要用最新人物表
        self.character_panel.flush_pending()
        # 隐藏所有面板
        self.prompt_panel.pack_forget()
        self.character_panel.pack_forget()
        self.chapter_trigger_panel.pack_forget()
        self.story_view_switch.pack_forget()
        self.graph_panel.pack_forget()
        self.component_panel.pack_forget()

        if tab_name == tab.TAB_GENERAL:
            self.prompt_panel.pack(fill='both', padx=9, expand=True)
        elif tab_name == tab.TAB_CHARACTER:
            self.character_panel.refresh_from_config()
            self.character_panel.pack(fill='both', expand=True)
        elif tab_name == tab.TAB_STORY:
            self.story_view_switch.pack(fill='x', padx=9, pady=(0, 6))
            self._show_story_view(self._story_view)
        elif tab_name == tab.TAB_COMPONENT:
            self.component_panel.refresh_list()
            self.component_panel.pack(fill='both', expand=True)

    def _on_story_view_switch(self, value, switch_widget=False):
        self._story_view = value
        if switch_widget and self.story_view_switch is not None:
            self.story_view_switch.set(value)
        self._show_story_view(value)

    def _story_config(self) -> dict:
        """编排图吃的配置：磁盘上的完整配置 + 面板里的实时章节与触发器。

        章节要过一遍 ``normalize_chapters``：方案里存的是精简字段，颜色等缺失项
        靠这一步补默认值，否则泳道强调条取不到章节自定义色。
        """
        config = {}
        if self.current_scenario_id:
            config = self._scenario_repo.load_config(self.current_scenario_id) or {}
        config = copy.deepcopy(config)
        config["chapters"] = normalize_chapters(self.chapters)
        config["triggers"] = self.triggers
        return config

    def _show_story_view(self, view):
        """剧情页只有一块内容区：列表与两张编排图三者互相替代。"""
        if view in (VIEW_CHAPTERS, VIEW_TRIGGERS):
            self.chapter_trigger_panel.pack_forget()
            # 顶栏校验条与编排图吃同一份诊断，避免两处各算一次给出不同结论
            summary = self._diag_summary
            self.graph_panel.set_data(
                self._story_config(),
                diagnostics=summary.diagnostics if summary is not None else None,
                view=view)
            self.graph_panel.pack(fill='both', expand=True)
            return
        self.graph_panel.pack_forget()
        self.chapter_trigger_panel.refresh_list()
        self.chapter_trigger_panel.pack(fill='both', expand=True)

    # ------------------ 新版通用面板 ------------------
    def _build_prompt_ui(self, parent):
        """通用面板：基础设置（通栏）+ 初始提示 / 段落分类提示。"""
        for child in parent.winfo_children():
            child.destroy()

        # 与其他管理页面保持一致的配色
        _CARD_BG = SC_PANEL_BG
        _TITLE = SC_TITLE
        _MUTED = SC_TEXT_SOFT
        _DARK = SC_TEXT
        _F_TITLE = 14
        _F_BIG = 14     # 表单标签与正文输入
        _F_SMALL = 13   # 次要说明

        # ---------- 底部按钮 ----------
        bottom_frame = ctk.CTkFrame(parent, fg_color="transparent")
        bottom_frame.pack(side='bottom', fill='x', pady=(6, 3))
        ctk.CTkButton(bottom_frame, text="保存此页面",
                      fg_color="transparent", border_width=2, corner_radius=10,
                      height=30, text_color=SC_OK,
                      hover_color=SC_OK_HOVER,
                      border_color=SC_OK,
                      font=ui_fonts.ui_font(_F_BIG, "bold"),
                      command=self._save_prompts).pack(fill='x')

        # ---------- 上排通栏 + 下排两栏 ----------
        columns = ctk.CTkFrame(parent, fg_color="transparent")
        columns.pack(fill='both', expand=True, pady=(0, 5))
        columns.grid_columnconfigure(0, weight=1, uniform='col')
        columns.grid_columnconfigure(1, weight=1, uniform='col')
        columns.grid_rowconfigure(0, weight=0)   # 上排按内容高度
        columns.grid_rowconfigure(1, weight=1)   # 下排吃掉剩余高度

        def _card(row, column, padx, columnspan=1):
            card = ctk.CTkFrame(columns, fg_color=_CARD_BG,
                                border_width=0, corner_radius=10)
            card.grid(row=row, column=column, columnspan=columnspan,
                      sticky='nsew', padx=padx,
                      pady=(0, 8) if row == 0 else 0)
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill='both', expand=True, padx=12, pady=10)
            return card, inner

        # ---- 上排：基础设置（耦合等级 / AP 消耗 / 进入准入 / 系统初始提示） ----
        basic_card, left_inner = _card(0, 0, (0, 0), columnspan=2)

        head_row = ctk.CTkFrame(left_inner, fg_color="transparent")
        head_row.pack(fill='x', padx=(0, 20))
        ctk.CTkLabel(head_row, text="耦合等级", font=ui_fonts.ui_font(_F_BIG),
                     text_color=_TITLE).pack(side='left')
        # 选项按钮：复用 widgets.OptionButton（点击弹出档位下拉），档位值用
        # 等级显示名，回调里再映射回等级键
        self.coupling_option = OptionButton(
            head_row, values=[coupling_label(lv) for lv in COUPLING_LEVELS],
            command=self._on_coupling_option,
            width=110, height=26, corner_radius=8, border_width=1,
            font=ui_fonts.ui_font(_F_BIG, "bold"),
            fg_color="transparent", border_color=SC_BORDER_STRONG,
            hover_color=SC_HOVER, text_color=SC_LINK)
        self.coupling_option.set(coupling_label(self.coupling_level))
        self.coupling_option.pack(side='left', padx=8)
        self.entry_cost_var = ctk.StringVar(value="0")
        self.entry_cost_entry = ctk.CTkEntry(head_row, textvariable=self.entry_cost_var,
                                             width=64, font=ui_fonts.ui_font(_F_BIG),
                                             text_color=_DARK, justify='right',
                                             fg_color=SC_PANEL_BG,
                                             border_color=SC_BORDER_STRONG)
        self.entry_cost_entry.pack(side='right')
        ctk.CTkLabel(head_row, text="AP 消耗量", font=ui_fonts.ui_font(_F_BIG),
                     text_color=_TITLE).pack(side='right', padx=(12, 6))

        # 说话人写法：方案级内容契约，二选一且与耦合等级 / 文本组件正交。
        # 值写回方案配置，运行时只读该字段，不由文本组件推导。
        notation_row = ctk.CTkFrame(left_inner, fg_color="transparent")
        notation_row.pack(fill='x', padx=(0, 20), pady=(6, 0))
        ctk.CTkLabel(notation_row, text="说话人写法",
                     font=ui_fonts.ui_font(_F_BIG), text_color=_TITLE).pack(side='left')
        self._notation_label_to_key = {
            label: key for key, label in SPEAKER_NOTATION_LABELS.items()}
        self.speaker_notation_option = OptionButton(
            notation_row,
            values=[SPEAKER_NOTATION_LABELS[k] for k in SPEAKER_NOTATIONS],
            command=self._on_speaker_notation_option,
            width=170, height=26, corner_radius=8, border_width=1,
            font=ui_fonts.ui_font(_F_BIG, "bold"),
            fg_color="transparent", border_color=SC_BORDER_STRONG,
            hover_color=SC_HOVER, text_color=SC_LINK)
        self.speaker_notation_option.set(
            SPEAKER_NOTATION_LABELS[self.speaker_notation])
        self.speaker_notation_option.pack(side='left', padx=8)
        ctk.CTkLabel(notation_row,
                     text="选定后全方案强制、不许混用；与耦合等级、文本组件无关。",
                     font=ui_fonts.ui_font(_F_SMALL), text_color=_MUTED,
                     anchor='w').pack(side='left', padx=(8, 0))

        ctk.CTkLabel(left_inner,
                     text="主角称呼与对话语音已移到「角色」页；进入准入见下。",
                     font=ui_fonts.ui_font(_F_SMALL), text_color=_MUTED,
                     anchor='w').pack(fill='x', pady=(6, 0))

        # 卡片宽度随窗口均分，文本按固定宽度折行即可（CTkLabel 的自然宽度
        # 不受 wraplength 约束，这里只用于排版）
        _TEXT_W = 860

        # ---- 进入准入：入口地址（主世界锚点，距离上限）与身高区间 ----
        admission_card = ctk.CTkFrame(left_inner, fg_color=SC_PANEL_BG,
                                      border_width=1, border_color=SC_BORDER,
                                      corner_radius=8)
        admission_card.pack(fill='x', padx=(0, 20), pady=(4, 0))

        addr_row = ctk.CTkFrame(admission_card, fg_color="transparent")
        addr_row.pack(fill='x', padx=8, pady=(6, 2))
        ctk.CTkLabel(addr_row, text="入口地址", font=ui_fonts.ui_font(_F_SMALL),
                     text_color=_TITLE, width=64, anchor='w').pack(side='left')
        self.entry_address_var = ctk.StringVar()
        self.entry_address_entry = ctk.CTkEntry(
            addr_row, textvariable=self.entry_address_var, height=26,
            font=ui_fonts.ui_font(_F_SMALL), text_color=_DARK,
            placeholder_text="（不限）", state="readonly",
            fg_color=SC_BG, border_color=SC_BORDER_STRONG)
        self.entry_address_entry.pack(side='left', fill='x', expand=True,
                                      padx=(6, 4))
        ctk.CTkButton(addr_row, text="选", width=28, height=26,
                      font=ui_fonts.ui_font(_F_SMALL),
                      fg_color="transparent", border_width=1,
                      border_color=SC_BORDER_STRONG, text_color=SC_LINK,
                      hover_color=SC_HOVER, corner_radius=6,
                      command=self._pick_entry_address).pack(side='left')

        dist_row = ctk.CTkFrame(admission_card, fg_color="transparent")
        dist_row.pack(fill='x', padx=8, pady=2)
        ctk.CTkLabel(dist_row, text="距离上限", font=ui_fonts.ui_font(_F_SMALL),
                     text_color=_TITLE, width=64, anchor='w').pack(side='left')
        self.entry_distance_var = ctk.StringVar()
        ctk.CTkEntry(dist_row, textvariable=self.entry_distance_var, width=64,
                     height=26, font=ui_fonts.ui_font(_F_SMALL),
                     text_color=_DARK, placeholder_text="不限",
                     fg_color=SC_BG, border_color=SC_BORDER_STRONG).pack(
            side='left', padx=(6, 4))
        ctk.CTkLabel(dist_row, text="米（0 = 必须同址）",
                     font=ui_fonts.ui_font(_F_SMALL), text_color=_MUTED).pack(
            side='left')

        height_row = ctk.CTkFrame(admission_card, fg_color="transparent")
        height_row.pack(fill='x', padx=8, pady=(2, 4))
        ctk.CTkLabel(height_row, text="身高区间", font=ui_fonts.ui_font(_F_SMALL),
                     text_color=_TITLE, width=64, anchor='w').pack(side='left')
        self.entry_height_min_var = ctk.StringVar()
        ctk.CTkEntry(height_row, textvariable=self.entry_height_min_var, width=56,
                     height=26, font=ui_fonts.ui_font(_F_SMALL),
                     text_color=_DARK, placeholder_text="不限",
                     fg_color=SC_BG, border_color=SC_BORDER_STRONG).pack(
            side='left', padx=(6, 3))
        ctk.CTkLabel(height_row, text="~", font=ui_fonts.ui_font(_F_SMALL),
                     text_color=_MUTED).pack(side='left')
        self.entry_height_max_var = ctk.StringVar()
        ctk.CTkEntry(height_row, textvariable=self.entry_height_max_var, width=56,
                     height=26, font=ui_fonts.ui_font(_F_SMALL),
                     text_color=_DARK, placeholder_text="不限",
                     fg_color=SC_BG, border_color=SC_BORDER_STRONG).pack(
            side='left', padx=(3, 4))
        ctk.CTkLabel(height_row, text="米", font=ui_fonts.ui_font(_F_SMALL),
                     text_color=_MUTED).pack(side='left')

        coord_row = ctk.CTkFrame(admission_card, fg_color="transparent")
        coord_row.pack(fill='x', padx=8, pady=(2, 6))
        ctk.CTkLabel(coord_row, text="起始坐标", font=ui_fonts.ui_font(_F_SMALL),
                     text_color=_TITLE, width=64, anchor='w').pack(side='left')
        self.initial_intrusion_var = ctk.StringVar()
        ctk.CTkEntry(coord_row, textvariable=self.initial_intrusion_var, width=56,
                     height=26, font=ui_fonts.ui_font(_F_SMALL),
                     text_color=_DARK, placeholder_text="随机",
                     fg_color=SC_BG, border_color=SC_BORDER_STRONG).pack(
            side='left', padx=(6, 3))
        ctk.CTkLabel(coord_row, text="介入 /", font=ui_fonts.ui_font(_F_SMALL),
                     text_color=_MUTED).pack(side='left')
        self.initial_destruction_var = ctk.StringVar()
        ctk.CTkEntry(coord_row, textvariable=self.initial_destruction_var, width=56,
                     height=26, font=ui_fonts.ui_font(_F_SMALL),
                     text_color=_DARK, placeholder_text="随机",
                     fg_color=SC_BG, border_color=SC_BORDER_STRONG).pack(
            side='left', padx=(3, 4))
        ctk.CTkLabel(coord_row, text="破坏（0.5–4.5；留空不继承角色）",
                     font=ui_fonts.ui_font(_F_SMALL), text_color=_MUTED).pack(
            side='left')

        ctk.CTkLabel(left_inner, text="系统初始提示",
                     font=ui_fonts.ui_font(_F_SMALL, "bold"),
                     text_color=_MUTED, anchor='w').pack(fill='x', pady=(10, 0))
        # 标签展示：直接读取 coupling.py 中该等级的 initial_prompt（只读）
        self.coupling_prompt_label = ctk.CTkLabel(
            left_inner, text=coupling_initial_prompt(self.coupling_level),
            width=_TEXT_W, wraplength=_TEXT_W,
            font=ui_fonts.ui_font(_F_SMALL), text_color=_MUTED,
            anchor='w', justify='left')
        self.coupling_prompt_label.pack(fill='x', pady=(4, 0))

        # ---- 左下：初始提示 ----
        prompt_card, prompt_inner = _card(1, 0, (0, 8))
        ctk.CTkLabel(prompt_inner, text="初始提示（角色设定/世界背景）",
                     font=ui_fonts.ui_font(_F_TITLE, "bold"),
                     text_color=_TITLE).pack(anchor='w')
        self.initial_prompt_text = ctk.CTkTextbox(prompt_inner, height=140, wrap='word',
                                                  font=ui_fonts.ui_font(_F_BIG),
                                                  text_color=_DARK,
                                                  fg_color=SC_PANEL_BG,
                                                  border_width=1,
                                                  border_color=SC_BORDER_STRONG)
        self.initial_prompt_text.pack(fill='both', expand=True, pady=(6, 0))

        # ---------- 右下：段落分类提示（横向可滚动卡片） ----------
        sections_card, sections_inner = _card(1, 1, (8, 0))
        title_row = ctk.CTkFrame(sections_inner, fg_color="transparent")
        title_row.pack(fill='x')
        ctk.CTkLabel(title_row, text="段落分类提示（针对不同文本类型）", font=ui_fonts.ui_font(_F_TITLE, "bold"),
                     text_color=_TITLE).pack(side='left')
        ctk.CTkButton(title_row, text="转移设置", width=100,
                      fg_color="transparent", border_width=1, corner_radius=8,
                      text_color=_MUTED,
                      hover_color=SC_HOVER,
                      border_color=SC_BORDER_STRONG,
                      font=ui_fonts.ui_font(_F_BIG),
                      command=lambda: self._edit_transition_matrix(None)).pack(side='right')

        # ---------- 各分类卡片 ----------
        self.section_frames = {}  # key -> CTkTextbox
        self.section_step_vars = {}  # key -> DoubleVar

        section_types = [
            ("background", "背景", "环境与世界状态的描写提示"),
            ("branch", "分支", "其他角色之间的对话或互动"),
            ("dialog", "对话", "与她有关的对话描写提示"),
            ("interaction", "互动", "她与其他人的身体互动"),
            ("action", "行动", "她独自做出的行动描写"),
        ]
        _CARD_WIDTH = 240

        strip = ctk.CTkScrollableFrame(sections_inner, orientation="horizontal",
                                       height=300, corner_radius=0,
                                       fg_color="transparent")
        strip.pack(fill='both', expand=True, pady=(8, 0))

        for key, label, hint in section_types:
            card = ctk.CTkFrame(strip, fg_color="transparent",
                                border_width=1, corner_radius=10,
                                border_color=SC_BORDER_STRONG,
                                width=_CARD_WIDTH)
            card.pack(side='left', fill='y', padx=4, pady=2)
            card.pack_propagate(False)

            # ---- 顶部：分类名 + 步进输入 ----
            head = ctk.CTkFrame(card, fg_color="transparent")
            head.pack(fill='x', padx=10, pady=(10, 0))
            ctk.CTkLabel(head, text=label, font=ui_fonts.ui_font(_F_TITLE, "bold"),
                         text_color=_TITLE).pack(side='left')

            step_box = ctk.CTkFrame(head, fg_color="transparent")
            step_box.pack(side='right')
            ctk.CTkLabel(step_box, text="步进:", font=ui_fonts.ui_font(_F_SMALL),
                         text_color=_MUTED).pack(side='left', padx=(0, 3))
            step_var = ctk.DoubleVar(value=self._default_step_for(key))
            step_entry = ctk.CTkEntry(step_box, textvariable=step_var, width=56,
                                      font=ui_fonts.ui_font(_F_SMALL + 1))
            step_entry.pack(side='left')
            self.section_step_vars[key] = step_var

            ctk.CTkLabel(card, text=hint, font=ui_fonts.ui_font(_F_SMALL),
                         text_color=_MUTED, anchor='w',
                         justify='left').pack(fill='x', padx=10, pady=(1, 0))

            # ---- 提示文本框（撑满卡片剩余高度） ----
            textbox = ctk.CTkTextbox(card, wrap='word',
                                     font=ui_fonts.ui_font(_F_BIG),
                                     text_color=_DARK,
                                     fg_color=SC_PANEL_BG,
                                     border_width=1,
                                     border_color=SC_BORDER_STRONG)
            textbox.pack(fill='both', expand=True, padx=10, pady=(4, 10))
            self.section_frames[key] = textbox

    # ------------------ 转移矩阵编辑对话框 ------------------
    def _edit_transition_matrix(self, section_key):
        """打开转移矩阵编辑窗口（编辑整个矩阵）"""
        dialog = BaseDialog(self)
        dialog.title("编辑转移概率矩阵")
        dialog.geometry("450x350")
        dialog.transient(self)
        # 抓取延到窗口可见之后（X11 要求 viewable，见 BaseDialog._grab_deferred）
        dialog._grab_deferred()

        types = ["background", "branch", "dialog", "interaction", "action"]
        matrix = self.transition_matrix if self.transition_matrix else self._default_transition_matrix()

        # 创建变量网格
        vars_dict = {}
        for src in types:
            vars_dict[src] = {}
            for dst in types:
                val = matrix.get(src, {}).get(dst, 0.0)
                vars_dict[src][dst] = ctk.DoubleVar(value=val)

        # 主框架
        main_frame = ctk.CTkFrame(dialog)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # 列标题
        ctk.CTkLabel(main_frame, text="源\\目标", font=ui_fonts.ui_font(10, "bold")).grid(row=0, column=0, padx=5, pady=5)
        for col, dst in enumerate(types, start=1):
            ctk.CTkLabel(main_frame, text=dst, font=ui_fonts.ui_font(10, "bold")).grid(row=0, column=col, padx=5, pady=5)

        # 行
        for row, src in enumerate(types, start=1):
            ctk.CTkLabel(main_frame, text=src, font=ui_fonts.ui_font(10, "bold")).grid(row=row, column=0, padx=5, pady=5)
            for col, dst in enumerate(types, start=1):
                entry = ctk.CTkEntry(main_frame, textvariable=vars_dict[src][dst], width=60)
                entry.grid(row=row, column=col, padx=2, pady=2)

        # 按钮区域
        btn_frame = ctk.CTkFrame(dialog)
        btn_frame.pack(pady=10)
        ctk.CTkButton(btn_frame, text="保存",
                      command=lambda: self._save_transition_matrix(dialog, vars_dict, types)).pack(side='left', padx=10)
        ctk.CTkButton(btn_frame, text="取消", command=dialog.destroy).pack(side='left', padx=10)
        ctk.CTkButton(btn_frame, text="重置默认", command=lambda: self._reset_transition_matrix(vars_dict, types)).pack(
            side='left', padx=10)

        dialog._center_dialog(self)

    def _save_transition_matrix(self, dialog, vars_dict, types):
        """保存矩阵并自动归一化每行"""
        new_matrix = {}
        for src in types:
            row = {}
            total = 0.0
            for dst in types:
                val = vars_dict[src][dst].get()
                if val < 0:
                    val = 0.0
                row[dst] = val
                total += val
            if total == 0:
                for dst in types:
                    row[dst] = 1.0 / len(types)
            else:
                for dst in types:
                    row[dst] /= total
            new_matrix[src] = row
        self.transition_matrix = new_matrix
        dialog.destroy()

    def _reset_transition_matrix(self, vars_dict, types):
        default = EvolutionRules().transition_matrix  # 使用 EvolutionRules 默认矩阵
        for src in types:
            for dst in types:
                vars_dict[src][dst].set(default.get(src, {}).get(dst, 0.0))

    def _default_transition_matrix(self):
        """返回默认转移矩阵（字符串键）"""
        return copy.deepcopy(EvolutionRules.DEFAULT_TRANSITION_MATRIX)

    def _default_step_for(self, key):
        """返回默认步进值"""
        steps = {
            "background": 0.02,
            "branch": 0.05,
            "dialog": 0.1,
            "interaction": 0.2,
            "action": 0.3
        }
        return steps.get(key, 0.1)

    def _refresh_ui_from_config(self):
        """更新所有UI控件（包括步进值）"""
        self.initial_prompt_text.delete("1.0", "end")
        self.initial_prompt_text.insert("1.0", self.initial_prompt)
        self._refresh_coupling_widgets()
        self._refresh_speaker_notation_widgets()
        self.entry_cost_var.set(str(int(self.entry_action_cost)))
        self.entry_address_var.set(self.entry_address)
        self.entry_distance_var.set(_format_optional_number(
            self.entry_address_max_distance))
        self.entry_height_min_var.set(_format_optional_number(self.entry_height_min))
        self.entry_height_max_var.set(_format_optional_number(self.entry_height_max))
        self.initial_intrusion_var.set(_format_optional_number(self.initial_intrusion))
        self.initial_destruction_var.set(
            _format_optional_number(self.initial_destruction))
        # 主角称呼与对话语音在「角色」页，由它自己回填
        self.character_panel.refresh_from_config()

        for key, box in self.section_frames.items():
            box.delete("1.0", "end")
            box.insert("1.0", self.section_prompts.get(key, ""))

        # 更新步进值
        for key, var in self.section_step_vars.items():
            step = self.section_steps.get(key, self._default_step_for(key))
            var.set(step)

        # 转移矩阵无需显示，但已保存在 self.transition_matrix 中

        self.chapter_trigger_panel.refresh_list()
        self.component_panel.refresh_list()
        self._update_prompt_snapshot()

    def _load_scenario(self, scenario_id):
        config = self._scenario_repo.load_config(scenario_id)
        if config is None:
            # 没有可读配置时不能沿用上一个方案的诊断
            self._apply_diagnostics([])
            return
        self.initial_prompt = config.get("initial_prompt", "")
        self.section_prompts = config.get("section_prompts", {})
        self.coupling_level = normalize_coupling_level(config.get("coupling_level"))
        self.protagonist_title = str(config.get("protagonist_title", "") or "").strip()
        self.protagonist_background = str(
            config.get("protagonist_background", "") or "").strip()
        self.cast = normalize_cast(config.get("cast"))
        self.evolution_attrs = config.get("evolution_attrs", [])
        self.chapters = normalize_chapters(config.get("chapters", []))
        self.triggers = config.get("triggers", [])
        self.entry_action_cost = max(0, int(config.get("entry_action_cost", 0) or 0))
        admission = normalize_admission_fields(config)
        self.entry_address = admission[FIELD_ADDRESS]
        self.entry_address_max_distance = admission[FIELD_MAX_DISTANCE]
        self.entry_height_min = admission[FIELD_HEIGHT_MIN]
        self.entry_height_max = admission[FIELD_HEIGHT_MAX]
        self.initial_intrusion = normalize_initial_coord(
            config.get("initial_intrusion"))
        self.initial_destruction = normalize_initial_coord(
            config.get("initial_destruction"))
        self.text_component = normalize_text_component(config.get("text_component"))
        self.speaker_notation = normalize_speaker_notation(
            config.get("speaker_notation"))
        self.voice = normalize_voice(config.get("voice"))
        self.components = [c for c in config.get("components", [])
                           if c not in ("text", "text_card", "text_nvl")]
        if not isinstance(self.components, list):
            self.components = []
        self.components_params = config.get("components_params", {})
        if not isinstance(self.components_params, dict):
            self.components_params = {}

        # 加载步进值和转移矩阵，缺失则用默认
        self.section_steps = config.get("section_steps", {})
        for key in ["background","branch","dialog","interaction","action"]:
            if key not in self.section_steps:
                self.section_steps[key] = self._default_step_for(key)

        self.transition_matrix = config.get("transition_matrix")
        if not self.transition_matrix:
            self.transition_matrix = self._default_transition_matrix()

        # 先定位副本方案 id 再刷新 UI：刷新过程中各子面板的自动保存/同步
        # 逻辑依赖 current_scenario_id 指向正在加载的配置
        self.current_scenario_id = scenario_id
        self._refresh_ui_from_config()
        self.scenario_combo.set(self._scenario_display(scenario_id))

        # 加载进来的方案也要立刻有诊断：顶栏与剧情页的编排图共用这一份，
        # 不能等作者保存一次才显示（`last_diagnostics` 只记最近一次保存）。
        diag_config = dict(config)
        diag_config["chapters"] = self.chapters
        diag_config["triggers"] = self.triggers
        self._apply_diagnostics(self._validate_config(scenario_id, diag_config))
        # 切方案时若正停在编排图，节点与诊断都得跟着换
        if (self._story_view in (VIEW_CHAPTERS, VIEW_TRIGGERS)
                and self.story_view_switch.winfo_manager()):
            self._show_story_view(self._story_view)

    def _get_prompt_data_from_ui(self) -> dict:
        """从UI控件收集提示词相关数据"""
        try:
            entry_cost = max(0, int(self.entry_cost_var.get()))
        except Exception:
            entry_cost = self.entry_action_cost
        return {
            "initial_prompt": self.initial_prompt_text.get("1.0", "end-1c").strip(),
            "coupling_level": self.coupling_level,
            "speaker_notation": self.speaker_notation,
            "protagonist_title": self.character_panel.protagonist_title(),
            "section_prompts": {key: box.get("1.0", "end-1c").strip()
                                for key, box in self.section_frames.items()},
            "section_steps": {key: var.get() for key, var in self.section_step_vars.items()},
            "transition_matrix": self.transition_matrix,
            "entry_action_cost": entry_cost,
            "entry_address": self.entry_address,
            "entry_address_max_distance_m": self._optional_number(
                self.entry_distance_var, self.entry_address_max_distance),
            "entry_height_min_m": self._optional_number(
                self.entry_height_min_var, self.entry_height_min),
            "entry_height_max_m": self._optional_number(
                self.entry_height_max_var, self.entry_height_max),
            "initial_intrusion": self._coord_number(
                self.initial_intrusion_var, self.initial_intrusion),
            "initial_destruction": self._coord_number(
                self.initial_destruction_var, self.initial_destruction),
            "voice": self.character_panel.collect_voice()
        }

    def _pick_entry_address(self):
        """选择入口地址（主世界锚点；复用地址注册表对话框；消除 = 不做地址准入）。"""
        dialog = AddressTextDialog(
            self, "副本入口地址（主世界）",
            description=("入口是主世界里的一扇门：角色有地址时，进入副本需要与这里选择的"
                         "地址满足距离上限，只能选择已申领的地址（详见 "
                         "docs/designs/address-system/authoring.md）；点「消除」表示不做地址准入。"
                         "它与副本内章节的取景地址无关。"),
            initial=self.entry_address, allow_empty=True)
        if dialog.result is None:
            return
        self.entry_address = dialog.result
        self.entry_address_var.set(self.entry_address)

    def _optional_number(self, var, fallback):
        """准入输入的归一化：空白 = None，非法输入保留上一次的值。"""
        text = var.get().strip()
        if not text:
            return None
        value = coerce_distance(text)
        return fallback if value is None else value

    def _coord_number(self, var, fallback):
        """起始坐标输入：空白 = None（随机），越界夹取，非法保留上一次的值。"""
        text = var.get().strip()
        if not text:
            return None
        value = normalize_initial_coord(text)
        return fallback if value is None else value

    def destroy(self):
        """销毁时收预听（停播、收线程、清临时 WAV）——预听在「角色」页里。"""
        panel = getattr(self, "character_panel", None)
        if panel is not None:
            panel.shutdown_preview()
        super().destroy()

    def _save_prompts(self):
        """仅保存提示词部分，不修改演化量和触发器"""
        if not self.current_scenario_id:
            return
        # 角色页有防抖保存：先落盘，避免这里读到旧的主角背景 / 人物表
        panel = getattr(self, "character_panel", None)
        if panel is not None:
            panel.flush_pending()
        # 加载现有配置
        config = self._scenario_repo.load_config(self.current_scenario_id)
        if config is None:
            config = {}
        # 更新提示词字段
        prompt_data = self._get_prompt_data_from_ui()
        config["initial_prompt"] = prompt_data["initial_prompt"]
        config["coupling_level"] = prompt_data["coupling_level"]
        config["speaker_notation"] = prompt_data["speaker_notation"]
        # 主角称呼与语音在「角色」页，由角色页自己防抖保存；这里一并写回，
        # 保证「保存此页面」之后磁盘上的方案与界面完全一致
        config["protagonist_title"] = prompt_data["protagonist_title"]
        config["voice"] = prompt_data["voice"]
        config["section_prompts"] = prompt_data["section_prompts"]
        config["section_steps"] = prompt_data["section_steps"]
        config["transition_matrix"] = prompt_data["transition_matrix"]
        config["entry_action_cost"] = prompt_data["entry_action_cost"]
        config["entry_address"] = prompt_data["entry_address"]
        config["entry_address_max_distance_m"] = prompt_data[
            "entry_address_max_distance_m"]
        config["entry_height_min_m"] = prompt_data["entry_height_min_m"]
        config["entry_height_max_m"] = prompt_data["entry_height_max_m"]
        config["initial_intrusion"] = prompt_data["initial_intrusion"]
        config["initial_destruction"] = prompt_data["initial_destruction"]
        self.initial_intrusion = prompt_data["initial_intrusion"]
        self.initial_destruction = prompt_data["initial_destruction"]
        self.entry_address_max_distance = prompt_data[
            "entry_address_max_distance_m"]
        self.entry_height_min = prompt_data["entry_height_min_m"]
        self.entry_height_max = prompt_data["entry_height_max_m"]
        # 保留组件选择与参数（组件面板独立保存，这里不覆盖已保存值）
        if "text_component" in config:
            config["text_component"] = self.text_component
        if "components" in config:
            config["components"] = self.components
        if "components_params" in config:
            config["components_params"] = self.components_params
        # 保存（保留 evolution_attrs 和 triggers）
        self._scenario_repo.save_config(self.current_scenario_id, config)
        # 更新快照
        self._update_prompt_snapshot()
        self._notify_validation()
        ui.ctk.dialogs.showinfo("成功", "通用设置已保存")

    def _save_evolution_triggers(self):
        """仅保存演化量、章节与触发器，不修改提示词"""
        if not self.current_scenario_id:
            return
        config = self._scenario_repo.load_config(self.current_scenario_id)
        if config is None:
            config = {}
        config["evolution_attrs"] = self.evolution_attrs
        config["chapters"] = self.chapters
        config["triggers"] = self.triggers
        self._scenario_repo.save_config(self.current_scenario_id, config)
        self._notify_validation()
        # 不更新提示词快照

    def _notify_validation(self) -> None:
        """保存后刷新顶栏校验条；有错误时只提示一次「去哪看」，不再弹窗挡住编辑。"""
        diagnostics = getattr(self._scenario_repo, "last_diagnostics", None) or []
        self._apply_diagnostics(diagnostics)
        if has_errors(diagnostics):
            print("[剧本编辑] 方案校验发现问题：\n"
                  + format_diagnostics(diagnostics, include_info=False))

    def _rename_scenario(self):
        """改名只改显示名，方案目录与 id 不变（已进世界包的清单照旧有效）。"""
        scenario_id = self.current_scenario_id
        if not scenario_id:
            return
        self.character_panel.flush_pending()
        dlg = ResourceNameDialog(
            self, resource_type="scenarios", title="重命名副本方案",
            mode="rename", initial_name=self._scenario_display(scenario_id),
            resource_id=scenario_id)
        if not dlg.result:
            return
        try:
            self._scenario_repo.set_title(scenario_id, dlg.result["title"])
        except Exception as e:
            ui.ctk.dialogs.showerror("错误", f"重命名失败: {e}")
            return
        # 只重刷下拉与当前项文字。改名不动载荷，重读配置会用磁盘内容盖掉
        # 尚未保存的通用设置（提示词、准入等），也会把快照重拍成“已保存”。
        self._refresh_scenario_list()
        self.scenario_combo.set(self._scenario_display(scenario_id))

    def _delete_scenario(self):
        if self.current_scenario_id == DEFAULT_SCENARIO_ID:
            ui.ctk.dialogs.showwarning("警告", "默认副本方案不可删除")
            return
        if not ui.ctk.dialogs.askyesno(
                "确认",
                f"确定删除副本方案「{self._scenario_display(self.current_scenario_id)}」吗？"
                "\n此操作不可恢复！"):
            return
        try:
            self._scenario_repo.delete(self.current_scenario_id)
            self._refresh_scenario_list()
            self._load_scenario(DEFAULT_SCENARIO_ID)
        except Exception as e:
            ui.ctk.dialogs.showerror("错误", str(e))

    def _new_scenario(self):
        """新建副本方案：只问名称，id 自动分配（高级里可手填）。"""
        dlg = ResourceNameDialog(
            self, resource_type="scenarios", title="新建副本方案",
            taken=self._scenario_repo.list_all())
        if not dlg.result:
            return
        new_id = dlg.result["id"]
        if self._scenario_repo.exists(new_id):
            ui.ctk.dialogs.showerror("错误", "副本方案已存在")
            return
        # 新建后立即切到空白方案：当前方案未保存的通用设置先问一次
        self._confirm_unsaved_prompts()
        self.character_panel.flush_pending()
        empty_config = {
            "initial_prompt": "",
            "coupling_level": DEFAULT_COUPLING_LEVEL,
            "speaker_notation": DEFAULT_SPEAKER_NOTATION,
            "protagonist_title": "",
            "protagonist_background": "",
            "cast": [],
            "text_component": DEFAULT_TEXT_COMPONENT,
            "section_prompts": {k: "" for k in ["background","branch","dialog","interaction","action"]},
            "custom_attrs": [],
            "chapters": [],
            "triggers": [],
            "entry_action_cost": 0,
            "entry_address": "",
            "entry_address_max_distance_m": None,
            "entry_height_min_m": None,
            "entry_height_max_m": None,
            "components": ["attr_bar"],
            "components_params": {},
        }
        if self._scenario_repo.create(new_id, empty_config):
            self._scenario_repo.set_title(new_id, dlg.result["title"])
            self._refresh_scenario_list()
            self._load_scenario(new_id)
        else:
            ui.ctk.dialogs.showerror("错误", "创建失败")

    def _update_prompt_snapshot(self):
        """用当前UI内容更新快照（用于对比）"""
        self._saved_prompt_snapshot = self._get_prompt_data_from_ui()

    def _is_prompt_modified(self) -> bool:
        """对比当前UI与快照，判断提示词是否被修改"""
        current = self._get_prompt_data_from_ui()
        return current != self._saved_prompt_snapshot

    def _on_scenario_select(self, choice):
        if self.current_scenario_id == choice:
            return
        # 切走前先落盘角色页挂起的防抖保存（否则最近 700ms 的编辑会丢）
        self.character_panel.flush_pending()
        self._confirm_unsaved_prompts()
        # 加载新副本方案
        self._load_scenario(choice)

    def open_scenario(self, scenario_id):
        """外部入口（资源页深跳）切方案：与下拉选择共用同一套未保存检查。"""
        if scenario_id:
            self._on_scenario_select(scenario_id)

    def _confirm_unsaved_prompts(self):
        """离开当前方案前处理未保存的通用设置：保存或明确放弃，避免静默丢弃。"""
        if not self.current_scenario_id or not self._is_prompt_modified():
            return
        if ui.ctk.dialogs.askyesno("通用设置未保存",
                                   "当前通用设置已修改，是否保存？", parent=self):
            self._save_prompts()

    def _refresh_scenario_list(self):
        dungeon_list = self._scenario_repo.list_all()
        self._rebuild_dropdown()
        if self.current_scenario_id not in dungeon_list:
            self.current_scenario_id = dungeon_list[0] if dungeon_list else None
            self.scenario_combo.set(
                self._scenario_display(self.current_scenario_id)
                if self.current_scenario_id else "")
            if self.current_scenario_id:
                self._load_scenario(self.current_scenario_id)

    def _mark_modified(self):
        # 仅用于标识，暂不需要额外操作，因为保存时重新收集
        pass

    def refresh_list_for_components(self):
        """组件面板保存后同步编辑器的 text_component/components/components_params。"""
        self.text_component = self.component_panel.text_component
        self.components = list(self.component_panel.components)
        self.components_params = dict(self.component_panel.components_params)

    def _on_coupling_option(self, value):
        """OptionButton 回调：把选项控件的档位标签映射回等级并刷新左栏。"""
        self.coupling_level = normalize_coupling_level(value)
        self._refresh_coupling_widgets()

    def _on_speaker_notation_option(self, value):
        """OptionButton 回调：把显示名映射回记法键并同步角色页提示。"""
        self.speaker_notation = self._notation_label_to_key.get(
            value, normalize_speaker_notation(value))
        self.character_panel.on_speaker_notation_changed(self.speaker_notation)

    def _refresh_speaker_notation_widgets(self):
        """把当前记法回显到左栏，并同步角色页的称呼 / 语音提示。"""
        self.speaker_notation_option.set(
            SPEAKER_NOTATION_LABELS[self.speaker_notation])
        self.character_panel.on_speaker_notation_changed(self.speaker_notation)

    def _refresh_coupling_widgets(self):
        """把当前耦合等级回显到左栏（轮换档位、说明、等级初始提示标签）。

        说话人写法与耦合等级正交：角色页的置灰由
        ``_refresh_speaker_notation_widgets`` 单独驱动，这里不再牵动它。
        """
        self.coupling_option.set(coupling_label(self.coupling_level))
        self.coupling_prompt_label.configure(
            text=coupling_initial_prompt(self.coupling_level))


