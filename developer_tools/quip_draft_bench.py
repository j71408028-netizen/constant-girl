#!/usr/bin/env python3
"""写描述素材（quip）草稿的工作台：出题 → 写 → 收卷 → 校正。

一格 = 观测等级 × 主轴 × 副轴。两根轴是隐坐标，不对写手暴露，只用来轮换一张场景卡
（着重部位 · 动作类型 · 表现手法 · 视角）；写手照卡写，不用对齐数字。落盘时坐标由工具
按出题记录填，事后觉得某条气质不对，人再用 apply 覆盖那条的隐坐标。写手可以是本机
用户、AI，或另一个 agent。

题材全在 quip_profiles/<name>.json：观测等级与缩比锚、两根轴、着重部位、动作类型、部位
修饰（衣着/姿势）、表现手法、地貌词表、视角池、接触判据。换题材 = 复制一份 JSON 改内容，
代码一行不动。档位的 key 与区间不在此列：运行期按身高只会落到 core/logic/sizing.py 的
SIZE_CATEGORIES 这五个档上，profile 只能给每档写「大概能碰什么」与缩比锚，doctor 会比对。
写哪几档随题材：只留用得上的档位是常态，缺档只是那段身高没有语料。

场景卡的四件事各管一件，别混：
  - 着重部位跟主轴（介入度）走；
  - 动作类型严格对应副轴（破坏性）1~4，决定用多少力、力落在多大范围、留下什么，
    与介入度无关；
  - 表现手法跟副轴走，定「怎么写」不定「写到哪」（对比／比喻／特写／转述或错认／
    数字错位／静止／省略／单一感官）；
  - 视角是平铺的开口，按权重抽，只给一句入法，不带候选词表——词表一旦进题面，
    写手就会把它当成必写清单，文体跟着清单塌成同一种。

针对 DeepSeek 调过，也只在 DeepSeek 上调过：卡面措辞、视角说明、收束句禁令、输出
JSON 的形状都是照 deepseek-v4 系列的反应反复改出来的。换后端要重新看一遍题面，
模型对"列表"和"否定句式"的反应差别很大。

尚未完全稳定：一到两成条目仍要人手改（主要是破坏用词、字数不足），个别批整格会被
模型的自我检查污染（parse_response 会丢弃但那一格就等于没写），破坏性 2 与 3 的
边界在"成片"与"一块"之间仍会飘。别拿它一次跑满整档，先跑一格看。

用法（仓库根目录执行）：
    python developer_tools/quip_draft_bench.py doctor        # profile 体检
    python developer_tools/quip_draft_bench.py status        # 进度表
    python developer_tools/quip_draft_bench.py write --cell small:2:3   # 人写，边写边判
    python developer_tools/quip_draft_bench.py draft --cell small:2:3   # AI 写 + 人审
    python developer_tools/quip_draft_bench.py fill --band small --apply --json  # agent 全自动
    python developer_tools/quip_draft_bench.py prompt --cell small:2:3 --json  # 不调 AI
    python developer_tools/quip_draft_bench.py plan --band small --out developer_tools/_out/quip_draft
    python developer_tools/quip_draft_bench.py append --from-file drafts.jsonl --apply
    python developer_tools/quip_draft_bench.py check -v      # 收卷总账
    python developer_tools/quip_draft_bench.py apply --by "21=后背:成片地坏"  # 校正隐坐标

一次只写一个观测等级（band，`--band` 挑）：等级之间口径不同，越界的地方事后很难改
回来；一个等级大约 20~100 条，正好是一次能把握住的规模。

一格 = 主轴 × 副轴，但 (1,4) 与 (4,1) 不存在（轴的端点互相否定），所以每级 14 格。
写哪几格由人看 `status` 的缺口定，再用 `--cell 档位:主轴:副轴` 补那几格。

产物写 developer_tools/_out/quip_draft/（默认 CSV <profile>.csv、drafts-*.jsonl、
plan --out 的题面），不动仓库数据；读写别处的语料用 --csv。
--count 是每格要几条，--batch 是一次调用写几条（默认 3，同格相邻的卡凑一块，
省掉重复的 system）；--seed 默认每次随机，给数字才复现同一批卡。AI 后端取自
data/user 里已配置的那一份；没配也能用 write / prompt / check / append。
坐标不从文本回推：check -v 的格内画像会打出每条的隐坐标与场景卡，只供人工校正。
"""

import argparse
import builtins
import contextlib
import csv
import json
import random
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

# 仓库根：脚本 → developer_tools/ → 根
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROFILE_DIR = Path(__file__).resolve().parent / "quip_profiles"
OUT_DIR = Path(__file__).resolve().parent / "_out" / "quip_draft"

#: CSV 列是 quip 读取器的对外契约，不随题材变化。
COLUMNS = ("size_category", "intrusion", "destruction", "text", "style", "step", "summary")
#: 不属于任何尺度档、也不参与档位判定的分类值（quip 侧的既有约定）。
EXTRA_CATEGORIES = ("any", "none")


def size_categories():
    """主程序认的档位 key（core.logic.sizing.SIZE_CATEGORIES）；取不到时退回空元组。

    profile 写哪几档是自由的（缺档位只是没有语料），但档位名必须落在这个集合里，
    否则产出的语料主程序取不到。
    """
    try:
        from core.logic.sizing import SIZE_CATEGORIES
    except Exception:                                            # noqa: BLE001
        return ()
    return tuple(SIZE_CATEGORIES)

#: 坐标默认权重表（与 persistence.quip_repo.QuipRepo.default_step 同源）。
DEFAULT_STEP = (
    (0.1, 0.2, 0.3, 0.4),
    (0.3, 0.4, 0.5, 0.6),
    (0.5, 0.6, 0.7, 0.8),
    (0.7, 0.8, 0.9, 1.0),
)
CIRCLED = "①②③④⑤⑥⑦⑧⑨"
#: summary 的下限；上限随 profile 的 text.summary_max 走。
SUMMARY_MIN = 2
#: 一个观测等级在设计上约 20~100 条，也是一次能把握住的规模；超过就提示分批。
SESSION_MAX = 100
#: 两根轴的端点在这两格互相否定，写不出来：(1,4) 是「只作为存在出现，却以摧毁为唯一
#: 目的」，(4,1) 是「身体占据玩弄，却一点没碰坏」。出题、进度与收卷都按每级 14 格算。
EXCLUDED_CELLS = frozenset({(1, 4), (4, 1)})
#: 实际存在的格：每级 14 个。
VALID_CELLS = tuple((i, d) for i in range(1, 5) for d in range(1, 5)
                    if (i, d) not in EXCLUDED_CELLS)

#: 旧语料里的替换标记：`[类型字母:细分编号:文本]`（a 衣着、b 姿势）。工具不再生成它，
#: 这里只负责识别与剥离：字数按去掉标记后的正文算，标记内部的文字不参与越档判定。
MARKER_RE = re.compile(r"\[([a-e]):(\d+):([^\[\]]+)\]")
#: 运行时认识的占位符（core/logic/quips.py 的替换口），收卷时放过。
KNOWN_PLACEHOLDERS = ("{name}", "{nick}")

#: 旧版判据的收尾层面，只用于识别旧 profile 并给出提示；新 profile 的手法不带层面。
LEGACY_CHANNELS = frozenset({"看得见的", "记录上的", "身体与环境"})
#: 句内位置指令：把判据挤到开头或结尾，写出来的落点必然是总结句。负面清单，可以列。
POSITION_BANNED = (
    "最后", "结尾", "末尾", "随后", "终于", "最终", "开始", "开头",
    "只剩", "再也", "从此", "再没有人", "再没人", "仿佛从未",
    "好像什么都没发生", "没再提起",
)


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------

class ProfileError(Exception):
    """profile 文件缺字段或自相矛盾。"""


