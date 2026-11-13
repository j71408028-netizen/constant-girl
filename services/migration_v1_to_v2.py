"""v1.0.0 数据目录 → 2.0 数据格式的转换内核（一次性，幂等）。

v1.0.0 之后资源层经历过多次**破坏性**改动，旧目录里的文件大多已不被读取
（有的连读取路径都换了）。本模块按类型逐个把 v1.0.0 数据改写成 2.0 形状，
并把改写不了的内容整理成一份「需要人工处理」清单。

两个入口共用本内核：

- 开发者命令行：``scripts/migrate_v1_to_v2.py``（预览 / ``--apply`` / ``--report``）；
- 发行包运行时入口：``app/maintenance.py``（玩家在打包版目录双击启动器触发）。

十步，每步都按「已经是目标形状就跳过」判断，因此跑第二遍必须输出 0 处变更：

1. **设置分家**：``settings.json`` 里的取材表四键合成 ``material_table``，
   副本独占键搬进 ``dungeon_settings.json``，资源域键搬进
   ``resource_settings.json``，删掉已无消费者的键；
2. **取材表**：``static/{names,news,presets,personalities}/<组>.csv`` →
   ``static/materials/<组>/<成员>.csv``；``news`` 表头改字段键，
   ``personalities`` 的 ``step_*`` 改 ``depth_*`` 并补 ``gravity`` 列；
3. **地标风格**：``packs/landmarks/<名>.json``（JSON 数组）→
   ``packs/landmarks/<id>.csv``，id 改拼音/小写；
4. **描述风格**：``packs/quips/<名>.json`` → ``packs/quips/<id>/quips.csv`` +
   ``config.json``，坐标行展开为 CSV 长表，``[summary:…]`` 拆成列；
5. **副本方案**：``packs/dungeons/`` → ``packs/scenarios/``，配置按当前
   schema 归一化（``view_mode`` → ``coupling_level``，``custom_attrs`` →
   ``evolution_attrs``，触发器 id → 名称）；
6. **世界包**：解压目录与 ``.world.zip`` 的清单（``resources.dungeons`` →
   ``scenarios``、素材表四键 → ``material_table``）与包内资源布局一并改写；
7. **角色档案**：旧演化三标量 + 三平行列表 → ``evolution`` 表，性格
   ``step_*`` → ``depth_*``，耐久表键 ``名称@地址`` → ``Ref`` 文本，
   ``achieved_endings[].dungeon_id`` → ``scenario_id``；
8. **行为包**：只体检不改写——覆盖了旧钩子名的包登记到人工清单；
9. **结局索引**：``user/endings.json`` 记录的 ``dungeon_id`` → ``scenario_id``；
10. **资源信封**：给每份资源补 ``<id>.meta.json``（内容哈希一致则不重写）。

``preview()`` / ``apply()`` 返回收集到的变更与人工清单，由调用方决定展示方式；
落盘前必须先经 :meth:`Migration.backup` 整目录备份到
``<data>.rollback-<时间戳>/``。回滚：把备份目录覆盖回 ``data/``。

改不动的部分（旧回放、加密挑战包、旧触发器动作、行为包旧钩子等）在
``scripts/README.md`` 的「v1.0.0 → 当前」一节，运行结果也会逐条列出。
"""

import csv
import datetime
import json
import os
import re
import shutil
import tempfile
import zipfile

from core.resource_spec import RESOURCE_TYPES, spec_of, valid_id_for  # noqa: E402
from dungeon.settings import LEGACY_KEYS as DUNGEON_SETTING_KEYS  # noqa: E402
from dungeon.settings import defaults as dungeon_setting_defaults  # noqa: E402
from dungeon.terms import (LEGACY_SCENARIO_ID_KEY,  # noqa: E402
                           LEGACY_SCENARIO_RESOURCE_KEY,
                           SCENARIO_ID_KEY, SCENARIO_RESOURCE_KEY)
from persistence.json_store import (BACKUP_SUFFIX, load_json_with_backup,  # noqa: E402
                                    write_json_atomic)
from persistence.landmark_repo import write_csv as write_landmark_csv  # noqa: E402
from persistence.quip_repo import write_style_dir  # noqa: E402
from persistence.resources import envelope, registry  # noqa: E402
from persistence.resources.registry import RESOURCE_SETTINGS_KEYS  # noqa: E402
from persistence.scenario_repo import ScenarioRepo  # noqa: E402
from persistence.world_pack import WORLD_MANIFEST_NAME, WORLD_SETTING_KEYS  # noqa: E402

#: 旧 id → 新 id。映射只活在本脚本里，代码侧不认旧名。
RENAMES = {
    "landmarks": {"ChineseMix": "chinese_mix", "Extension": "extension"},
    "quips": {"Events": "events", "PixelGame": "pixel_game"},
    "scenarios": {"_default": "default", "巨影临城": "juying_lincheng"},
}

#: 旧视图模式 → 新耦合等级。这是**语义**映射，不是机械改名，逐条记入人工清单。
VIEW_MODE_COUPLING = {"story": "velum", "game": "bulla"}

#: v1.0.0 的四张独立取材表键（现在只剩整组切换的 ``material_table``）。
OLD_TABLE_KEYS = ("name_table", "news_table", "preset_table", "personality_table")

#: v1.0.0 有、当前已无消费者的设置键。
DEAD_SETTING_KEYS = ("theme_mode", "quip_rate_factor", "voice_proxy")

#: 已失效的旧触发器动作类型（运行时不再执行，需要作者改写）。
DEAD_ACTIONS = {"background": "由章节的 background 字段承担",
                "sensitivity": "由章节的 sensitivity 字段承担",
                "sensitive": "由章节的 sensitivity 字段承担",
                "ending": "由「结束章节」（章节 ending=true）承担"}

#: 旧行为包钩子名 → 新名（``docs/terminology.md`` §2.3）。
LEGACY_HOOKS = ("evolve_step_rates", "decay_step_rates", "nudge_step_rates")

_SUMMARY_RE = re.compile(r"\s*\[summary:(.*?)\]\s*$")
_LEGACY_MAIN_SUFFIX = ".json"
_MIGRATED_DIRNAME = "migrated"


# ---------------------------------------------------------------------------
# 迁移上下文
# ---------------------------------------------------------------------------

