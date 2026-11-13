"""跨平台资源与用户数据路径工具。"""
import json
import os
import shutil
import sys


#: 对外正式名：窗口标题、启动页、界面署名等一切用户可见处。
APP_NAME = "ConstantGirl"

#: 仓库名 / 技术名：数据目录、可执行文件、发行包名、User-Agent 等一切
#: 机器可读处。形如 ``<repo>-<ver>-<os>-<arch>.zip``。
APP_SLUG = "constant-girl"

#: 项目仓库主页；「检查更新」据此构造 GitHub Releases API 地址与下载页链接。
APP_REPO_URL = "https://github.com/j71408028-netizen/constant-girl"

APP_VERSION = "2.0.0 beta"

#: 改名前使用过的应用目录名，仅在打包版首次启动时用于整体搬迁一次。
_LEGACY_SLUGS = ("GiantessGenerator",)

#: data_dir() 会被频繁调用，旧目录探测只做一次。
_migration_checked = False


def resource_root() -> str:
    """返回随源码或 PyInstaller 包发布的只读资源根目录。

    - 源码运行：返回本文件所在目录（仓库根）；
    - PyInstaller 打包：返回资源目录；macOS .app 为 Contents/Resources。
    """
    if getattr(sys, "frozen", False):  # PyInstaller
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.abspath(__file__))


def project_root() -> str:
    """兼容旧调用：返回应用资源根目录。"""
    return resource_root()


def _packaged_data_base() -> str:
    """返回打包应用数据目录所在的系统级根目录。"""
    if sys.platform.startswith("darwin"):
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    if sys.platform.startswith("win"):
        return os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    return os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))


def _migrate_legacy_app_dir(base: str) -> None:
    """把旧应用目录整体搬到当前名下（仅当目标不存在时，且只搬不改写内容）。"""
    global _migration_checked
    if _migration_checked:
        return
    _migration_checked = True
    target = os.path.join(base, APP_SLUG)
    if os.path.exists(target):
        return
    for legacy in _LEGACY_SLUGS:
        source = os.path.join(base, legacy)
        if not os.path.isdir(source):
            continue
        try:
            os.makedirs(base, exist_ok=True)
            shutil.move(source, target)
        except OSError as e:
            print(f"[Warning] 迁移旧数据目录 {source} 失败: {e}")
        return


def _packaged_data_parent() -> str:
    """返回打包应用可写用户数据目录的父级。"""
    base = _packaged_data_base()
    _migrate_legacy_app_dir(base)
    return os.path.join(base, APP_SLUG)


def data_dir() -> str:
    """返回数据目录。

    源码运行保持使用项目内的 ``data/``；打包应用则使用系统可写目录，避免
    Finder / App Translocation 将数据写入只读的 ``.app`` 资源目录。
    """
    if getattr(sys, "frozen", False):
        return os.path.join(_packaged_data_parent(), "data")
    return os.path.join(resource_root(), "data")


def assets_dir() -> str:
    """返回资源目录（默认为 <项目根>/assets）。"""
    return os.path.join(resource_root(), "assets")


def icon_dir() -> str:
    """返回应用图标资源目录（默认为 <项目根>/assets/icons）。"""
    return os.path.join(assets_dir(), "icons")


def template_dir() -> str:
    """返回文档/页面静态模板目录（默认为 <项目根>/assets/templates）。"""
    return os.path.join(assets_dir(), "templates")


def names_dir() -> str:
    """返回静态姓名表目录（默认为 <数据目录>/static/names）。"""
    return os.path.join(data_dir(), "static", "names")


def presets_dir() -> str:
    """返回静态身材表目录（默认为 <数据目录>/static/presets）。"""
    return os.path.join(data_dir(), "static", "presets")


def personalities_dir() -> str:
    """返回静态性格表目录（默认为 <数据目录>/static/personalities）。"""
    return os.path.join(data_dir(), "static", "personalities")


def behaviors_dir() -> str:
    """返回静态行为包目录（默认为 <数据目录>/static/behaviors）。"""
    return os.path.join(data_dir(), "static", "behaviors")


def worlds_dir() -> str:
    """返回世界包目录（默认为 <数据目录>/worlds）。"""
    return os.path.join(data_dir(), "worlds")


def _read_json_dict(path: str):
    """读一个 JSON 对象文件；不存在、解析失败或不是对象时返回 None。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


#: ``active_world`` 的读取顺序：资源域设置（2.0 起）→ 旧版共享设置。
#: 前者是它现在的家，后者只为尚未迁移的旧数据保留。
_ACTIVE_WORLD_SETTING_FILES = ("resource_settings.json", "settings.json")


def active_world_id() -> str:
    """当前激活的世界包 id；未激活或读不到设置时返回空串。

    只提供路径事实（不解释资源语义）：副本子进程没有注册表与持久层，
    需要靠它定位包内的小游戏与素材。

    按 :data:`_ACTIVE_WORLD_SETTING_FILES` 的顺序取第一个能读的文件，读到就
    以它为准（哪怕里面没有这个键）——``SettingsRepo.save`` 会把资源域键从
    ``settings.json`` 摘掉，用旧文件里的残留值兜底会让已关闭的世界包复活。
    """
    user_dir = os.path.join(data_dir(), "user")
    for name in _ACTIVE_WORLD_SETTING_FILES:
        file = os.path.join(user_dir, name)
        if not os.path.exists(file):
            continue
        data = _read_json_dict(file)
        if data is None:
            continue
        value = data.get("active_world")
        return value if isinstance(value, str) else ""
    return ""


def _bootstrap_packaged_data() -> None:
    """首次启动打包应用时，初始化可写用户数据与内置内容包。"""
    if not getattr(sys, "frozen", False):
        return
    target = data_dir()
    packs_target = os.path.join(target, "packs")
    packs_source = os.path.join(resource_root(), "data", "packs")
    if not os.path.exists(packs_target) and os.path.isdir(packs_source):
        os.makedirs(target, exist_ok=True)
        shutil.copytree(packs_source, packs_target)
    static_target = os.path.join(target, "static")
    static_source = os.path.join(resource_root(), "data", "static")
    if not os.path.exists(static_target) and os.path.isdir(static_source):
        os.makedirs(target, exist_ok=True)
        shutil.copytree(static_source, static_target)
    os.makedirs(os.path.join(target, "user"), exist_ok=True)
    os.makedirs(os.path.join(target, "archives"), exist_ok=True)


def ensure_cwd() -> str:
    """准备用户数据并将进程当前工作目录切换到数据目录的父级。

    应用启动时调用一次即可，使历史上所有基于相对路径（如 "data"）的代码
    在任何平台、任何启动方式下都保持一致。返回项目根目录。
    """
    _bootstrap_packaged_data()
    root = os.path.dirname(data_dir())
    try:
        os.makedirs(root, exist_ok=True)
        os.chdir(root)
    except OSError:
        pass
    return root