class Profile:
    """一个题材的全部数据。引擎只通过这里取词，不 import 任何题材模块。"""

    def __init__(self, data, source="<inline>"):
        if not isinstance(data, dict):
            raise ProfileError(f"{source}: profile 顶层必须是对象")
        self.source = str(source)
        self.data = data
        self.name = str(data.get("name") or Path(str(source)).stem or "profile")
        self.title = str(data.get("title") or self.name)
        self.subject = str(data.get("subject") or "主体")
        self.band_label = str(data.get("band_label") or "尺度")

        bands = data.get("bands") or []
        if not bands:
            raise ProfileError(f"{source}: 缺 bands")
        self.bands = [_need(b, "key", source) for b in bands]
        self.band_info = {b["key"]: b for b in bands}
        self.rank = {k: i + 1 for i, k in enumerate(self.bands)}

        axes = data.get("axes") or {}
        self.axis_i = self._axis(axes, "intrusion", source)
        self.axis_d = self._axis(axes, "destruction", source)

        self.grid = {}
        for k, v in (data.get("grid") or {}).items():
            try:
                i, d = (int(x) for x in str(k).split("-"))
            except ValueError:
                raise ProfileError(f"{source}: grid 键要写成 主轴-副轴（如 2-3），收到 {k!r}")
            self.grid[(i, d)] = str(v)

        self.words, self.word_order, self.uncovered_words = self._landforms(data, source)

        self.vague = [str(w) for w in data.get("vague") or []]
        self.banned = [str(w) for w in data.get("banned") or []]

        pats = data.get("patterns") or {}
        self.rx_contact = _rx(pats.get("contact"), "patterns.contact", source)
        self.rx_loc = _rx(pats.get("loc_only"), "patterns.loc_only", source)
        self.rx_neg = _rx(pats.get("neg"), "patterns.neg", source)
        self.rx_observe = _rx(pats.get("observe"), "patterns.observe", source)
        self.rx_qualifier = _rx(pats.get("qualifier") or r"^\s*的", "patterns.qualifier", source)
        self.rx_clause = _rx(pats.get("clause") or r"[^，。；：！？、]+", "patterns.clause", source)

        self.angles = []
        for a in data.get("angles") or []:
            if isinstance(a, str):
                self.angles.append({"label": a, "weight": 1, "note": "", "cue_list": ()})
                continue
            label = str(a.get("label", "")).strip()
            if not label:
                continue
            self.angles.append({
                "label": label,
                "weight": max(1, int(a.get("weight", 1))),
                "note": str(a.get("note") or "").strip(),
                "cue_list": tuple(str(c) for c in a.get("cues") or ()),
            })
        if not self.angles:
            raise ProfileError(f"{source}: angles 不能为空")
        self.angle_edges = []
        total = 0
        for a in self.angles:
            total += a["weight"]
            self.angle_edges.append(total)

        text = data.get("text") or {}
        self.text_min = int(text.get("min", 12))
        self.text_max = int(text.get("max", 34))
        self.summary_max = int(text.get("summary_max", 8))
        self.sentence_min = int(text.get("sentences", (1, 3))[0])
        self.sentence_max = int(text.get("sentences", (1, 3))[1])

        self.rules = [str(r) for r in data.get("rules") or []]
        self.notes = data.get("notes") or {}
        self.craft = self._craft(data.get("craft") or {}, source)
        # 手部接触：一次一行，各有各的对象范围与后果边界
        self.touch = self._touch(data.get("touch") or [], source)

    @staticmethod
    def _landforms(data, source):
        """地貌词与它出现的档位。

        推荐写法是按档位分组：键是档位名，值是词表（`{"small": ["路灯", …]}`），
        一组写一行，同一个档位名只出现一次。也接受旧的逐词写法
        `[["路灯", ["small"]], …]`。两条路都收成 `words[词] = (档位…)`，
        词序按首次出现的顺序走，出题时的轮换与 report 里的列举都用它。

        档位名要落在主程序认的 key 上；profile 没写的档位不算错，只是这段不覆盖，
        但词不能标注在没写进 bands 的档位上——那一档根本不会出题。
        """
        known = size_categories()
        runk = {str(b["key"]): i + 1 for i, b in enumerate(data.get("bands") or [])}
        words, order, uncovered = {}, [], defaultdict(list)
        raw = data.get("landforms") or []

        def claim(word, bands):
            word = str(word).strip()
            if not word:
                return
            bs = tuple(str(b) for b in bands)
            unknown = [b for b in bs if b not in runk and b not in known]
            if unknown:
                raise ProfileError(f"{source}: 地貌词「{word}」用了未知档位 {unknown}")
            if not bs:
                raise ProfileError(f"{source}: 地貌词「{word}」没有标档位")
            # 同一个词挂几个档位是常态（如「居民楼」small 与 medium 都能碰），
            # 只有同一档位里写两遍才算笔误
            seen = words.get(word, ())
            dup = [b for b in bs if b in seen]
            if dup:
                raise ProfileError(f"{source}: 地貌词「{word}」在档位 {dup} 里写了两次")
            for b in bs:
                if b not in runk:
                    uncovered[b].append(word)
            words[word] = seen + bs
            if not seen:
                order.append(word)

        if isinstance(raw, dict):
            for band, items in raw.items():
                if isinstance(items, str):
                    items = [items]
                for word in items:
                    if isinstance(word, (list, tuple)):
                        raise ProfileError(
                            f"{source}: landforms 分组写法里值只要词名，收到 {word!r}；"
                            "一个词要挂多个档位就分别写进那几组")
                    claim(word, (band,))
        else:
            for item in raw:
                if not (isinstance(item, (list, tuple)) and len(item) == 2):
                    raise ProfileError(
                        f"{source}: landforms 要被写成按档位分组的对象，"
                        f"或旧的 [词, [档位…]] 列表，收到 {item!r}")
                claim(item[0], item[1])
        return words, order, uncovered

    @staticmethod
    def _axis(axes, key, source):
        axis = axes.get(key) or {}
        levels = axis.get("levels") or {}
        if not levels:
            raise ProfileError(f"{source}: axes.{key}.levels 为空")
        return {
            "label": str(axis.get("label") or key),
            "levels": {int(k): str(v) for k, v in levels.items()},
            "not_yet": {int(k): str(v) for k, v in (axis.get("not_yet") or {}).items()},
        }

    @staticmethod
    def _craft(craft, source):
        """场景卡素材：着重部位跟主轴走，表现手法跟副轴走。

        动作类型与副轴一一对应（静态 / 轻触 / 施力 / 激烈动作），具体动作由写手挑；
        用多少力、力落在多大范围、留下什么都挂在它上面，不再由手法承担。`action_modes`
        的某一级可以写成对象，用 `default` 给默认名、用介入度数字键给变体（`"4": "占有"`），
        出题时按主轴覆盖。`parts` 是一张表：部位名为键、等级与衣着/姿势写在值里，
        同一个部位词只出现一次（见 `_part_table`）。

        `reach` 是表现手法的一张表：`[手法, 说明]` 对平铺，一份就够——手法按破坏性
        轮换，但同一个词在不同破坏性下写法不变，所以不必分四级抄四遍。也接受按级分组
        `{"1": […]}`（某一级要另给一套时才用）。手法是「怎么写」——对比 / 比喻 /
        特写 / 转述或错认 / 数字错位 / 静止 / 省略 / 单一感官，不规定写到哪一步，
        也不规定这一句的哪一部分写什么。档位造成的缩比不写在这里，由 `bands[].anchor` 给。
        """
        def pools(key, label, required=True):
            raw = craft.get(key) or {}
            out = {}
            for lv in range(1, 5):
                items = raw.get(str(lv), raw.get(lv, []))
                if isinstance(items, str):
                    items = [items]
                out[lv] = [str(x) for x in items if str(x).strip()]
            if required and not any(out.values()):
                raise ProfileError(f"{source}: craft.{key} 为空，出题时没有可轮换的{label}")
            return out

        raw_reach = craft.get("reach") or {}
        if isinstance(raw_reach, dict):
            per_level = {lv: raw_reach.get(str(lv), raw_reach.get(lv, [])) for lv in range(1, 5)}
        else:
            # 平铺一份：四级共用，改手法只改这一处
            per_level = {lv: raw_reach for lv in range(1, 5)}
        pairs = {}
        for lv in range(1, 5):
            items = per_level[lv]
            if isinstance(items, str):
                items = [items]
            got = []
            for it in items:
                if isinstance(it, (list, tuple)) and len(it) == 2:
                    got.append((str(it[0]).strip(), str(it[1]).strip()))
                elif str(it).strip():
                    got.append(("", str(it).strip()))
            pairs[lv] = got
        if not any(pairs.values()):
            raise ProfileError(f"{source}: craft.reach 为空，出题时没有可轮换的手法")

        # 手法短名与说明分开反查：写作时给写手看说明，人工校正时给人敲短名。
        genres = {lv: [ch or tx for ch, tx in pairs[lv]] for lv in pairs}
        descriptions = {lv: [tx for _ch, tx in pairs[lv]] for lv in pairs}
        # 旧写法：`genres` / `consequences` 按级另给一份短名或说明。手法已收成一张表，
        # 这两块只在老 profile 里还挂着，读进来覆盖同名的那一级。
        raw_genres = craft.get("genres") or {}
        raw_cons = craft.get("consequences") or {}
        for lv in range(1, 5):
            if raw_genres.get(str(lv)) or raw_genres.get(lv):
                items = raw_genres.get(str(lv), raw_genres.get(lv))
                genres[lv] = [str(x).strip() for x in items if str(x).strip()]
            if raw_cons.get(str(lv)) or raw_cons.get(lv):
                items = raw_cons.get(str(lv), raw_cons.get(lv))
                descriptions[lv] = [str(x).strip() for x in items if str(x).strip()]

        parts, details = _part_table(craft, source)

        default_modes = {1: "静态", 2: "轻触", 3: "施力", 4: "激烈动作"}
        raw_modes = craft.get("action_modes") or {}
        modes, mode_variants = {}, {}
        for lv in range(1, 5):
            value = raw_modes.get(str(lv), raw_modes.get(lv, default_modes[lv]))
            if isinstance(value, dict):
                # 「默认档 + 按介入度覆盖」：{"default": "激烈动作", "4": "占有"}
                variants = {int(k): str(v).strip()
                            for k, v in value.items() if str(k).isdigit() and str(v).strip()}
                value = value.get("default", default_modes[lv])
                mode_variants[lv] = variants
            if not str(value).strip():
                raise ProfileError(f"{source}: craft.action_modes.{lv} 不能为空")
            modes[lv] = str(value).strip()

        return {
            "part_label": str(craft.get("part_label") or "身体部位"),
            "reach_label": str(craft.get("reach_label")
                                or craft.get("consequence_label") or "表现手法"),
            "parts": parts,
            "action_modes": modes,
            "action_variants": mode_variants,
            "part_details": details,
            "reach_pairs": pairs,
            "genres": genres,
            "descriptions": descriptions,
            "consequences": descriptions,   # 兼容 apply --by / doctor 的按级反查
        }

    @staticmethod
    def _touch(items, source):
        """手能干什么：一项一种接触方式，不合并成一句。

        「握住/捏住」要求掌心圈得住，对象必须比手小，抓住之后能整件处置；
        「指尖点、推、拨」只碰一个点，对象可以大得多，但只动得了碰的那一处。
        两者的对象范围与后果边界都不同，写成「握/捏/指尖拨弄」一条必错。
        """
        out = []
        for it in items:
            if not isinstance(it, dict) or not it.get("label"):
                raise ProfileError(f"{source}: touch 每项要有 label")
            scope = str(it.get("objects") or "")
            if scope not in ("", "contact", "upper"):
                raise ProfileError(
                    f"{source}: touch.objects 只能是 contact（本档词表）/ upper（高一档）/ 空，"
                    f"收到 {scope!r}")
            out.append({
                "key": str(it.get("key") or f"touch{len(out) + 1}"),
                "label": str(it["label"]),
                "scope": scope,
                "can": str(it.get("can") or ""),      # 这一种接触能做到什么
                "cannot": str(it.get("cannot") or ""),  # 到哪儿为止
            })
        return out

    # -- 派生量 ---------------------------------------------------------

    def default_step(self, i, d):
        """坐标的默认权重，直接取主程序那份表，profile 不再自带一份。"""
        return DEFAULT_STEP[int(d) - 1][int(i) - 1]

    def grid_text(self, i, d):
        return self.grid.get((int(i), int(d))) or f"{self.axis_i['label']} {i} × {self.axis_d['label']} {d}"

    def craft_of(self, i, d, k=0, salt=0):
        """按坐标轮换一张场景卡。

        着重部位跟主轴（介入度）走；动作类型跟副轴（破坏性）一一对应——用多少力、
        力落在多大范围、留下什么全由它定，与介入度无关，所以同一部位在不同破坏性下
        可以是静态、轻触、施力或激烈动作。衣着、姿势是部位的修饰：只有该部位在
        `part_details` 里时，才按 `wear_every` / `posture_every` 偶尔带出来，并跟部位
        写在一起。表现手法跟副轴走，与部位各自轮换——同一张卡可以是「特写」，也可以是
        「单一感官」，两种都不改这一段写到哪。
        """
        level = int(i)
        parts = self.craft["parts"].get(level) or []
        if not parts:
            for delta in (1, -1, 2, -2, 3):
                parts = self.craft["parts"].get(level + delta) or []
                if parts:
                    break

        part = parts[(salt + k) % len(parts)] if parts else ""
        wear = posture = posture_limit = ""
        detail = self.craft["part_details"].get(part)
        if detail:
            wear_key = salt * 3 + k * 5 + level * 7
            if detail["wear"] and wear_key % detail["wear_every"] == 0:
                wear = detail["wear"][wear_key % len(detail["wear"])]
            posture_key = salt * 11 + k * 3 + level * 5
            if detail["posture"] and posture_key % detail["posture_every"] == 0:
                posture, posture_limit = detail["posture"][
                    posture_key % len(detail["posture"])]
        part_display = f"{part}（穿着{wear}）" if wear else part

        pairs = self.craft["reach_pairs"].get(int(d)) or []
        if not pairs:
            for delta in (1, -1, 2, -2, 3):
                pairs = self.craft["reach_pairs"].get(int(d) + delta) or []
                if pairs:
                    break
        # 手法跟部位错开：两边项数相同时若用同一个下标，某个部位会永远配同一种手法。
        ridex = (salt * 2 + k * 5 + int(i) * 3 + int(d)) % len(pairs) if pairs else 0
        genre, text = pairs[ridex] if pairs else ("", "")
        # 动作类型按副轴取，介入度有变体时用变体（例如 (4,4) 的占有）
        variants = self.craft["action_variants"].get(int(d)) or {}
        action_mode = variants.get(level) or self.craft["action_modes"].get(int(d), "")
        return {
            "part": part,
            "part_display": part_display,
            "wear": wear,
            "posture": posture,
            "posture_limit": posture_limit,
            "action_mode": action_mode,
            "genre": genre,
            "reach": text,
            "reach_line": f"{genre}：{text}" if genre else text,
        }

    def pick_angle(self, key):
        """按权重抽一个视角。

        权重高的开口自带画面，权重低的只有制度、数据或时间，必须落回一个正在做这件事
        的人身上。键相同则结果相同，同一批题可以复现。
        """
        total = self.angle_edges[-1]
        pos = (key * 2654435761) % total
        for a, edge in zip(self.angles, self.angle_edges):
            if pos < edge:
                return a
        return self.angles[-1]

    def levels_of(self, kind, word, exact_only=False):
        """场景卡词反查等级（apply --by 用）。

        先找完全相同的词，再退回包含匹配；返回所有命中的等级，交给调用方判断
        是唯一命中还是歧义。不能直接返回第一个——否则「手」会被更早的「手掌」抢走。
        `genres` 是手法短名，先按短名精确命中，再退到说明文本里找。
        """
        pool = self.craft[kind]
        word = str(word).strip()
        exact = [lv for lv in sorted(pool) if word in pool[lv]]
        if exact or exact_only:
            return exact
        return [lv for lv in sorted(pool) if any(word in it for it in pool[lv])]

    def size_desc(self, band):
        """这一档能碰到什么，只用来让写手知道大概的尺寸量级。"""
        return self.band_info[band].get("can", "")

    def size_anchor(self, band):
        """这一档的缩比锚：判据在同档位的“多大”上折算成什么。"""
        return self.band_info[band].get("anchor", "")

    def size_display(self, band):
        return self.band_info[band].get("display", "")

    def contact_budget(self, band):
        """本档能碰哪些地貌、手里能额外拿哪些、哪些禁写。词序沿用 profile。"""
        rank = self.rank[band]
        ok = [w for w in self.word_order if band in self.words[w]]
        near = [w for w in self.word_order
                if any(abs(self.rank[b] - rank) <= 1 for b in self.words[w] if b in self.rank)]
        blocked = [w for w in self.word_order if band not in self.words[w]]
        upper = [w for w in near
                 if band not in self.words[w]
                 and any(self.rank.get(b) == rank + 1 for b in self.words[w])]
        return ok, near, upper, blocked

    def iter_cells(self, bands=None):
        for band in (bands or self.bands):
            for i, d in VALID_CELLS:
                yield band, i, d


def _need(obj, key, source):
    if not isinstance(obj, dict) or not obj.get(key):
        raise ProfileError(f"{source}: bands 每项都要有 {key}")
    return str(obj[key])


def _part_table(craft, source):
    """着重部位：一张表同时给出分级与衣着/姿势修饰。

    推荐写法是一个部位一个键，等级写在值里——改部位名只改这一处：

        "parts": {
          "腿":   {"level": 2, "wear": ["短裙"], "posture": {"站立": "脚底是唯一接触面"}},
          "手":   {"level": 3, "wear": ["袖套"]},
          "指尖": {"level": 4},
          "轮廓": 1
        }

    也接受旧的 `{"1": ["轮廓"], "2": ["腿", ...]}` + 并列的 `part_details`：
    两处都写部位名，改词要改两次。两种一起给时以单表为准。

    返回 `({等级: [部位…]}, {部位: 修饰})`；同一等级内保持写法里的先后顺序。
    """
    raw = craft.get("parts")
    if not isinstance(raw, dict) or not raw:
        raise ProfileError(f"{source}: craft.parts 为空，出题时没有可轮换的部位")

    by_level = {lv: [] for lv in range(1, 5)}
    details, seen = {}, {}
    table_form = any(not str(k).isdigit() for k in raw)

    for key, spec in raw.items():
        name = str(key).strip()
        if table_form and name.isdigit():
            raise ProfileError(f"{source}: craft.parts 不能混用两种写法——"
                               f"有部位名键（如「{next(k for k in raw if not str(k).isdigit())}」）"
                               f"时不应再出现数字等级键「{name}」")
        if not name:
            continue

        if name.isdigit():
            level = int(name)
            items = spec if isinstance(spec, (list, tuple)) else [spec]
            for item in items:
                part = str(item).strip()
                if not part:
                    continue
                if part in seen:
                    raise ProfileError(f"{source}: craft.parts「{part}」在 {seen[part]}、"
                                       f"{level} 级都出现，同一个词只能属于一级")
                seen[part] = level
                by_level.setdefault(level, []).append(part)
            continue

        if isinstance(spec, int):
            spec = {"level": spec}
        elif isinstance(spec, str):
            spec = {"level": spec}
        elif isinstance(spec, (list, tuple)):
            # "腿": [2, "短裙", "长筒袜"] —— 首项等级，其余是衣着
            spec = {"level": spec[0], "wear": list(spec[1:])}
        if not isinstance(spec, dict):
            raise ProfileError(f"{source}: craft.parts「{name}」要是等级、列表或对象")

        level = spec.get("level")
        try:
            level = int(str(level).strip())
        except (TypeError, ValueError):
            raise ProfileError(f"{source}: craft.parts「{name}」缺 level（1~4）")
        if not 1 <= level <= 4:
            raise ProfileError(f"{source}: craft.parts「{name}」的 level={level} 越界，"
                               "两根轴都只有 1~4")
        by_level.setdefault(level, []).append(name)

        wear, posture = _part_extras(spec, name, source)
        if wear or posture:
            details[name] = {
                "wear": wear,
                "posture": posture,
                "wear_every": max(1, int(spec.get("wear_every", 3))),
                "posture_every": max(1, int(spec.get("posture_every", 2))),
            }

    if table_form:
        return by_level, details

    legacy = craft.get("part_details") or {}
    for part, spec in legacy.items():
        part = str(part)
        if part not in seen:
            raise ProfileError(f"{source}: craft.part_details.{part} 不在 craft.parts 里")
        if isinstance(spec, str):
            spec = {"wear": [spec]}
        if not isinstance(spec, dict):
            raise ProfileError(f"{source}: craft.part_details.{part} 要是对象")
        wear, posture = _part_extras(spec, part, source)
        if wear or posture:
            details[part] = {
                "wear": wear,
                "posture": posture,
                "wear_every": max(1, int(spec.get("wear_every", 3))),
                "posture_every": max(1, int(spec.get("posture_every", 2))),
            }
    return by_level, details


def _part_extras(spec, part, source):
    """部位的衣着与姿势：`wear` 收成词表，`posture` 收成 [(姿势, 物理约束)]。"""
    raw_wear = spec.get("wear") or []
    if isinstance(raw_wear, str):
        raw_wear = [raw_wear]
    elif isinstance(raw_wear, dict):
        raw_wear = list(raw_wear)
    wear = [str(x).strip() for x in raw_wear if str(x).strip()]

    raw_posture = spec.get("posture") or []
    if isinstance(raw_posture, dict):
        posture = [(str(k).strip(), str(v).strip())
                   for k, v in raw_posture.items() if str(k).strip()]
    else:
        if isinstance(raw_posture, str):
            raw_posture = [raw_posture]
        posture = [(str(x).strip(), "") for x in raw_posture if str(x).strip()]
    return wear, posture


