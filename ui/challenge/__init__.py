# ui/challenge/__init__.py（原 ui/challenge.py）
import os
import json

import ui.ctk.dialogs
import customtkinter as ctk

from core.ai import resolve_ai_config
from dungeon.terms import scenario_config_of, scenario_id_of
from persistence.resources import registry
from services.challenges import ChallengeService
from core.models import Personality, BodyPreset
from core.address_model import world_of
from ui.ctk.widgets import ClickableCard, CollapsibleBlock, StyleListBox, CTkScrollableDropdownFrame
from ui.ctk.theme import (
    CHAL_PANEL_BG, CHAL_BORDER_STRONG, CHAL_HOVER, CHAL_CARD_HOVER,
    CHAL_TEXT, CHAL_TEXT_SOFT, CHAL_TEXT_MUTED, CHAL_TITLE,
    CHAL_PLACEHOLDER, CHAL_OK, CHAL_OK_HOVER, CHAL_ERR,
    CHAL_ERR_HOVER, CHAL_INTRO_CYAN, CHAL_INTRO_ORANGE,
)
from ui.ctk import fonts as ui_fonts


class ChallengeModePanel(ctk.CTkFrame):
    def __init__(self, parent, gui_ref):
        super().__init__(parent, fg_color="transparent")
        self.gui = gui_ref
        self.challenge_mgr = ChallengeService(
            gui_ref._settings_repo, gui_ref._character_repo,
            gui_ref._landmark_repo, gui_ref._quip_repo, gui_ref._scenario_repo,
            world_state=getattr(gui_ref, "world_state", None)
        )

        self._build_ui()
        self._refresh_packs()

    def _build_ui(self):
        title_bar = ctk.CTkFrame(self, fg_color="transparent")
        title_bar.pack(fill='x', padx=22, pady=(13, 2))

        self.title_label = ctk.CTkLabel(title_bar, text="🎯  挑战模式", font=ui_fonts.ui_font(16, "bold"),
                                        text_color=CHAL_TEXT_SOFT)
        self.title_label.pack(side='left')

        info_bar = ctk.CTkFrame(self, fg_color="transparent")
        info_bar.pack(fill='x', padx=22, pady=(2, 5))
        self.info_label = ctk.CTkLabel(info_bar, text="", font=ui_fonts.ui_font(11),
                                       text_color=CHAL_PLACEHOLDER)
        self.info_label.pack(side='left')

        # 创建挑战包折叠块：标题按钮置于标题栏右侧，内容区展开在信息栏下方
        self.create_block = CollapsibleBlock(self, "创建挑战包", expanded=False,
                                             body_after=info_bar, width=300,
                                             header_parent=title_bar)
        self.create_block.header.pack(side='right', padx=10)

        # ---- 创建挑战包折叠块（嵌入主界面） ----
        form_body = self.create_block.body

        name_head = ctk.CTkFrame(form_body, fg_color="transparent")
        name_head.pack(fill='x', pady=(6, 2), padx=10)
        ctk.CTkLabel(name_head, text="挑战包名称", font=ui_fonts.ui_font(13, "bold"),
                     text_color=CHAL_TITLE).pack(side='left')
        self.pack_id_var = ctk.StringVar(value="")
        self.pack_advanced_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(name_head, text="高级：指定 ID", variable=self.pack_advanced_var,
                        command=self._toggle_pack_id_row, font=ui_fonts.ui_font(11),
                        text_color=CHAL_TEXT_MUTED, fg_color=CHAL_OK,
                        hover_color=CHAL_OK_HOVER, border_color=CHAL_BORDER_STRONG,
                        checkbox_width=16, checkbox_height=16
                        ).pack(side='right')
        self.pack_name_entry = ctk.CTkEntry(form_body, width=300,
                                            placeholder_text="输入挑战包名称（界面显示名，可随时改）",
                                            border_width=1, border_color=CHAL_BORDER_STRONG,
                                            fg_color=CHAL_PANEL_BG)
        self.pack_name_entry.pack(fill='x', pady=(0, 6), padx=10)
        # 高级：手填 id（唯一标识，创建后不进界面）；不勾选时按名称自动派生
        self.pack_id_row = ctk.CTkFrame(form_body, fg_color="transparent")
        ctk.CTkLabel(self.pack_id_row, text="ID", width=40, anchor='w',
                     font=ui_fonts.ui_font(11), text_color=CHAL_TEXT_MUTED).pack(side='left')
        self.pack_id_entry = ctk.CTkEntry(self.pack_id_row, width=240,
                                          placeholder_text="留空则按名称自动分配",
                                          textvariable=self.pack_id_var,
                                          border_width=1, border_color=CHAL_BORDER_STRONG,
                                          fg_color=CHAL_PANEL_BG)
        self.pack_id_entry.pack(side='left', fill='x', expand=True)
        self.pack_name_entry.bind("<KeyRelease>", lambda _e: self._refresh_pack_id_placeholder())

        # ---- 两列布局 ----
        three_col = ctk.CTkFrame(form_body, fg_color="transparent")
        three_col.pack(fill='x', pady=2, padx=10)
        three_col.grid_columnconfigure(0, weight=1)
        three_col.grid_columnconfigure(1, weight=1)

        # 左列：角色 + 剧本（外部入口短标签按术语表用「剧本」）
        left_col = ctk.CTkFrame(three_col, fg_color="transparent")
        left_col.grid(row=0, column=0, sticky='nsew', padx=(0, 10))

        ctk.CTkLabel(left_col, text="选择角色", font=ui_fonts.ui_font(11, "bold"),
                     text_color=CHAL_TEXT_SOFT).pack(anchor='w', pady=(2, 2))
        self.char_combo = ctk.CTkComboBox(left_col, values=[], state="readonly",
                                          border_width=1, border_color=CHAL_BORDER_STRONG,
                                          fg_color=CHAL_PANEL_BG,
                                          button_color=CHAL_HOVER,
                                          button_hover_color=CHAL_TITLE,
                                          dropdown_fg_color=CHAL_PANEL_BG,
                                          dropdown_hover_color=CHAL_HOVER)
        self.char_combo.pack(fill='x', pady=(2, 2))
        self._char_dropdown = CTkScrollableDropdownFrame(
            attach=self.char_combo, values=[], command=self._on_char_change,
            height=160, button_height=28,
            fg_color=CHAL_PANEL_BG,
            hover_color=CHAL_CARD_HOVER,
            frame_border_color=CHAL_BORDER_STRONG,
            text_color=CHAL_TEXT,
            button_color=CHAL_PANEL_BG,
            scrollbar_button_color=CHAL_HOVER,
            scrollbar_button_hover_color=CHAL_HOVER,
            frame_border_width=1, justify="left")
        self.char_info_label = ctk.CTkLabel(left_col, text="", font=ui_fonts.ui_font(10),
                                             text_color=CHAL_PLACEHOLDER)
        self.char_info_label.pack(anchor='w')

        ctk.CTkLabel(left_col, text="剧本", font=ui_fonts.ui_font(11, "bold"),
                     text_color=CHAL_TEXT_SOFT).pack(anchor='w', pady=2)
        self._scenario_map = {}
        self.dungeon_combo = ctk.CTkComboBox(left_col, values=[], state="readonly",
                                             border_width=1, border_color=CHAL_BORDER_STRONG,
                                             fg_color=CHAL_PANEL_BG,
                                             button_color=CHAL_HOVER,
                                             button_hover_color=CHAL_TITLE,
                                             dropdown_fg_color=CHAL_PANEL_BG,
                                             dropdown_hover_color=CHAL_HOVER)
        self.dungeon_combo.pack(fill='x', pady=(2, 6))
        self._dungeon_dropdown = CTkScrollableDropdownFrame(
            attach=self.dungeon_combo, values=[], command=self.dungeon_combo.set,
            height=160, button_height=28,
            fg_color=CHAL_PANEL_BG,
            hover_color=CHAL_CARD_HOVER,
            frame_border_color=CHAL_BORDER_STRONG,
            text_color=CHAL_TEXT,
            button_color=CHAL_PANEL_BG,
            scrollbar_button_color=CHAL_HOVER,
            scrollbar_button_hover_color=CHAL_HOVER,
            frame_border_width=1, justify="left")
        self._sync_scenario_choices()

        # 中列：地标风格组
        center_col = ctk.CTkFrame(three_col, fg_color="transparent")
        center_col.grid(row=0, column=1, sticky='nsew', padx=10)

        self.landmark_selector = StyleListBox(center_col, "地标风格组", height=2,
                                              on_change=self._on_landmark_selection_changed)
        self.landmark_selector.pack(fill='x', pady=2)
        self.landmark_selector.add_button("默认", self.landmark_selector.set_default, padx=0)
        self.landmark_selector.add_button("全选", self.landmark_selector.select_all, padx=10)

        # 简介（可用 / 分隔背景与目标文本，卡片视图中会自动着色）
        ctk.CTkLabel(form_body, text="简介（可用 / 分隔背景与目标文本）", font=ui_fonts.ui_font(11, "bold"),
                     text_color=CHAL_TEXT_SOFT).pack(anchor='w', pady=(6, 2), padx=10)
        self.intro_text = ctk.CTkTextbox(form_body, height=80, wrap='word',
                                         border_width=1, border_color=CHAL_BORDER_STRONG,
                                         fg_color=CHAL_PANEL_BG)
        self.intro_text.pack(fill='x', pady=(0, 6), padx=10)

        # 创建/取消按钮
        btn_frame = ctk.CTkFrame(form_body, fg_color="transparent")
        btn_frame.pack(fill='x', pady=(6, 6))
        ctk.CTkButton(btn_frame, text="创建", command=self._do_create, width=100,
                      fg_color="transparent",
                    text_color=CHAL_OK,
                    hover_color=CHAL_OK_HOVER,
                    border_width=2, border_color=CHAL_OK,
                      corner_radius=10).pack(side='left', padx=10)
        ctk.CTkButton(btn_frame, text="取消", command=self._toggle_create_block, width=100,
                      fg_color="transparent",
                      text_color=CHAL_TEXT_MUTED,
                      hover_color=CHAL_HOVER,
                      border_width=1, border_color=CHAL_BORDER_STRONG,
                      corner_radius=8).pack(side='left')

        # 卡片列表
        self.card_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.card_frame.pack(fill='both', expand=True, padx=22, pady=5)
        self._pack_cards = {}

        # 挑战风格选择：按维度互斥的已选集合
        self._sel_lm = []

        self._init_char_data()
        self._sync_landmark_styles()

    def _init_char_data(self):
        self.char_map = {}
        states_dir = self.gui._character_repo.states_dir
        if not os.path.exists(states_dir):
            return
        chars = []
        for folder in os.listdir(states_dir):
            data_file = os.path.join(states_dir, folder, "info.json")
            if not os.path.isfile(data_file):
                continue
            try:
                with open(data_file, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                cid = d.get('giantess_id', folder)
                name = d.get('name', '')
                nick = d.get('nick', '')
                dis = f"{name} ({nick})" if nick else name
                chars.append(dis)
                self.char_map[dis] = (cid, d)
            except Exception:
                pass
        chars.sort()
        self.char_combo.configure(values=chars)
        if hasattr(self, '_char_dropdown'):
            self._char_dropdown.configure(values=chars)
        if chars:
            self.char_combo.set(chars[0])
            self._on_char_change(chars[0])

        self.char_combo.configure(command=self._on_char_change)

    def _on_char_change(self, choice):
        if choice in getattr(self, 'char_map', {}):
            _, d = self.char_map[choice]
            h = d.get('height', 0)
            p = d.get('personality', {})
            pname = p.get('name', '无') if isinstance(p, dict) else getattr(p, 'name', '无')
            self.char_info_label.configure(text=f"身高: {h:.1f}m | 个性: {pname}")

    def _sync_landmark_styles(self, filter_world=None):
        styles = self.gui._landmark_repo.get_styles()
        display_items = []
        kept = []
        for style in styles:
            reg_world = world_of(self.gui._landmark_repo.load_style_address(style))
            if filter_world and reg_world and reg_world != filter_world:
                continue  # 同一维度自动筛选：隐藏其它维度的地标风格
            landmarks = self.gui._landmark_repo.load(style)
            display = self.gui._landmark_repo.display_name(style)
            display_items.append(f"{display} ({len(landmarks)})")
            kept.append(style)
        selected = [s for s in getattr(self, "_sel_lm", []) if s in kept]
        if not selected and kept:
            default = self.gui._landmark_repo.default_style
            selected = [default] if default in kept else [kept[0]]
        idx = [i for i, s in enumerate(kept) if s in selected]
        self.landmark_selector.sync_items(display_items, idx or None, keys=kept)
        self._sel_lm = self.landmark_selector.get_selected_raw_names() or (selected if kept else [])

    def _lock_world_from_selection(self):
        """当前已选风格共同锁定的维度；未注册返回 None。"""
        for s in getattr(self, "_sel_lm", []):
            w = world_of(self.gui._landmark_repo.load_style_address(s))
            if w:
                return w
        return None

    def _apply_world_lock(self, forced=None):
        """同一维度互斥：地标风格按维度自动筛选，剔除混选。"""
        lock = forced if forced is not None else self._lock_world_from_selection()

        def _filter_for_world(names, repo):
            out = []
            for s in names:
                w = world_of(repo.load_style_address(s))
                if not w or (lock is not None and w == lock):
                    out.append(s)
            return out

        self._sel_lm = _filter_for_world(self._sel_lm, self.gui._landmark_repo)
        self._sync_landmark_styles(lock)
        self._sel_lm = self.landmark_selector.get_selected_raw_names() or self._sel_lm

    def _on_landmark_selection_changed(self):
        prev = list(getattr(self, "_sel_lm", []))
        names = self.landmark_selector.get_selected_raw_names()
        forced = None
        for n in names:
            if n in prev:
                continue
            w = world_of(self.gui._landmark_repo.load_style_address(n))
            if w:
                forced = w
                break
        self._sel_lm = names
        self._apply_world_lock(forced)

    def _update_info_bar(self, count: int):
        self.info_label.configure(text=f"挑战包: {count} 个")

    def set_world_active(self, active: bool):
        """世界包加载状态：挑战模式标题保持不变；加载期间禁用挑战包新建。"""
        self.create_block.collapse()
        self.create_block.header.configure(
            state="disabled" if active else "normal",
            text=("▶ 创建挑战包（世界包加载期间不可用）" if active
                  else "▶ 创建挑战包"))

    def refresh_world_resources(self):
        """世界包状态变化后，刷新地标风格组、剧本下拉框与挑战包列表。"""
        self._sync_landmark_styles()
        self._sync_scenario_choices()
        self._refresh_packs()

    def _refresh_packs(self):
        for w in self.card_frame.winfo_children():
            w.destroy()

        self._pack_cards.clear()
        metas = self.challenge_mgr.get_all_metas()
        self._update_info_bar(len(metas))
        world_active = (getattr(self.gui, "world_state", None) is not None
                        and self.gui.world_state.active)

        if not metas:
            msg = ("本世界包未附带挑战包\n\n自由挑战包会显示在此处" if world_active
                   else "暂无挑战包\n\n点击上方「创建挑战包」折叠块创建新挑战")
            ctk.CTkLabel(self.card_frame, text=msg,
                         font=ui_fonts.ui_font(14),
                         text_color=CHAL_PLACEHOLDER).pack(expand=True, pady=60)
            return

        for meta in metas:
            filename = meta.get("filename", "")
            file_path = meta.get("file_path", "")
            pack_base = meta.get("pack_base", os.path.splitext(filename)[0])
            bundled = meta.get("bundled", False)
            intro = meta.get("intro", "")[:60]
            title = (meta.get("title") or os.path.splitext(filename)[0]
                     or pack_base)
            if not bundled and world_active:
                title = f"{title}  ·  非本世界场景"

            def _colorize_card(tb):
                txt = tb._textbox
                txt.tag_configure("cyan_part", foreground=CHAL_INTRO_CYAN)
                txt.tag_configure("orange_part", foreground=CHAL_INTRO_ORANGE)
                content = txt.get("1.0", "end-1c")
                dbl = "//"
                if dbl in content:
                    dbl_idx = content.index(dbl)
                    txt.tag_add("orange_part", f"1.0 + {dbl_idx + 2}c", "end")
                    if "/" in content and content.index("/") < dbl_idx:
                        s_idx = content.index("/")
                        txt.tag_add("cyan_part", f"1.0 + {s_idx + 1}c", f"1.0 + {dbl_idx}c")
                elif "/" in content:
                    s_idx = content.index("/")
                    txt.tag_add("cyan_part", f"1.0 + {s_idx + 1}c", "end")

            buttons = []
            if not bundled:
                buttons.append({
                    "text": "删除",
                    "command": lambda p=file_path: self._delete_pack(p),
                    "fg_color": "transparent",
                    "text_color": CHAL_ERR,
                    "hover_color": CHAL_ERR_HOVER,
                    "border_width": 1,
                    "border_color": CHAL_ERR,
                    "corner_radius": 8,
                    "width": 50,
                    "pack_kw": {"side": "top", "pady": 2}
                })
            card = ClickableCard(
                self.card_frame,
                title=title,
                title_font=ui_fonts.ui_font(13, "bold"),
                detail=intro + ("..." if intro and len(intro) >= 60 else ""),
                is_detail_textbox=True,
                detail_height=55,
                detail_cb=_colorize_card,
                info_pad=(10, 6),
                on_click=lambda p=pack_base: self._launch_pack(p),
                gold_hover=True,
                cursor="xterm",
                buttons=[{
                    "text": "读取",
                    "command": lambda p=pack_base: None,
                    "fg_color": "transparent",
                    "text_color": CHAL_OK,
                    "hover_color": CHAL_OK_HOVER,
                    "border_width": 1,
                    "border_color": CHAL_OK,
                    "corner_radius": 8,
                    "width": 50,
                    "pack_kw": {"side": "top", "pady": 2}
                }] + buttons
            )
            card.pack(fill='x', padx=5, pady=3)
            self._pack_cards[file_path] = card

    def _on_create_ok(self, key):
        ui.ctk.dialogs.showinfo("成功", f"挑战包已创建\n自动生成秘钥:\n{key}\n\n秘钥已写入环境变量")
        # 表单复位：名称与手填 id 都不该留在下一次新建里
        self.pack_name_entry.delete(0, "end")
        self.pack_id_var.set("")
        self.pack_advanced_var.set(False)
        self.pack_id_row.pack_forget()
        self._refresh_packs()
        if hasattr(self.gui, 'refresh_challenge_pack_dropdowns'):
            self.gui.refresh_challenge_pack_dropdowns()

    def _delete_pack(self, file_path):
        if self.challenge_mgr._is_bundled_path(file_path):
            ui.ctk.dialogs.showwarning("提示", "世界包附带的挑战包不可删除")
            return
        filename = os.path.basename(file_path)
        display = (self.challenge_mgr.pack_title(filename, file_path=file_path)
                   or os.path.splitext(filename)[0])
        if not ui.ctk.dialogs.askyesno("确认", f"确定删除挑战包「{display}」吗？"):
            return
        card = self._pack_cards.pop(file_path, None)
        if card:
            card.destroy()

        def _do_work():
            self.challenge_mgr.delete_pack(file_path)
            self.after(0, lambda: self._on_delete_done())

        self.after(50, _do_work)

    def _on_delete_done(self):
        remaining = self.challenge_mgr.get_all_metas()
        self._update_info_bar(len(remaining))
        if not remaining:
            self._refresh_packs()
        if hasattr(self.gui, 'refresh_challenge_pack_dropdowns'):
            self.gui.refresh_challenge_pack_dropdowns()

    def _sync_scenario_choices(self):
        """剧本下拉：只显示方案名，id 留在映射里（同名时补 id 区分）。"""
        labels, mapping = [], {}
        for scenario_id in self.gui._scenario_repo.list_all():
            display = self.gui._scenario_repo.display_name(scenario_id) or scenario_id
            if display in mapping:
                display = f"{display} ({scenario_id})"
            labels.append(display)
            mapping[display] = scenario_id
        self._scenario_map = mapping
        self.dungeon_combo.configure(values=labels)
        if hasattr(self, "_dungeon_dropdown"):
            self._dungeon_dropdown.configure(values=labels)
        if self.dungeon_combo.get() not in labels:
            self.dungeon_combo.set(labels[0] if labels else "")

    # ---------- 新建：名称进界面，id 默认派生（高级里可手填） ----------
    def _toggle_pack_id_row(self):
        if self.pack_advanced_var.get():
            self.pack_id_row.pack(fill='x', pady=(0, 6), padx=10,
                                 after=self.pack_name_entry)
            self._refresh_pack_id_placeholder()
        else:
            self.pack_id_row.pack_forget()
            self.pack_id_var.set("")

    def _pack_taken_ids(self):
        return [os.path.splitext(name)[0]
                for name in self.challenge_mgr.get_available_packs()]

    def _refresh_pack_id_placeholder(self):
        candidate = registry.suggest_id("challenges", self.pack_name_entry.get(),
                                        self._pack_taken_ids())
        self.pack_id_entry.configure(placeholder_text=f"留空则用 {candidate}")

    def _toggle_create_block(self):
        self.create_block.toggle()
        if self.create_block._expanded:
            self.card_frame.pack_forget()
        else:
            self.card_frame.pack(fill='both', expand=True, padx=22, pady=5)

    def _do_create(self):
        if (getattr(self.gui, "world_state", None) is not None
                and self.gui.world_state.active):
            ui.ctk.dialogs.showwarning("提示", "世界包加载期间不可创建挑战包")
            return
        pack_title = self.pack_name_entry.get().strip()
        if not pack_title:
            ui.ctk.dialogs.showerror("错误", "请输入挑战包名称")
            return
        taken = self._pack_taken_ids()
        manual_id = (self.pack_id_var.get().strip()
                     if self.pack_advanced_var.get() else "")
        if manual_id:
            if not registry.valid_id_of("challenges", manual_id):
                ui.ctk.dialogs.showerror(
                    "错误", f"ID「{manual_id}」不合规：小写字母、数字、下划线、"
                           "点与连字符，且以字母或数字开头")
                return
            if manual_id in taken:
                ui.ctk.dialogs.showerror("错误", f"ID「{manual_id}」已被占用")
                return
            pack_name = manual_id
        else:
            pack_name = registry.suggest_id("challenges", pack_title, taken)

        choice = self.char_combo.get()
        cid = self.char_map.get(choice, ("", {}))[0]
        if not cid:
            ui.ctk.dialogs.showerror("错误", "请选择角色")
            return

        lms = self.landmark_selector.get_selected_raw_names()
        if not lms:
            ui.ctk.dialogs.showerror("错误", "请至少选择一个地标风格组")
            return

        dg = self._scenario_map.get(self.dungeon_combo.get(), "")
        if not dg:
            ui.ctk.dialogs.showerror("错误", "请选择剧本")
            return

        intro = self.intro_text.get("1.0", "end-1c").strip()

        # 先关闭折叠块，界面即时响应
        self._toggle_create_block()

        def _do_work():
            try:
                key = self.challenge_mgr.create_challenge(
                    cid, lms, dg, intro, pack_name, title=pack_title
                )
                self.after(0, lambda k=key: self._on_create_ok(k))
            except Exception as e:
                self.after(0, lambda e=e: ui.ctk.dialogs.showerror("错误", str(e)))

        self.after(50, _do_work)

    def _launch_pack(self, pack_base: str):
        try:
            data = self.challenge_mgr.open_challenge_by_name(pack_base)
        except Exception as e:
            ui.ctk.dialogs.showerror("错误", f"打开挑战包失败: {e}")
            return

        if data is None:
            ui.ctk.dialogs.showerror("错误", "无法读取挑战包内容")
            return

        self._launch_dungeon_from_data(data)

    def _launch_dungeon_from_data(self, data: dict):
        char_data = data.get("character_data", {})
        name = char_data.get("name", "未知")
        nick = char_data.get("nick", "")
        height = char_data.get("height", 1.6)
        original_height = char_data.get("original_height", 1.6)
        intro_hidden = char_data.get("intro_hidden", "")
        intro_visible = char_data.get("intro_visible", "")
        tags = char_data.get("selected_tags", [])
        greed = char_data.get("greed", 0)
        body_parts = char_data.get("body_parts", {})

        personality_dict = char_data.get("personality")
        if not personality_dict:
            ui.ctk.dialogs.showerror("错误", "挑战包中缺少性格数据")
            return
        personality = Personality.from_dict(personality_dict)

        preset = BodyPreset(
            name="标准", leg_ratio=0.5, foot_length_ratio=0.15, arm_span_ratio=0.4,
            index_finger_ratio=0.05, palm_length_ratio=0.1, chest_width_ratio=0.25,
            thigh_diameter_ratio=0.12, forearm_diameter_ratio=0.08,
            knee_height_ratio=0.3, ankle_height_ratio=0.085,
            finger_gap_ratio=0.02, stride_ratio=0.8
        )

        scenario_config = scenario_config_of(data)
        scenario_id = scenario_id_of(data)

        # 挑战模式没有角色地址，进入准入只按身高检查。
        from dungeon.admission import check_entry_requirements
        admission_error = check_entry_requirements(
            scenario_config, position="", height=height)
        if admission_error:
            ui.ctk.dialogs.showerror("无法进入", admission_error)
            return

        gui_settings = self.gui._settings_repo.load()
        ai_config = resolve_ai_config(gui_settings)

        landmark_styles = data.get("landmark_styles", [])

        saved_styles = self.gui.context.selected_styles.copy()

        self.gui.context.selected_styles = landmark_styles
        self.gui.context.reload_merged_data()
        self.gui.selected_styles = self.gui.context.selected_styles

        # L4：run() 返回结果对象（挑战模式无入口阶段，暂无需要处理的分支）。
        # 会话在独立子进程里跑（DPG/GLFW 独占子进程），参数与窗口构造一致。
        from ui.hosting.dungeon_spawner import launch_dungeon_subprocess

        launch_dungeon_subprocess(
            host_window=self.gui.root, app=self.gui,
            dialogs=ui.ctk.dialogs,
            name=name, nick=nick,
            personality=personality, preset=preset,
            original_height=original_height, intro_hidden=intro_hidden,
            intro_visible=intro_visible, tags=tags, uploaded_image=None,
            scenario_config=scenario_config,
            merged_landmarks=self.gui.context.landmarks_for_dungeon(),
            selected_styles=landmark_styles, height=height,
            ai_config=ai_config,
            greed=greed, is_replay=False, replay_data=None,
            scenario_id=scenario_id, body_parts=body_parts,
            character=None, settings=gui_settings, mode="challenge",
        )

        self.gui.context.selected_styles = saved_styles
        self.gui.context.reload_merged_data()
        self.gui.selected_styles = self.gui.context.selected_styles
