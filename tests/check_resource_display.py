"""资源显示名贯通自检：同名可区分、包往返名称不丢、名称与载荷同源。

用法：``python tests/check_resource_display.py``
输出：控制台一行 ASCII 结论 + UTF-8 报告文件路径。

覆盖：
1. 下拉行去重：同名两条补 id，各自仍能反查回自己的那一项（三处下拉共用）；
2. 挑战包信封归一：``x.chal`` 与 ``x`` 指向同一份 ``x.meta.json``，命名的
   显示名对带后缀的 id 同样可读可写；
3. 世界包导出：挑战包的兄弟信封随包进 ``challenges/x.meta.json``；
4. 世界包安装：包内信封落到自由目录后仍能被读出（往返不丢）；
5. 包内缺信封时不借用自由目录同 id 的名称（名称与载荷必须同源）。

全部在系统临时目录构造数据，不触碰 data/、不联网、不开 GUI。
"""

import json
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_report_path = os.path.join(tempfile.mkdtemp(prefix="resource_display_"), "report.txt")
_log = open(_report_path, "w", encoding="utf-8")
sys.stdout = _log
sys.stderr = _log

failures = []
total = 0


def check(name, ok, extra=""):
    global total
    total += 1
    print(("  OK   " if ok else "  FAIL ") + name
          + (f"  <{extra}>" if extra and not ok else ""))
    if not ok:
        failures.append(name)


from persistence.resources import envelope as envelope_mod  # noqa: E402
from persistence.resources import registry  # noqa: E402
from persistence.world_pack import WorldPackManifest, WorldState  # noqa: E402
from services.challenges.imports import unique_display  # noqa: E402

# ---------------- 1. 下拉行去重 ----------------
_used = set()
_a = unique_display("⚔ 巨影临城", "juying.chal", _used)
_b = unique_display("⚔ 巨影临城", "juying_cn.chal", _used)
check("同名两条不会挤成一行", _a != _b, (_a, _b))
check("先出现的保持原样（短名不喧宾夺主）", _a == "⚔ 巨影临城", _a)
check("后出现的补上自己的 id", _b == "⚔ 巨影临城（juying_cn.chal）", _b)

_names = {}
_shared = set()
for pack in ("juying.chal", "juying_cn.chal"):
    _names[unique_display("⚔ 巨影临城", pack, _shared)] = pack
check("各自反查回自己那一项",
      _names.get("⚔ 巨影临城") == "juying.chal"
      and _names.get("⚔ 巨影临城（juying_cn.chal）") == "juying_cn.chal", _names)

_used = set()
_d = unique_display("⚔ a", "a.chal", _used)
check("重复调用是幂等的（同一行不会二次补 id）",
      unique_display("⚔ a", "a.chal", _used) == "⚔ a（a.chal）")

_used = set()
check("空显示名回落成 id",
      unique_display("", "only_id.chal", _used) == "only_id.chal")

# ---------------- 2. 信封 id 归一 ----------------
check("带后缀的 id 剥成信封名",
      registry.envelope_id("challenges", "p1.chal") == "p1",
      registry.envelope_id("challenges", "p1.chal"))
check("不带后缀的 id 原样返回",
      registry.envelope_id("challenges", "p1") == "p1")
check("大小写后缀同样认",
      registry.envelope_id("challenges", "p1.CHAL") == "p1")
check("目录型容器不受影响（landmarks 无容器后缀）",
      registry.envelope_id("landmarks", "chinese_mix") == "chinese_mix")

_DATA = tempfile.mkdtemp(prefix="display_data_")
_chal_dir = os.path.join(_DATA, "packs", "challenges")
os.makedirs(_chal_dir, exist_ok=True)
for base in ("p1", "p2"):
    with open(os.path.join(_chal_dir, f"{base}.chal"), "wb") as handle:
        handle.write(b"not-a-real-pack")

