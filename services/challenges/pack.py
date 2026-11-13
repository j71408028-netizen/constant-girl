"""挑战包的方案素材：把方案引用的文本/图片/音频打进包，打开时解到临时目录。

挑战包原本只带加密配置，素材却以「相对方案目录」的路径存在配置里，接收方
没有这些文件——背景不显示、BGM 不响、固定文本直接判 error 拦住进入
（``dungeon/validate.py::_validate_fixed_text``）。本模块补齐这一环：

- :func:`collect_asset_paths` 从方案配置里收集**方案目录内**的素材相对路径；
  方案目录外的绝对路径一律不收，否则等于把发送方磁盘任意文件打出去；
- :func:`extract_pack_assets` 把 ``.chal`` 里的 ``assets/`` 条目解到调用方给的
  临时目录，条目名做越界过滤。

包内条目名与方案目录布局一致（``assets/texts/a.txt`` → 解出后是
``<临时目录>/texts/a.txt``），这样解出来的目录可以直接顶替方案目录参与
``ScenarioRepo.asset_dir`` 的相对路径解析。
"""

import os
import zipfile

#: 挑战包 zip 里素材条目的前缀（与 ``challenge_data.bin`` 区分）
ASSET_PREFIX = "assets/"

#: 被引用素材的字段路径：``(配置键, 素材路径键)``。
#: 章节与触发器用的是同一套字段名（触发器覆盖章节的环境）：
#: ``fixed_text.path`` / ``background.image_path`` / ``bgm.path`` / ``icon_path``。
_ASSET_FIELDS = (
    ("fixed_text", "path"),
    ("background", "image_path"),
    ("bgm", "path"),
)

#: 只收这些目录下的素材（与 ``ui/scenario/asset_import.py`` 的落盘约定一致）。
#: 白名单而非黑名单：配置里出现的相对路径必须落在这四类里，其他位置不打包。
ASSET_DIRS = ("texts", "images", "audio", "endings")


def _norm_rel(path) -> str:
    """相对路径归一成 ``a/b/c`` 形态；绝对路径与越界路径返回空串。"""
    rel = str(path or "").strip().replace("\\", "/")
    if not rel or os.path.isabs(rel):
        return ""
    parts = [piece for piece in rel.split("/") if piece not in ("", ".")]
    if not parts or any(piece == ".." for piece in parts):
        return ""
    return "/".join(parts)


def _add(raw, seen: set):
    rel = _norm_rel(raw)
    if not rel:
        return
    if rel.split("/", 1)[0] not in ASSET_DIRS:
        return
    seen.add(rel)


def collect_asset_paths(scenario_config: dict) -> list:
    """收集方案配置里引用到的素材相对路径（按 ``texts/images/audio/endings`` 过滤）。

    遍历章节与触发器的 ``fixed_text.path`` / ``background.image_path`` /
    ``bgm.path`` / ``icon_path``，加上 ``chapters[].endings[].icon_path``
    （结局列表挂在章节下的 ``endings`` 里，不是字段级 icon_path）。

    返回去重排序后的相对路径列表（正斜杠）。
    """
    if not isinstance(scenario_config, dict):
        return []
    seen = set()

    def scan(item):
        if not isinstance(item, dict):
            return
        for section, key in _ASSET_FIELDS:
            block = item.get(section)
            if isinstance(block, dict):
                _add(block.get(key), seen)
        _add(item.get("icon_path"), seen)
        for ending in item.get("endings") or []:
            if isinstance(ending, dict):
                _add(ending.get("icon_path"), seen)

    for chapter in scenario_config.get("chapters") or []:
        scan(chapter)
    for trigger in scenario_config.get("triggers") or []:
        scan(trigger)
    return sorted(seen)


def asset_source_dir(scenario_repo, scenario_id: str) -> str:
    """素材实际所在的方案目录；仓库/方案不可用时返回空串。

    优先 ``asset_dir``（挑战包解包目录顶替场景目录时由宿主仓库给出），
    没有该方法时退回 ``scenario_dir``。
    """
    if scenario_repo is None or not scenario_id:
        return ""
    getter = getattr(scenario_repo, "asset_dir", None)
    try:
        if callable(getter):
            return getter(scenario_id) or ""
        return scenario_repo.scenario_dir(scenario_id) or ""
    except Exception:
        return ""


def pack_assets(zf: zipfile.ZipFile, scenario_repo, scenario_id: str,
                scenario_config: dict) -> list:
    """把方案引用的素材写进 ``zf`` 的 ``assets/`` 条目，返回实际打包的相对路径。

    只收「配置引用到 + 文件真实存在 + 落在方案目录内」的条目；不存在的引用
    跳过（配置本身可能就写着不存在的路径，由校验器在作者那边报）。
    """
    base = asset_source_dir(scenario_repo, scenario_id)
    if not base or not os.path.isdir(base):
        return []
    packed = []
    for rel in collect_asset_paths(scenario_config):
        absolute = os.path.normpath(os.path.join(base, *rel.split("/")))
        if not os.path.isfile(absolute):
            continue
        zf.write(absolute, ASSET_PREFIX + rel)
        packed.append(rel)
    return packed


def has_pack_assets(file_path: str) -> bool:
    """包里是否带素材条目（旧包没有，打开时按「无包内素材」处理）。"""
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            return any(name.startswith(ASSET_PREFIX) for name in zf.namelist())
    except (OSError, zipfile.BadZipFile):
        return False


def extract_pack_assets(file_path: str, dest_dir: str) -> int:
    """把包内 ``assets/`` 条目解到 ``dest_dir``，返回解出的文件数。

    条目名必须是 ``assets/`` 开头、且解出后仍在 ``dest_dir`` 内（挡掉构造出来的
    ``assets/../../x``）；不符合的条目跳过而不是抛错——包是别人给的，坏条目
    不该让整局进不去。
    """
    root = os.path.abspath(dest_dir)
    os.makedirs(root, exist_ok=True)
    count = 0
    with zipfile.ZipFile(file_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.startswith(ASSET_PREFIX):
                continue
            rel = _norm_rel(info.filename[len(ASSET_PREFIX):])
            if not rel:
                continue
            target = os.path.abspath(os.path.join(root, *rel.split("/")))
            if not target.startswith(root + os.sep):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            count += 1
    return count


__all__ = ["ASSET_PREFIX", "ASSET_DIRS", "collect_asset_paths",
           "asset_source_dir", "pack_assets", "has_pack_assets",
           "extract_pack_assets"]
