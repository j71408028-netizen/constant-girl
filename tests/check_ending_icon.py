"""结局图标共享封装自检（无 GUI、不触 GL）。

用法：``python tests/check_ending_icon.py``
输出：控制台一行 ASCII 结论 + UTF-8 报告文件路径（报告在临时目录，含全部明细）。

覆盖 ``dungeon/window/ending_icon`` 可离线验证的部分，锁住入口页轮播 /
实时结局 / 回放共用的同一套口径：

1. ``resolve_ending_icon``：绝对路径 → 副本根 → 自由副本根的候选顺序、
   分隔符归一、``..`` 段过滤、缺失与空路径返回 None；
2. ``square_icon_canvas``：等比缩放、正方形留白、居中、小图不放大；
3. 显示链字段：``load_ending_icon_texture`` 的 None 静默口径、launcher 对
   ``resolve_ending_icon`` 的再导出、``_drain_gpu_textures`` 收编
   ``_ending_icon_texture`` 句柄；
4. ``_update_ending_icon`` 降级分支（文件缺失 / 图片损坏 / 上传失败 / 成功）
   的日志与句柄状态——真实上传桩掉，GL 路径由窗口运行背书。
"""

import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_report_path = os.path.join(tempfile.mkdtemp(prefix="ending_icon_check_"), "report.txt")
_log = open(_report_path, "w", encoding="utf-8")
sys.stdout = _log
sys.stderr = _log

failures = []
total = 0


def check(name, ok, extra=""):
    global total
    total += 1
    print(("  OK   " if ok else "  FAIL ") + name + (f"  <{extra}>" if extra and not ok else ""))
    if not ok:
        failures.append(name)


from PIL import Image  # noqa: E402

import dungeon.window.ending_icon as ending_icon  # noqa: E402
from dungeon.window.ending_icon import (  # noqa: E402
    load_ending_icon_texture, resolve_ending_icon, square_icon_canvas)

tmp = tempfile.mkdtemp(prefix="ending_icon_")

# ---------------- 1. resolve_ending_icon ----------------
sid = "sc_icon_test"
repo_root = os.path.join(tmp, "repo")
os.makedirs(os.path.join(repo_root, sid, "images"))
icon_rel = os.path.join(repo_root, sid, "images", "end.png")
open(icon_rel, "wb").write(b"png")
free_root = os.path.join(tmp, "free")
os.makedirs(os.path.join(free_root, "sc_free"))
icon_free = os.path.join(free_root, "sc_free", "end.png")
open(icon_free, "wb").write(b"png")

_real_free_root = ending_icon.free_dungeons_root
ending_icon.free_dungeons_root = lambda: free_root
try:
    repo = types.SimpleNamespace(root=repo_root)
    check("空路径返回 None", resolve_ending_icon(repo, sid, "") is None)
    check("绝对路径命中",
          resolve_ending_icon(repo, sid, icon_rel) == os.path.normpath(icon_rel))
    check("副本根相对路径命中（正斜杠）",
          resolve_ending_icon(repo, sid, "images/end.png")
          == os.path.normpath(icon_rel))
    check("反斜杠分隔符同样命中",
          resolve_ending_icon(repo, sid, "images\\end.png")
          == os.path.normpath(icon_rel))
    check("repo 为 None 时落自由副本根",
          resolve_ending_icon(None, "sc_free", "end.png")
          == os.path.normpath(icon_free))
    check("路径穿越被过滤（.. 段忽略）",
          resolve_ending_icon(repo, sid, "../outside.png") is None)
    check("两处都缺失返回 None",
          resolve_ending_icon(repo, sid, "images/missing.png") is None)
    check("无 repo 且无 scenario_id 返回 None",
          resolve_ending_icon(None, "", "end.png") is None)
finally:
    ending_icon.free_dungeons_root = _real_free_root

# ---------------- 2. square_icon_canvas ----------------
box = 96
canvas = square_icon_canvas(Image.new("RGBA", (300, 150), (255, 0, 0, 255)), box)
check("画布恰为 box×box", canvas.size == (box, box), canvas.size)
# 内容 300×150 → 等比缩到 96×48，垂直方向上下各留 24 透明边
check("非方形内容等比缩放进边长内",
      canvas.getpixel((48, 24))[:3] == (255, 0, 0)
      and canvas.getpixel((48, 0))[3] == 0 and canvas.getpixel((48, 95))[3] == 0,
      (canvas.getpixel((48, 24)), canvas.getpixel((48, 0))))
