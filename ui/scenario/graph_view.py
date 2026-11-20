"""编排视图：章节与触发器之间的四类关系，一处看清，并与字段路径联动定位。

嵌在「剧情」页里（上方分段切换「章节与触发器 / 章节编排 / 触发器依赖」），不再是
独立对话框；校验结论与定位入口由编辑器顶栏的校验条承担（``ui/scenario/diagnostics.py``），
本模块只负责把路径带到图上的节点（``ScenarioGraphPanel.focus_path``）。

它替换掉早期的依赖图对话框（``dependency_dlg.py``，用 networkx 建图 + graphviz 出
PNG），差别在三处：

1. **画的东西多**：早期只画 ``precondition_names`` 一条边，章节只当节点里的一行小字。
   现在四类关系都在图里——前置条件、章节跳转（``goto``）、超限跳转
   （``overflow_target``）、条件引用（条件键 ``选择:X``）——章节另有**归属**关系，
   以泳道形式表达（触发器按依赖分层排在自己章节那一条泳道里）。模型见
   ``dungeon/scenario_graph.py``。但「触发器依赖」视图里，章节跳转与超限跳转
   **都不画跨泳道箭头**（会把视线拽出泳道），只在节点右上角画一个 ↗ 跳出角标
   （触发器 = goto 蓝实线，章节抬头 = 超限橙虚线）；跨章节箭头只留给「前置条件
   引用了另一章的触发器」这种触发器→触发器依赖。
2. **是校验器的一部分**：图上的结构问题由 ``dungeon/graph_lint.py`` 产出，与字段级
   规则共用同一套 ``Diagnostic``，保存方案和启动副本前**都会**跑。这些诊断与字段级
   诊断一起收进编辑器顶栏的校验条，点一条就切回这里并定位到对应节点。
3. **把校验器不报的「可能竞争」摆出来**：``ACTION_POSITIONS`` 同位置至多生效一个，
   条件非空时「谁挡住谁」需要求解器才判得准，因此不进校验器（见
   ``docs/Dungeon/scenario_graph.md`` §3.2）。这里按位分组呈现——点一个触发器就能
   看到同位置、同作用域的邻居，无争议的那几条还会写明「永远轮不到」。
4. **不依赖外部重器**：自绘 ``tkinter.Canvas``（分层布局自己算），不再需要
   ``networkx`` / ``graphviz``，也不需要系统装 ``dot``。

只读：不改配置、不写盘。双击节点不会打开编辑框——那属于"编辑"而不是"看"，
回归面完全不同，要做得另开一次改动。
"""

import re
import tkinter as tk
from dataclasses import dataclass

import customtkinter as ctk

from dungeon.actions import action_label
from dungeon.audio.chapters import normalize_chapters, shade_for_mode
from dungeon.graph_lint import lint_graph
from dungeon.scenario_graph import (
    DRAWABLE_EDGE_KINDS, EDGE_CHOICE, EDGE_ENTRY, EDGE_GOTO, EDGE_LABELS,
    EDGE_OVERFLOW, EDGE_PRECOND, FLAG_DANGLING, FLAG_ENDING, FLAG_FIXED, FLAG_MISSING,
    FLAG_START, NODE_CHAPTER, NODE_ROOT, NODE_TRIGGER, ROOT_ID, build_graph,
)
from dungeon.validate import (
    LEGACY_ACTIONS, LEVEL_LABELS, format_diagnostics, validate_scenario_config,
)
from ui.ctk import fonts as ui_fonts
from ui.ctk.dialogs import BaseDialog, showerror
from ui.ctk.theme import (
    ACTION_FILL_BACKGROUND, ACTION_FILL_EFFECT, ACTION_FILL_ENDING, ACTION_FILL_FX,
    ACTION_FILL_GOTO, ACTION_FILL_INSERT, ACTION_FILL_NONE, ACTION_FILL_OPTION,
    ACTION_FILL_SENSITIVITY,
    DEPENDENCY_ERR, DEPENDENCY_TEXT,
    DLG_TEXT, DLG_TEXT_SOFT,
    GRAPH_CANVAS_BG, GRAPH_CANVAS_TEXT, GRAPH_CANVAS_TEXT_SOFT,
    GRAPH_EDGE_CHOICE, GRAPH_EDGE_ENTRY, GRAPH_EDGE_GOTO,
    GRAPH_EDGE_HIGHLIGHT, GRAPH_EDGE_OVERFLOW, GRAPH_EDGE_PRECOND, GRAPH_LANE_BG,
    GRAPH_LANE_BORDER, GRAPH_NODE_ERR_BORDER, GRAPH_NODE_HEAD_FILL,
    GRAPH_NODE_MUTED_FILL, GRAPH_NODE_OUTLINE,
    SC_BORDER, SC_HOVER, SC_TEXT, SC_TEXT_SOFT,
)

#: 动作类型 → 节点填充色。``mini_game`` 与 ``option`` 同处「模态」位（运行时同轮
#: 至多生效一个），因此共用一色；旧版动作沿用旧的映射，方便一眼认出来。
_ACTION_FILL = {
    "insert": ACTION_FILL_INSERT,
    "option": ACTION_FILL_OPTION,
    "mini_game": ACTION_FILL_OPTION,
    "effect": ACTION_FILL_EFFECT,
    "fx": ACTION_FILL_FX,
    "goto": ACTION_FILL_GOTO,
    "none": ACTION_FILL_NONE,
    "ending": ACTION_FILL_ENDING,
    "background": ACTION_FILL_BACKGROUND,
    "sensitivity": ACTION_FILL_SENSITIVITY,
    "sensitive": ACTION_FILL_SENSITIVITY,
}

_EDGE_COLOR = {
    EDGE_ENTRY: GRAPH_EDGE_ENTRY,
    EDGE_PRECOND: GRAPH_EDGE_PRECOND,
    EDGE_GOTO: GRAPH_EDGE_GOTO,
    EDGE_OVERFLOW: GRAPH_EDGE_OVERFLOW,
    EDGE_CHOICE: GRAPH_EDGE_CHOICE,
}

#: 可开关的边。``entry`` 不是"关系"而是起点标记，恒画，不进开关。
_TOGGLE_EDGE_KINDS = (EDGE_PRECOND, EDGE_GOTO, EDGE_OVERFLOW, EDGE_CHOICE)