registry.set_title("challenges", "p1.chal", "一号包", _DATA)
registry.set_title("challenges", "p2", "二号包", _DATA)
check("带后缀写入与不带后缀写入落到同一份信封",
      sorted(f for f in os.listdir(_chal_dir) if f.endswith(".meta.json"))
      == ["p1.meta.json", "p2.meta.json"],
      sorted(os.listdir(_chal_dir)))
check("带后缀的 id 能读到显示名",
      registry.title_of("challenges", "p1.chal", _DATA) == "一号包",
      registry.title_of("challenges", "p1.chal", _DATA))
check("不带后缀的 id 读同一份信封",
      registry.title_of("challenges", "p1", _DATA) == "一号包")
check("display_name 回落成 id（含后缀，调用方据此开包）",
      registry.display_name("challenges", "p1.chal", _DATA) == "一号包")
check("信封文件名不带 .chal.chal",
      registry.envelope_path_of("challenges", "p1.chal", _DATA).endswith(
          os.path.join("challenges", "p1.meta.json")),
      registry.envelope_path_of("challenges", "p1.chal", _DATA))

# ---------------- 3/4. 世界包往返 ----------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from services.worlds.service import WorldManager  # noqa: E402

_WORLD = "dispW"
_world_root = os.path.join(_DATA, "worlds", _WORLD)
_chal_pack_dir = os.path.join(_world_root, "challenges")
os.makedirs(_chal_pack_dir, exist_ok=True)
for base in ("p1", "p2"):
    with open(os.path.join(_chal_pack_dir, f"{base}.chal"), "wb") as handle:
        handle.write(b"bundled")
_manifest = WorldPackManifest(world_id=_WORLD, name="显示名往返")
_manifest.resources = {"challenges": ["p1.chal", "p2.chal"]}
with open(os.path.join(_world_root, "world.json"), "w", encoding="utf-8") as handle:
    json.dump(_manifest.to_dict(), handle, ensure_ascii=False)

# 自由目录里的 p1 / p2 信封（导出时应当被带走）
registry.set_title("challenges", "p1.chal", "一号包", _DATA)
registry.set_title("challenges", "p2.chal", "二号包", _DATA)

_mgr = WorldManager(_DATA)
_export = os.path.join(_DATA, "out")
os.makedirs(_export, exist_ok=True)
_export_target = os.path.join(_export, "exported")
os.makedirs(_export_target, exist_ok=True)
_mgr._copy_envelopes(_manifest, _export_target)
_exported = sorted(os.listdir(os.path.join(_export_target, "challenges"))) \
    if os.path.isdir(os.path.join(_export_target, "challenges")) else []
check("挑战包信封随包导出（不是 .chal.meta.json）",
      _exported == ["p1.meta.json", "p2.meta.json"], _exported)
_exported_title = ""
try:
    with open(os.path.join(_export_target, "challenges", "p1.meta.json"),
              encoding="utf-8") as handle:
        _exported_title = json.load(handle).get("title", "")
except OSError:
    pass
check("包内信封带着显示名本身", _exported_title == "一号包", _exported_title)

# 安装侧：包内 challenges/ 下的 .chal 落到自由挑战目录；信封应随之落盘
_INSTALL_DATA = tempfile.mkdtemp(prefix="display_install_")
_inst = os.path.join(_INSTALL_DATA, "worlds", _WORLD, "challenges")
os.makedirs(_inst, exist_ok=True)
for base in ("p1", "p2"):
    with open(os.path.join(_inst, f"{base}.chal"), "wb") as handle:
        handle.write(b"bundled")
with open(os.path.join(_inst, "p1.meta.json"), "w", encoding="utf-8") as handle:
    json.dump({"schema": "gg.challenges/1", "id": "p1", "title": "一号包"},
              handle, ensure_ascii=False)