class Migration:
    """一次迁移：``apply=False`` 时只记变更，不碰磁盘。"""

    def __init__(self, data_dir: str, apply: bool):
        self.data_dir = data_dir
        self.apply = apply
        self.changes = []       # [(step, detail)]
        self.manual = []        # [{category, target, issue, advice}]
        self.backup_dir = ""
        self._step = ""

    # ---------- 记录 ----------
    def step(self, title: str):
        self._step = title
        print(f"\n[{title}]")

    def note(self, detail: str):
        self.changes.append((self._step, detail))
        print(("  ✓ " if self.apply else "  · ") + detail)

    def manual_add(self, category: str, target: str, issue: str, advice: str = ""):
        entry = {"category": category, "target": target, "issue": issue,
                 "advice": advice}
        if entry in self.manual:
            return
        self.manual.append(entry)
        print(f"  ! {category}：{target} —— {issue}")

    # ---------- 文件操作（预览模式下全部空转） ----------
    def rename(self, source: str, target: str):
        if self.apply:
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            os.rename(source, target)

    def copy_file(self, source: str, target: str):
        if self.apply:
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            shutil.copy2(source, target)

    def write_json(self, path: str, data):
        if self.apply:
            write_json_atomic(path, data)

    def makedirs(self, path: str):
        if self.apply:
            os.makedirs(path, exist_ok=True)

    def drop_empty_dir(self, path: str):
        if self.apply and os.path.isdir(path) and not os.listdir(path):
            os.rmdir(path)

    def to_legacy(self, path: str):
        """把已被替换掉的源文件挪进 ``migrated/v1-legacy/``（不删用户数据）。

        数据目录之外的路径（世界包临时解压目录）不搬：那棵树用完即弃。
        """
        if not os.path.exists(path):
            return
        relative = os.path.relpath(path, self.data_dir)
        if relative.startswith(os.pardir):
            return
        target = os.path.join(self.data_dir, _MIGRATED_DIRNAME, "v1-legacy", relative)
        if self.apply:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if os.path.exists(target):
                target += datetime.datetime.now().strftime(".%Y%m%d%H%M%S")
            shutil.move(path, target)

    # ---------- 备份 ----------
    def backup(self) -> str:
        stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        target = f"{self.data_dir.rstrip(os.sep)}.rollback-{stamp}"
        if os.path.exists(target):
            raise SystemExit(f"备份目录已存在，拒绝覆盖：{target}")
        shutil.copytree(self.data_dir, target)
        self.backup_dir = target
        print(f"\n已备份到 {target}")
        return target


# ---------------------------------------------------------------------------
# 命名
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    """任意名字 → 合规资源 id 的尽力改写（不含拼音转写）。"""
    text = re.sub(r"[^a-z0-9._-]+", "_", str(text or "").strip().lower())
    text = re.sub(r"_{2,}", "_", text).strip("._-")
    return text[:64]


def new_id(type_id: str, old: str) -> str:
    """旧容器名 → 当前资源 id；无法得到合规 id 时返回空串。"""
    mapped = RENAMES.get(type_id, {}).get(old)
    if mapped:
        return mapped
    if valid_id_for(type_id, old):
        return old
    candidate = _slug(old)
    return candidate if valid_id_for(type_id, candidate) else ""


def _resolve_id(m: Migration, type_id: str, old: str, where: str) -> str:
    """改名并登记无法自动改名的条目；返回空串表示该条跳过。"""
    target = new_id(type_id, old)
    if target:
        if target != old:
            m.note(f"{where}：{old} → {target}")
        return target
    m.manual_add("资源 id", f"{where}/{old}",
                 "名字含中文或非法字符，无法自动生成合规 id",
                 "在资源中心改名为小写英文/数字（允许 . _ -），或直接改目录名")
    return ""


def _load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 1. 设置分家
# ---------------------------------------------------------------------------

def _merged_json(path: str, patch: dict, defaults: dict = None) -> tuple:
    """把 ``patch`` 并入文件现值（已有的键不覆盖）；返回 ``(新 dict, 是否变化)``。"""
    current = load_json_with_backup(path)
    current = dict(current) if isinstance(current, dict) else dict(defaults or {})
    changed = False
    for key, value in patch.items():
        if key not in current:
            current[key] = value
            changed = True
    return current, changed or not os.path.exists(path)


def step_settings(m: Migration):
    m.step("设置分家")
    path = os.path.join(m.data_dir, "user", "settings.json")
    raw = load_json_with_backup(path)
    if not isinstance(raw, dict):
        print("  未找到 settings.json，跳过")
        return
    settings = dict(raw)
    resource_values = {}
    dungeon_values = {}

    # 资源域：四张独立取材表键 → 一个整组键
    tables = {k: str(settings.get(k) or "").strip() for k in OLD_TABLE_KEYS}
    tables = {k: v for k, v in tables.items() if v}
    if tables:
        groups = sorted(set(tables.values()))
        if len(groups) == 1:
            resource_values["material_table"] = groups[0]
            m.note(f"material_table = {groups[0]}")
        else:
            # 四个键指向不同组：新版只能整组指定一张，取多数并交人工确认
            best = max(groups, key=lambda g: sum(1 for v in tables.values() if v == g))
            resource_values["material_table"] = best
            m.manual_add(
                "取材表", "user/settings.json",
                f"四张表分别指向 {tables}，新版只能整组切换一张",
                f"已取多数值 {best!r}；请在资源中心重新确认取材表组")
        for key in tables:
            settings.pop(key, None)

    for key, type_id in (("selected_styles", "landmarks"),
                         ("selected_quip_styles", "quips")):
        values = settings.pop(key, None)
        if not isinstance(values, list):
            if values is not None:
                resource_values[key] = values
            continue
        mapped = []
        for item in values:
            target = new_id(type_id, str(item))
            if not target:
                m.manual_add("资源 id", f"user/settings.json:{key}",
                             f"选中项 {item!r} 无法自动改名",
                             "迁移后重新在资源中心选中同名风格")
                continue
            if target != item:
                m.note(f"{key}：{item} → {target}")
            mapped.append(target)
        resource_values[key] = mapped

    if "active_world" in settings:
        resource_values["active_world"] = settings.pop("active_world")

    # 副本独占设置
    for key in DUNGEON_SETTING_KEYS:
        if key in settings:
            dungeon_values[key] = settings.pop(key)

    # 代理：语音与 AI 共用后改名
    if settings.get("voice_proxy") and not settings.get("net_proxy"):
        settings["net_proxy"] = settings["voice_proxy"]
        m.note("voice_proxy → net_proxy")

    theme_mode = settings.get("theme_mode")
    for key in DEAD_SETTING_KEYS:
        if key in settings:
            settings.pop(key, None)
            m.note(f"删除已失效的键 {key}")
    if theme_mode:
        m.manual_add("外观", "user/settings.json",
                     f"旧主题模式 theme_mode={theme_mode!r} 没有等价设置",
                     "外观改跟随系统深浅色；请在设置页重新选配色（可另选深色配色）")

    if settings != raw:
        m.write_json(path, settings)

    if resource_values:
        target = os.path.join(m.data_dir, "user", "resource_settings.json")
        known = {k: v for k, v in resource_values.items()
                 if k in RESOURCE_SETTINGS_KEYS}
        merged, changed = _merged_json(target, known)
        if changed:
            m.write_json(target, merged)
            m.note(f"resource_settings.json += {sorted(known)}")

    if dungeon_values:
        target = os.path.join(m.data_dir, "user", "dungeon_settings.json")
        merged, changed = _merged_json(target, dungeon_values,
                                       dungeon_setting_defaults())
        if changed:
            m.write_json(target, merged)
            m.note(f"dungeon_settings.json += {sorted(dungeon_values)}")