check("水平方向铺满无留白",
      canvas.getpixel((0, 24))[:3] == (255, 0, 0)
      and canvas.getpixel((95, 24))[:3] == (255, 0, 0))

small = square_icon_canvas(Image.new("RGBA", (64, 32), (0, 255, 0, 255)), box)
cx = (box - 64) // 2
cy = (box - 32) // 2
check("小于 box 的图不放大、居中放置",
      small.size == (box, box)
      and small.getpixel((cx, cy))[:3] == (0, 255, 0)
      and small.getpixel((0, 0))[3] == 0)

check("竖长图按高缩放",
      square_icon_canvas(Image.new("RGBA", (50, 200), (0, 0, 255, 255)), box)
      .getpixel((box // 2, box // 2))[:3] == (0, 0, 255))

# ---------------- 3. 显示链字段 ----------------
check("load 无图标静默返回", load_ending_icon_texture(None, box) == (None, ""))

from dungeon.window.launcher import resolve_ending_icon as _from_launcher  # noqa: E402

check("launcher 仍再导出 resolve_ending_icon", _from_launcher is resolve_ending_icon)

from dungeon.window import ui as ui_mod  # noqa: E402

tex = object()
stub = types.SimpleNamespace(_ending_icon_texture=tex)
handles = ui_mod.DungeonWindowUI._drain_gpu_textures(stub)
check("drain 收编 _ending_icon_texture 并清空",
      tex in handles and stub._ending_icon_texture is None)
check("drain 对空会话安全",
      ui_mod.DungeonWindowUI._drain_gpu_textures(types.SimpleNamespace()) == [])

# ---------------- 4. _update_ending_icon 降级分支 ----------------
from dungeon import process_log  # noqa: E402

_logs = []
process_log.log = lambda msg: _logs.append(str(msg))

_load_calls = []


def _stub_load(pil, box):
    _load_calls.append((pil, box))
    return object(), ""


ui_mod.load_ending_icon_texture = _stub_load


def _session(icon_path, texture=None):
    return types.SimpleNamespace(
        ending_icon_path=icon_path, scenario_repo=None, scenario_id=sid,
        _dpi_scale=1.0, _ending_icon_texture=texture)


ui_mod.DungeonWindowUI._update_ending_icon(_session("no/such.png"))
check("文件缺失记明确日志且不调上传",
      _logs[-1] == "[Ending] 结局图标文件不存在: no/such.png" and not _load_calls, _logs[-1])

bad = os.path.join(tmp, "bad.png")
open(bad, "wb").write(b"not-an-image")
ui_mod.DungeonWindowUI._update_ending_icon(_session(bad))
check("图片损坏记加载失败且不调上传",
      _logs[-1].startswith("[Ending] 结局图标加载失败") and len(_load_calls) == 0, _logs[-1])

good = os.path.join(tmp, "ok.png")
Image.new("RGBA", (64, 32), (255, 0, 0, 255)).save(good)
ui_mod.load_ending_icon_texture = lambda pil, box: (None, "no gl ctx")
self3 = _session(good)
ui_mod.DungeonWindowUI._update_ending_icon(self3)
check("上传失败记原因且不留句柄",
      self3._ending_icon_texture is None
      and _logs[-1] == f"[Ending] 结局图标纹理上传失败 {os.path.normpath(good)}: no gl ctx",
      _logs[-1])

_holder = {}


def _ok_load(pil, box):
    assert pil.size == (64, 32) and box == 96   # 96 = _ENDING_ICON_SIZE @ dpi=1
    return _holder.setdefault("tex", object()), ""


ui_mod.load_ending_icon_texture = _ok_load
old = object()
self4 = _session(good, texture=old)
ui_mod.DungeonWindowUI._update_ending_icon(self4)
check("成功路径替换旧句柄",
      self4._ending_icon_texture is _holder["tex"] and self4._ending_icon_texture is not old)

# ---------------- 结论 ----------------
_log.flush()
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
if failures:
    print(f"[check_ending_icon] FAILED {len(failures)}/{total}: {failures}")
else:
    print(f"[check_ending_icon] PASSED {total}/{total}")
print(f"[check_ending_icon] report: {_report_path}")
sys.exit(1 if failures else 0)