_inst_manifest = WorldPackManifest(world_id=_WORLD, name="装包")
_inst_manifest.resources = {"challenges": ["p1.chal"]}
with open(os.path.join(_INSTALL_DATA, "worlds", _WORLD, "world.json"),
          "w", encoding="utf-8") as handle:
    json.dump(_inst_manifest.to_dict(), handle, ensure_ascii=False)

_inst_mgr = WorldManager(_INSTALL_DATA)
_renamed = {}
_inst_mgr._restore_envelopes(_inst_manifest,
                             os.path.join(_INSTALL_DATA, "worlds", _WORLD), _renamed)
_restored = os.path.join(_INSTALL_DATA, "packs", "challenges", "p1.meta.json")
check("解散时包内信封写回自由目录（路径不带 .chal）",
      os.path.isfile(_restored), sorted(
          os.listdir(os.path.join(_INSTALL_DATA, "packs", "challenges")))
      if os.path.isdir(os.path.join(_INSTALL_DATA, "packs", "challenges")) else [])
check("写回后按带后缀的 id 仍读得到显示名",
      registry.title_of("challenges", "p1.chal", _INSTALL_DATA) == "一号包",
      registry.title_of("challenges", "p1.chal", _INSTALL_DATA))

# ---------------- 5. 包内缺信封时不借用自由目录的名称 ----------------
_SAME = tempfile.mkdtemp(prefix="display_same_")
_SAME_WORLD = "sameW"
_same_root = os.path.join(_SAME, "worlds", _SAME_WORLD)
os.makedirs(os.path.join(_same_root, "landmarks"), exist_ok=True)
with open(os.path.join(_same_root, "landmarks", "style_x.csv"), "w",
          encoding="utf-8-sig", newline="") as handle:
    handle.write("name,size,dimension,frequency,horizontal_type,address,address_mode\n")
    handle.write("包内地标,100,vertical,common,,,\n")
_same_manifest = WorldPackManifest(world_id=_SAME_WORLD, name="同 id 包")
_same_manifest.resources = {"landmarks": ["style_x"]}
with open(os.path.join(_same_root, "world.json"), "w", encoding="utf-8") as handle:
    json.dump(_same_manifest.to_dict(), handle, ensure_ascii=False)

# 自由目录里同 id 的资源，带一个完全不同的显示名
registry.set_title("landmarks", "style_x", "自由层的另一个风格", _SAME)

_state = WorldState(_SAME)
_state.set_active(_same_manifest)
check("包接管后 load 到的是包内载荷",
      registry.read_path("landmarks", "style_x", _SAME, _state).startswith(
          os.path.normpath(_same_root)))

_title = registry.title_of("landmarks", "style_x", _SAME, _state)
check("包内无信封时显示名为空（不借用自由层同 id 的名称）",
      _title == "", _title)
_name = registry.display_name("landmarks", "style_x", _SAME, _state)
check("此时界面回落成 id 而不是别人的名字",
      _name == "style_x", _name)

# 包内补上信封后应当读到包内那份，而不是自由层那份
envelope_mod.save_envelope(os.path.join(_same_root, "landmarks"), "landmarks",
                           "style_x", {"title": "包内的名字"})
check("包内信封优先于自由层同 id 信封",
      registry.title_of("landmarks", "style_x", _SAME, _state) == "包内的名字",
      registry.title_of("landmarks", "style_x", _SAME, _state))
_state.set_active(None)
check("卸下世界包后回到自由层那份名称",
      registry.title_of("landmarks", "style_x", _SAME) == "自由层的另一个风格")

# ---------------- 清理 ----------------
for _path in (_DATA, _INSTALL_DATA, _SAME, _chal_dir):
    if os.path.isdir(_path):
        shutil.move(_path, tempfile.mkdtemp(prefix="display_retired_"))

_log.flush()
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
if failures:
    print(f"[check_resource_display] FAILED {len(failures)}/{total}: {failures}")
else:
    print(f"[check_resource_display] PASSED {total}/{total}")
print(f"[check_resource_display] report: {_report_path}")
sys.exit(1 if failures else 0)