# ---------------------------------------------------------------------------
# 2. 取材表
# ---------------------------------------------------------------------------

def _rewrite_csv_header(path: str, mapping: dict, insert: tuple = (),
                        order: tuple = ()):
    """改写 CSV 表头并把列排成声明顺序。

    ``mapping`` 改列名，``insert`` 是缺失时补的 ``(键, 默认值)``，
    ``order`` 是声明的字段顺序（表里多出来的未知列排在最后，不删）。
    """
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return
    original = [str(cell).strip() for cell in rows[0]]
    header = [mapping.get(cell, cell) for cell in original]
    for key, value in insert:
        if key in header:
            continue
        header.append(key)
        for row in rows[1:]:
            row.append(value)
    source = header
    if order:
        header = ([key for key in order if key in header]
                  + [key for key in header if key not in order])
    if header == original:
        return
    width = max([len(row) for row in rows[1:]] + [len(source)])
    positions = [source.index(key) for key in header]
    body = []
    for row in rows[1:]:
        padded = list(row) + [""] * (width - len(row))
        body.append([padded[i] for i in positions])
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(body)


def _member_field_order(member_key: str) -> tuple:
    """取材表某成员的声明字段顺序。"""
    member = spec_of("materials").member(member_key)
    return member.field_keys() if member is not None else ()


def _news_header_map() -> dict:
    """中文列名 → 字段键：news 现在是取材表的成员，字段声明在 ``materials`` 里。"""
    member = spec_of("materials").member("news")
    return {field.label: field.key for field in member.fields if field.label}


def _materials_root(data_dir: str) -> str:
    return os.path.join(data_dir, "static", "materials")


def step_materials(m: Migration):
    m.step("取材表")
    src_dirs = {member: os.path.join(m.data_dir, "static", member)
                for member in ("names", "news", "presets", "personalities")}
    if not any(os.path.isdir(path) for path in src_dirs.values()):
        print("  没有旧布局的取材表目录，跳过")
        return

    groups = set()
    for directory in src_dirs.values():
        if not os.path.isdir(directory):
            continue
        for name in os.listdir(directory):
            if name.lower().endswith(".csv"):
                groups.add(name[:-4])

    for group in sorted(groups):
        group_id = _resolve_id(m, "materials", group, "static/*/<组>")
        if not group_id:
            continue
        target_dir = os.path.join(_materials_root(m.data_dir), group_id)
        for member, directory in src_dirs.items():
            source = os.path.join(directory, group + ".csv")
            target = os.path.join(target_dir, member + ".csv")
            if not os.path.isfile(source) or os.path.exists(target):
                continue
            if member == "news":
                m.copy_file(source, target)
                if m.apply:
                    _rewrite_csv_header(target, _news_header_map(),
                                        order=_member_field_order("news"))
                m.note(f"{member}/{group}.csv → materials/{group_id}/{member}.csv（表头改字段键）")
            elif member == "personalities":
                m.copy_file(source, target)
                if m.apply:
                    _rewrite_csv_header(
                        target,
                        {"step_intrusion": "depth_intrusion",
                         "step_destruction": "depth_destruction"},
                        insert=(("gravity", "0"),),
                        order=_member_field_order("personalities"))
                m.note(f"{member}/{group}.csv → materials/{group_id}/{member}.csv"
                       "（step_* → depth_*，补 gravity）")
                m.manual_add(
                    "性格表", f"materials/{group_id}/personalities.csv",
                    "旧的「步长」列已按新语义改名为「深度」列，但两者量纲不同",
                    "复核该表的 depth_intrusion / depth_destruction 取值是否合理")
            else:
                m.copy_file(source, target)
                m.note(f"{member}/{group}.csv → materials/{group_id}/{member}.csv")
            m.to_legacy(source)

    for directory in src_dirs.values():
        m.drop_empty_dir(directory)


# ---------------------------------------------------------------------------
# 3. 地标风格
# ---------------------------------------------------------------------------

_COMPANION_SUFFIXES = (registry.ADDR_SUFFIX, envelope.ENVELOPE_SUFFIX)


def _legacy_entries(directory: str, legacy_suffixes: tuple) -> list:
    """目录里尚未转换的旧主文件（排除伴随文件、备份、临时文件与新格式文件）。"""
    found = []
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        if name.startswith(".") or name.endswith(".tmp"):
            continue
        if name in ("config.json", "quips.csv") or name.lower().endswith(".csv"):
            continue
        if name.endswith(BACKUP_SUFFIX) or name.endswith(_COMPANION_SUFFIXES):
            continue
        if not any(name.endswith(suffix) for suffix in legacy_suffixes):
            continue
        found.append(name)
    return found