def _rx(pattern, field, source):
    if not pattern:
        raise ProfileError(f"{source}: 缺 {field}")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ProfileError(f"{source}: {field} 不是合法正则（{exc}）")


def load_profile(spec):
    """`giantess` 取 quip_profiles/giantess.json；带路径则直接读。"""
    path = Path(spec)
    if not path.suffix:
        path = PROFILE_DIR / f"{spec}.json"
    if not path.exists():
        have = "、".join(sorted(p.stem for p in PROFILE_DIR.glob("*.json"))) or "（无）"
        raise ProfileError(f"找不到 profile {spec!r}；现有：{have}。"
                           "题材数据各人写各人的，不入库：照 template.json 复制一份改内容即可")
    with open(path, "r", encoding="utf-8") as f:
        return Profile(json.load(f), path)


def profile_problems(p):
    """doctor 用：能写能跑的底线，全部列出来而不是首个报错就停。"""
    bad = []
    if not p.bands:
        bad.append("bands 为空：一档都没有，出不了题")
    for axis, name in ((p.axis_i, "intrusion"), (p.axis_d, "destruction")):
        if sorted(axis["levels"]) != [1, 2, 3, 4]:
            bad.append(f"axes.{name}.levels 要正好覆盖 1~4，现在 {sorted(axis['levels'])}")
        for lv in axis["levels"]:
            if lv in axis["not_yet"] and lv == 4:
                bad.append(f"axes.{name}.not_yet 不该有 4 级")
    for band in p.bands:
        if not p.size_desc(band):
            bad.append(f"bands[{band}] 缺 can（这一档能写什么）")
        if not p.size_anchor(band):
            bad.append(f"bands[{band}] 缺 anchor：没有缩比锚，判据就折不成这一档的大小")
        ok, near, _upper, _blocked = p.contact_budget(band)
        if not ok:
            bad.append(f"bands[{band}] 在 landforms 里没有任何专属词，这一档写不出东西")
        if not near:
            bad.append(f"bands[{band}] 没有 ±1 档的地貌词，判据没有可缩比的对象")
    missing = [(i, d) for i, d in VALID_CELLS if (i, d) not in p.grid]
    if missing:
        bad.append(f"grid 缺 {len(missing)} 格（{missing[:4]}…），出题时用坐标兜底")
    # 部位词要唯一归属一级：同一个词落在两级，apply --by 判不出是哪个坐标的卡
    owner = defaultdict(list)
    for lv, words in p.craft["parts"].items():
        for word in words:
            owner[word].append(lv)
    dup = [f"{w}（{'/'.join(str(x) for x in sorted(lvs))} 级）"
           for w, lvs in owner.items() if len(lvs) > 1]
    if dup:
        bad.append(f"craft.parts 有跨级重复的{p.craft['part_label']}：{'、'.join(dup)}；"
                   "同一个词只能属于一级，否则 apply --by 判不出是哪一级")
    empty = [lv for lv in range(1, 5) if not p.craft["parts"][lv]]
    if empty:
        bad.append(f"craft.parts 的 {empty} 级是空的，{p.craft['part_label']}会回退到相邻级")
    short = [lv for lv in range(1, 5) if 0 < len(p.craft["parts"][lv]) < 3]
    if short:
        bad.append(f"craft.parts 的 {short} 级不足 3 项，同格三条会撞"
                   f"{p.craft['part_label']}")
    # 动作类型的变体名必须与它覆盖的那一档同属一个强度，且不许撞默认名
    for lv, variants in p.craft["action_variants"].items():
        for i, name in variants.items():
            if name in p.craft["action_modes"].values():
                bad.append(f"craft.action_modes.{lv} 的介入度 {i} 变体「{name}」与默认动作"
                           "类型重名：题面里分不出它是哪一档")
    # 手部接触：一项一种方式；只有「只碰一点」的那些才配高一档的对象
    if not p.touch:
        bad.append("touch 为空：能碰什么只剩「够得着」，握得住与够得着的区别没地方讲")
    for h in p.touch:
        if not h["scope"] and not h["can"] and not h["cannot"]:
            bad.append(f"touch「{h['label']}」既没写能做到什么，也没写到哪儿为止")
    # 视角：平铺的开口。带词表的旧式视角会把清单塞进题面，写手照着清单挑好写的写
    labels = [a["label"] for a in p.angles]
    if len(labels) != len(set(labels)):
        bad.append("angles 有重名的开口，视角单一检测会判错")
    for a in p.angles:
        if a["cue_list"]:
            bad.append(f"angles「{a['label']}」还带着词表：词表进题面就会变成必写清单")
        if not a["note"]:
            bad.append(f"angles「{a['label']}」没有说明：只给一个标签，写手不知道从哪入")
    if not any(a["weight"] > 1 for a in p.angles):
        bad.append("angles 权重全是 1：加权没起作用，难写的开口会照样占满配额")
    # 手法：每级至少 3 条；同一级内不许重名（同格会撞），跨级复用是正常轮换
    genres_seen = set()
    for lv in range(1, 5):
        pairs = p.craft["reach_pairs"][lv]
        if len(pairs) < 3:
            bad.append(f"craft.reach 第 {lv} 级只有 {len(pairs)} 条手法，同格三条会撞")
        names = [gen for gen, _tx in pairs if gen]
        if len(names) != len(set(names)):
            bad.append(f"craft.reach 第 {lv} 级有重复的手法名")
        for gen, tx in pairs:
            if not gen:
                bad.append(f"craft.reach 第 {lv} 级有手法没写短名：写手分不清这是哪种写法")
                continue
            genres_seen.add(gen)
            if "最后" in tx or "结尾" in tx or "之后" in tx:
                bad.append(f"craft.reach「{gen}」的说明含句内位置词：手法不规定写在哪儿")
    if len(genres_seen) < 3:
        bad.append("craft.reach 的手法不足三种：副轴会被压回同一个写法")
    # 部位修饰：空修饰在解析期就丢掉了，这里只剩「挂了却轮换不到」要看
    for part in p.craft["part_details"]:
        if part not in {x for lv in p.craft["parts"] for x in p.craft["parts"][lv]}:
            bad.append(f"部位修饰「{part}」不在 craft.parts 里，永远不会命中")
    if p.text_min >= p.text_max:
        bad.append(f"text.min({p.text_min}) 要小于 text.max({p.text_max})")
    return bad


# ---------------------------------------------------------------------------
# 出题
# ---------------------------------------------------------------------------

def _wrap(words, limit=14, tail="全表见 profile"):
    """词表截断：长表只给前几个，后面缀上总量。tail 为空则只报总数。"""
    if len(words) <= limit:
        return "、".join(words) or "（无）"
    more = f"…（共 {len(words)} 词" + (f"，{tail}）" if tail else "）")
    return "、".join(words[:limit]) + more


def channel_names(p):
    """旧 profile 里判据用到的收尾层面；新 profile 的手法没有层面，返回空。"""
    out = []
    for pairs in p.craft["reach_pairs"].values():
        for ch, text in pairs:
            if ch and ch in LEGACY_CHANNELS and ch not in out:
                out.append(ch)
    return out


def size_anchor_line(anchor):
    """缩比锚的解释：只交代这一档多大，不再让写手拿它折算判据。"""
    return f"缩比：{anchor}（这一档多大；正文不写尺寸）"


def glossary(p):
    """题面里的术语与称呼写法：光给词，写手（人或模型）猜不出它要自己做什么。"""
    channels = channel_names(p)
    out = []
    if channels:
        out.append(f"判据层面：{' / '.join(channels)}；落到任一层都算到位，层面名不写进正文。")
    out.append("称呼：可以直接写称呼，也可以用 {name}（角色名）/ {nick}（昵称）占位符，"
               "运行时替换成当前角色；花括号只认这两个。")
    return out


def writing_rules(p):
    """进题面的写作规则：只留能改变这一段怎么写的。"""
    rules = [
        f"{p.text_min}~{p.text_max} 字，{p.sentence_min}~{p.sentence_max} 句；"
        "句子长短不齐，不写排比与整齐的对照。",
        "「表现手法」说的是这一段怎么写，不是写到哪一步；照它写，别把它当结果交代。",
        "不规定句内顺序：不写「先…再…」「最后…」这种位置关系；正文里也不许出现手法名。",
        f"不用收束句：{'、'.join(POSITION_BANNED[:10])}这类把话合拢的说法一律不写。",
        "可接触范围只限定主体能碰到多大的东西，不是要求这一条必须发生接触。",
    ]
    return rules + p.rules


def output_contract(p):
    """落盘约定：CSV 与字段的工程约束，跟写作本身无关。"""
    return [
        f"正文不用半角逗号；summary 可留空，写了就 {SUMMARY_MIN}~{p.summary_max} 字；"
        "style 留空；step 工具填。",
    ]


#: 动作类型与副轴（破坏性）一一对应，与主轴（介入度）无关。四档各管一件事：
#: 她用了多少力、力落在多大范围、留下什么，全部由这里定。
ACTION_HINTS = {
    "静态": "不施力。可以站着、坐着、看着或做个小动作，但凡碰到的东西都不留形变："
            "没有裂缝、凹陷、扬尘、焦痕。",
    "轻触": "力只到碰到的那一点。那一点变了形，或者什么也没变，两者选一，不写中间态；"
            "碰着之处以外一律完好，不写连锁、不写波及。",
    "施力": "力压进接触面，接触的那一片成片损坏——塌、裂、碎、压平，"
            "边界清晰可指认，但损坏停在接触范围内的那一块，不到别处。",
    "激烈动作": "接触面下的东西先于她垮：她还没使上劲，底下的已经塌了、断了、陷了；"
                "该碰到的范围内没有留下能修的东西。",
    "占有": "破坏不是目的，拿到手才是：接触的对象被她圈住、占住、据为己有，"
            "它坏不坏取决于她要不要留它——留的那部分完好，不要的当场不成形。",
}


def action_hint(mode):
    """动作类型定强度、范围与破坏边界；不替写手挑具体动作。

    变体名（如「占有」）在本表里有一句自己的说明；没登记的名字退回默认那句。
    """
    return ACTION_HINTS.get(
        mode, "只定强度、范围与破坏边界；具体动作由你挑，不要写成姿势。")


def build_brief(p, band, i, d, k, seed, style_note=""):
    """一条题面。

    对外的可见部分：着重部位（可带衣着/姿势）、动作类型、表现手法、视角、
    可接触范围；(i, d) 与未显示的修饰留在返回值的内部字段里，供落盘与原样回传。
    """
    cell_index = p.rank[band] * 16 + (i - 1) * 4 + (d - 1)
    angle = p.pick_angle(cell_index + k * 7 + seed * 3)

    ok, _near, upper, _blocked = p.contact_budget(band)
    card = p.craft_of(i, d, k, cell_index + seed)

    return {
        "id": f"{band}-{i}{d}-{k + 1}",
        "profile": p.name,
        "band": band, "intrusion": i, "destruction": d,
        "step": p.default_step(i, d),
        "band_display": p.size_display(band),
        "band_can": p.size_desc(band),
        "band_anchor": p.size_anchor(band),
        "part": card["part"],
        "part_display": card["part_display"],
        "wear": card["wear"],
        "posture": card["posture"],
        "posture_limit": card["posture_limit"],
        "action_mode": card["action_mode"],
        "reach": card["reach"],
        "genre": card["genre"],
        "witness": angle["label"],
        "witness_note": angle["note"],
        "witness_weight": angle["weight"],
        "objects_contact": ok,
        "objects_poke": upper,
        "rules": writing_rules(p),
        "contract": output_contract(p),
        "glossary": glossary(p),
        "style_note": style_note or "",
    }


def _angle_line(b, limit=6):
    """视角只给一个开口和一句说明，不给可选词表。

    词表一旦出现，写手就会把它当成必写清单，句子的文体跟着清单塌成同一种。
    """
    note = (b.get("witness_note") or "").strip()
    return f"{b['witness']}（{note}）" if note else b["witness"]


def _reach_line(b):
    """手法：短名在前，后面跟这一条对写法的要求；短名本身不进正文。"""
    genre = b.get("genre") or ""
    return f"{genre}（{b['reach']}）" if genre else b["reach"]


def _touch_lines(p, brief, limit=14):
    """可接触范围：一项一种接触方式，各带自己的对象范围与边界。

    它是「描写里允许主体碰到什么」，不是动作清单，也不是要求这一条必须接触。
    握与拨不能合成一句——握要求圈得住（对象比手小），拨只碰一个点（对象可以大得多），
    两句话的对象集合和后果都不一样，合起来写手只能照抄一半。对象表会截断，所以
    统一声明它是示例而不是白名单。
    """
    out = []
    if not any(h["scope"] == "contact" for h in p.touch):
        out.append(f"够得着（本档）：{_wrap(brief['objects_contact'], limit, tail='')}")
    for h in p.touch:
        body = ""
        if h["scope"] == "upper":
            words = brief["objects_poke"]
            body = (_wrap(words, limit, tail="") if words
                    else "本档已最高，按接触部位所及")
        elif h["scope"] == "contact":
            body = _wrap(brief["objects_contact"], limit, tail="")
        tag = {"contact": "本档", "upper": "高一档"}.get(h["scope"], "")
        head = h["label"] + (f"（{tag}）" if tag else "")
        notes = (["对象由接触部位决定"] if h["scope"] == "" else [])
        notes += [x for x in (h["can"], h["cannot"]) if x]
        line = f"{head}：{body}" if body else head
        if notes:
            line += "；" + "；".join(notes)
        out.append(line)
    return out


def render_cell_md(p, cell_briefs, group_no=None, group_total=None):
    """一格题面：档位、缩比锚与词表共享，每条只给卡、手法、部位修饰与观察者。"""
    b0 = cell_briefs[0]
    band = b0["band"]
    head = f"## {band} · {len(cell_briefs)} 条"
    if group_no and group_total and group_total > 1:
        head += f"（第 {group_no}/{group_total} 组）"
    title = f"**{p.band_label} {band}"
    if b0["band_display"]:
        title += f"（{b0['band_display']}）"
    lines = [
        head,
        "",
        title + f"**：{b0['band_can']}",
        f"- {size_anchor_line(b0['band_anchor'])}" if b0["band_anchor"] else "",
        "",
        "**这一组**",
    ]
    for n, b in enumerate(cell_briefs):
        mark = CIRCLED[n] if n < len(CIRCLED) else f"({n + 1})"
        lines.append(f"- {mark} {p.craft['part_label']}：{b['part_display']} ｜ "
                     f"动作类型：{b['action_mode']}")
        lines.append(f"  {p.craft['reach_label']}：{_reach_line(b)}")
        extra = []
        if b["posture"]:
            posture = f"姿势：{b['posture']}"
            if b["posture_limit"]:
                posture += f"（{b['posture_limit']}）"
            extra.append(posture)
        extra.append(f"视角：{_angle_line(b)}")
        lines.append("  " + "｜".join(extra))
    lines += [
        "",
        "**可接触范围（写到接触时用）**",
        "- 这是描写里允许主体接触的物体范围，不是动作清单，也不是要求这一条必须接触。",
    ]
    lines += [f"- {line}" for line in _touch_lines(p, b0)]
    lines += ["- 列表是示例，不是白名单；同类物体可以写，但不要跨到更高一档。"]
    lines += [
        "",
        "**术语**",
    ]
    lines += [f"- {g}" for g in b0["glossary"]]
    lines += [
        "",
        "**写作**",
    ]
    lines += [f"- {c}" for c in b0["rules"]]
    lines += ["", "**落盘**"]
    lines += [f"- {c}" for c in b0["contract"]]
    if b0["style_note"]:
        lines += ["", "**风格附加要求**", "", b0["style_note"].strip()]
    lines.append("")
    return "\n".join(l for l in lines if l is not None)


