import customtkinter as ctk

from paths import APP_NAME, APP_VERSION
from ui.ctk.theme import (
    NAV_BG, NAV_HOVER, NAV_TEXT, NAV_TITLE,
    NAV_SELECTED_BG, NAV_SELECTED_TEXT, NAV_WORLD_BG, NAV_WORLD_GREEN,
    NAV_WORLD_HOVER, NAV_WORLD_SELECTED_BG, NAV_WORLD_SELECTED_TEXT, NAV_WORLD_TEXT,
    NAV_WORLD_TITLE,
)
from ui.ctk import fonts as ui_fonts


class NavigationBar(ctk.CTkFrame):
    """左侧导航栏组件

    ``on_switch`` 是页面切换回调（点页面按钮）；``on_switch_ui`` 是**界面模式**
    切换回调（点底部「ME模式」）；``on_open_settings`` 是页脚「设置」的回调
    ——设置是一个对话框，不是页面，所以它不参与 ``set_active`` 的页面高亮，
    也不出现在页面列表里。
    """

    def __init__(self, master, on_switch, on_switch_ui=None,
                 on_open_settings=None, **kwargs):
        super().__init__(master, width=200, height=60, corner_radius=0,
                         fg_color=NAV_BG, **kwargs)
        self.pack_propagate(False)
        self._on_switch = on_switch
        self._on_switch_ui = on_switch_ui
        self._on_open_settings = on_open_settings
        self._buttons = {}
        self._frames = {}
        self._current_page = None
        self._world_active = False

        self._build()

    # 分组 → 页面。顺序即侧栏自上而下的显示顺序；设置单独放页脚。
    _PAGE_GROUPS = (
        ("游玩", (
            ("  🧭  探索模式", "generator"),
            ("  🎯  挑战模式", "challenge"),
            ("  📦  资源中心", "resources"),
        )),
        ("内容", (
            ("  🎭  剧本编辑", "scenario"),
            ("  📍  地标管理", "landmark"),
            ("  📝  描述管理", "quip"),
        )),
    )

    def _make_page_button(self, parent, text, key):
        initial = key == "generator"
        btn = ctk.CTkButton(
            parent, text=text, anchor='w', height=36,
            fg_color=NAV_SELECTED_BG if initial else "transparent",
            text_color=NAV_SELECTED_TEXT if initial else NAV_TEXT,
            hover_color=NAV_HOVER,
            font=ui_fonts.ui_font(14),
            command=lambda k=key: self._on_switch(k))
        self._buttons[key] = btn
        return btn

    def _build(self):
        # 品牌区：应用名 + 版本，取代原来不承载信息的「导航菜单」标题
        self._brand = ctk.CTkFrame(self, fg_color="transparent")
        self._brand.pack(fill='x', padx=14, pady=(14, 10))
        self.app_name_label = ctk.CTkLabel(
            self._brand, text=APP_NAME, font=ui_fonts.ui_font(16, "bold"),
            text_color=NAV_TITLE, anchor='w')
        self.app_name_label.pack(anchor='w')
        self.brand_version_label = ctk.CTkLabel(
            self._brand, text=f"v{APP_VERSION}", font=ui_fonts.ui_font(11),
            text_color=NAV_TEXT, anchor='w')
        self.brand_version_label.pack(anchor='w')

        for caption, pages in self._PAGE_GROUPS:
            cap = ctk.CTkLabel(self, text=caption, font=ui_fonts.ui_font(12, "bold"),
                               text_color=NAV_TITLE, anchor='w')
            cap.pack(fill='x', padx=18, pady=(12, 3))
            for text, key in pages:
                self._make_page_button(self, text, key).pack(fill='x', padx=9, pady=2)

        # ---- 页脚固定区 ----
        # 世界包信息贴最底；其上的「页脚动作」用一个 grid 容器统一管，
        # 从上到下依次是 设置 / 分隔线 / ME模式。程序版本号只在顶部品牌区
        # 出现一次，页脚不再重复。
        foots = ["worldpack_version", "packloaded"]
        for foot in foots:
            frame = ctk.CTkFrame(self, fg_color="transparent")
            frame.pack(side='bottom', fill='x')
            self._frames[foot] = frame

        self._footer_actions = ctk.CTkFrame(self, fg_color="transparent")
        self._footer_actions.pack(side='bottom', fill='x')
        self._footer_actions.grid_columnconfigure(0, weight=1)

        # 「设置」从页面列表移到页脚，与玩法入口分层。它打开的是模态对话框，
        # 不是页面，因此不进 _buttons、不参与 set_active 高亮。
        self.settings_btn = ctk.CTkButton(
            self._footer_actions, text="  ⚙️  设置", anchor='w', height=36,
            fg_color="transparent", text_color=NAV_TEXT, hover_color=NAV_HOVER,
            font=ui_fonts.ui_font(14), command=self._on_settings_clicked)
        self.settings_btn.grid(row=0, column=0, sticky='ew', padx=9, pady=(4, 0))

        # 设置与 ME模式之间的分隔线。沿用探索参数面板的画法：
        # CTkFrame(height=3, corner_radius=0) 配 grid 的 sticky='ew'——
        # 纯 pack 下细 CTkFrame 会被几何管理器压到几乎不可见。
        self._footer_sep = ctk.CTkFrame(
            self._footer_actions, height=3, corner_radius=0, fg_color=NAV_HOVER)
        self._footer_sep.grid(row=1, column=0, sticky='ew', padx=14, pady=(2, 4))

        # 「ME模式」不参与页面高亮：界面模式切换会重建整个窗口，
        # 因此和页面按钮分开，放在页脚动作容器的末行。
        self.ui_switch_btn = ctk.CTkButton(
            self._footer_actions, text="  ⇄  ME模式", anchor='w', height=36,
            fg_color="transparent", text_color=NAV_TEXT, hover_color=NAV_HOVER,
            font=ui_fonts.ui_font(14), command=self._on_ui_switch_clicked)
        self.ui_switch_btn.grid(row=2, column=0, sticky='ew', padx=9, pady=(6, 2))

        # 世界包信息区
        self.worldpack_version_label = ctk.CTkLabel(
            self._frames["worldpack_version"], text="", font=ui_fonts.ui_font(11),
            text_color=NAV_WORLD_GREEN)
        self.worldpack_version_label.pack(side="left", padx=22)

        self.packloaded_label = ctk.CTkLabel(
            self._frames["packloaded"], text="", font=ui_fonts.ui_font(11, "bold"),
            text_color=NAV_WORLD_GREEN)
        self.packloaded_label.pack(side="left", padx=14, pady=2)
        # 悬停展开行为包启用诊断（接管清单 / API 版本 / 异常与警告）
        self._behavior_tip_text = ""
        self._behavior_tip = None
        self.packloaded_label.bind("<Enter>", self._show_behavior_tip)
        self.packloaded_label.bind("<Leave>", self._hide_behavior_tip)

    def _show_behavior_tip(self, event=None):
        """在标签旁弹出诊断全文；无诊断内容时不弹。"""
        if not self._behavior_tip_text or self._behavior_tip is not None:
            return
        tip = ctk.CTkToplevel(self)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        label = ctk.CTkLabel(
            tip, text=self._behavior_tip_text, justify="left",
            font=ui_fonts.ui_font(11), text_color=NAV_TEXT,
            wraplength=420)
        label.pack(padx=10, pady=8)
        lx = self.packloaded_label.winfo_rootx()
        ly = self.packloaded_label.winfo_rooty()
        tip.geometry(f"+{lx + 30}+{ly - 8}")
        self._behavior_tip = tip

    def _hide_behavior_tip(self, event=None):
        if self._behavior_tip is not None:
            self._behavior_tip.destroy()
            self._behavior_tip = None

    def _on_ui_switch_clicked(self):
        """「ME模式」按钮：只负责转发，确认框与拦截都在主窗口管理器里。"""
        if self._on_switch_ui is not None:
            self._on_switch_ui()

    def _on_settings_clicked(self):
        """页脚「设置」：打开设置对话框。"""
        if self._on_open_settings is not None:
            self._on_open_settings()

    def set_active(self, page_key):
        """高亮指定按钮，其余恢复默认"""
        self._current_page = page_key
        self._apply_world_style()

    def set_world_active(self, active, world_name="", world_version="",
                         has_behavior_pack=False, behavior_report=None):
        """世界包加载状态：导航栏整体淡绿色风格 + 底部世界包信息区。

        程序版本号显示在顶部品牌区；加载世界包时底部额外展示世界包版本，
        并在包含行为包时按启用诊断报告提示接管项数或诊断异常。
        """
        self._world_active = bool(active)
        tip_lines = (list(behavior_report.log_lines())
                     if behavior_report is not None else [])
        self._behavior_tip_text = "\n".join(tip_lines)
        self._hide_behavior_tip()
        if active:
            self.worldpack_version_label.configure(
                text=f"世界包版本：v{world_version}" if world_version else "世界包版本：未知")
            if has_behavior_pack:
                if behavior_report is not None and behavior_report.errors:
                    suffix = (f"（⚠ 行为包诊断异常 {len(behavior_report.errors)} 项，"
                              f"行为已更改 {len(behavior_report.overridden)} 项）")
                elif (behavior_report is not None and behavior_report.overridden):
                    suffix = f"（行为已更改 {len(behavior_report.overridden)} 项）"
                else:
                    suffix = "（行为已更改）"
                self.packloaded_label.configure(text=f"🌍 {world_name} {suffix}"
                if world_name else f"🌍 世界包已加载 {suffix}")
            else:
                self.packloaded_label.configure(text=f"🌍 {world_name}" if world_name else "🌍 世界包已加载")
        else:
            self.worldpack_version_label.configure(text="")
            self.packloaded_label.configure(text="")
        self._apply_world_style()

    def _apply_world_style(self):
        """世界包启用时导航栏整体变为淡绿色，标题与按钮同步切换为绿色主题。"""
        if self._world_active:
            self.configure(fg_color=NAV_WORLD_BG)
            title_color = NAV_WORLD_TITLE
            sel_bg, sel_text = NAV_WORLD_SELECTED_BG, NAV_WORLD_SELECTED_TEXT
            bg, text, hover = "transparent", NAV_WORLD_TEXT, NAV_WORLD_HOVER
            footer_color = NAV_WORLD_TEXT
        else:
            self.configure(fg_color=NAV_BG)
            title_color = NAV_TITLE
            sel_bg, sel_text = NAV_SELECTED_BG, NAV_SELECTED_TEXT
            bg, text, hover = "transparent", NAV_TEXT, NAV_HOVER
            footer_color = NAV_TEXT
        self.app_name_label.configure(text_color=title_color)
        self.brand_version_label.configure(text_color=footer_color)
        # 分隔线跟随悬停色，世界包风格下同步变绿，避免旧棕色细线突兀
        self._footer_sep.configure(fg_color=hover)
        # 「ME模式」与「设置」不是页面按钮，不参与高亮，只跟随整体文字/悬停配色
        self.ui_switch_btn.configure(text_color=text, hover_color=hover)
        self.settings_btn.configure(text_color=text, hover_color=hover)
        for key, btn in self._buttons.items():
            if key == self._current_page:
                btn.configure(fg_color=sel_bg, text_color=sel_text, hover_color=hover)
            else:
                btn.configure(fg_color=bg, text_color=text, hover_color=hover)