def _convert_landmark_dir(directory: str, m: Migration, label: str) -> int:
    """``<名>.json``（数组）→ ``<id>.csv``；返回改动条数。"""
    before = len(m.changes)
    if not os.path.isdir(directory):
        return 0
    for name in _legacy_entries(directory, (_LEGACY_MAIN_SUFFIX,)):
        old = name[:-len(_LEGACY_MAIN_SUFFIX)]
        target_id = new_id("landmarks", old)
        if not target_id:
            _resolve_id(m, "landmarks", old, label)
            continue
        target = os.path.join(directory, target_id + ".csv")
        if os.path.exists(target):
            continue
        data = _load_json(os.path.join(directory, name))
        if not isinstance(data, list):
            m.manual_add("地标风格", f"{label}/{name}",
                         "旧主文件不是 JSON 数组，无法识别为地标风格",
                         "人工确认后改名或移出该目录")
            continue
        rows = [item for item in data if isinstance(item, dict)]
        if m.apply:
            write_landmark_csv(target, rows)
        m.note(f"{label}/{name} → {target_id}.csv（{len(rows)} 条地标）")
        _rename_companions(directory, old, target_id, m, label)
        m.to_legacy(os.path.join(directory, name))
    return len(m.changes) - before


def _rename_companions(directory: str, old: str, target_id: str, m: Migration,
                       label: str):
    """把 ``<旧名>`` 的伴随文件跟着改成 ``<新名>``。"""
    for suffix in _COMPANION_SUFFIXES + (_LEGACY_MAIN_SUFFIX + BACKUP_SUFFIX,
                                         BACKUP_SUFFIX):
        source = os.path.join(directory, old + suffix)
        if not os.path.isfile(source):
            continue
        target_suffix = suffix.replace(_LEGACY_MAIN_SUFFIX + BACKUP_SUFFIX,
                                       BACKUP_SUFFIX)
        target = os.path.join(directory, target_id + target_suffix)
        if os.path.exists(target):
            continue
        m.rename(source, target)
        m.note(f"{label}/{old}{suffix} → {target_id}{target_suffix}")


def step_landmarks(m: Migration):
    m.step("地标风格")
    directory = os.path.join(m.data_dir, "packs", "landmarks")
    if not _convert_landmark_dir(directory, m, "packs/landmarks"):
        print("  没有旧布局的地标风格，跳过")


# ---------------------------------------------------------------------------
# 4. 描述风格
# ---------------------------------------------------------------------------

def _quip_items(items, style_map: dict, style_name: str) -> list:
    """旧条目 → 新条目：字符串补成对象，风格名改新 id，``[summary:…]`` 拆列。"""
    result = []
    for item in items or []:
        if isinstance(item, str):
            item = {"text": item, "style": style_name}
        if not isinstance(item, dict):
            continue
        item = dict(item)
        style = item.get("style")
        if style in style_map:
            item["style"] = style_map[style]
        text = item.get("text")
        if isinstance(text, str):
            match = _SUMMARY_RE.search(text)
            if match:
                item["summary"] = match.group(1).strip()
                item["text"] = _SUMMARY_RE.sub("", text).strip()
        result.append(item)
    return result


def _legacy_quips_matrix(data: dict, style_name: str) -> tuple:
    """旧 JSON → ``(矩阵, meta)``；``矩阵`` 为 ``{尺寸档: {(介入度, 破坏性): [条目]}}``。"""
    style_map = RENAMES.get("quips", {})
    matrix = {}
    for category, value in data.items():
        if category == "_meta":
            continue
        if isinstance(value, dict):
            for coord, items in value.items():
                try:
                    intrusion, destruction = (int(part) for part in
                                              str(coord).split("_"))
                except ValueError:
                    continue
                matrix.setdefault(category, {}).setdefault(
                    (intrusion, destruction), []).extend(
                        _quip_items(items, style_map, style_name))
        elif isinstance(value, list):
            for row in value:
                if not isinstance(row, dict):
                    continue
                try:
                    coord = (int(row.get("intrusion")), int(row.get("destruction")))
                except (TypeError, ValueError):
                    continue
                matrix.setdefault(category, {}).setdefault(coord, []).extend(
                    _quip_items(row.get("items"), style_map, style_name))
    meta = data.get("_meta")
    return matrix, meta if isinstance(meta, dict) else {}


def _convert_quip_dir(directory: str, m: Migration, label: str) -> int:
    """旧单文件风格 → ``<id>/quips.csv`` + ``config.json``；返回改动条数。"""
    before = len(m.changes)
    if not os.path.isdir(directory):
        return 0
    for name in _legacy_entries(directory, ("", _LEGACY_MAIN_SUFFIX)):
        old = name[:-len(_LEGACY_MAIN_SUFFIX)] if name.endswith(
            _LEGACY_MAIN_SUFFIX) else name
        target_id = new_id("quips", old)
        if not target_id:
            _resolve_id(m, "quips", old, label)
            continue
        source = os.path.join(directory, name)
        target_dir = os.path.join(directory, target_id)
        if os.path.isdir(target_dir):
            continue
        data = _load_json(source)
        if not isinstance(data, dict):
            m.manual_add("描述风格", f"{label}/{name}",
                         "旧主文件不是 JSON 对象，无法识别为描述风格",
                         "人工确认后改名或移出该目录")
            continue
        matrix, meta = _legacy_quips_matrix(data, target_id)
        rows = sum(len(items) for style in matrix.values() for items in style.values())
        if m.apply:
            staging = target_dir + ".migrating"
            shutil.rmtree(staging, ignore_errors=True)
            write_style_dir(staging, matrix, meta, target_id)
            if os.path.isfile(target_dir):
                os.remove(target_dir)
            os.replace(staging, target_dir)
        m.note(f"{label}/{name} → {target_id}/quips.csv + config.json（{rows} 条）")
        _rename_companions(directory, old, target_id, m, label)
        m.to_legacy(source)
    return len(m.changes) - before


def step_quips(m: Migration):
    m.step("描述风格")
    directory = os.path.join(m.data_dir, "packs", "quips")
    if not _convert_quip_dir(directory, m, "packs/quips"):
        print("  没有旧布局的描述风格，跳过")


# ---------------------------------------------------------------------------
# 5. 副本方案
# ---------------------------------------------------------------------------

def _migrate_scenario_config(config: dict) -> dict:
    """旧方案配置 → 当前形状（``ScenarioRepo._migrate`` 是代码侧的兼容入口）。"""
    config = dict(config)
    view_mode = config.get("view_mode")
    if not config.get("coupling_level") and view_mode:
        config["coupling_level"] = VIEW_MODE_COUPLING.get(str(view_mode), "velum")
    migrated = ScenarioRepo._migrate(config)
    migrated.pop("view_mode", None)
    return migrated