def render_cell_text(p, cell_briefs, index=1, total=1):
    """控制台里的一条，比 md 短，逐条出题时反复用。"""
    b0 = cell_briefs[0]
    head = f"── {index}/{total}  {b0['band']}"
    if b0["band_display"]:
        head += f"（{b0['band_display']}）"
    lines = [head, f"  {b0['band_can']}"]
    if b0["band_anchor"]:
        lines.append(f"  {size_anchor_line(b0['band_anchor'])}")
    for n, b in enumerate(cell_briefs):
        mark = CIRCLED[n] if n < len(CIRCLED) else f"({n + 1})"
        lines.append(f"  {mark} {p.craft['part_label']}：{b['part_display']} ｜ "
                     f"动作类型：{b['action_mode']}")
        lines.append(f"    {p.craft['reach_label']}：{_reach_line(b)}")
        extra = []
        if b["posture"]:
            posture = f"姿势：{b['posture']}"
            if b["posture_limit"]:
                posture += f"（{b['posture_limit']}）"
            extra.append(posture)
        extra.append(f"视角：{_angle_line(b)}")
        lines.append("    " + "｜".join(extra))
    lines.append("  可接触范围（写到接触时用；不是动作清单，也不是必须接触）：")
    lines += [f"  - {line}" for line in _touch_lines(p, b0, limit=10)]
    lines.append("  - 列表是示例，不是白名单；不要写到更高一档。")
    lines.append("  术语：")
    lines += [f"  - {g}" for g in b0["glossary"]]
    lines.append("  写作：")
    lines += [f"  - {r}" for r in b0["rules"]]
    lines.append("  落盘：")
    lines += [f"  - {c}" for c in b0["contract"]]
    return "\n".join(lines)


def reject_cell(i, d):
    """(1,4) 与 (4,1) 不存在：先拦下来，别让它进题面也别让它落盘。"""
    if (i, d) not in EXCLUDED_CELLS:
        return
    raise SystemExit(
        f"({i},{d}) 不是可写的格：两根轴的端点在这里互相否定——"
        "(1,4) 什么都没做却彻底毁坏，(4,1) 拿建筑当玩物却一点没碰坏。\n"
        "每级只有 14 格：出题时看 status 挑要补的格，校正时换个部位或判据。")


def cell_targets(p, args):
    """--cell / --band / 全量，统一成 [(band, i, d)]。"""
    bands = tuple(args.band) if getattr(args, "band", None) else p.bands
    if getattr(args, "cell", None):
        targets = []
        for spec in args.cell:
            parts = str(spec).split(":")
            try:
                if len(parts) == 3:
                    band, i, d = parts[0], int(parts[1]), int(parts[2])
                    if band not in p.rank:
                        raise SystemExit(f"未知档位 {band!r}；本 profile 有 {p.bands}")
                    targets.append((band, i, d))
                elif len(parts) == 2:
                    i, d = int(parts[0]), int(parts[1])
                    targets += [(b, i, d) for b in bands]
                else:
                    raise ValueError
            except ValueError:
                raise SystemExit(f"--cell 要写成 档位:主轴:副轴，或省略档位写成 主轴:副轴，"
                                 f"收到 {spec!r}")
        for _b, i, d in targets:
            if not (1 <= i <= 4 and 1 <= d <= 4):
                raise SystemExit(f"坐标越界：{i}/{d}，两根轴都只有 1~4")
            reject_cell(i, d)
        return targets
    return list(p.iter_cells(bands))


def one_band(p, targets):
    """一次撰写只做一个观测等级：等级之间口径不同，越界的表达事后很难改回来。"""
    bands = list(dict.fromkeys(b for b, _i, _d in targets))
    if len(bands) <= 1:
        return targets
    counts = Counter(b for b, _i, _d in targets)
    detail = "、".join(f"{b} {counts[b]} 格" for b in bands)
    raise SystemExit(
        f"一次只写一个观测等级，这次目标跨了 {len(bands)} 个（{detail}）。\n"
        f"用 --band <{'|'.join(p.bands)}> 挑一个：一批里混了等级，写偏了按坐标还能调，"
        "等级本身调不回来。")


def session_targets(p, args):
    """本次要写的格：--cell / --band / 全量，且必须收在一个观测等级内。

    不按「取前几格」截断：写哪些格由人看着 status 的表定，截一段只会总停在固定的前方。
    """
    return one_band(p, cell_targets(p, args))


def plan_briefs(p, targets, csv_path, count, force, seed, style_note):
    """按已有条数补齐每格，返回（题面列表，满格跳过列表）。"""
    counts = read_counts(csv_path)
    briefs, skipped = [], []
    for band, i, d in targets:
        have = 0 if force else counts.get((band, i, d), 0)
        if have >= count:
            skipped.append((band, i, d, have))
            continue
        for k in range(have, count):
            briefs.append(build_brief(p, band, i, d, k, seed, style_note))
    if len(briefs) > SESSION_MAX:
        print(f"! {len(briefs)} 条超过一个观测等级的常规规模（约 20~{SESSION_MAX} 条），"
              "越往后越容易写飘；分几批写，或调小 --count。", file=sys.stderr)
    return briefs, skipped


def seed_of(args):
    """本次运行的种子：没给就抽一个，免得每次重跑都撞出同一批卡。"""
    if getattr(args, "seed", None) is None:
        args.seed = random.randrange(1000, 1000000)
    return args.seed


def batch_of(briefs, size):
    """把同格的题面按 size 切块：一次调用写完一块，省掉重复的 system。"""
    step = max(1, size)
    out = []
    for _key, group in group_by_cell(briefs):
        out += [group[k:k + step] for k in range(0, len(group), step)]
    return out


def group_by_cell(briefs):
    groups = []
    for b in briefs:
        key = (b["band"], b["intrusion"], b["destruction"])
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(b)
    return groups


# ---------------------------------------------------------------------------
# 读写与校验
# ---------------------------------------------------------------------------

def read_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_counts(path):
    counts = Counter()
    for r in read_rows(path):
        try:
            counts[((r["size_category"] or "").strip(),
                    int(r["intrusion"]), int(r["destruction"]))] += 1
        except (KeyError, ValueError):
            continue
    return counts


def cell_of_row(r):
    try:
        return (r["size_category"].strip(), int(r["intrusion"]), int(r["destruction"]))
    except (KeyError, ValueError, AttributeError):
        return None


def clause_of(p, text, pos):
    for m in p.rx_clause.finditer(text):
        if m.start() <= pos < m.end():
            return m.group()
    return text


def spans_of(text, vocab):
    """所有命中，去掉被更长词包含的短命中（江堤里的「江」、大桥里的「桥」）。"""
    raw = [(m.start(), m.end(), w) for w in vocab for m in re.finditer(re.escape(w), text)]
    return [(s, e, w) for s, e, w in raw
            if not any(s2 <= s and e <= e2 and (e2 - s2) > (e - s)
                       for s2, e2, _ in raw)]


def contact_words(p, text, vocab):
    """接触句里出现的对象词：同一分句里既有接触动词、又不是方位/否定。"""
    out = []
    for s, e, w in spans_of(text, vocab):
        if p.rx_qualifier.search(text[e:e + 2]):
            continue
        cl = clause_of(p, text, s)
        if p.rx_loc.search(cl) or p.rx_neg.search(cl):
            continue
        if p.rx_contact.search(cl) and w not in out:
            out.append(w)
    return out


def strip_markers(text):
    """去掉合法标记，剩下的才是写手写的正文。字数、句数只算这一半。"""
    return MARKER_RE.sub("", text or "")


def analyse(p, rows):
    """一次遍历算出档位判定、视角与句子类型。坐标不从文本回推。

    标记内的文本是替换槽，属于别的条目的同一格，不参与越档判定——判的是这一条
    自己写的字。
    """
    vocab = list(p.words) + p.vague
    out = []
    for n, r in enumerate(rows, 2):
        band = (r.get("size_category") or "").strip()
        raw = (r.get("text") or "").strip()
        text = strip_markers(raw)
        try:
            i, d = int(r["intrusion"]), int(r["destruction"])
        except (KeyError, ValueError):
            i = d = None
        words = contact_words(p, text, vocab)
        objects = [w for w in words if w in p.words]
        rec = {
            "line": n, "band": band, "text": raw, "plain": text, "i": i, "d": d,
            "words": words,
            "contact": objects,
            "vague": [w for w in words if w in p.vague],
            "banned": [w for w in p.banned if w in text],
            "closing": [w for w in POSITION_BANNED if w in text],
            "over": [w for w in objects if band in p.rank and band not in p.words[w]],
            "angle": classify_angle(p, text),
            "marks": [(m.group(1), m.group(2)) for m in MARKER_RE.finditer(raw)],
        }
        rec["kind"] = row_kind(p, rec)
        out.append(rec)
    return out


def classify_angle(p, text):
    """按开口的说明词估一下这条是从哪个视角写的，只供人工校正时参考。

    新 profile 的视角不再带候选词表，说明里那几个具体名词（手机、读数、理赔窗口）
    才是能对上的东西；都对不上就返回空，不硬猜。
    """
    for a in p.angles:
        words = a["cue_list"] or tuple(
            w for w in re.split(r"[，。：；、（）\s]+", a["note"]) if len(w) >= 2)
        if words and any(w in text for w in words):
            return a["label"]
    return ""


def row_kind(p, rec):
    """「观测/通报」还是「接触」，只供格内画像用（不判坐标）。"""
    if p.rx_observe.search(rec["text"]) and not rec["contact"]:
        return "观测"
    if rec["contact"]:
        return "接触"
    return "其他"


def structural_issues(p, rows, first_line=2):
    issues = []
    if not rows:
        return [(0, "CSV 没有数据行")]
    missing = [c for c in p.columns if c not in rows[0]]
    if missing:
        return [(0, f"表头缺列：{'、'.join(missing)}")]
    for n, r in enumerate(rows, first_line):
        raw = (r.get("text") or "").strip()
        band = (r.get("size_category") or "").strip()
        if not raw:
            issues.append((n, "text 为空"))
            continue
        if "," in raw or "\n" in raw:
            issues.append((n, "含半角逗号或换行"))
        text = strip_markers(raw)
        if "[" in text or "]" in text:
            issues.append((n, "括号不配对，或标记不是 [a-e]:编号:文本 的形状"))
        residue = text
        for ph in KNOWN_PLACEHOLDERS:
            residue = residue.replace(ph, "")
        if "{" in residue or "}" in residue:
            issues.append((n, f"含未知占位符（只认 {'、'.join(KNOWN_PLACEHOLDERS)}）"))
        if not (p.text_min <= len(text) <= p.text_max):
            issues.append((n, f"字数 {len(text)} 不在 {p.text_min}~{p.text_max}"
                              + (f"（不含标记；标记另占 {len(raw) - len(text)} 字）"
                                 if len(raw) != len(text) else "")))
        sentences = len(re.findall(r"[。！？]", text))
        if not (p.sentence_min <= sentences <= p.sentence_max):
            issues.append((n, f"{sentences} 句，要 {p.sentence_min}~{p.sentence_max} 句"))
        summary = (r.get("summary") or "").strip()
        if summary and not (SUMMARY_MIN <= len(summary) <= p.summary_max):
            issues.append((n, f"summary {len(summary)} 字，要 {SUMMARY_MIN}~{p.summary_max} 字"))
        if band not in p.rank and band not in EXTRA_CATEGORIES \
                and band not in size_categories():
            issues.append((n, f"未知档位 {band!r}"))
        try:
            i, d = int(r["intrusion"]), int(r["destruction"])
        except (KeyError, ValueError):
            issues.append((n, "坐标不是整数"))
            continue
        if not (1 <= i <= 4 and 1 <= d <= 4):
            issues.append((n, f"坐标越界 {i}/{d}"))
        elif band in p.rank:
            try:
                if abs(float(r.get("step") or 0) - p.default_step(i, d)) > 1e-6:
                    issues.append((n, f"step {r.get('step')} 与坐标默认值 {p.default_step(i, d):g} 不符"))
            except ValueError:
                issues.append((n, "step 不是数字"))
    return issues


def draft_row(p, band, i, d, text, summary=""):
    return {"size_category": band, "intrusion": str(i), "destruction": str(d),
            "text": text, "style": "", "step": f"{p.default_step(i, d):g}",
            "summary": summary}


def validate_draft(p, band, i, d, text, summary, seen):
    """单条草稿的全部判据。返回（错误列表，提醒列表，画像记录）。"""
    text = (text or "").strip()
    row = draft_row(p, band, i, d, text, summary)
    errors = [why for _n, why in structural_issues(p, [row])]
    rec = analyse(p, [row])[0]
    if rec["over"]:
        errors.append("越档：" + "、".join(f"{w} 至少要 {'/'.join(p.words[w])}"
                                          for w in rec["over"]))
    if rec["banned"]:
        errors.append("禁用词：" + "、".join(rec["banned"]))
    if rec["closing"]:
        errors.append("收束句或位置词：" + "、".join(rec["closing"])
                      + "（把判据挤到结尾，写出来必然是总结句）")
    warns = []
    if rec["vague"]:
        warns.append("模糊词不能承担尺度：" + "、".join(rec["vague"]))
    if text in seen:
        errors.append("与已有条目重复")
    if not rec["contact"] and p.rx_contact.search(text) and not p.rx_observe.search(text):
        warns.append("这一句没有可判档的地貌接触，尺度无从复核")
    return errors, warns, rec


def describe_rec(p, rec):
    bits = [f"{len(rec['plain'])} 字", rec["kind"]]
    if rec["contact"]:
        bits.append("对象 " + "、".join(rec["contact"][:3]))
    if rec["angle"]:
        bits.append("视角 " + rec["angle"])
    if rec.get("marks"):
        bits.append("标记 " + "、".join(f"{k}:{n}" for k, n in rec["marks"]))
    return " ｜ ".join(bits)


# ---------------------------------------------------------------------------
# 落盘
# ---------------------------------------------------------------------------