#: 剧情页上的两张编排图；面板本身不再带视图切换，由剧情页顶部的分段控件驱动。
VIEW_CHAPTERS = "章节编排"
VIEW_TRIGGERS = "触发器依赖"

# 画布尺寸常量（世界坐标，缩放只在绘制时施加）
BOX_H = 40
HEAD_W = 200
CHIP_W = 176
LANE_COL_GAP = 30    # 泳道内相邻依赖层（列）的横向间距；要留得下扇出连线的竖直段
LANE_ROW_GAP = 16    # 泳道内同层相邻节点（行）的纵向间距
LANE_PAD = 12
LANE_GAP = 16
ORIGIN = 36
SIDE_W = 176         # 左侧「图层 / 过滤」栏宽度（网格定宽，不参与挤压）
FLOW_GAP_Y = 22
FLOW_COL_GAP = 64
_SCALE_MIN = 0.45
_SCALE_MAX = 2.6

_PATH_INDEX = re.compile(r"(triggers|chapters)\[(\d+)\]")

_KIND_LABELS = {NODE_ROOT: "起点", NODE_CHAPTER: "章节", NODE_TRIGGER: "触发器"}


def _legend_text():
    """连线 / 节点图例文案：面板帮助对话框与离线导出报告共用同一份。"""
    return ("绿=进入　灰=前置条件　蓝=章节跳转（触发器依赖视图上以节点右上角"
            "实线 ↗ 角标表示）　橙=超限跳转（同一视图上以章节抬头右上角虚线 ↗ "
            "角标表示，跳转目标都看详情面板）　紫点线=条件引用；"
            "节点按动作类型着色，红框=有问题或指向不存在的章节。"
            "拖拽平移 · 滚轮缩放 · 点节点高亮入出边并列出同位置竞争。")


def _mode() -> str:
    return ctk.get_appearance_mode()


def _pick(token):
    """配色 token 可能是 ``[light, dark]`` 成对值，也可能本来就是单色字符串。"""
    if isinstance(token, (list, tuple)):
        return token[1] if _mode() == "Dark" else token[0]
    return token


def node_title(node) -> str:
    if node.kind == NODE_CHAPTER:
        mark = "★ " if node.has(FLAG_START) else ("✦ " if node.has(FLAG_ENDING) else "")
        return mark + node.name
    return node.name


def node_caption(node) -> str:
    """节点第二行的说明。"""
    if node.kind == NODE_CHAPTER:
        if node.has(FLAG_MISSING):
            return "章节不存在"
        marks = []
        if node.has(FLAG_START):
            marks.append("起始")
        if node.has(FLAG_ENDING):
            marks.append("结束")
        if node.has(FLAG_FIXED):
            marks.append("固定文本")
        return "·".join(marks) or "章节"
    if node.kind == NODE_ROOT:
        return "任意章节 / 无章节"
    label = action_label(node.action_type)
    if node.action_type in LEGACY_ACTIONS:
        label += "（旧版·已失效）"
    if node.has(FLAG_DANGLING):
        label += " · 目标章节不存在"
    return label


@dataclass
class Box:
    """画布上的一个节点矩形（世界坐标；缩放只在绘制时施加）。"""

    node_id: str
    x: float
    y: float
    w: float
    h: float

    @property
    def x1(self):
        return self.x + self.w

    @property
    def y1(self):
        return self.y + self.h

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2


@dataclass
class Band:
    """节点背后的一条带：泳道（触发器依赖视图）或分层列（章节编排视图）。"""

    x: float
    y: float
    w: float
    h: float
    label: str = ""
    accent: str = ""