def _scenario_dirs(m: Migration) -> list:
    """待归一化的方案目录：``[(目录, 目录名, 显示前缀)]``（预览时也含旧根）。"""
    found = []
    for root_key in (SCENARIO_RESOURCE_KEY, LEGACY_SCENARIO_RESOURCE_KEY):
        root = os.path.join(m.data_dir, "packs", root_key)
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if os.path.isdir(path):
                # 预览时目录还没搬，显示名按迁移后的落点取，免得清单里是旧路径
                shown = new_id("scenarios", name) or name
                found.append((path, shown, f"packs/{SCENARIO_RESOURCE_KEY}"))
    return found


def _migrate_scenario_dirs(dirs, m: Migration) -> int:
    """逐个方案改写 ``config.json``（已迁移的目录见旧配置会再跑一遍，幂等）。"""
    before = len(m.changes)
    for path, scenario_id, prefix in dirs:
        config_path = os.path.join(path, "config.json")
        config = _load_json(config_path)
        if not isinstance(config, dict):
            continue
        migrated = _migrate_scenario_config(config)
        if migrated == config:
            continue
        m.note(f"{prefix}/{scenario_id}/config.json：按当前 schema 归一化")
        m.write_json(config_path, migrated)
        _report_scenario_breaks(m, scenario_id,
                                f"{prefix}/{scenario_id}", config, migrated)
    return len(m.changes) - before


def _report_scenario_breaks(m: Migration, scenario_id: str, where: str,
                            old: dict, new: dict):
    """把方案里改不动、只能重写的内容登记到人工清单。"""
    view_mode = old.get("view_mode")
    if view_mode and not old.get("coupling_level"):
        level = new.get("coupling_level")
        m.manual_add(
            "副本方案", where,
            f"旧视图模式 {view_mode!r} 已废弃，按语义写入耦合等级 {level!r}",
            "在剧本编辑器里确认耦合等级（Velum 读者 / Solea 任务 / Bulla 个体互动）")

    for trigger in new.get("triggers") or []:
        action = str((trigger or {}).get("action_type") or "")
        if action in DEAD_ACTIONS:
            m.manual_add(
                "副本方案", f"{where}：触发器 {trigger.get('name')!r}",
                f"动作 {action!r} 运行时不执行",
                f"改写为{DEAD_ACTIONS[action]}")

    components = old.get("components")
    if isinstance(components, list) and any(
            isinstance(item, str) for item in components):
        m.manual_add(
            "副本方案", where,
            "显示组件仍是旧写法（字符串列表）",
            "在新编辑器的「显示组件」页重新勾选，文本组件三选一并入 text_component")

    if not new.get("chapters"):
        m.manual_add(
            "副本方案", where,
            "旧配置没有章节模型（背景/敏感效果散在触发器里）",
            "按新模型补章节：背景、持续演化修正、配色改为章节属性")


def step_scenarios(m: Migration):
    m.step("副本方案")
    old_root = os.path.join(m.data_dir, "packs", LEGACY_SCENARIO_RESOURCE_KEY)
    new_root = os.path.join(m.data_dir, "packs", SCENARIO_RESOURCE_KEY)
    moved = 0
    if os.path.isdir(old_root):
        for name in sorted(os.listdir(old_root)):
            source = os.path.join(old_root, name)
            if not os.path.isdir(source):
                continue
            target_id = new_id("scenarios", name)
            if not target_id:
                _resolve_id(m, "scenarios", name, f"packs/{LEGACY_SCENARIO_RESOURCE_KEY}")
                continue
            target = os.path.join(new_root, target_id)
            if os.path.exists(target):
                m.manual_add("副本方案", f"packs/{SCENARIO_RESOURCE_KEY}/{target_id}",
                             "目标目录已存在，旧方案未搬入",
                             "人工合并两份 config.json 后删除旧目录")
                continue
            m.makedirs(new_root)
            m.rename(source, target)
            m.note(f"packs/{LEGACY_SCENARIO_RESOURCE_KEY}/{name} → "
                   f"packs/{SCENARIO_RESOURCE_KEY}/{target_id}")
            moved += 1
        m.drop_empty_dir(old_root)

    changed = _migrate_scenario_dirs(_scenario_dirs(m), m)
    if not moved and not changed:
        print("  方案目录已是当前布局，跳过")


# ---------------------------------------------------------------------------
# 6. 世界包
# ---------------------------------------------------------------------------

def _convert_material_dirs(src_dirs: dict, target_root: str, m: Migration,
                           label: str) -> tuple:
    """旧 ``names/ news/ presets/ personalities/`` → ``materials/<组>/``。

    返回 ``({组名}, 是否改动)``，组名供清单的 ``material_table`` 参考。
    """
    before = len(m.changes)
    groups = set()
    for directory in src_dirs.values():
        if not os.path.isdir(directory):
            continue
        for name in os.listdir(directory):
            if name.lower().endswith(".csv"):
                groups.add(name[:-4])
    for group in sorted(groups):
        group_id = new_id("materials", group) or group
        for member, directory in src_dirs.items():
            source = os.path.join(directory, group + ".csv")
            target = os.path.join(target_root, group_id, member + ".csv")
            if not os.path.isfile(source) or os.path.exists(target):
                continue
            m.copy_file(source, target)
            if m.apply and member == "news":
                _rewrite_csv_header(target, _news_header_map(),
                                    order=_member_field_order("news"))
            if m.apply and member == "personalities":
                _rewrite_csv_header(
                        target,
                        {"step_intrusion": "depth_intrusion",
                         "step_destruction": "depth_destruction"},
                        insert=(("gravity", "0"),),
                        order=_member_field_order("personalities"))
            m.note(f"{label}/{member}/{group}.csv → materials/{group_id}/{member}.csv")
            m.to_legacy(source)
        for directory in src_dirs.values():
            m.drop_empty_dir(directory)
    return groups, len(m.changes) > before