def ensure_parent(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def backup(path):
    dst = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copyfile(path, dst)
    return dst


def write_rows(path, rows):
    ensure_parent(path)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(COLUMNS), lineterminator="\r\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLUMNS})


def append_rows(p, csv_path, new_rows, apply=False):
    """所有模式共用的落盘口：先全量复核，再留备份整表重写。"""
    rows = read_rows(csv_path)
    seen = {(r.get("text") or "").strip() for r in rows}
    kept, rejected, dup = [], [], 0
    for n, r in enumerate(new_rows, 1):
        cell = cell_of_row(r)
        if not cell:
            rejected.append((n, r.get("text", ""), ["坐标不合法"]))
            continue
        band, i, d = cell
        text = (r.get("text") or "").strip()
        if text in seen:
            dup += 1
            continue
        errors, _warns, _rec = validate_draft(p, band, i, d, text,
                                              str(r.get("summary") or ""), seen)
        if errors:
            rejected.append((n, text, errors))
            continue
        kept.append(r)
        seen.add(text)
    if not kept:
        return 0, rejected, dup, None
    bak = None
    if apply:
        ensure_parent(csv_path)
        if Path(csv_path).exists():
            bak = backup(csv_path)
        write_rows(csv_path, rows + kept)
    return len(kept), rejected, dup, bak


# ---------------------------------------------------------------------------
# AI 接入
# ---------------------------------------------------------------------------

def ai_client():
    """仓库里已配置的后端；没配返回 (None, "")，不影响其它子命令。"""
    try:
        from core.ai import get_ai_client
    except Exception as exc:                                     # noqa: BLE001
        print(f"! 读不到 core.ai（{type(exc).__name__}: {exc}），AI 模式不可用。", file=sys.stderr)
        return None, ""
    try:
        client, name = get_ai_client()
    except Exception as exc:                                     # noqa: BLE001
        print(f"! AI 客户端初始化失败（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return None, ""
    return client, (name or "")


def complete(client, messages, temperature=0.8):
    chunks = []
    for chunk in client.generate_stream(messages, temperature=temperature):
        if chunk:
            chunks.append(chunk)
    return "".join(chunks)


def _card_lines(p, brief):
    """一张卡的锚点与方向：强锚点在前，方向在后，顺序就是写的时候该看的顺序。"""
    head = [f"- {p.craft['part_label']}：{brief['part_display']}"]
    if brief["posture"]:
        posture = f"- 姿势：{brief['posture']}"
        if brief["posture_limit"]:
            posture += f"（{brief['posture_limit']}）"
        head.append(posture)
    tail = [f"- 动作类型：{brief['action_mode']}。{action_hint(brief['action_mode'])}",
            f"- {p.craft['reach_label']}：{_reach_line(brief)}"]
    tail.append(f"- 视角：{_angle_line(brief, limit=5)}")
    return head, tail


def build_messages(p, briefs, avoid=(), rejects=()):
    """把一组同格的卡翻成模型指令。

    档位、术语、规则与输出格式放 system，卡放 user：`briefs` 只有一项时是单条题面，
    多于一项时一次写一组，每条各跟一张卡。强锚点只有着重部位（含跟它一起给出的衣着）
    和给出的姿势；动作只给类型，表现手法、视角与可接触范围都不替写手把句子写完。
    """
    b0 = briefs[0]
    n = len(briefs)
    system_lines = [
        f"你在为「{p.title}」题材写短句。这个题材里，主体是{p.subject}。",
        "",
        f"### {p.band_label}：{b0['band']}"
        + (f"（{b0['band_display']}）" if b0["band_display"] else ""),
        b0["band_can"],
    ]
    if b0["band_anchor"]:
        system_lines.append(f"这一档的{size_anchor_line(b0['band_anchor'])}")
    system_lines += [
        "",
        "## 术语",
        *(f"- {g}" for g in b0["glossary"]),
        "",
        "## 规则",
        *(f"- {r}" for r in b0["rules"]),
        "",
        "## 输出",
        (f"只输出一个 JSON 数组，只含 {n} 个对象（按卡的顺序，一条一个）：" if n > 1
         else "只输出一个 JSON 数组，只含 1 个对象："),
        f'[{{"text": "正文", "summary": "{SUMMARY_MIN}~{p.summary_max} 字短标签"}}]',
        "不要输出数组以外的解释，不要代码块。",
    ]
    system = "\n".join(system_lines)

    cards = [_card_lines(p, b) for b in briefs]
    if n == 1:
        head, tail = cards[0]
        user_lines = ["## 强锚点（必须照做）", *head, "", "## 写作方向", *tail]
    else:
        user_lines = [f"## 每条一张卡（{n} 条，一条一卡，按顺序写，不要合并）"]
        for k, (head, tail) in enumerate(cards, 1):
            if k > 1:
                user_lines.append("")
            user_lines += [f"### 第 {k} 条", *head, *tail]
    user_lines += [
        "",
        "## 可接触范围（写到接触时用）",
        "- 这是描写里允许主体接触的物体范围，不是动作清单，也不是要求这一条必须接触。",
    ]
    if all(b["action_mode"] == "静态" for b in briefs):
        user_lines.append(("- 这条是静态：不要为了用上范围而硬加接触。" if n == 1
                           else "- 这组都是静态：不要为了用上范围而硬加接触。"))
    user_lines += [f"- {line}" for line in _touch_lines(p, b0, limit=10)]
    if avoid:
        user_lines.append("同组已有条目，不要重复它们的意思与开头：")
        user_lines += [f"- {t}" for t in avoid[:8]]
    if rejects:
        user_lines.append("上一轮不合格的原因，这次必须避开：")
        user_lines += [f"- {r}" for r in rejects[:8]]
    if n == 1:
        user_lines.append("按上面的格式写 1 条。")
    else:
        user_lines.append(f"上面 {n} 张卡各写 1 条，共 {n} 条；"
                          "彼此的处境与观察者要能看出差别。")

    if b0["style_note"]:
        system += "\n\n## 风格附加要求\n" + b0["style_note"].strip()
    return [{"role": "system", "content": system},
            {"role": "user", "content": "\n".join(user_lines)}]


#: 模型把自我检查当正文交上来的痕迹。命中的候选一律丢弃，不落盘——
#: 一条泄漏进 CSV 就会污染整批语料，比少一条贵得多。
LEAK_RE = re.compile(
    r"(?:\bCard\s*\d|\bLet me\b|\bHmm\b|\bRevise\b|\bverify\b|\bexplicit\b"
    r"|\bI'll\b|\bLet's\b|good,)", re.I)


def looks_like_leak(text):
    """正文是否其实是模型的思考过程，或整段没解析开的 JSON。"""
    t = (text or "").strip()
    if not t:
        return True
    if t[0] in "[{" or t.endswith('"}]'):
        return True
    return bool(LEAK_RE.search(t))


def parse_response(response, count=3):
    """从模型输出里抠出候选。JSON 失败时退回按行切，尽量不让生成流程断掉。

    解析出来的每条都过一遍泄漏过滤：模型偶尔会把「第几张卡用到哪个部位」这种
    自我检查写进 text，或者干脆把整个数组塞进一个 text 字段里。这类候选直接跳过。
    """
    text = (response or "").strip()
    if not text:
        return []
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    body = fenced.group(1) if fenced else text
    start, end = body.find("["), body.rfind("]")
    if start != -1 and end > start:
        raw = body[start:end + 1]
        for attempt in (raw, re.sub(r",\s*([}\]])", r"\1", raw)):
            try:
                data = json.loads(attempt)
            except json.JSONDecodeError:
                continue
            items = []
            for d in data:
                if isinstance(d, dict):
                    t = str(d.get("text", "")).strip()
                    if t and not looks_like_leak(t):
                        items.append({"text": t, "summary": str(d.get("summary", "")).strip()})
                elif isinstance(d, str) and d.strip() and not looks_like_leak(d):
                    items.append({"text": d.strip(), "summary": ""})
            if items:
                return items[:count]
    # 退化：一行一条，去掉常见编号与引号
    items = []
    for line in body.splitlines():
        s = re.sub(r"^\s*(?:[-*·]|\d+[.、)]|[①-⑨])\s*", "", line).strip().strip('",')
        if len(s) >= 4 and not s.startswith("{") and not looks_like_leak(s):
            items.append({"text": s, "summary": ""})
    return items[:count]


def generate(p, client, briefs, avoid=(), rejects=(), temperature=0.8):
    """调一次模型，返回解析出的候选（未校验）；briefs 是一组同格的卡。"""
    messages = build_messages(p, briefs, avoid=avoid, rejects=rejects)
    return parse_response(complete(client, messages, temperature), len(briefs))


# ---------------------------------------------------------------------------
# 子命令：出题 / 收卷 / 进度
# ---------------------------------------------------------------------------

def cmd_plan(args, p):
    seed = seed_of(args)
    targets = session_targets(p, args)
    briefs, skipped = plan_briefs(p, targets, args.csv,
                                  args.count, args.force, seed, _style_note(args))
    groups = group_by_cell(briefs)
    if not briefs:
        print("没有要出的题：所有目标格都已写满（--force 可强行重出）。")
        return 0
    mode_names = "、".join(p.craft["action_modes"][lv] for lv in range(1, 5))
    intro = (f"每条一张卡：着重部位（可带衣着/姿势）＋ 动作类型（{mode_names}）"
             "＋ 表现手法＋视角。只有着重部位和给出的姿势/衣着是强锚点；"
             "动作类型由破坏性定，管用多少力、力落在多大范围、留下什么，具体动作自己挑；"
             "表现手法定怎么写，不定写到哪。"
             "档位只给缩比锚（这一档多大），"
             "可接触范围只限定"
             "描写里允许主体碰到的东西，不是必须碰到。落盘时坐标由工具填，不用管。")
    md = [f"# {p.title} 题面（{len(briefs)} 条 · profile={p.name} · seed={seed}）", "",
          intro, ""]
    md += [render_cell_md(p, g, n, len(groups)) for n, (_key, g) in enumerate(groups, 1)]
    text = "\n".join(md)

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        md_path, jsonl_path = out / "briefs.md", out / "briefs.jsonl"
        md_path.write_text(text + "\n", encoding="utf-8")
        with open(jsonl_path, "w", encoding="utf-8", newline="\n") as f:
            for b in briefs:
                f.write(json.dumps(b, ensure_ascii=False) + "\n")
        print(f"题面 {len(briefs)} 条 → {md_path}\n           {jsonl_path}")
    else:
        print(text)
    if skipped:
        print(f"已满，跳过 {len(skipped)} 格："
              + "、".join(f"{b}:{i}:{d}({n})" for b, i, d, n in skipped[:8])
              + ("…" if len(skipped) > 8 else ""))
    return 0


def cmd_check(args, p):
    rows = read_rows(args.csv)
    if not rows:
        if args.json:
            print(json.dumps({"summary": {"profile": p.name, "条目": 0, "空": True},
                              "cells": {}}, ensure_ascii=False, indent=2))
        else:
            print(f"profile={p.name}  csv={args.csv}")
            print("CSV 还没有数据。先用 plan/write/fill 产出，或用 --csv 指向已有语料。")
        return 0
    issues = structural_issues(p, rows)
    recs = analyse(p, rows)
    canon = [r for r in recs if r["band"] in p.rank]
    detail = args.verbose or args.all

    kinds = Counter(r["kind"] for r in recs)
    clean = sum(1 for r in canon if r["contact"] and not r["over"] and not r["vague"])
    no_obj = sum(1 for r in canon if not r["words"])
    over = [r for r in recs if r["over"]]
    vague_hit = [r for r in recs if r["vague"] and not r["over"]]
    banned_hit = [r for r in recs if r["banned"]]
    closing_hit = [r for r in recs if r["closing"]]
    extra = Counter(r["band"] for r in recs if r["band"] not in p.rank)

    by_cell = defaultdict(list)
    for r in recs:
        by_cell[(r["band"], r["i"], r["d"])].append(r)

    dups = []
    for cell, group in by_cell.items():
        seen_obj, seen_head = {}, {}
        for r in group:
            key = tuple(sorted(r["contact"]))
            head = r["text"][:6]
            if key and key in seen_obj:
                dups.append((cell, seen_obj[key], r["line"], "接触对象相同"))
            elif head and head in seen_head:
                dups.append((cell, seen_head[head], r["line"], "开头相同"))
            if key:
                seen_obj.setdefault(key, r["line"])
            if head:
                seen_head.setdefault(head, r["line"])

    flat_angle = []
    for cell, group in by_cell.items():
        angles = [r["angle"] for r in group if r["angle"]]
        if len(group) >= 3 and len(angles) == len(group) and len(set(angles)) == 1:
            flat_angle.append((cell, angles[0]))

    missing = [(b, i, d) for b, i, d in p.iter_cells()
               if sum(1 for r in recs if (r["band"], r["i"], r["d"]) == (b, i, d)) < args.count]
    dead = sum(1 for r in recs if r["band"] in p.rank and (r["i"], r["d"]) in EXCLUDED_CELLS)

    summary = {
        "profile": p.name,
        "条目": len(rows),
        "结构问题": len(issues),
        "接触句干净": clean,
        "接触句无对象词": no_obj,
        "句类": dict(kinds),
        "越档": len(over),
        "模糊词承担尺度": len(vague_hit),
        "禁用词": len(banned_hit),
        "收束句或位置词": len(closing_hit),
        "同格重复": len(dups),
        "视角单一": len(flat_angle),
        "不足目标的格": len(missing),
        "挖掉的格": dead,
        "非档位条目": dict(extra),
    }
    failed = bool(issues or over or banned_hit)

    if args.json:
        print(json.dumps({
            "summary": summary,
            "seed": args.seed,
            "issues": [{"line": n, "why": w} for n, w in issues],
            "over": [{"line": r["line"], "band": r["band"], "words": r["over"],
                      "text": r["text"]} for r in over],
            "vague": [{"line": r["line"], "band": r["band"], "words": r["vague"],
                       "text": r["text"]} for r in vague_hit],
            "banned": [{"line": r["line"], "words": r["banned"], "text": r["text"]}
                       for r in banned_hit],
            "closing": [{"line": r["line"], "words": r["closing"], "text": r["text"]}
                        for r in closing_hit],
            "dups": [{"cell": list(c), "a": a, "b": b, "why": w} for c, a, b, w in dups],
            "flat_angle": [{"cell": list(c), "angle": g} for c, g in flat_angle],
            "missing": [{"band": b, "intrusion": i, "destruction": d} for b, i, d in missing],
            "cells": {f"{c[0]}:{c[1]}:{c[2]}": [
                {"line": r["line"], "kind": r["kind"], "contact": r["contact"],
                 "angle": r["angle"], "len": len(r["text"]), "text": r["text"]}
                for r in g] for c, g in by_cell.items()},
        }, ensure_ascii=False, indent=2))
        return 1 if failed else 0

    print(f"profile={p.name}"
          + ("；非档位条目 " + "、".join(f"{k} {v}" for k, v in sorted(extra.items()))
             if extra else ""))
    print(f"读入 {len(rows)} 条，结构：{len(issues)} 处问题")
    print(f"档位：可判且无越档/模糊词 {clean}，无可判对象 {no_obj}，越档 {len(over)}，"
          f"模糊词代替尺度 {len(vague_hit)}，禁用词 {len(banned_hit)}，"
          f"收束句/位置词 {len(closing_hit)}")
    print(f"句类：接触 {kinds['接触']}、观测 {kinds['观测']}、其他 {kinds['其他']}")
    print(f"重复：同格重复 {len(dups)} 处，视角单一 {len(flat_angle)} 格")
    rank_entries = sum(1 for r in recs if r["band"] in p.rank)
    total_target = len(p.bands) * len(VALID_CELLS) * args.count
    uneven = "；总数够但分布不均" if missing and rank_entries >= total_target else ""
    print(f"覆盖：{len(missing)} 格不足 {args.count} 条"
          f"（档位条目 {rank_entries - dead} / {total_target}）{uneven}")
    if dead:
        print(f"  另有 {dead} 条落在已挖掉的 (1,4)/(4,1) 上，不计入覆盖")
    print("隐坐标：-v 的格内画像里带每条的主轴/副轴与场景卡，只供人工校正；"
          "改写用 apply --set 行=主轴:副轴 或 --by 行=部位:判据")

    def section(title, items, fmt):
        if not items:
            return
        print(f"\n== {title} ==")
        for it in items:
            print("  " + fmt(it))

    section("结构问题", issues, lambda it: f"行{it[0]} {it[1]}")
    section("越档", over, lambda r: f"行{r['line']} [{r['band']}] "
            + "、".join(f"{w}→{'/'.join(p.words[w])}" for w in r["over"])
            + (f"\n      {r['text']}" if detail else ""))
    section("模糊词代替尺度", vague_hit, lambda r: f"行{r['line']} [{r['band']}] "
            f"{'、'.join(r['vague'])}" + (f"\n      {r['text']}" if detail else ""))
    section("收束句或位置词", closing_hit, lambda r: f"行{r['line']} {'、'.join(r['closing'])}"
            + (f"\n      {r['text']}" if detail else ""))
    section("禁用词", banned_hit, lambda r: f"行{r['line']} {'、'.join(r['banned'])}"
            + (f"\n      {r['text']}" if detail else ""))
    section("同格重复", dups, lambda d: f"{d[0][0]}:{d[0][1]}:{d[0][2]} 行{d[1]} / 行{d[2]} {d[3]}")
    section("视角单一", flat_angle, lambda a: f"{a[0][0]}:{a[0][1]}:{a[0][2]} 全是「{a[1]}」")

    if detail:
        problem_cells = {cell for cell, group in by_cell.items()
                         if any(r["over"] or r["vague"] or r["banned"] for r in group)}
        problem_cells |= {d[0] for d in dups}
        problem_cells |= {a[0] for a in flat_angle}
        order = sorted(by_cell, key=lambda c: (c[0] not in p.rank, p.rank.get(c[0], 0), c[1], c[2]))
        selected = order if args.all else [c for c in order if c in problem_cells]
        print("\n== 格内画像 ==")
        if not selected:
            print("  没有需要展开的格；--all 查看全部。")
        else:
            print(f"  seed={args.seed}；隐坐标与场景卡只在这里出现，供人工校正；"
                  "卡按组内顺序回放，跟正文不必一一对应。")
            for cell in selected:
                group = by_cell[cell]
                print(f"\n{cell[0]}:{cell[1]}:{cell[2]}  {len(group)} 条 — {p.grid_text(cell[1], cell[2])}")
                if cell[0] in p.rank:
                    salt = p.rank[cell[0]] * 16 + (cell[1] - 1) * 4 + (cell[2] - 1) + args.seed
                    for k in range(len(group)):
                        card = p.craft_of(cell[1], cell[2], k, salt)
                        extra = ""
                        if card["posture"]:
                            extra = f"　姿势 {card['posture']}"
                        print(f"    卡{k + 1} {card['part_display']}·{card['action_mode']}"
                              f" → {card['reach_line']}{extra}")
                for r in group:
                    flag = "  ← 越档" if r["over"] else ""
                    print(f"  行{r['line']:>3} {describe_rec(p, r)}{flag}")
                    print(f"        {r['text']}")
        if missing:
            show = missing if args.all else missing[:12]
            print("\n== 不足目标的格 ==")
            print("  " + "、".join(f"{b}:{i}:{d}" for b, i, d in show))
            if len(missing) > len(show):
                print(f"  …另有 {len(missing) - len(show)} 格；--all 列出全部")

    return 1 if failed else 0


def cmd_status(args, p):
    counts = read_counts(args.csv)
    total_target = len(p.bands) * len(VALID_CELLS) * args.count
    cells = list(p.iter_cells())
    done = sum(1 for cell in cells if counts.get(cell, 0) >= args.count)
    overfull = sum(1 for cell in cells if counts.get(cell, 0) > args.count)
    entries = sum(counts.get(cell, 0) for cell in cells)
    dead = sum(counts.get((b, i, d), 0) for b in p.bands for i, d in EXCLUDED_CELLS)
    other = sum(counts.values()) - entries - dead
    print(f"profile={p.name}  csv={args.csv}")
    print(f"列 d1~d4：{p.axis_d['label']}；行 i1~i4：{p.axis_i['label']}")
    print(f"{'':<11}" + "".join(f"  d{d}" for d in range(1, 5)))
    for b in p.bands:
        for i in range(1, 5):
            row = ""
            for d in range(1, 5):
                row += ("   ·" if (i, d) in EXCLUDED_CELLS
                        else f"  {counts.get((b, i, d), 0):>2}")
            print(f"{b:<11}i{i} {row}")
    cells_total = len(p.bands) * len(VALID_CELLS)
    print(f"\n满格 {done}/{cells_total}；条目 {entries}/{total_target}；超填 {overfull} 格"
          + (f"；另有非档位条目 {other}" if other else "")
          + (f"；挖掉的格（·）里还留着 {dead} 条" if dead else ""))
    gaps = [(b, i, d, args.count - counts.get((b, i, d), 0))
            for b, i, d in p.iter_cells() if counts.get((b, i, d), 0) < args.count]
    if gaps:
        gaps.sort(key=lambda g: (-g[3], p.rank[g[0]]))
        print("缺口最大：" + "、".join(f"{b}:{i}:{d}(缺{n})" for b, i, d, n in gaps[:6]))
    print("补哪一格就 --cell 档位:主轴:副轴；· 是 (1,4)/(4,1)，两根轴的端点互相否定，不再出题。")
    return 0


def cmd_doctor(args, p):
    print(f"profile={p.name}（{p.source}）")
    print(f"题材「{p.title}」主体「{p.subject}」；{p.band_label} {len(p.bands)} 档：{'、'.join(p.bands)}")
    print(f"地貌词 {len(p.words)}；模糊词 {len(p.vague)}；禁用词 {len(p.banned)}；"
          f"接触方式 {len(p.touch)} 条")
    covered = sum(1 for i, d in VALID_CELLS if (i, d) in p.grid)
    print(f"格释义 {covered}/{len(VALID_CELLS)} 格（每级 14 格，(1,4)/(4,1) 不写）；"
          f"视角池 {len(p.angles)} 个")
    sizes = "/".join(str(len(p.craft["parts"][lv])) for lv in range(1, 5))
    print(f"  场景卡·{p.craft['part_label']:<6} 每级 {sizes} 词")
    modes = "、".join(f"d{lv} {mode}" for lv, mode in sorted(p.craft["action_modes"].items()))
    print(f"  动作类型：{modes}")
    for lv, variants in sorted(p.craft["action_variants"].items()):
        for i, name in sorted(variants.items()):
            print(f"    (i{i},d{lv}) → {name}")
    for part, detail in p.craft["part_details"].items():
        bits = []
        if detail["wear"]:
            bits.append("衣着 " + "、".join(detail["wear"]))
        if detail["posture"]:
            bits.append("姿势 " + "、".join(x[0] for x in detail["posture"]))
        print(f"  部位修饰·{part}：" + "；".join(bits))
    counts = {lv: len(p.craft["reach_pairs"][lv]) for lv in range(1, 5)}
    if len(set(counts.values())) == 1:
        print(f"  场景卡·{p.craft['reach_label']} {counts[1]} 条，各档共用")
    else:
        sizes = "/".join(str(counts[lv]) for lv in range(1, 5))
        print(f"  场景卡·{p.craft['reach_label']} 每级 {sizes} 条")
    for h in p.touch:
        scope = {"upper": "可碰高一档的对象", "contact": "只碰本档", "": "对象随接触部位"}[h["scope"]]
        print(f"  接触·{h['label']}：{scope}" + (f"｜{h['can']}" if h["can"] else ""))
    if getattr(args, "craft", False):
        print(f"\n{p.craft['part_label']}")
        for lv in range(1, 5):
            print(f"  {lv}: {'、'.join(p.craft['parts'][lv]) or '（空，回退相邻级）'}")
        print("\n动作类型（按副轴；介入度变体写在括号里）")
        for lv in range(1, 5):
            variants = p.craft["action_variants"].get(lv) or {}
            tail = "".join(f"（i{i}→{name}）" for i, name in sorted(variants.items()))
            print(f"  {lv}: {p.craft['action_modes'][lv]}{tail}")
        if p.craft["part_details"]:
            print("\n部位修饰（衣着/姿势只在对应部位出现时给）")
            for part, detail in p.craft["part_details"].items():
                print(f"  {part}:")
                if detail["wear"]:
                    print(f"    衣着：{'、'.join(detail['wear'])}"
                          f"（每 {detail['wear_every']} 条给一次）")
                if detail["posture"]:
                    for label, limit in detail["posture"]:
                        print(f"    姿势：{label}" + (f" —— {limit}" if limit else ""))
                    print(f"    （每 {detail['posture_every']} 条给一次）")
        print(f"\n{p.craft['reach_label']}")
        for lv in range(1, 5):
            print(f"  {lv}:")
            for gen, tx in p.craft["reach_pairs"][lv]:
                print(f"    {gen or '未标手法'}：{tx}")
    bad = profile_problems(p)
    for band in p.bands:
        ok, near, upper, blocked = p.contact_budget(band)
        print(f"  {band:<11} 可接触 {len(ok):>2} 词 / ±1 档 {len(near):>2} 词"
              f"（其中高于本档 {len(upper)} 词）"
              f" / 够不着 {len(blocked):>2} 词")
    try:
        from persistence.quip_repo import QuipRepo
        mismatch = [(i, d) for i in range(1, 5) for d in range(1, 5)
                    if abs(QuipRepo.default_step(i, d) - p.default_step(i, d)) > 1e-9]
        if mismatch:
            bad.append(f"step 矩阵与 QuipRepo 不一致：{mismatch[:4]}")
        else:
            print("step 矩阵与 persistence.quip_repo.QuipRepo.default_step 一致")
    except Exception as exc:                                     # noqa: BLE001
        print(f"step 矩阵未与 QuipRepo 比对（{type(exc).__name__}: {exc}），按 profile 自带表")
    # 档位的 key 与区间是主程序的契约：运行期按身高只会落到 SIZE_CATEGORIES 这几个 key 上。
    # 但覆盖范围不是契约——只写用得上的几档是常态，缺的档位只是没有语料。
    try:
        from core.logic.sizing import SIZE_CATEGORIES, SIZE_DISPLAY
    except Exception as exc:                                     # noqa: BLE001
        print(f"档位未与 core.logic.sizing 比对（{type(exc).__name__}: {exc}）")
    else:
        unknown = [b for b in p.bands if b not in SIZE_CATEGORIES]
        absent = [b for b in SIZE_CATEGORIES if b not in p.bands]
        off = [f"{b}（{p.size_display(b) or '未写'} / 主程序 {SIZE_DISPLAY[b]}）"
               for b in p.bands if b in SIZE_DISPLAY and p.size_display(b) != SIZE_DISPLAY[b]]
        if unknown:
            bad.append(f"档位 {unknown} 主程序不认，只会被当成多余分类；"
                       f"按身高能落到的是 {SIZE_CATEGORIES}")
        if off:
            bad.append("区间与 core.logic.sizing.SIZE_DISPLAY 不一致：" + "、".join(off))
        if not (unknown or off):
            print(f"档位与 core.logic.sizing 一致：{'、'.join(p.bands)}")
        # 缺档位不报错：一个题材往往只写自己用得上的尺寸段，写满五档不是目标
        if absent:
            print(f"未覆盖 {'、'.join(absent)}：这些身高段没有语料，不影响其余档位")
        if p.uncovered_words:
            n = sum(len(v) for v in p.uncovered_words.values())
            detail = "、".join(f"{b} {len(v)} 处" for b, v in p.uncovered_words.items())
            print(f"landforms 里有 {n} 处标注落在未覆盖的档上（{detail}）："
                  "相关词本题材用不到，可留可删")
    rows = read_rows(args.csv)
    print(f"CSV {args.csv}：{len(rows)} 行；表头 {'OK' if not rows or all(c in rows[0] for c in COLUMNS) else '异常'}")
    if p.notes:
        for k, v in p.notes.items():
            print(f"  · {v}")
    if bad:
        print("\n问题：")
        for b in bad:
            print(f"  - {b}")
        return 1
    print("profile 与代码口径自洽。")
    print(
        "\n注意：本工具的题面按 DeepSeek 调过，也只在 DeepSeek 上验过；"
        "换后端请重看题面。\n"
        "      尚未完全稳定——一到两成条目仍要人手改，偶尔整格被模型的自我检查污染。"
        "别一次跑满整档。"
    )
    return 0


# ---------------------------------------------------------------------------
# 子命令：人写 / AI+人审 / agent 全自动 / 只出提示词
# ---------------------------------------------------------------------------

def _style_note(args):
    path = getattr(args, "style_file", None)
    if not path:
        return ""
    return Path(path).read_text(encoding="utf-8")


def _ask(label="> "):
    try:
        return input(label)
    except EOFError:
        return ""
    except KeyboardInterrupt:
        print()
        return ":q"


def _stdin_is_pipe():
    try:
        return not sys.stdin.isatty()
    except Exception:                                            # noqa: BLE001
        return False


def cmd_write(args, p):
    """人写：一格一格出题，敲完立刻判，判完可以改。"""
    seed = seed_of(args)
    targets = session_targets(p, args)
    briefs, skipped = plan_briefs(p, targets, args.csv, args.count, args.force,
                                  seed, _style_note(args))
    if not briefs:
        print("没有要写的格：都满了（--force 可重出）。")
        return 0
    if skipped:
        print(f"跳过已满 {len(skipped)} 格。")
    print(f"seed={seed}（要复现同一批卡就用 --seed {seed}）")
    seen = {(r.get("text") or "").strip() for r in read_rows(args.csv)}
    groups = group_by_cell(briefs)
    accepted = []
    total = len(briefs)
    n = 0
    quit_early = False
    for _key, group in groups:
        for b in group:
            n += 1
            if n > 1:
                print()
            print(render_cell_text(p, [b], n, total))
            while True:
                raw = _ask("  正文（:s 跳过，:b 重看，:q 保存并退出）> ").strip()
                if raw == ":q":
                    quit_early = True
                    break
                if raw == ":s":
                    print("  · 跳过")
                    break
                if raw == ":b":
                    print(render_cell_text(p, [b], n, total))
                    continue
                if not raw:
                    print("  · 空行跳过（:q 退出）")
                    break
                summary = _ask(f"  summary（{SUMMARY_MIN}~{p.summary_max} 字，回车留空）> "
                               ).strip()[:p.summary_max]
                errors, warns, rec = validate_draft(p, b["band"], b["intrusion"],
                                                    b["destruction"], raw, summary, seen)
                for w in warns:
                    print(f"  ! {w}")
                if errors:
                    print("  ✗ " + "\n  ✗ ".join(errors))
                    if _ask("  仍然收下？[y/N] ").strip().lower() != "y":
                        continue
                else:
                    print("  ✓ " + describe_rec(p, rec))
                accepted.append(draft_row(p, b["band"], b["intrusion"], b["destruction"],
                                          raw.strip(), summary))
                seen.add(raw.strip())
                break
            if quit_early:
                break
        if quit_early:
            break

    if not accepted:
        print("\n没有收下任何条目。")
        return 0
    print(f"\n收下 {len(accepted)} 条：")
    for r in accepted:
        print(f"  「{r['summary']}」{r['text']}")
    if args.apply:
        written, rejected, dup, bak = _commit(p, args.csv, accepted)
        if written:
            print(f"已落盘 {written} 条" + (f"，跳过重复 {dup} 条" if dup else "")
                  + (f"；备份 {Path(bak).name}" if bak else "（新建文件，无旧版可备份）"))
        elif rejected:
            print("没有条目落盘（原因见下）。")
        else:
            print(f"没有条目落盘（{dup} 条与已有条目重复）。" if dup else "没有条目落盘。")
        _print_rejected(rejected)
        return 1 if rejected else 0
    out = Path(args.draft_out or OUT_DIR / f"drafts-{p.name}.jsonl")
    ensure_parent(out)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for r in accepted:
            f.write(json.dumps({"cell": f"{r['size_category']}:{r['intrusion']}:{r['destruction']}",
                                "text": r["text"], "summary": r["summary"]},
                               ensure_ascii=False) + "\n")
    print(f"\n草稿 → {out}（加 --apply 直接落盘，或 append --from-file）")
    return 0


def _commit(p, csv_path, rows):
    """统一落盘：整表复核 + 备份 + 重写。"""
    return append_rows(p, csv_path, rows, apply=True)


def _print_rejected(rejected):
    """把落盘复核拒掉的条目逐条打出来，别让“仍然收下”的条目静默消失。"""
    for n, text, errors in rejected:
        print(f"  ✗ 收下的第 {n} 条未落盘：{'；'.join(errors)}")
        print(f"    {text}")


def cmd_append(args, p):
    """把草稿 JSONL 落盘：每行一条 {cell, text, summary}。"""
    rows = read_rows(args.csv)
    seen = {(r.get("text") or "").strip() for r in rows}
    drafts, rejected, warns, dup = [], [], [], 0
    with open(args.from_file, "r", encoding="utf-8-sig") as f:
        for n, line in enumerate(f, 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            try:
                d = json.loads(s)
            except json.JSONDecodeError:
                raise SystemExit(f"草稿第 {n} 行不是合法 JSON：{s[:40]}")
            cell = str(d.get("cell") or "").strip()
            parts = cell.split(":")
            if len(parts) != 3 or parts[0] not in p.rank:
                raise SystemExit(f"草稿第 {n} 行 cell 要写成 档位:{i}:{d}，收到 {cell!r}")
            band, i, dest = parts[0], int(parts[1]), int(parts[2])
            if not (1 <= i <= 4 and 1 <= dest <= 4):
                raise SystemExit(f"草稿第 {n} 行坐标 {i}/{dest} 越界：两根轴都只有 1~4")
            text = (d.get("text") or "").strip()
            if text in seen:
                dup += 1
                continue
            errors, w, rec = validate_draft(p, band, i, dest, text,
                                            str(d.get("summary") or ""), seen)
            warns += [(n, text, x) for x in w]
            if errors:
                rejected.append((n, text, errors))
                continue
            seen.add(text)
            drafts.append(draft_row(p, band, i, dest, text, str(d.get("summary") or "").strip()))

    for n, text, why in warns:
        print(f"! 草稿第 {n} 行：{why}\n    {text}")
    for n, text, bad in rejected:
        print(f"✗ 草稿第 {n} 行：{'；'.join(bad)}\n    {text}")
    if dup:
        print(f"跳过 {dup} 条与已有条目重复的草稿")
    if not drafts:
        print("没有可落盘的草稿。")
        return 1 if rejected else 0

    print(f"\n待落盘 {len(drafts)} 条：")
    for r in drafts:
        print(f"  「{r['summary']}」{r['text']}")
    if not args.apply:
        print("\ndry-run，加 --apply 落盘。")
        return 0
    written, commit_rejected, dup2, bak = _commit(p, args.csv, drafts)
    if written:
        print(f"已落盘 {written} 条" + (f"，跳过重复 {dup2} 条" if dup2 else "")
              + (f"；备份 {Path(bak).name}" if bak else "；新建文件"))
    elif commit_rejected:
        print("没有条目落盘（原因见下）。")
    else:
        print(f"没有条目落盘（{dup2} 条与已有条目重复）。" if dup2 else "没有条目落盘。")
    _print_rejected(commit_rejected)
    return 1 if (rejected or commit_rejected) else 0


def cmd_prompt(args, p):
    """只出提示词：不调模型，交给别的 agent / 别家模型 / 人自己贴。

    一块对应一格里相邻的几张卡（`--batch` 控制张数）：块里几张卡就要回几条，
    回执按 {cell, text, summary} 一行一条，正好是 append --from-file 认的格式，
    坐标不用人来对。
    """
    seed = seed_of(args)
    targets = session_targets(p, args)
    briefs, _skipped = plan_briefs(p, targets, args.csv, args.count, args.force,
                                   seed, _style_note(args))
    if not briefs:
        print("没有缺口格可出提示词。")
        return 0
    avoid = {}
    for r in read_rows(args.csv):
        cell = cell_of_row(r)
        if cell:
            avoid.setdefault(cell, []).append((r.get("text") or "").strip())
    payload = []
    for batch in batch_of(briefs, args.batch):
        b0 = batch[0]
        cell = (b0["band"], b0["intrusion"], b0["destruction"])
        payload.append({
            "cell": f"{cell[0]}:{cell[1]}:{cell[2]}",
            "ids": [b["id"] for b in batch],
            "messages": build_messages(p, batch, avoid=avoid.get(cell, [])),
        })
    if args.json:
        print(json.dumps({"profile": p.name, "seed": seed, "blocks": len(payload),
                          "briefs": len(briefs), "items": payload},
                         ensure_ascii=False, indent=2))
        return 0
    print(f"seed={seed}；共 {len(payload)} 块 / {len(briefs)} 条"
          f"（每块最多 {args.batch} 条）。回执按 "
          '{"cell": "...", "text": "...", "summary": "..."} 一行一条，攒成文件后 '
          "append --from-file 落盘。\n")
    for item in payload:
        print(f"===== {item['cell']}（{len(item['ids'])} 条）=====")
        for msg in item["messages"]:
            print(f"--- {msg['role'].upper()} ---")
            print(msg["content"])
        print()
    return 0


def _review(p, client, brief, cand, avoid, seen, temperature):
    """人审一条候选：接受 / 编辑 / 重写 / 跳过。返回（落盘行或 None，是否退出）。"""
    cell = (brief["band"], brief["intrusion"], brief["destruction"])
    rejects = []
    while True:
        text = (cand or {}).get("text", "")
        summary = (cand or {}).get("summary", "")
        errors, warns, rec = [], [], None
        if text:
            errors, warns, rec = validate_draft(p, *cell, text, summary, seen)
            print(f"\n  「{text}」")
            for w in warns:
                print(f"  ! {w}")
            if errors:
                print("  ✗ " + "\n  ✗ ".join(errors))
            else:
                print("  ✓ " + describe_rec(p, rec))
        else:
            print("\n  · 这条没有可用候选。")
        choice = _ask("  [a]接受 [e]编辑 [r]重写 [s]跳过 [q]退出 > ").strip().lower()
        if choice == "q":
            return None, True
        if choice == "s":
            print("  · 跳过")
            return None, False
        if choice == "r":
            rejects = list(errors) or ["换一个写法"]
            print("  生成中…（重写 1 条）")
            try:
                cands = generate(p, client, [brief], avoid=avoid, rejects=rejects,
                                 temperature=temperature)
            except Exception as exc:                             # noqa: BLE001
                print(f"  ! 调用失败：{type(exc).__name__}: {exc}")
                cands = []
            cand = cands[0] if cands else None
            continue
        if choice == "e":
            edited = _ask("  改写正文 > ").strip()
            if not edited:
                print("  · 取消编辑，保留当前候选。")
                continue
            cand = {"text": edited,
                    "summary": _ask(f"  summary（{SUMMARY_MIN}~{p.summary_max} 字，"
                                    "回车留空）> ").strip()[:p.summary_max]}
            continue
        if choice != "a":
            print("  · 无效输入：按 a 接受、e 编辑、r 重写、s 跳过、q 退出。")
            continue
        if not text:
            print("  · 没有候选可接受，按 r 重写或 s 跳过。")
            continue
        if errors and _ask("  仍然收下？[y/N] ").strip().lower() != "y":
            continue
        return draft_row(p, *cell, text.strip(), summary), False


def cmd_draft(args, p):
    """AI 写 + 人审：候选逐条过，接受/编辑/重写/跳过。"""
    client, name = ai_client()
    if not client:
        print("没有可用的 AI 后端。用 `prompt` 交出提示词，或先用 `write` 人写。")
        return 2
    seed = seed_of(args)
    targets = session_targets(p, args)
    briefs, _skipped = plan_briefs(p, targets, args.csv, args.count, args.force,
                                   seed, _style_note(args))
    if not briefs:
        print("没有缺口的格。")
        return 0
    by_cell = defaultdict(list)
    for r in read_rows(args.csv):
        cell = cell_of_row(r)
        if cell:
            by_cell[cell].append((r.get("text") or "").strip())
    seen = {(r.get("text") or "").strip() for r in read_rows(args.csv)}
    batches = batch_of(briefs, args.batch)
    print(f"后端 {name or '默认'}；{len(briefs)} 条待写（{len(batches)} 次调用）；"
          f"seed={seed}。\n")

    accepted = []
    quit_early = False
    for n, batch in enumerate(batches, 1):
        b0 = batch[0]
        cell = (b0["band"], b0["intrusion"], b0["destruction"])
        if n > 1:
            print()
        print(render_cell_text(p, batch, n, len(batches)))
        avoid = by_cell.get(cell, []) + [r["text"] for r in accepted
                                         if (r["size_category"], int(r["intrusion"]),
                                             int(r["destruction"])) == cell]
        print(f"  生成中…（{p.title} / {cell[0]}，{len(batch)} 条）")
        try:
            cands = generate(p, client, batch, avoid=avoid,
                             temperature=args.temperature)
        except Exception as exc:                                 # noqa: BLE001
            print(f"  ! 调用失败：{type(exc).__name__}: {exc}")
            return 2
        if len(cands) < len(batch):
            print(f"  ! 只解析出 {len(cands)}/{len(batch)} 条，缺的按 r 重写。")
        for k, b in enumerate(batch):
            if len(batch) > 1:
                print(f"\n  — 第 {k + 1}/{len(batch)} 条 —")
            row, quit_early = _review(p, client, b,
                                      cands[k] if k < len(cands) else None,
                                      avoid, seen, args.temperature)
            if row:
                accepted.append(row)
                seen.add(row["text"])
                avoid.append(row["text"])
            if quit_early:
                break
        if quit_early:
            break

    if not accepted:
        print("\n没有收下任何条目。")
        return 0
    print(f"\n收下 {len(accepted)} 条：")
    for r in accepted:
        print(f"  「{r['summary']}」{r['text']}")
    if args.apply:
        written, rejected, dup, bak = _commit(p, args.csv, accepted)
        if written:
            print(f"已落盘 {written} 条" + (f"，跳过重复 {dup} 条" if dup else "")
                  + (f"；备份 {Path(bak).name}" if bak else ""))
        elif rejected:
            print("没有条目落盘（原因见下）。")
        else:
            print(f"没有条目落盘（{dup} 条与已有条目重复）。" if dup else "没有条目落盘。")
        _print_rejected(rejected)
        return 1 if rejected else 0
    else:
        print("\ndry-run，加 --apply 落盘。")
    return 0


def cmd_fill(args, p):
    """agent 全自动：生成 → 校验 → 带失败原因重试 → 合格入队。"""
    _out = builtins.print

    def say(*a, **k):
        """进度信息；--json 时改走 stderr，别污染 stdout 的 JSON。"""
        _out(*a, **({**k, "file": sys.stderr} if args.json else k))
    # core.ai 初始化时会把失败原因直接打到 stdout，JSON 模式下先截住
    with contextlib.redirect_stdout(sys.stderr) if args.json else contextlib.nullcontext():
        client, name = ai_client()
    if not client:
        if args.json:
            _out(json.dumps({"profile": p.name, "error": "no_ai_backend",
                             "hint": "没有可用的 AI 后端；用 prompt 把提示词交给外部模型"},
                            ensure_ascii=False))
        else:
            say("没有可用的 AI 后端。用 `prompt` 把提示词交给外部模型。")
        return 2
    seed = seed_of(args)
    targets = session_targets(p, args)
    briefs, _skipped = plan_briefs(p, targets, args.csv, args.count, args.force,
                                   seed, _style_note(args))
    if not briefs:
        say("没有缺口的格。")
        return 0
    by_cell = defaultdict(list)
    for r in read_rows(args.csv):
        cell = cell_of_row(r)
        if cell:
            by_cell[cell].append((r.get("text") or "").strip())
    seen = {(r.get("text") or "").strip() for r in read_rows(args.csv)}

    accepted, failed = [], []
    log = [] if args.json else None
    batches = batch_of(briefs, args.batch)
    say(f"后端 {name or '默认'}；{len(briefs)} 条待写（{len(batches)} 次调用）；"
        f"重试上限 {args.retries}；seed={seed}。")
    for batch in batches:
        b0 = batch[0]
        cell = (b0["band"], b0["intrusion"], b0["destruction"])
        avoid = list(by_cell.get(cell, []))
        pending = list(batch)
        rejects = []
        for attempt in range(args.retries + 1):
            if not pending:
                break
            try:
                cands = generate(p, client, pending, avoid=avoid, rejects=rejects,
                                 temperature=args.temperature)
            except Exception as exc:                             # noqa: BLE001
                say(f"  ! {pending[0]['id']} 调用失败：{type(exc).__name__}: {exc}")
                cands = []
            for cand in cands:
                if not pending:
                    break
                errors, warns, rec = validate_draft(p, cell[0], cell[1], cell[2],
                                                    cand["text"], cand["summary"], seen)
                if errors:
                    rejects += errors
                    continue
                b = pending.pop(0)
                row = draft_row(p, cell[0], cell[1], cell[2], cand["text"].strip(),
                                cand["summary"])
                accepted.append(row)
                seen.add(cand["text"].strip())
                avoid.append(cand["text"].strip())
                say(f"  ✓ {len(accepted)}/{len(briefs)} {b['id']} {describe_rec(p, rec)}")
                if log is not None:
                    log.append({"cell": f"{cell[0]}:{cell[1]}:{cell[2]}", "id": b["id"],
                                "text": row["text"], "summary": row["summary"],
                                "attempt": attempt, "warnings": warns})
        for b in pending:
            failed.append({"id": b["id"], "cell": f"{cell[0]}:{cell[1]}:{cell[2]}",
                           "reasons": rejects[:6]})
            say(f"  ✗ {b['id']} 用完 {args.retries + 1} 次机会，跳过")

    written, rejected, dup, bak = 0, [], 0, None
    if accepted and args.apply:
        written, rejected, dup, bak = _commit(p, args.csv, accepted)
        if not args.json:
            if written:
                say(f"\n已落盘 {written} 条" + (f"，跳过重复 {dup} 条" if dup else "")
                    + (f"；备份 {Path(bak).name}" if bak else ""))
            elif rejected:
                say("\n没有条目落盘（原因见下）。")
            else:
                say(f"\n没有条目落盘（{dup} 条与已有条目重复）。" if dup
                    else "\n没有条目落盘。")
            for n, text, errors in rejected:
                say(f"  ✗ 收下的第 {n} 条未落盘：{'；'.join(errors)}")
                say(f"    {text}")
    elif accepted and not args.json:
        say(f"\n合格 {len(accepted)} 条（dry-run，加 --apply 落盘）：")
        for r in accepted:
            say(f"  「{r['summary']}」{r['text']}")
    if args.json:
        _out(json.dumps({"profile": p.name, "seed": seed, "accepted": log, "failed": failed,
                         "rejected": [{"n": n, "text": text, "errors": errors}
                                      for n, text, errors in rejected],
                         "applied": bool(written), "written": written},
                        ensure_ascii=False, indent=2))
    return 1 if (failed or rejected) else 0


# ---------------------------------------------------------------------------
# 子命令：改坐标
# ---------------------------------------------------------------------------

def _format_pool(p, kind, per_level=8):
    """把场景卡词表按等级分行打印，别再挤成一条几十个词的报错。

    手法是一张平铺表，各档内容相同时只列一份，不重复四遍。
    """
    pool = p.craft[kind]
    distinct = []
    for lv in sorted(pool):
        items = list(pool[lv])
        if items and items not in distinct:
            distinct.append(items)
    if len(distinct) == 1:
        shown = "、".join(distinct[0][:per_level])
        return f"  {shown}" + ("…" if len(distinct[0]) > per_level else "")
    lines = []
    for lv in sorted(pool):
        items = list(pool[lv])
        if not items:
            continue
        shown = "、".join(items[:per_level]) + ("…" if len(items) > per_level else "")
        lines.append(f"  {lv}: {shown}")
    return "\n".join(lines)


def parse_set(p, spec):
    """`21=3:2`（只改坐标）或 `21=medium:3:2`（连档位一起改）。"""
    if "=" not in spec:
        raise SystemExit("--set 要写成 行=主轴:副轴 或 行=档位:主轴:副轴，"
                         f"例如 21=3:2 或 21=medium:3:2，收到 {spec!r}")
    lhs, rhs = spec.split("=", 1)
    parts = rhs.split(":")
    try:
        if len(parts) == 2:
            band, i, d = None, int(parts[0]), int(parts[1])
        elif len(parts) == 3:
            band, i, d = parts[0], int(parts[1]), int(parts[2])
        else:
            raise ValueError
        line = int(lhs)
    except ValueError:
        raise SystemExit("--set 要写成 行=主轴:副轴 或 行=档位:主轴:副轴，"
                         f"例如 21=3:2 或 21=medium:3:2，收到 {spec!r}")
    if band is not None and band not in p.rank:
        raise SystemExit(f"未知档位 {band!r}；本 profile 有 {p.bands}")
    if not (1 <= i <= 4 and 1 <= d <= 4):
        raise SystemExit(f"坐标越界：{i}/{d}，两根轴都只有 1~4")
    return line, band, i, d


def parse_by(p, spec):
    """`21=后背:成片地坏`：用场景卡里的部位词反查介入度，空段表示这一轴不改。"""
    if "=" not in spec:
        raise SystemExit("--by 要写成 行=部位:判据，例如 21=后背:成片地坏")
    lhs, rhs = spec.split("=", 1)
    part_word, _, cons_word = rhs.partition(":")
    try:
        line = int(lhs)
    except ValueError:
        raise SystemExit(f"--by 的行号不是整数：{spec!r}")
    i = d = None
    if part_word.strip():
        word = part_word.strip()
        levels = (p.levels_of("parts", word, exact_only=True)
                  or p.levels_of("parts", word))
        if not levels:
            raise SystemExit(
                f"「{word}」不在场景卡里。\n"
                f"  {p.craft['part_label']}：\n{_format_pool(p, 'parts')}")
        if len(levels) > 1:
            levels_txt = "、".join(str(x) for x in levels)
            raise SystemExit(f"「{word}」在 {levels_txt} 级都出现，--by 无法判断是哪一级；"
                             "请改用 --set，或换一个只属于一级的词")
        i = levels[0]
    if cons_word.strip():
        word = cons_word.strip()
        # 先按手法短名（「特写」）命中，没有再退到说明全文里找
        levels = p.levels_of("genres", word, exact_only=True) or p.levels_of("consequences", word)
        if not levels:
            raise SystemExit(
                f"「{word}」不在{p.craft['reach_label']}里。可用的手法：\n"
                f"{_format_pool(p, 'genres')}")
        if len(levels) > 1:
            # 手法已收成一张表，各破坏性档共用同一批，按判据反查副轴本就判不出来
            raise SystemExit(f"「{word}」在 {len(levels)} 个破坏性档上都是同一种手法，"
                             "--by 判不出副轴；请用 --set 直接给副轴，"
                             "部位那一段仍可照常写")
        d = levels[0]
    if i is None and d is None:
        raise SystemExit("--by 至少要给部位或判据其中一段")
    return line, i, d


def cmd_apply(args, p):
    """把人工校正后的隐坐标写回 CSV。脚本不猜坐标，只负责改对、校验、留备份。"""
    rows = read_rows(args.csv)
    if not rows:
        raise SystemExit("没有数据行")

    edits = [parse_set(p, s) for s in (args.set or [])]
    for spec in (args.by or []):
        line, i, d = parse_by(p, spec)
        idx = line - 2
        if not (0 <= idx < len(rows)):
            raise SystemExit(f"行号 {line} 超出范围（数据行 2~{len(rows) + 1}）")
        r = rows[idx]
        try:
            cur_i, cur_d = int(r["intrusion"]), int(r["destruction"])
        except (KeyError, ValueError):
            raise SystemExit(f"行 {line} 现有坐标不是整数，改用 --set 明确指定")
        edits.append((line, None, i or cur_i, d or cur_d))
    if args.from_file:
        with open(args.from_file, "r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                band = (r.get("size_category") or "").strip() or None
                edits.append((int(r["line"]), band, int(r["intrusion"]), int(r["destruction"])))
    if not edits:
        raise SystemExit("没说要改哪几条：--by 行=部位:判据 / "
                         "--set 行=主轴:副轴 / --from-file 清单.csv")

    planned = []
    for line, band, i, d in edits:
        idx = line - 2
        if not (0 <= idx < len(rows)):
            raise SystemExit(f"行号 {line} 超出范围（数据行 2~{len(rows) + 1}）")
        reject_cell(i, d)
        r = rows[idx]
        old = (r["size_category"].strip(), r["intrusion"], r["destruction"], r.get("step", ""))
        new_band = band or old[0]
        new_step = f"{p.default_step(i, d):g}" if new_band in p.rank else old[3]
        planned.append((line, r, old, (new_band, str(i), str(d), new_step)))

    print("待写回：")
    for line, r, old, new in planned:
        print(f"行 {line}：{old[0]}:{old[1]}:{old[2]}（step={old[3]}）"
              f" → {new[0]}:{new[1]}:{new[2]}（step={new[3]}）")
        print(f"  {r['text']}")
    print(f"\n共 {len(planned)} 条，" + ("写入中…" if args.apply else "dry-run，加 --apply 写回。"))
    if not args.apply:
        return 0
    bak = backup(args.csv)
    for line, r, _old, new in planned:
        r["size_category"], r["intrusion"], r["destruction"], r["step"] = new
    write_rows(args.csv, rows)
    print(f"已写回 {len(planned)} 条；备份在 {bak}")
    return 0


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def _add_plan_args(sp):
    sp.add_argument("--band", action="append",
                    help="观测等级（band）；一次撰写只做一个，给多个会报错")
    sp.add_argument("--cell", action="append",
                    help="档位:主轴:副轴 或 主轴:副轴（数字坐标；省略档位时等于全等级，"
                         "要配 --band 才不越界）")
    sp.add_argument("--count", type=int, default=3, help="每格目标条数（默认 3）")
    sp.add_argument("--force", action="store_true", help="无视已有条数，按 --count 出满")
    sp.add_argument("--seed", type=int, default=None,
                    help="场景卡与视角的轮换偏移；默认每次随机，给数字可复现同一批")
    sp.add_argument("--style-file", help="风格附加要求，贴进题面与提示词")


def _add_batch_arg(sp):
    sp.add_argument("--batch", type=int, default=3,
                    help="一次调用写几条（同格相邻的卡分到一块，默认 3；1 = 一条一调）")


def build_parser():
    p = argparse.ArgumentParser(
        prog="quip_draft_bench",
        description="描述素材草稿工作台：出题（隐坐标轮换场景卡）/ 人写 / AI 写+人审 / "
                    "agent 全自动 / 收卷")
    p.add_argument("--profile", default="giantess",
                   help="题材 profile 名或 JSON 路径（默认 giantess）")
    p.add_argument("--csv", default=None,
                   help="读写哪份语料 CSV；默认 _out/quip_draft/<profile>.csv")
    # 同一组参数子命令也收一份：`check --csv X` 和 `--csv X check` 都能用
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--csv", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("plan", help="出题面（md/jsonl）", parents=[common])
    _add_plan_args(sp)
    sp.add_argument("--out", help="输出目录，写 briefs.md + briefs.jsonl")

    sp = sub.add_parser("write", help="人写：逐条出题，边写边判", parents=[common])
    _add_plan_args(sp)
    sp.add_argument("--apply", action="store_true", help="收下的直接落盘")
    sp.add_argument("--draft-out", help="不落盘时草稿写哪（默认 _out/quip_draft/drafts-*.jsonl）")

    sp = sub.add_parser("draft", help="AI 写 + 人审", parents=[common])
    _add_plan_args(sp)
    _add_batch_arg(sp)
    sp.add_argument("--temperature", type=float, default=0.8)
    sp.add_argument("--apply", action="store_true", help="收下的直接落盘")

    sp = sub.add_parser("fill", help="agent 全自动：生成→校验→重试→入队", parents=[common])
    _add_plan_args(sp)
    _add_batch_arg(sp)
    sp.add_argument("--temperature", type=float, default=0.8)
    sp.add_argument("--retries", type=int, default=2, help="单条失败后的重试次数")
    sp.add_argument("--apply", action="store_true", help="真正落盘")
    sp.add_argument("--json", action="store_true", help="机器可读结果")

    sp = sub.add_parser("prompt", help="只出提示词，不调模型", parents=[common])
    _add_plan_args(sp)
    _add_batch_arg(sp)
    sp.add_argument("--json", action="store_true",
                    help="输出 {cell, ids, messages} 数组（一块可含多条卡）")

    sp = sub.add_parser("append", help="把草稿 JSONL 落盘", parents=[common])
    sp.add_argument("--from-file", required=True,
                    help="草稿 JSONL，每行 {cell, text, summary}")
    sp.add_argument("--apply", action="store_true", help="真正写入 CSV；默认 dry-run")

    sp = sub.add_parser("check", help="收卷：结构、档位、重复、覆盖", parents=[common])
    sp.add_argument("-v", "--verbose", action="store_true",
                    help="打印问题详情；格内画像默认只展开有问题的格")
    sp.add_argument("--all", action="store_true",
                    help="格内画像展开全部格（默认只展开有问题的格）")
    sp.add_argument("--seed", type=int, default=0,
                    help="回放场景卡的偏移（默认 0；出题默认随机，想对上就用同一个数）")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--count", "--target", dest="count", type=int, default=3,
                    help="每格目标条数（默认 3；--target 同义）")

    sp = sub.add_parser("apply", help="人工校正：把隐坐标写回 CSV", parents=[common])
    sp.add_argument("--by", action="append", metavar="行=部位:判据",
                    help="用场景卡里的词反查等级；空段表示这一轴不改")
    sp.add_argument("--set", action="append", metavar="行=主轴:副轴",
                    help="直接改坐标；也可写成 行=档位:主轴:副轴")
    sp.add_argument("--from-file", help="批量清单 CSV（line,intrusion,destruction[,size_category]）")
    sp.add_argument("--apply", action="store_true", help="真正写回；默认 dry-run")

    sp = sub.add_parser("status", help="进度表", parents=[common])
    sp.add_argument("--count", "--target", dest="count", type=int, default=3,
                    help="每格目标条数（默认 3；--target 同义）")

    sp = sub.add_parser("doctor", help="profile 体检", parents=[common])
    sp.add_argument("--craft", action="store_true", help="打印场景卡全表（apply --by 的用词参考）")
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if _stdin_is_pipe() and hasattr(sys.stdin, "reconfigure"):
        try:
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                        # noqa: BLE001
            pass

    args = build_parser().parse_args(argv)
    try:
        profile = load_profile(args.profile)
    except ProfileError as exc:
        raise SystemExit(f"profile 载入失败：{exc}")
    if not args.csv:
        args.csv = str(OUT_DIR / f"{profile.name}.csv")

    handler = {
        "plan": cmd_plan, "write": cmd_write, "draft": cmd_draft, "fill": cmd_fill,
        "prompt": cmd_prompt, "append": cmd_append, "check": cmd_check,
        "apply": cmd_apply, "status": cmd_status, "doctor": cmd_doctor,
    }[args.cmd]
    return handler(args, profile)


if __name__ == "__main__":
    sys.exit(main())