class GraphCanvas(ctk.CTkFrame):
    """自绘分层画布：泳道式（触发器依赖）与分层式（章节编排）共用一套渲染。

    交互：拖拽平移、滚轮缩放、点节点高亮它的入边与出边。
    """

    def __init__(self, parent, dialog):
        super().__init__(parent, fg_color="transparent")
        self.dialog = dialog
        self.scale = 1.0
        self._boxes = {}
        self._rects = {}
        self._default_outlines = {}
        self._edge_items = []
        self._jump_items = []      # 跳出角标（node_id → canvas 元素）
        self._jump_marks = ()      # 需要画跳出角标的触发器 node_id
        self._selected = None
        self._pressed_on_node = False

        self.canvas = tk.Canvas(self, bg=_pick(GRAPH_CANVAS_BG), highlightthickness=0)
        self.vbar = ctk.CTkScrollbar(self, orientation="vertical",
                                     command=self.canvas.yview)
        self.hbar = ctk.CTkScrollbar(self, orientation="horizontal",
                                     command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vbar.set, xscrollcommand=self.hbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda _e: self._zoom(1.1))
        self.canvas.bind("<Button-5>", lambda _e: self._zoom(1 / 1.1))

    @property
    def graph(self):
        """始终读面板当前的模型：``set_data`` 换方案时会替换整张图。"""
        return self.dialog.graph

    # ---------- 绘制 ----------

    def redraw(self):
        self.canvas.configure(bg=_pick(GRAPH_CANVAS_BG))
        self.canvas.delete("all")
        self._rects = {}
        self._default_outlines = {}
        self._edge_items = []
        self._jump_items = []
        self._jump_marks = ()
        self._boxes, bands, edges = self._layout()

        for band in bands:
            self._rect(band.x, band.y, band.w, band.h, fill=_pick(GRAPH_LANE_BG),
                       outline=_pick(GRAPH_LANE_BORDER))
            if band.accent:
                self._rect(band.x, band.y, 4, band.h, fill=band.accent, outline="")
            if band.label:
                self.canvas.create_text(self._sx(band.x + band.w / 2),
                                        self._sy(band.y - 12), text=band.label,
                                        fill=_pick(GRAPH_CANVAS_TEXT_SOFT),
                                        font=self._font(10))

        for edge in edges:
            self._draw_edge(edge)
        for node_id, box in self._boxes.items():
            self._draw_node(self.graph.node(node_id), box)
        for node_id, kind in self._jump_marks:
            self._draw_jump_mark(node_id, kind)

        self.canvas.configure(scrollregion=self.canvas.bbox("all") or (0, 0, 10, 10))
        self._apply_selection()

    def _sx(self, value):
        return value * self.scale

    def _sy(self, value):
        return value * self.scale

    def _font(self, size):
        return ui_fonts.ui_font(max(8, round(size * self.scale)))

    def _rect(self, x, y, w, h, fill, outline, tags=(), width=1):
        return self.canvas.create_rectangle(self._sx(x), self._sy(y), self._sx(x + w),
                                            self._sy(y + h), fill=fill, outline=outline,
                                            width=width, tags=tags)

    def _layout(self):
        visible = self.dialog.visible_nodes()
        kinds = set(self.dialog.enabled_edge_kinds())
        if self.dialog.view == VIEW_CHAPTERS:
            self._jump_marks = ()
            return self._flow_layout(visible, kinds)
        return self._lane_layout(visible, kinds)

    def _lane_layout(self, visible, kinds):
        """触发器依赖视图：一条泳道一个章节，泳道内按依赖分层。

        列 = 依赖深度（章节抬头在第 0 列；泳道内没有前置 / 条件引用来源的触发器在
        第 1 列，其下游依次向后），行 = 同列内逐个排开。这样「一个枢纽触发器被多条
        触发器引用」时，那些下游各占一行、缩进在枢纽右侧，前置 / 条件引用连线向右
        扇出；否则它们会横挤在同一行，连线也叠成一条横线，看起来像链式依赖。
        """
        boxes = {}
        bands = []
        y = ORIGIN
        for _label, ids in self.graph.lanes:
            shown = [node_id for node_id in ids if node_id in visible]
            if not shown:
                continue
            cells, column_x, band_w, band_h = self._lane_grid(ids, shown)
            for node_id, (column, row) in cells.items():
                width = HEAD_W if node_id == ids[0] else CHIP_W
                boxes[node_id] = Box(
                    node_id, column_x[column],
                    y + LANE_PAD + row * (BOX_H + LANE_ROW_GAP), width, BOX_H)
            head = self.graph.node(ids[0])
            bands.append(Band(ORIGIN, y, band_w, band_h,
                              accent=self.dialog.accent_for(head)))
            y += band_h + LANE_GAP
        # 章节跳转 + 超限跳转在泳道视图里都不画跨泳道箭头（会把视线拽出泳道），
        # 改为只在节点右上角画一个跳出角标（见 _draw_jump_mark）：触发器是
        # goto（蓝色实线），章节抬头是 overflow（橙色虚线）。两个图层开关各自
        # 控制自己那类角标的显隐。
        marks = []
        if EDGE_GOTO in kinds:
            marks += [(edge.src, EDGE_GOTO) for edge in self.graph.edges
                      if edge.kind == EDGE_GOTO and edge.src in boxes]
        if EDGE_OVERFLOW in kinds:
            marks += [(edge.src, EDGE_OVERFLOW) for edge in self.graph.edges
                      if edge.kind == EDGE_OVERFLOW and edge.src in boxes]
        self._jump_marks = tuple(marks)
        edges = [edge for edge in self.graph.edges
                 if edge.kind in kinds
                 and edge.kind not in (EDGE_GOTO, EDGE_OVERFLOW)
                 and edge.src in boxes and edge.dst in boxes]
        return boxes, bands, edges

    def _lane_grid(self, ids, shown):
        """泳道内网格：``{节点: (列, 行)}`` + 各列 x + 泳道尺寸。

        列按依赖深度算（只看泳道内的前置 / 条件引用；跨泳道的来源不算，那条边照旧
        跨泳道画）。同列内每个节点各占一行：从一个来源扇出的下游依次排开，行号从
        来源所在行起步，于是「谁依赖谁」一眼可读。互为前置、定不了序的环（没有种子
        成员的死锁分量）统一落在第 1 列，连线走同列绕行。
        """
        head = ids[0] if ids[0] in shown else None
        triggers = [node_id for node_id in ids[1:] if node_id in shown]
        members = set(triggers)
        if head is not None:
            members.add(head)
        sources = {}
        for node_id in triggers:
            sources[node_id] = [edge.src for edge in self.graph.in_edges(node_id)
                                if edge.kind in (EDGE_PRECOND, EDGE_CHOICE)
                                and edge.src in members and edge.src != node_id]

        depth = {head: 0} if head is not None else {}
        cap = len(triggers) + 1
        changed = True
        while changed:      # 迭代到不动点；有环时深度单调递增、顶到 cap 即止
            changed = False
            for node_id in triggers:
                if not sources[node_id]:
                    level = 1
                else:
                    levels = [depth.get(src) for src in sources[node_id]]
                    if any(value is None for value in levels):
                        continue
                    level = min(cap, 1 + max(levels))
                if depth.get(node_id) != level:
                    depth[node_id] = level
                    changed = True
        for node_id in triggers:
            depth.setdefault(node_id, 1)

        cells = {}
        if head is not None:
            cells[head] = (0, 0)
        taken = {}
        for node_id in sorted(triggers, key=lambda node_id: depth[node_id]):
            column = depth[node_id]
            source_rows = [cells[src][1] for src in sources[node_id] if src in cells]
            row = max(source_rows) if source_rows else 0
            used = taken.setdefault(column, set())
            while row in used:
                row += 1
            used.add(row)
            cells[node_id] = (column, row)

        columns = sorted({column for column, _row in cells.values()})
        column_x = {}
        x = ORIGIN + LANE_PAD
        for column in columns:
            column_x[column] = x
            width = HEAD_W if column == 0 and head is not None else CHIP_W
            x += width + LANE_COL_GAP
        band_w = x - LANE_COL_GAP + LANE_PAD - ORIGIN
        rows = max((row for _column, row in cells.values()), default=0)
        band_h = (rows + 1) * BOX_H + rows * LANE_ROW_GAP + 2 * LANE_PAD
        return cells, column_x, band_w, band_h

    def _flow_layout(self, visible, kinds):
        edges = [edge for edge in self.graph.chapter_view_edges()
                 if edge.kind in kinds and edge.src in visible and edge.dst in visible]
        depth = {ROOT_ID: 0} if ROOT_ID in visible else {}
        queue = list(depth)
        while queue:
            current = queue.pop(0)
            for edge in edges:
                if edge.src != current or edge.dst in depth:
                    continue
                depth[edge.dst] = depth[current] + 1
                queue.append(edge.dst)

        leftovers = [node_id for node_id in visible if node_id not in depth]
        columns = {}
        for node_id, level in depth.items():
            columns.setdefault(level, []).append(node_id)
        unreachable_level = None
        if leftovers:
            unreachable_level = max(columns, default=-1) + 1
            columns[unreachable_level] = leftovers

        boxes = {}
        bands = []
        for level in sorted(columns):
            members = [nid for nid in columns[level] if nid in self.graph.nodes]
            if not members:
                continue
            x = ORIGIN + level * (HEAD_W + FLOW_COL_GAP)
            y = ORIGIN + 26
            for node_id in members:
                boxes[node_id] = Box(node_id, x, y, HEAD_W, BOX_H)
                y += BOX_H + FLOW_GAP_Y
            bottom = y - FLOW_GAP_Y
            if level == unreachable_level:
                # 走不到的章节只算提示（创作期短接常见），用警示橙而非错误红
                label, accent = "不可达（从起始章节走不到）", _pick(GRAPH_EDGE_OVERFLOW)
            elif level == 0:
                label, accent = "起点", _pick(GRAPH_EDGE_ENTRY)
            else:
                label, accent = f"第 {level} 跳", ""
            bands.append(Band(x - 12, ORIGIN, HEAD_W + 24, bottom - ORIGIN + 12,
                              label=label, accent=accent))
        return boxes, bands, edges

    def _draw_node(self, node, box):
        if node.kind == NODE_ROOT:
            fill = _pick(GRAPH_NODE_MUTED_FILL)
            outline = _pick(GRAPH_NODE_OUTLINE)
        elif node.kind == NODE_CHAPTER:
            fill = _pick(GRAPH_NODE_MUTED_FILL if node.has(FLAG_MISSING)
                         else GRAPH_NODE_HEAD_FILL)
            outline = self._default_outline(node)
        else:
            fill = _pick(_ACTION_FILL.get(node.action_type, ACTION_FILL_NONE))
            outline = _pick(GRAPH_NODE_OUTLINE)

        rect = self._rect(box.x, box.y, box.w, box.h, fill=fill, outline=outline,
                          tags=(node.id, "node"))
        self._rects[node.id] = rect
        self._default_outlines[node.id] = outline
        self.canvas.create_text(self._sx(box.cx), self._sy(box.cy - 8),
                                text=node_title(node), fill=_pick(GRAPH_CANVAS_TEXT),
                                font=self._font(11), tags=(node.id, "node"))
        caption = node_caption(node)
        if caption:
            self.canvas.create_text(self._sx(box.cx), self._sy(box.cy + 9), text=caption,
                                    fill=_pick(GRAPH_CANVAS_TEXT_SOFT),
                                    font=self._font(9), tags=(node.id, "node"))

    def _default_outline(self, node):
        if node.kind == NODE_CHAPTER:
            if node.has(FLAG_MISSING):
                return _pick(GRAPH_NODE_ERR_BORDER)
            return self.dialog.accent_for(node) or _pick(GRAPH_NODE_OUTLINE)
        return _pick(GRAPH_NODE_OUTLINE)

    def _draw_edge(self, edge):
        source = self._boxes.get(edge.src)
        target = self._boxes.get(edge.dst)
        if source is None or target is None:
            return
        points, direction = self._route(source, target, loop=edge.src == edge.dst)
        color = _pick(_EDGE_COLOR.get(edge.kind, GRAPH_NODE_OUTLINE))
        dashed = edge.kind in (EDGE_CHOICE, EDGE_OVERFLOW)
        flat = []
        for point in points:
            flat.extend((self._sx(point[0]), self._sy(point[1])))
        options = {"fill": color, "width": 1.5}
        if dashed:
            options["dash"] = (4, 3)
        line = self.canvas.create_line(*flat, **options)
        head = self.canvas.create_polygon(self._arrow_points(points[-1], direction),
                                         fill=color, outline="")
        self._edge_items.append((edge, [line, head]))

    def _route(self, source, target, loop=False):
        """正交路由：自环绕头顶；目标在右→横穿；目标在左→从下方绕；同列→右侧绕行。"""
        if loop:
            top = source.y - 16
            return ([(source.cx, source.y), (source.cx, top),
                     (source.x1 + 6, top), (source.x1 + 6, source.y)], (0, 1))
        if target.x > source.x1 + 6:
            middle = (source.x1 + target.x) / 2
            return ([(source.x1, source.cy), (middle, source.cy),
                     (middle, target.cy), (target.x, target.cy)], (1, 0))
        if target.x1 < source.x - 6:
            bottom = max(source.y1, target.y1) + 20
            return ([(source.cx, source.y1), (source.cx, bottom),
                     (target.cx, bottom), (target.cx, target.y1)], (0, -1))
        right = max(source.x1, target.x1) + 28
        return ([(source.x1, source.cy), (right, source.cy),
                 (right, target.cy), (target.x1, target.cy)], (-1, 0))

    def _arrow_points(self, point, direction):
        size = 7 * self.scale
        px, py = -direction[1], direction[0]
        x, y = self._sx(point[0]), self._sy(point[1])
        return (x, y,
                x - direction[0] * size + px * size * 0.45,
                y - direction[1] * size + py * size * 0.45,
                x - direction[0] * size - px * size * 0.45,
                y - direction[1] * size - py * size * 0.45)

    def _draw_jump_mark(self, node_id, kind):
        """「触发器依赖」视图的章节跳转标志：一个从节点右上角斜穿出去的小 ↗。

        只示意「这里有一条跳出本章节的移动」，不画指向目标章节的箭头——跳到哪里
        看左侧详情面板（点节点即列出出边）。触发器上是章节跳转（蓝色实线），
        章节抬头上是超限跳转（橙色虚线，与边图例的虚线一脉相承）。角标带节点
        tag，点它等同点节点。
        """
        box = self._boxes.get(node_id)
        if box is None:
            return
        overflow = kind == EDGE_OVERFLOW
        color = _pick(GRAPH_EDGE_OVERFLOW if overflow else GRAPH_EDGE_GOTO)
        tail = (box.x1 - 13, box.y + 5)
        tip = (box.x1 - 4, box.y - 4)
        tags = (node_id, "jump")
        options = {"fill": color, "width": 1.5, "tags": tags}
        if overflow:
            options["dash"] = (4, 3)
        line = self.canvas.create_line(self._sx(tail[0]), self._sy(tail[1]),
                                       self._sx(tip[0]), self._sy(tip[1]), **options)
        head = self.canvas.create_polygon(self._arrow_points(tip, (1, -1)),
                                          fill=color, outline="", tags=tags)
        self._jump_items.append((node_id, [line, head]))

    # ---------- 交互 ----------

    def _on_press(self, event):
        self.canvas.scan_mark(event.x, event.y)
        hit = self._hit(event)
        self._pressed_on_node = hit is not None
        if hit is not None:
            self.select(hit)

    def _on_motion(self, event):
        if not self._pressed_on_node:
            self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _on_wheel(self, event):
        self._zoom(1.1 if event.delta > 0 else 1 / 1.1)

    def _zoom(self, factor):
        target = max(_SCALE_MIN, min(_SCALE_MAX, self.scale * factor))
        if target == self.scale:
            return
        region = self.canvas.bbox("all") or (0, 0, 1, 1)
        width, height = max(1, region[2] - region[0]), max(1, region[3] - region[1])
        fx = (self.canvas.canvasx(0) - region[0]) / width
        fy = (self.canvas.canvasy(0) - region[1]) / height
        selected = self._selected
        self.scale = target
        self.redraw()
        new_region = self.canvas.bbox("all") or (0, 0, 1, 1)
        new_w = max(1, new_region[2] - new_region[0])
        new_h = max(1, new_region[3] - new_region[1])
        self.canvas.xview_moveto(max(0.0, min(0.9, fx * width / new_w)))
        self.canvas.yview_moveto(max(0.0, min(0.9, fy * height / new_h)))
        self._selected = selected
        self._apply_selection()

    def _hit(self, event):
        for item in reversed(self.canvas.find_overlapping(event.x - 2, event.y - 2,
                                                          event.x + 2, event.y + 2)):
            for tag in self.canvas.gettags(item):
                if tag in self._boxes:
                    return tag
        return None

    def select(self, node_id, notify=True):
        self._selected = node_id if node_id in self._boxes else None
        self._apply_selection()
        if notify and self._selected:
            self.dialog.on_node_selected(self._selected)

    def _apply_selection(self):
        highlight = _pick(GRAPH_EDGE_HIGHLIGHT)
        for node_id, rect in self._rects.items():
            if node_id == self._selected:
                self.canvas.itemconfigure(rect, outline=highlight, width=2.5)
            else:
                self.canvas.itemconfigure(rect, outline=self._default_outlines[node_id],
                                          width=1)
        for edge, items in self._edge_items:
            incident = self._selected in (edge.src, edge.dst)
            color = highlight if incident else _pick(
                _EDGE_COLOR.get(edge.kind, GRAPH_NODE_OUTLINE))
            for item in items:
                self.canvas.itemconfigure(item, fill=color,
                                          width=2.5 if incident else 1.5)
        for node_id, items in self._jump_items:
            incident = node_id == self._selected
            color = highlight if incident else _pick(GRAPH_EDGE_GOTO)
            for item in items:
                self.canvas.itemconfigure(item, fill=color,
                                          width=2.5 if incident else 1.5)

    def focus_node(self, node_id):
        """把某个节点滚进可视区并选中。"""
        if node_id not in self._boxes:
            return
        self.select(node_id, notify=False)
        box = self._boxes[node_id]
        region = self.canvas.bbox("all") or (0, 0, 1, 1)
        width, height = max(1, region[2] - region[0]), max(1, region[3] - region[1])
        self.canvas.xview_moveto(max(0.0, (self._sx(box.cx) - region[0]) / width - 0.28))
        self.canvas.yview_moveto(max(0.0, (self._sy(box.cy) - region[1]) / height - 0.28))