def _rewrite_manifest(path: str, m: Migration, label: str, groups: set) -> bool:
    """改写 ``world.json``：资源键、素材表键与资源 id。返回是否改动。"""
    data = _load_json(path)
    if not isinstance(data, dict):
        m.manual_add("世界包", label, "world.json 无法解析，整包需人工重建")
        return False
    original = json.loads(json.dumps(data))

    resources = data.get("resources")
    resources = dict(resources) if isinstance(resources, dict) else {}
    legacy = resources.pop(LEGACY_SCENARIO_RESOURCE_KEY, None)
    if legacy is not None and SCENARIO_RESOURCE_KEY not in resources:
        resources[SCENARIO_RESOURCE_KEY] = legacy
        m.note(f"{label}/world.json：resources.dungeons → scenarios")
    for type_id, value in list(resources.items()):
        if not isinstance(value, list):
            continue
        mapped = []
        for item in value:
            target = new_id(type_id, str(item))
            if target:
                mapped.append(target)
            else:
                m.manual_add("世界包", f"{label}/world.json",
                             f"resources.{type_id} 含无法改名的 id {item!r}",
                             "改为小写英文 id 后重新导出世界包")
        if mapped != value:
            m.note(f"{label}/world.json：resources.{type_id} {value} → {mapped}")
            resources[type_id] = mapped
    data["resources"] = resources

    settings = data.get("settings")
    settings = dict(settings) if isinstance(settings, dict) else {}
    tables = {key: str(settings.pop(key) or "").strip()
              for key in OLD_TABLE_KEYS if key in settings}
    if tables:
        values = sorted({v for v in tables.values() if v})
        if len(values) == 1:
            settings["material_table"] = values[0]
            m.note(f"{label}/world.json：{sorted(tables)} → material_table={values[0]}")
        else:
            m.manual_add(
                "世界包", f"{label}/world.json",
                f"包内四张表分别指向 {tables}，新版只能整组指定一张",
                "重整包内取材表为同一组后重新导出")
            common = values[0] if values else ""
            if common:
                settings["material_table"] = common
    for key in list(settings):
        if key not in WORLD_SETTING_KEYS:
            m.manual_add("世界包", f"{label}/world.json",
                         f"settings 里的键 {key!r} 已不被接受",
                         "该键在新建世界包的对话框里重新设置")
            settings.pop(key, None)
    data["settings"] = settings

    if data == original:
        return False
    m.write_json(path, data)
    return True


def _convert_pack_root(root: str, m: Migration, label: str) -> bool:
    """改写一个世界包根目录（解压目录或临时解压出的包）。"""
    before = len(m.changes)
    _convert_landmark_dir(os.path.join(root, "landmarks"), m, f"{label}/landmarks")
    _convert_quip_dir(os.path.join(root, "quips"), m, f"{label}/quips")
    groups, _ = _convert_material_dirs(
        {member: os.path.join(root, member)
         for member in ("names", "news", "presets", "personalities")},
        os.path.join(root, "materials"), m, label)

    old_scenarios = os.path.join(root, LEGACY_SCENARIO_RESOURCE_KEY)
    if os.path.isdir(old_scenarios):
        for name in sorted(os.listdir(old_scenarios)):
            source = os.path.join(old_scenarios, name)
            if not os.path.isdir(source):
                continue
            target_id = new_id("scenarios", name) or name
            target = os.path.join(root, SCENARIO_RESOURCE_KEY, target_id)
            if not os.path.exists(target):
                m.rename(source, target)
                m.note(f"{label}/dungeons/{name} → scenarios/{target_id}")
        m.drop_empty_dir(old_scenarios)

    dirs = []
    for root_name in (SCENARIO_RESOURCE_KEY, LEGACY_SCENARIO_RESOURCE_KEY):
        base = os.path.join(root, root_name)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            path = os.path.join(base, name)
            if os.path.isdir(path):
                shown = new_id("scenarios", name) or name
                dirs.append((path, shown, f"{label}/{SCENARIO_RESOURCE_KEY}"))
    _migrate_scenario_dirs(dirs, m)

    _rewrite_manifest(os.path.join(root, WORLD_MANIFEST_NAME), m, label, groups)
    return len(m.changes) > before


def _rewrite_world_zip(path: str, m: Migration, label: str) -> bool:
    """解压 → 按目录规则改写 → 重新打包。"""
    with tempfile.TemporaryDirectory(prefix="cg-world-") as temp:
        try:
            with zipfile.ZipFile(path) as archive:
                archive.extractall(temp)
        except (OSError, zipfile.BadZipFile) as exc:
            m.manual_add("世界包", label, f"压缩包无法打开（{exc}）",
                         "用新版本重新导入/导出该世界包")
            return False
        changed = _convert_pack_root(temp, m, label)
        if not changed or not m.apply:
            return changed
        backup = path + BACKUP_SUFFIX
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
        temp_zip = path + ".tmp"
        with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for dirpath, dirnames, filenames in os.walk(temp):
                dirnames.sort()
                for name in sorted(filenames):
                    full = os.path.join(dirpath, name)
                    arcname = os.path.relpath(full, temp).replace(os.sep, "/")
                    archive.write(full, arcname)
        os.replace(temp_zip, path)
        m.note(f"{label}：压缩包已重新打包（原包留 {BACKUP_SUFFIX}）")
        return True


def step_worlds(m: Migration):
    m.step("世界包")
    worlds = os.path.join(m.data_dir, "worlds")
    if not os.path.isdir(worlds):
        print("  没有 worlds/ 目录，跳过")
        return
    touched = 0
    for name in sorted(os.listdir(worlds)):
        path = os.path.join(worlds, name)
        if os.path.isdir(path):
            if _convert_pack_root(path, m, f"worlds/{name}"):
                touched += 1
        elif name.endswith(".world.zip"):
            if _rewrite_world_zip(path, m, f"worlds/{name}"):
                touched += 1
    if not touched:
        print("  世界包已是当前布局，跳过")


# ---------------------------------------------------------------------------
# 7. 角色档案
# ---------------------------------------------------------------------------

OLD_SCALARS = ("intrusion", "destruction", "total_casualties")
OLD_LISTS = ("intrusion_evolution", "destruction_evolution", "casualties_evolution")
MIGRATION_SOURCE = "migration_v1_to_v2"


def _parse_time(value, fallback):
    try:
        return datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return fallback


def _interpolate_times(count, start, end):
    """在 start 与 end 之间线性插值出 count 个时间点；count 为 1 时取 start。"""
    if count <= 1:
        return [start.isoformat()]
    span = (end - start).total_seconds()
    return [(start + datetime.timedelta(seconds=span * i / (count - 1))).isoformat()
            for i in range(count)]


