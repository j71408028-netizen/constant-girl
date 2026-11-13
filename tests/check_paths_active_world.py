"""F4 回归守卫：激活世界包的读取位置必须跟着资源域设置走。

用法：``python tests/check_paths_active_world.py``

**为什么需要**：``active_world`` 是资源域键，2.0 起住
``data/user/resource_settings.json``，``SettingsRepo.save`` 写盘时还会把它从
``user/settings.json`` 里摘掉。而 ``paths.active_world_id()`` 仍只读旧文件，
于是副本子进程（没有注册表，只能靠这个路径事实）拿到的世界 id 是空串——
世界包独有、自由目录里没有的小游戏就定位不到。本地恰好有同名游戏时会掩盖
故障，所以这里只用「仅存在于世界包内」的游戏验证。

两段：

1. **读取优先级**：资源域文件为准，旧文件只在它缺失/坏掉时回退，关掉的世界
   包不能被旧值复活；
2. **小游戏定位**：按上行优先级真的建目录树，看 ``pack_ids`` / ``pack_root``
   能否找到独有小游戏，并确认自由目录仍然优先。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paths  # noqa: E402
from dungeon.minigame_pack import pack_ids, pack_root  # noqa: E402
from persistence.settings_repo import SettingsRepo  # noqa: E402

failures = []
total = 0


def check(name, ok, extra=""):
    global total
    total += 1
    print(("  OK   " if ok else "  FAIL ") + name + (f"  <{extra}>" if extra and not ok else ""))
    if not ok:
        failures.append(name)


def _write(path, data, raw=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        if raw is not None:
            handle.write(raw)
        else:
            json.dump(data, handle, ensure_ascii=False)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class _DataDir:
    """临时数据目录：把 ``paths.data_dir`` 换成它，退出时恢复。"""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self._saved = None

    def __enter__(self):
        os.makedirs(os.path.join(self.root, "user"), exist_ok=True)
        self._saved = paths.data_dir
        paths.data_dir = lambda: self.root
        return self

    def __exit__(self, *exc):
        paths.data_dir = self._saved
        self._tmp.cleanup()
        return False

    def user(self, name):
        return os.path.join(self.root, "user", name)

    def world_minigame(self, world_id, game_id):
        root = os.path.join(self.root, "worlds", world_id, "minigames", game_id)
        os.makedirs(root, exist_ok=True)
        _write(os.path.join(root, "manifest.json"), {"name": game_id})
        return root

    def free_minigame(self, game_id):
        root = os.path.join(self.root, "packs", "minigames", game_id)
        os.makedirs(root, exist_ok=True)
        _write(os.path.join(root, "manifest.json"), {"name": game_id})
        return root


# ---------------- 1. 读取优先级 ----------------
print("--------------- 1. 激活态读取 ----------------")

with _DataDir() as d:
    _write(d.user("resource_settings.json"), {"active_world": "w_new"})
    check("资源域文件独有 active_world 时能读到", paths.active_world_id() == "w_new",
          paths.active_world_id())

with _DataDir() as d:
    _write(d.user("settings.json"), {"active_world": "w_old"})
    check("只有旧版文件时回退读到", paths.active_world_id() == "w_old",
          paths.active_world_id())

with _DataDir() as d:
    _write(d.user("resource_settings.json"), {"active_world": "w_new"})
    _write(d.user("settings.json"), {"active_world": "w_old"})
    check("两份都在时以资源域为准", paths.active_world_id() == "w_new",
          paths.active_world_id())

with _DataDir() as d:
    # 关掉世界包后资源域文件里没有这个键，旧文件可能还留着上次的值
    _write(d.user("resource_settings.json"), {"selected_styles": ["chinese_mix"]})
    _write(d.user("settings.json"), {"active_world": "w_old"})
    check("已关闭的世界包不被旧值复活", paths.active_world_id() == "",
          paths.active_world_id())

with _DataDir() as d:
    _write(d.user("resource_settings.json"), None, raw="{ 坏掉的 json")
    _write(d.user("settings.json"), {"active_world": "w_old"})
    check("资源域文件坏掉时回退旧文件", paths.active_world_id() == "w_old",
          paths.active_world_id())

with _DataDir() as d:
    check("两份都没有时返回空串", paths.active_world_id() == "", paths.active_world_id())

with _DataDir() as d:
    _write(d.user("resource_settings.json"), {"active_world": 123})
    check("非字符串的 active_world 视为未激活", paths.active_world_id() == "",
          paths.active_world_id())

# 让 migrate 后的真实落盘路径参与验证：SettingsRepo 写 active_world 只会进
# 资源域文件，settings.json 里不会留下它。
with _DataDir() as d:
    SettingsRepo(data_dir=d.root).save({"active_world": "w_saved", "seed": 1})
    raw_shared = _read(d.user("settings.json"))
    raw_resource = _read(d.user("resource_settings.json"))
    check("SettingsRepo 把 active_world 分流到资源域文件",
          raw_resource.get("active_world") == "w_saved"
          and "active_world" not in raw_shared, raw_shared)
    check("分流后仍能读到激活世界", paths.active_world_id() == "w_saved",
          paths.active_world_id())


# ---------------- 2. 小游戏定位 ----------------
print("--------------- 2. 世界包独有小游戏 ----------------")

with _DataDir() as d:
    world_root = d.world_minigame("w_new", "lone")
    _write(d.user("resource_settings.json"), {"active_world": "w_new"})
    check("独有小游戏能被枚举", "lone" in pack_ids(), pack_ids())
    check("独有小游戏解析到世界包目录",
          os.path.normpath(pack_root("lone")) == os.path.normpath(world_root),
          pack_root("lone"))

with _DataDir() as d:
    free_root = d.free_minigame("dup")
    d.world_minigame("w_new", "dup")
    _write(d.user("resource_settings.json"), {"active_world": "w_new"})
    check("同名时自由目录优先",
          os.path.normpath(pack_root("dup")) == os.path.normpath(free_root),
          pack_root("dup"))

with _DataDir() as d:
    d.world_minigame("w_old", "stale")
    _write(d.user("resource_settings.json"), {"selected_styles": ["chinese_mix"]})
    _write(d.user("settings.json"), {"active_world": "w_old"})
    check("世界包已关闭时其独有游戏不再出现", "stale" not in pack_ids(), pack_ids())

with _DataDir() as d:
    world_root = d.world_minigame("w_legacy", "old_style")
    _write(d.user("settings.json"), {"active_world": "w_legacy"})
    check("旧版数据（未迁移）也能定位独有小游戏",
          os.path.normpath(pack_root("old_style")) == os.path.normpath(world_root),
          pack_root("old_style"))

# ---------------- 结论 ----------------
print()
if failures:
    print(f"[check_paths_active_world] FAILED {len(failures)}/{total}: "
          + "; ".join(failures))
    sys.exit(1)
print(f"[check_paths_active_world] PASSED {total}/{total}")