class ScenarioGraphPanel(ctk.CTkFrame):
    """编排视图：章节编排与触发器依赖共用一块画布。

    它嵌在「剧情」页里，与章节触发器列表平级（上方分段切换三者之一），不再是
    独立对话框。两张图由剧情页的分段控件切换，面板内部不再自带视图选择，也没有
    清单视图。校验结论由编辑器顶栏的校验条统一承担
    （``ui/scenario/diagnostics.py``），因此面板里只做**定位**——``focus_path()``
    把某个字段路径带到图上的节点。
    只读，不写盘。
    """

    def __init__(self, parent, config=None, scenario_dir=None):
        super().__init__(parent, fg_color="transparent")
        # 字体：嵌在编辑器页里，与章节列表用同一档字号
        self.UI_FONT = ui_fonts.ui_font(13)
        self.UI_FONT_SMALL = ui_fonts.ui_font(12)
        self.config = config if isinstance(config, dict) else {}
        self.scenario_dir = scenario_dir
        #: 由面板自己做的整份校验（类型校验 + 图校验）；不传 config 时为空
        self.diagnostics = validate_scenario_config(self.config,
                                                    scenario_dir=scenario_dir)
        self.graph = build_graph(self.config)
        self.graph_rules = lint_graph(self.graph)
        self.diags_by_node = {}
        self._chapter_colors = self._collect_chapter_colors()
        self._edge_toggles = {kind: ctk.BooleanVar(value=True)
                              for kind in _TOGGLE_EDGE_KINDS}
        self._only_problems = ctk.BooleanVar(value=False)
        self.view = VIEW_TRIGGERS
        self._index_diagnostics()
        self._build_ui()

    # ---------- 数据 ----------

    def set_data(self, config, diagnostics=None, view=None):
        """换方案 / 换章节触发器后重建模型；``diagnostics`` 缺省时自己校验。

        传进来的诊断与编辑器顶栏校验条用的是同一份（``_diag_summary``），避免两处
        各算一次给出不同结论。``view`` 为剧情页当前选中的图（章节编排 / 触发器依赖）。
        """
        self.config = config if isinstance(config, dict) else {}
        if view in (VIEW_CHAPTERS, VIEW_TRIGGERS):
            self.view = view
        if diagnostics is None:
            diagnostics = validate_scenario_config(
                self.config, scenario_dir=self.scenario_dir)
        self.diagnostics = list(diagnostics)
        self.graph = build_graph(self.config)
        self.graph_rules = lint_graph(self.graph)
        self.diags_by_node = {}
        self._chapter_colors = self._collect_chapter_colors()
        self._index_diagnostics()
        self._render()

    def focus_path(self, path):
        """把字段路径（``triggers[2].action_data.chapter``）定位到图上的节点。"""
        node_id = self._node_for_path(path)
        if not node_id:
            return False
        node = self.graph.node(node_id)
        if node is None:
            return False
        self.canvas.focus_node(node_id)
        return True

    def _collect_chapter_colors(self):
        colors = {}
        for chapter in normalize_chapters(self.config.get("chapters")):
            colors[chapter["name"]] = shade_for_mode(chapter.get("color"), _mode())
        return colors

    def _index_diagnostics(self):
        for diagnostic in self.diagnostics:
            node_id = self._node_for_path(diagnostic.path)
            if node_id:
                self.diags_by_node.setdefault(node_id, []).append(diagnostic)

    def _node_for_path(self, path):
        match = _PATH_INDEX.match(path or "")
        if not match:
            return None
        group, index = match.group(1), int(match.group(2))
        kind = NODE_TRIGGER if group == "triggers" else NODE_CHAPTER
        for node in self.graph.nodes.values():
            if node.index == index and node.kind == kind:
                return node.id
        return None

    def worst_level(self, node_id):
        levels = {diagnostic.level for diagnostic in self.diags_by_node.get(node_id, ())}
        for level in ("error", "warning", "info"):
            if level in levels:
                return level
        return ""

    def accent_for(self, node):
        """泳道左侧强调条 / 章节节点边框：优先按问题级别上色，其次用章节自定义色。"""
        if node is None:
            return ""
        level = self.worst_level(node.id)
        if level == "error":
            return _pick(GRAPH_NODE_ERR_BORDER)
        if level == "warning":
            return _pick(DEPENDENCY_ERR)
        if node.kind == NODE_CHAPTER and node.has(FLAG_MISSING):
            return _pick(GRAPH_NODE_ERR_BORDER)
        return self._chapter_colors.get(node.name, "")

    def visible_nodes(self):
        """当前视图与过滤下要画的节点；筛选时补上所属泳道头，泳道才有标题。"""
        keep = set(self.graph.nodes)
        if self._only_problems.get():
            keep = set(self.diags_by_node)
            for node_id in list(keep):
                node = self.graph.node(node_id)
                if node is not None and node.kind == NODE_TRIGGER:
                    keep.add(node.owner)
        if self.view == VIEW_CHAPTERS:
            keep = {node_id for node_id in keep
                    if self.graph.node(node_id).kind in (NODE_CHAPTER, NODE_ROOT)}
        return keep

    def enabled_edge_kinds(self):
        kinds = {EDGE_ENTRY}
        for kind, variable in self._edge_toggles.items():
            if variable.get():
                kinds.add(kind)
        return kinds

    # ---------- 界面 ----------

    def _build_ui(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True)
        self._main = main

        self.empty_label = ctk.CTkLabel(
            main, text="当前副本方案还没有章节与触发器，编排图为空。",
            font=self.UI_FONT, text_color=DEPENDENCY_TEXT)

        # 摘要行：只报结构概况（章节 / 触发器 / 图校验条数 / 同位竞争）。
        # 问题的条数与定位统一由编辑器顶栏的校验条负责，这里不重复报警；
        # 图例与导出报告都挪到左侧栏的「帮助」对话框与按钮里。
        self.summary_label = ctk.CTkLabel(main, text="", justify="left",
                                          font=self.UI_FONT,
                                          text_color=DEPENDENCY_TEXT)

        body = ctk.CTkFrame(main, fg_color="transparent")
        self._body = body
        self._build_side_panel(body)
        self._build_center(body)
        self._render()

    def _render(self):
        """按当前模型重画：空方案只留一句话，否则更新摘要并刷新当前视图。"""
        has_content = bool(self.graph.chapters() or self.graph.triggers())
        for widget in (self.empty_label, self.summary_label, self._body):
            widget.pack_forget()
        if not has_content:
            self.empty_label.pack(pady=40)
            return
        self.summary_label.pack(anchor="w", pady=(0, 8))
        self._body.pack(fill="both", expand=True)
        self.summary_label.configure(text=self._summary_text())
        self._refresh()

    def _build_side_panel(self, parent):
        # 用 grid 定宽：pack 里固定宽度的面板会被右侧 expand 的内容区压窄
        panel = ctk.CTkFrame(parent, fg_color="transparent", width=SIDE_W)
        panel.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        panel.grid_propagate(False)

        # 操作入口：图例说明收进「帮助」对话框，导出报告也搬到这里
        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.pack(fill="x", pady=(0, 12))
        _action_btn = dict(width=SIDE_W // 2 - 4, height=28, font=self.UI_FONT_SMALL,
                           fg_color="transparent", border_width=1, corner_radius=8,
                           text_color=SC_TEXT_SOFT, hover_color=SC_HOVER,
                           border_color=SC_BORDER)
        ctk.CTkButton(actions, text="? 帮助", command=self._show_help,
                      **_action_btn).pack(side="left", padx=(0, 3))
        ctk.CTkButton(actions, text="导出报告", command=self._export_report,
                      **_action_btn).pack(side="left", padx=(3, 0))

        ctk.CTkLabel(panel, text="图层", font=self.UI_FONT,
                     text_color=SC_TEXT_SOFT).pack(anchor="w", pady=(0, 4))
        for kind in _TOGGLE_EDGE_KINDS:
            ctk.CTkCheckBox(panel, text=EDGE_LABELS[kind], font=self.UI_FONT,
                            checkbox_width=16, checkbox_height=16, text_color=SC_TEXT,
                            border_color=SC_BORDER, variable=self._edge_toggles[kind],
                            command=self._refresh).pack(anchor="w", pady=2)

        ctk.CTkLabel(panel, text="过滤", font=self.UI_FONT,
                     text_color=SC_TEXT_SOFT).pack(anchor="w", pady=(14, 4))
        ctk.CTkCheckBox(panel, text="只看有问题的", font=self.UI_FONT,
                        checkbox_width=16, checkbox_height=16, text_color=SC_TEXT,
                        border_color=SC_BORDER, variable=self._only_problems,
                        command=self._refresh).pack(anchor="w", pady=2)

        self.detail = ctk.CTkLabel(panel, text="点一个节点看它的关系。", justify="left",
                                   wraplength=SIDE_W - 8, font=self.UI_FONT_SMALL,
                                   text_color=SC_TEXT_SOFT)
        self.detail.pack(anchor="w", pady=(16, 0))

    def _build_center(self, parent):
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        holder = ctk.CTkFrame(parent, fg_color="transparent")
        holder.grid(row=0, column=1, sticky="nsew")
        self.canvas = GraphCanvas(holder, self)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.redraw()

    def _refresh(self):
        """图层 / 过滤开关变化后重画当前那张图。"""
        self.canvas.redraw()

    # ---------- 联动 ----------

    def on_node_selected(self, node_id):
        self._show_detail(node_id)

    def position_group_of(self, node_id):
        """node_id 所属的同位置分组（没有竞争中就返回 None）。"""
        for group in self.graph.same_position_groups():
            if any(member.id == node_id for member in group.members):
                return group
        return None

    def _show_detail(self, node_id):
        node = self.graph.node(node_id)
        if node is None:
            return
        lines = [f"{node_title(node)}（{_KIND_LABELS.get(node.kind, '')}）"]
        if node.kind == NODE_TRIGGER:
            lines.append(f"章节：{node.chapter or '任意章节 / 无章节'}")
            lines.append(f"动作：{node_caption(node)}")
            preconditions = [self.graph.node(edge.src).name
                             for edge in self.graph.in_edges(node_id)
                             if edge.kind == EDGE_PRECOND and self.graph.node(edge.src)]
            lines.append("前置：" + ("、".join(preconditions) if preconditions else "无"))
        outgoing = []
        dependents = []
        for edge in self.graph.out_edges(node_id):
            if edge.kind in DRAWABLE_EDGE_KINDS:
                target = self.graph.node(edge.dst)
                if target is not None:
                    if edge.kind in (EDGE_PRECOND, EDGE_CHOICE):
                        # 直接以前置 / 条件引用挂到本触发器上的其他触发器：
                        # 一触器一行，不和其他关系挤一行（选项、小游戏这类被
                        # 多处引用的枢纽触发器尤其需要）
                        dependents.append(f"{EDGE_LABELS[edge.kind]}→{target.name}")
                    else:
                        outgoing.append(f"{EDGE_LABELS[edge.kind]}→{target.name}")
        if dependents:
            lines.append("依赖它的触发器：")
            lines.extend(f"　{row}" for row in dependents)
        lines.append("出边：" + ("、".join(outgoing) if outgoing else "无"))
        if node.kind in (NODE_TRIGGER, NODE_CHAPTER):
            lines.extend(self._position_lines(node_id))
        issues = self.diags_by_node.get(node_id, [])
        if issues:
            lines.append("问题：")
            lines.extend(f"· {issue.message}" for issue in issues)
        self.detail.configure(text="\n".join(lines))

    def _position_lines(self, node_id):
        """同位置竞争：校验器不报，只在这里按位摆出来（见模块说明第 3 点）。

        组员一触器一行，与「依赖它的触发器」同一份排版口径——被引用的枢纽触发器
        同位置组员往往就是那批依赖它的触发器，挤一行读不了。
        """
        group = self.position_group_of(node_id)
        if group is None:
            return []
        lines = [f"同位竞争（{group.label}，作用域：{group.scope}）："]
        lines.extend(("▸ " if member.id == node_id else "　　") + member.name
                     for member in group.members)
        losers = group.shadowed()
        if losers:
            lines.append("永远轮不到（恒真且配置顺序靠后，同位置至多生效一个）：")
            lines.extend(f"　{member.name}" for member in losers)
        return lines

    # ---------- 文案 ----------

    def _summary_text(self):
        """面板顶部的结构概况；诊断计数与定位由编辑器顶栏校验条承担，这里不重复。"""
        groups = len(self.graph.same_position_groups())
        competitors = f" · {groups} 组同位竞争" if groups else ""
        return (f"{len(self.graph.chapters())} 个章节 · "
                f"{len(self.graph.triggers())} 个触发器 · "
                f"图校验 {len(self.graph_rules)} 条{competitors}")

    def _diagnostic_counts_text(self):
        """导出报告里单独给出的诊断统计——报告是离线文档，没有顶栏可看。"""
        counts = {"error": 0, "warning": 0, "info": 0}
        for diagnostic in self.diagnostics:
            counts[diagnostic.level] = counts.get(diagnostic.level, 0) + 1
        if not self.diagnostics:
            return "未发现问题：章节与触发器的依赖关系正常。"
        return (f"{counts['error']} 错误 · {counts['warning']} 警告 · "
                f"{counts['info']} 提示")

    # ---------- 帮助 ----------

    def _show_help(self):
        """打开只读说明对话框：两张图的区别、图例与画图示意。"""
        GraphHelpDialog(self)

    # ---------- 导出 ----------

    def _export_report(self):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            parent=self, title="导出编排报告", defaultextension=".txt",
            initialfile="剧情编排报告.txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        lines = [self._summary_text(), self._diagnostic_counts_text(), "",
                 "【图例】" + _legend_text(), ""]
        for label, ids in self.graph.lanes:
            lines.append(f"● 泳道 {label}")
            for node_id in ids:
                node = self.graph.node(node_id)
                if node is None:
                    continue
                issue = self.worst_level(node_id)
                suffix = f"  [{LEVEL_LABELS.get(issue, '')}]" if issue else ""
                caption = f"：{node_caption(node)}" if node.kind == NODE_TRIGGER else ""
                lines.append(f"    {node.name}"
                             f"（{_KIND_LABELS.get(node.kind, '')}）{caption}{suffix}")
        lines.extend(["", "【关系】"])
        for edge in self.graph.edges:
            if edge.kind not in DRAWABLE_EDGE_KINDS:
                continue
            source, target = self.graph.node(edge.src), self.graph.node(edge.dst)
            if source is None or target is None:
                continue
            detail = f"（{edge.detail}）" if edge.detail else ""
            lines.append(f"    {source.name} --{EDGE_LABELS[edge.kind]}--> "
                         f"{target.name}{detail}")
        lines.extend(["", "【校验诊断】", format_diagnostics(self.diagnostics)])
        lines.extend(self._report_position_groups())
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError as exc:
            showerror("导出失败", f"无法写入文件：{exc}", parent=self)

    def _report_position_groups(self):
        """同位置竞争：校验器不报（判不准），报告里单列一节供作者核对。"""
        groups = self.graph.same_position_groups()
        if not groups:
            return []
        lines = ["", "【同位置竞争】运行时同位置至多生效一个，条件非空的可能竞争需人工判断"]
        for group in groups:
            lines.append(f"    ▸ {group.scope}·{group.label}："
                         + "、".join(member.name for member in group.members))
            losers = group.shadowed()
            if losers:
                lines.append("        恒真且配置顺序靠后（永远轮不到）："
                             + "、".join(member.name for member in losers))
        return lines