def _evolution_rows(data: dict) -> list:
    """旧三标量 + 三平行列表 → 演化表行（不含 ``changed_at``）。"""
    intr = float(data.get("intrusion") or 0.0)
    dest = float(data.get("destruction") or 0.0)
    cas = float(data.get("total_casualties") or 0.0)
    intr_evo = [float(v) for v in (data.get("intrusion_evolution") or [])]
    dest_evo = [float(v) for v in (data.get("destruction_evolution") or [])]
    cas_evo = [float(v) for v in (data.get("casualties_evolution") or [])]

    rows = []

    def add_row(intrusion, destruction, casualties):
        rows.append({"step": 0.0, "intrusion": intrusion,
                     "destruction": destruction, "casualties": casualties,
                     "source": MIGRATION_SOURCE})

    # 伤亡列表多出的前段是创建报告的逐段累计伤亡，折成一行；
    # 介入度/破坏性的逐段值未存档，以首个事件值近似
    n_events = min(len(intr_evo), len(dest_evo))
    cas_offset = len(cas_evo) - n_events
    if cas_offset > 0:
        add_row(intr_evo[0] if intr_evo else intr,
                dest_evo[0] if dest_evo else dest,
                cas_evo[cas_offset - 1])

    last_cas = cas_evo[cas_offset - 1] if cas_offset > 0 else 0.0
    for i in range(n_events):
        cas_idx = cas_offset + i
        if 0 <= cas_idx < len(cas_evo):
            last_cas = cas_evo[cas_idx]
        add_row(intr_evo[i], dest_evo[i], last_cas)

    if rows:
        last = rows[-1]
        if (abs(last["intrusion"] - intr) > 1e-9
                or abs(last["destruction"] - dest) > 1e-9
                or abs(last["casualties"] - cas) > 1e-9):
            add_row(intr, dest, cas)
    else:
        add_row(intr, dest, cas)
    return rows


def _landmark_name_index(data_dir: str) -> dict:
    """``显示名 → {风格 id}``：把旧耐久键里的名字折射回声明身份。"""
    index = {}
    directory = os.path.join(data_dir, "packs", "landmarks")
    if not os.path.isdir(directory):
        return index
    for name in os.listdir(directory):
        if not name.lower().endswith(".csv") or name.endswith(".bak"):
            continue
        style = name[:-4]
        path = os.path.join(directory, name)
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    landmark = (row.get("name") or "").strip()
                    if landmark:
                        index.setdefault(landmark, set()).add(style)
        except OSError:
            continue
    return index


def _durability_ref(key: str, names: dict) -> str:
    """旧键（``名称@完整地址`` 或仅名称）→ ``Ref`` 文本；已是 Ref 的原样返回。"""
    if ":" in key:
        return key
    name = key.split("@", 1)[0]
    styles = names.get(name) or set()
    if len(styles) == 1:
        return f"landmarks:{next(iter(styles))}/{name}"
    return key


def _migrate_archive(data: dict, names: dict, where: str, m: Migration) -> dict:
    """改写一份档案（返回新 dict；``where`` 仅用于人工清单）。"""
    result = json.loads(json.dumps(data))

    # 性格：步长 → 深度，并补重力
    personality = result.get("personality")
    if isinstance(personality, dict):
        for old, new in (("step_intrusion", "depth_intrusion"),
                         ("step_destruction", "depth_destruction")):
            if old in personality and new not in personality:
                personality[new] = personality.pop(old)
        if "depth_intrusion" not in personality or "depth_destruction" not in personality:
            m.manual_add("角色档案", where,
                         "性格缺少介入/破坏深度，读档会失败",
                         "重建该角色，或手工补齐 depth_intrusion / depth_destruction")
        personality.setdefault("gravity", 0.0)

    # 演化表
    if "evolution" not in result:
        rows = _evolution_rows(result)
        start = _parse_time(result.get("created_at"), datetime.datetime.now())
        end = max(start, _parse_time(result.get("updated_at"), start))
        times = _interpolate_times(len(rows), start, end)
        evolution = [dict(changed_at=time, **row) for time, row in zip(times, rows)]
        rebuilt = {}
        for key, value in result.items():
            if key in OLD_SCALARS or key in OLD_LISTS:
                continue
            rebuilt[key] = value
            if key == "body_parts":
                rebuilt["evolution"] = evolution
        rebuilt.setdefault("evolution", evolution)
        result = rebuilt
        m.note(f"{where}：旧演化字段 → evolution 表（{len(evolution)} 行）")
    else:
        filled = 0
        for row in result.get("evolution") or []:
            if isinstance(row, dict) and not row.get("source"):
                row["source"] = MIGRATION_SOURCE
                filled += 1
        if filled:
            m.note(f"{where}：回填 {filled} 行演化记录的 source 标签")

    for key in ("negative_triggered", "negative_reduction_intrusion",
                "negative_reduction_destruction"):
        result.pop(key, None)

    # 结局索引
    endings = result.get("achieved_endings")
    touched = 0
    if isinstance(endings, list):
        for record in endings:
            if isinstance(record, dict) and LEGACY_SCENARIO_ID_KEY in record:
                value = str(record.pop(LEGACY_SCENARIO_ID_KEY))
                record.setdefault(SCENARIO_ID_KEY, new_id("scenarios", value) or value)
                touched += 1
    if touched:
        m.note(f"{where}：{touched} 条结局记录 dungeon_id → scenario_id")

    # 耐久表 / 地址表：拼接键 → Ref
    for field in ("landmark_durability", "landmark_addresses"):
        table = result.get(field)
        if not isinstance(table, dict):
            continue
        renamed = {}
        for key, value in table.items():
            new_key = _durability_ref(key, names)
            if new_key != key:
                m.note(f"{where}：{field} {key} → {new_key}")
            elif names and ":" not in key:
                m.manual_add("角色档案", where,
                             f"{field} 的键 {key!r} 对不上任何地标",
                             "迁移后该地标耐久会按新名字重新计算，必要时手工改键为 landmarks:<风格>/<名称>")
            renamed[new_key] = value
        result[field] = renamed
    return result


def step_archives(m: Migration):
    m.step("角色档案")
    archives = os.path.join(m.data_dir, "archives")
    if not os.path.isdir(archives):
        print("  没有 archives/ 目录，跳过")
        return
    names = _landmark_name_index(m.data_dir)
    changed = 0
    for gid in sorted(os.listdir(archives)):
        path = os.path.join(archives, gid, "info.json")
        data = _load_json(path)
        if not isinstance(data, dict):
            continue
        migrated = _migrate_archive(data, names, f"archives/{gid}", m)
        if migrated != data:
            m.write_json(path, migrated)
            changed += 1
    if not changed:
        print("  档案已是当前形状，跳过")

    legacy_replays = 0
    for base in (os.path.join(archives),
                 os.path.join(m.data_dir, "user", "replays")):
        for dirpath, _dirnames, filenames in os.walk(base):
            legacy_replays += sum(1 for name in filenames
                                  if name.endswith(".replay.json"))
    if legacy_replays:
        m.manual_add(
            "回放", f"{legacy_replays} 份 .replay.json",
            "回放记录的是当时代码的逐步状态，结构已随演化表/账本改动",
            "本脚本不改写回放；需要留档时在角色页导出 HTML 档案（回放会被读成原始记录）")


# ---------------------------------------------------------------------------
# 8. 行为包
# ---------------------------------------------------------------------------

def step_behaviors(m: Migration):
    m.step("行为包")
    root = os.path.join(m.data_dir, "static", "behaviors")
    if not os.path.isdir(root):
        print("  没有 behaviors/ 目录，跳过")
        return
    hits = 0
    for name in sorted(os.listdir(root)):
        pack = os.path.join(root, name)
        if not os.path.isdir(pack):
            continue
        for dirpath, _dirnames, filenames in os.walk(pack):
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(dirpath, filename)
                try:
                    with open(path, "r", encoding="utf-8") as handle:
                        text = handle.read()
                except OSError:
                    continue
                found = [hook for hook in LEGACY_HOOKS if hook in text]
                if not found:
                    continue
                hits += 1
                m.manual_add(
                    "行为包", f"static/behaviors/{name}",
                    f"覆盖了已改名的钩子 {found}",
                    "改为 evolve_depths / decay_depths / nudge_depths；"
                    "旧键不会报错，只会静默回退默认实现")
    if not hits:
        print("  没有使用旧钩子名的行为包，跳过")


# ---------------------------------------------------------------------------
# 9. 结局索引
# ---------------------------------------------------------------------------

def step_endings(m: Migration):
    m.step("结局索引")
    path = os.path.join(m.data_dir, "user", "endings.json")
    data = _load_json(path)
    if not isinstance(data, dict):
        print("  没有 endings.json，跳过")
        return
    changed = 0
    for record in data.get("records") or []:
        if isinstance(record, dict) and LEGACY_SCENARIO_ID_KEY in record:
            value = str(record.pop(LEGACY_SCENARIO_ID_KEY))
            record.setdefault(SCENARIO_ID_KEY, new_id("scenarios", value) or value)
            changed += 1
    if changed:
        m.note(f"user/endings.json：{changed} 条记录 dungeon_id → scenario_id")
        m.write_json(path, data)
    else:
        print("  结局索引已是当前形状，跳过")


# ---------------------------------------------------------------------------
# 10. 资源信封
# ---------------------------------------------------------------------------

def step_envelopes(m: Migration):
    m.step("资源信封")
    if not m.apply:
        print("  （落盘后再补信封与内容哈希）")
        return
    written = 0
    for spec in RESOURCE_TYPES:
        directory = registry.free_dir(spec.type_id, m.data_dir)
        if not os.path.isdir(directory):
            continue
        for resource_id in registry.list_ids(spec.type_id, m.data_dir):
            primary = registry.free_path(spec.type_id, resource_id, m.data_dir)
            if not os.path.exists(primary):
                primary = os.path.join(directory, resource_id)
            if not os.path.exists(primary):
                continue
            current = envelope.content_hash(primary, spec.container)
            recorded = envelope.load_envelope(
                directory, spec.type_id, resource_id).get("content_hash")
            if current and recorded == current:
                continue
            data = envelope.build_envelope(directory, spec.type_id,
                                           resource_id, primary)
            envelope.save_envelope(directory, spec.type_id, resource_id, data)
            written += 1
    if written:
        m.note(f"补写/刷新 {written} 份资源信封")
    else:
        print("  信封与内容哈希一致，跳过")


STEPS = (step_settings, step_materials, step_landmarks, step_quips,
         step_scenarios, step_worlds, step_archives, step_behaviors,
         step_endings, step_envelopes)


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def report_markdown(m: Migration, applied: bool) -> str:
    """把一次迁移（预览或落盘）的变更与人工清单渲染成 Markdown。"""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = ["# v1.0.0 → 2.0 数据迁移清单", "",
             f"- 生成时间：{stamp}",
             f"- 数据目录：`{m.data_dir}`",
             f"- 模式：{'已落盘' if applied else '预览（未落盘）'}",
             f"- 变更：{len(m.changes)} 处",
             f"- 需人工处理：{len(m.manual)} 项", ""]
    if m.backup_dir:
        lines += [f"- 备份：`{m.backup_dir}`", ""]

    if m.changes:
        lines += ["## 变更明细", ""]
        current = None
        for step, detail in m.changes:
            if step != current:
                lines += ["", f"### {step}", ""]
                current = step
            lines.append(f"- {detail}")
        lines.append("")

    if m.manual:
        lines += ["## 需要人工处理", "",
                  "| 类别 | 对象 | 问题 | 建议 |", "|---|---|---|---|"]
        for entry in m.manual:
            cells = [str(entry[name]).replace("|", "\\|")
                     for name in ("category", "target", "issue", "advice")]
            cells[1] = f"`{cells[1]}`"
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)


def preview(data_dir: str) -> Migration:
    """对 ``data_dir`` 做一次预览（不碰磁盘），返回收集到的变更与人工清单。

    每步把计划打印到标准输出；窗口化环境里这些输出自动丢弃，
    结构化结果以返回值为准。
    """
    m = Migration(data_dir, apply=False)
    for step in STEPS:
        step(m)
    return m


def apply(data_dir: str) -> Migration:
    """整目录备份后落盘执行迁移，返回结果（``backup_dir`` 含备份路径）。"""
    worker = Migration(data_dir, apply=True)
    worker.backup()
    for step in STEPS:
        step(worker)
    return worker