class GraphHelpDialog(BaseDialog):
    """编排图的只读帮助：两张图的区别、连线图例、一张画图示意与操作方法。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("编排图帮助")
        self.geometry("680x620")
        self.resizable(False, False)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=(16, 6))

        ctk.CTkLabel(body, text="两张关系图", font=self.SECTION_FONT,
                     text_color=DLG_TEXT).pack(anchor="w")
        intro = (
            "图是只读的：双击节点不会改配置，只看关系。问题计数与定位在编辑器顶栏的校验条，"
            "点一条会切到这里并选中对应节点。"
        )
        ctk.CTkLabel(body, text=intro, font=self.UI_FONT_SMALL, justify="left",
                     text_color=DLG_TEXT_SOFT, wraplength=640).pack(anchor="w", pady=(4, 10))

        for title, desc in (
            ("章节编排", "按可达深度分列，节点是章节，画章节之间的跳转与不可达。"),
            ("触发器依赖", "泳道式：一条泳道一个章节；泳道内按依赖分层，列是依赖深度、行是同层逐个。"),
        ):
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=title, font=self.UI_FONT_BOLD,
                         text_color=DLG_TEXT, width=76, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=desc, font=self.UI_FONT_SMALL, justify="left",
                         text_color=DLG_TEXT_SOFT, wraplength=560,
                         anchor="w").pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(body, text="画图示意", font=self.SECTION_FONT,
                     text_color=DLG_TEXT).pack(anchor="w", pady=(14, 4))
        sketch = tk.Canvas(body, height=190, bg=_pick(GRAPH_CANVAS_BG),
                           highlightthickness=0)
        sketch.pack(fill="x")
        self._draw_sketch(sketch)

        ctk.CTkLabel(body, text="连线与节点", font=self.SECTION_FONT,
                     text_color=DLG_TEXT).pack(anchor="w", pady=(14, 4))
        ctk.CTkLabel(body, text=_legend_text(), font=self.UI_FONT_SMALL,
                     justify="left", text_color=DLG_TEXT_SOFT,
                     wraplength=640).pack(anchor="w")

        ctk.CTkLabel(body, text="操作", font=self.SECTION_FONT,
                     text_color=DLG_TEXT).pack(anchor="w", pady=(14, 4))
        ctk.CTkLabel(
            body,
            text="拖拽平移 · 滚轮缩放 · 点节点高亮入出边并在左侧列出关系与同位置竞争。"
                 "左侧「图层」可关掉某类边，「只看有问题的」只留带诊断的节点。",
            font=self.UI_FONT_SMALL, justify="left", text_color=DLG_TEXT_SOFT,
            wraplength=640).pack(anchor="w")

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(pady=(6, 14))
        self._make_std_button(btns, "知道了", True, self._close).pack()
        self.bind("<Escape>", self._close)
        self._show_modal()

    @staticmethod
    def _draw_sketch(canvas):
        """画一张示意：一条泳道、章节抬头与触发器、几类连线和跳转角标。"""
        def rect(x0, y0, x1, y1, **kw):
            return canvas.create_rectangle(x0, y0, x1, y1, **kw)

        def text(x, y, label, color, size=10):
            canvas.create_text(x, y, text=label, fill=color,
                               font=ui_fonts.ui_font(size))

        def arrow(x0, y0, x1, y1, color, dashed=False, label=""):
            opts = {"fill": color, "width": 2,
                    "arrow": tk.LAST, "arrowshape": (10, 12, 4)}
            if dashed:
                opts["dash"] = (5, 3)
            canvas.create_line(x0, y0, x1, y1, **opts)
            if label:
                text((x0 + x1) // 2, (y0 + y1) // 2 - 9, label, color, 9)

        lane_fill = _pick(GRAPH_LANE_BG)
        lane_border = _pick(GRAPH_LANE_BORDER)
        canvas.create_rectangle(18, 16, 662, 168, fill=lane_fill,
                                outline=lane_border)
        text(32, 32, "泳道：坠入城内", _pick(GRAPH_CANVAS_TEXT_SOFT), 10)

        head_fill = _pick(GRAPH_NODE_HEAD_FILL)
        outline = _pick(GRAPH_NODE_OUTLINE)
        trig_fill = _pick(ACTION_FILL_OPTION)
        err = _pick(GRAPH_NODE_ERR_BORDER)

        # 章节抬头（第 0 列）
        rect(36, 74, 176, 122, fill=head_fill, outline=outline)
        text(106, 92, "坠入城内", _pick(GRAPH_CANVAS_TEXT), 10)
        text(106, 108, "章节", _pick(GRAPH_CANVAS_TEXT_SOFT), 9)
        # 触发器 A / B（第 1、2 列）
        rect(268, 84, 408, 132, fill=trig_fill, outline=outline)
        text(338, 102, "钟声响起", _pick(GRAPH_CANVAS_TEXT), 10)
        text(338, 118, "选项分支", _pick(GRAPH_CANVAS_TEXT_SOFT), 9)
        rect(500, 84, 640, 132, fill=trig_fill, outline=err)
        text(570, 102, "坠入深井", _pick(GRAPH_CANVAS_TEXT), 10)
        text(570, 118, "跳转章节 · 红框=有问题", _pick(GRAPH_CANVAS_TEXT_SOFT), 9)

        arrow(176, 104, 264, 104, _pick(GRAPH_EDGE_PRECOND), label="前置")
        arrow(408, 104, 496, 104, _pick(GRAPH_EDGE_CHOICE), dashed=True,
              label="条件引用")
        # 起点进入
        arrow(28, 60, 60, 76, _pick(GRAPH_EDGE_ENTRY), label="进入")
        # 跳转角标（触发器右上角 ↗ 蓝实线）
        canvas.create_text(632, 78, text="↗", fill=_pick(GRAPH_EDGE_GOTO),
                           font=ui_fonts.ui_font(13))
