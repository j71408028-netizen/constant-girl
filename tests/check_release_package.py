"""发行打包器自检：macOS .app 归档对象、许可进包与校验和收口（audit R2/R4）。

用法：``python tests/check_release_package.py``
输出：控制台一行 ASCII 结论 + UTF-8 报告文件路径。

覆盖 ``build/release/package.py`` 的纯逻辑（不跑真实 PyInstaller 构建）：

1. R2 产物定位：macOS windowed 选 ``dist/<name>.app``（缺 .app 大声失败），
   其余平台仍是 ``dist/<name>`` 目录；``.app`` 经暂存层与启动器同层归档；
2. 维护启动器正文：macOS 版先找同层 ``*.app``、再退回裸可执行文件（Nuitka
   对照包无 .app 结构），三平台正文均为 ASCII；
3. R4 许可进包：仓库根 LICENSE 复制进暂存层；依赖许可从 ``*.dist-info``
   收集（随包许可文件、PEP 639 ``licenses/``、METADATA 兜底三路）并出索引；
4. 校验和收口：发布说明与单次校验和文件名带平台后缀互不覆盖；
   ``--sums-only`` 对最终附件集合（zip + 发布说明）统一生成 SHA256SUMS.txt，
   不混入各平台单跑的校验和与零散文件。

全部使用系统临时目录，不写仓库数据区。
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_report_path = os.path.join(tempfile.mkdtemp(prefix="release_package_"),
                            "report.txt")
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


def _load_package_module():
    root = Path(__file__).resolve().parent.parent
    mod_path = root / "build" / "release" / "package.py"
    spec = importlib.util.spec_from_file_location("release_package", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pkg = _load_package_module()

ROOT = Path(tempfile.mkdtemp(prefix="release_pkg_fixtures_"))


def _mk(path: Path, content: str = "x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _fake_app_bundle(dist: Path, name: str):
    """伪造 PyInstaller macOS windowed 产物：.app bundle + 裸 COLLECT 目录。"""
    _mk(dist / f"{name}.app" / "Contents" / "MacOS" / name, "Mach-O")
    _mk(dist / f"{name}.app" / "Contents" / "Resources" / "main.py", "pass")
    _mk(dist / name / name, "raw collect exe")


# ---------------- R2：产物定位与暂存层 ----------------

src = ROOT / "src"
_fake_app_bundle(src / "dist", "ConstantGirl")

app = pkg.locate_pyinstaller_bundle(src, "ConstantGirl", darwin=True)
check("macOS 定位到 .app", app == src / "dist" / "ConstantGirl.app", app)
check("macOS .app 真实存在", app.is_dir())

try:
    pkg.locate_pyinstaller_bundle(ROOT / "empty_src", "ConstantGirl", darwin=True)
    check("缺 .app 大声失败", False, "未抛 SystemExit")
except SystemExit:
    check("缺 .app 大声失败", True)

try:
    pkg.locate_pyinstaller_bundle(ROOT / "empty_src", "constant-girl", darwin=False)
    check("缺 dist/<name> 大声失败", False, "未抛 SystemExit")
except SystemExit:
    check("缺 dist/<name> 大声失败", True)

dir_bundle = pkg.locate_pyinstaller_bundle(src, "ConstantGirl", darwin=False)
check("非 macOS 仍是 dist/<name> 目录", dir_bundle == src / "dist" / "ConstantGirl",
      dir_bundle)

# 接线行为：build_bundle 最终交给 locate 的口径（stub 掉 PyInstaller 调用，
# 临时把 sys.platform 换成 darwin，覆盖 Windows 上走不到的分支）。
_mk(src / "main.py", "pass")
_real_run, _real_platform = pkg.run, sys.platform
pkg.run = lambda cmd, cwd=None: None
try:
    sys.platform = "darwin"
    wired_app = pkg.build_bundle(Path("unused/python.exe"), src, "ConstantGirl",
                                 targets=[], console=False)
    sys.platform = "linux"
    wired_dir = pkg.build_bundle(Path("unused/python.exe"), src, "ConstantGirl",
                                 targets=[], console=False)
finally:
    pkg.run, sys.platform = _real_run, _real_platform
check("build_bundle 接线：macOS 返回 .app",
      wired_app == src / "dist" / "ConstantGirl.app", wired_app)
check("build_bundle 接线：非 macOS 返回 dist/<name>",
      wired_dir == src / "dist" / "ConstantGirl", wired_dir)

work = ROOT / "work"
work.mkdir()
stage = pkg.stage_bundle(app, work)
check(".app 移入暂存层", stage == work / "stage" and (stage / "ConstantGirl.app").is_dir())
check("dist/ 里不再留 .app", not (src / "dist" / "ConstantGirl.app").exists())
check("裸 COLLECT 目录不进暂存层", not (stage / "ConstantGirl").exists())
same = pkg.stage_bundle(dir_bundle, work)
check("非 .app 目录原地作暂存层", same == dir_bundle)

# ---------------- 启动器正文（含 Nuitka 无 .app 的退路） ----------------

body = pkg.launcher_body("darwin", "migrate", "constant-girl")
check("macOS 启动器找同层 .app", 'APP="$(ls -d *.app 2>/dev/null | head -n 1)"' in body)
check("macOS 启动器走 app 内二进制",
      'exec "$APP/Contents/MacOS/$(basename "$APP" .app)" migrate' in body)
check("macOS 启动器有裸可执行退路（Nuitka 对照包）",
      body.rstrip().endswith('exec "./constant-girl" migrate'), body)
check("macOS 启动器正文 ASCII",
      all(ord(c) < 128 for c in body))
for plat, name in (("win", "constant-girl.exe"), ("linux", "constant-girl")):
    body_p = pkg.launcher_body(plat, "check-update", "constant-girl")
    check(f"{plat} 启动器引用主程序 {name}", name in body_p
          and all(ord(c) < 128 for c in body_p))

win_bundle = work / "stage_win"
win_bundle.mkdir()
written = pkg.write_maintenance_launchers(win_bundle, "constant-girl", "ConstantGirl")
check("Windows 启动器落盘为 .bat", written == ["迁移旧版数据.bat", "检查更新.bat"], written)
check("Windows 启动器内容 ASCII",
      all(all(b < 128 for b in (win_bundle / n).read_bytes()) for n in written))
check("Windows 启动器调用 migrate 子命令",
      "constant-girl.exe\" migrate" in (win_bundle / "迁移旧版数据.bat").read_text(encoding="ascii"))

# ---------------- R4：许可进包 ----------------

lic_src = ROOT / "lic_src"
lic_src.mkdir()
(lic_src / "LICENSE").write_text("MIT text", encoding="utf-8")
target = ROOT / "stage_lic"
target.mkdir()
check("LICENSE 复制进暂存层", pkg.copy_license(lic_src, target) == "LICENSE"
      and (target / "LICENSE").read_text() == "MIT text")
both = ROOT / "lic_src3"
_mk(both / "LICENSE", "A")
_mk(both / "LICENSE.md", "B")
target2 = ROOT / "stage_lic2"
target2.mkdir()
check("许可候选按序取第一个", pkg.copy_license(both, target2) == "LICENSE")
check("找不到许可返回 None", pkg.copy_license(ROOT / "no_lic", target2) is None)

site = ROOT / "site-packages"
_mk(site / "A_pkg-1.0.dist-info" / "METADATA", "Metadata-Version: 2.1\nName: A\n")
_mk(site / "A_pkg-1.0.dist-info" / "LICENSE", "Apache 2.0 text")
_mk(site / "b_dist-2.3.4.dist-info" / "METADATA", "Metadata-Version: 2.1\nName: b\n")
_mk(site / "b_dist-2.3.4.dist-info" / "licenses" / "MIT.txt", "MIT (PEP 639)")
_mk(site / "C_Dist-0.1.dist-info" / "METADATA",
   "Metadata-Version: 2.1\nName: C\nLicense: BSD-3-Clause\n\nlong description\n")
_mk(site / "D_Dist-9.9.dist-info" / "METADATA",
   "Metadata-Version: 2.1\nName: D\n\nno license header\n")
out_lic = ROOT / "stage_dep" / "licenses"
dists = pkg.collect_dependency_licenses(site, out_lic)
check("四个发行版全部登记", dists == ["A_pkg", "b_dist", "C_Dist", "D_Dist"], dists)
check("dist-info 根的许可文件被收集",
      (out_lic / "A_pkg" / "LICENSE").read_text() == "Apache 2.0 text")
check("PEP 639 licenses/ 子目录被收集",
      (out_lic / "b_dist" / "MIT.txt").read_text() == "MIT (PEP 639)")
check("METADATA 的 License 声明兜底成 NOTICE.txt",
      (out_lic / "C_Dist" / "NOTICE.txt").exists()
      and "BSD-3-Clause" in (out_lic / "C_Dist" / "NOTICE.txt").read_text())
check("无许可信息也有目录但不出文件",
      (out_lic / "D_Dist").is_dir()
      and not any((out_lic / "D_Dist").iterdir()))
index = (out_lic / "INDEX.txt").read_text(encoding="utf-8")
check("索引列出四个发行版与实际文件",
      index.count("\n") == 4 and "A_pkg==1.0: LICENSE" in index
      and "b_dist==2.3.4: MIT.txt" in index
      and "C_Dist==0.1: NOTICE.txt" in index
      and "D_Dist==9.9: （未找到许可信息）" in index, index)

real_site = pkg.site_packages_dir(Path(sys.executable))
check("site-packages 探测返回真实目录", real_site is not None and real_site.is_dir())

# ---------------- 暂存层装配 ----------------

asm_work = ROOT / "asm_work"
asm_work.mkdir()
asm_bundle = asm_work / "bundle"
asm_bundle.mkdir()
_mk(asm_bundle / "constant-girl.exe", "exe")
asm_src = ROOT / "asm_src"
_mk(asm_src / "LICENSE", "MIT")
stage2, logs2 = pkg.prepare_runtime_stage(asm_bundle, asm_work, asm_src, None,
                                          "constant-girl", "ConstantGirl")
check("装配返回产物目录本身", stage2 == asm_bundle)
check("装配日志含许可/跳过/启动器三项",
      len(logs2) == 3 and any("项目许可：LICENSE" in l for l in logs2)
      and any("跳过" in l for l in logs2) and any("维护启动器" in l for l in logs2),
      logs2)
check("装配后暂存层含许可与启动器",
      (stage2 / "LICENSE").is_file()
      and (stage2 / "迁移旧版数据.bat").is_file())

# ---------------- 归档布局 ----------------

out_zip = ROOT / "layout.zip"
count = pkg.zip_tree(stage2, out_zip, arc_prefix="constant-girl/")
names = zipfile.ZipFile(out_zip).namelist()
check("zip 条目带技术名前缀",
      "constant-girl/LICENSE" in names
      and "constant-girl/迁移旧版数据.bat" in names
      and "constant-girl/constant-girl.exe" in names, names[:6])
check("zip 条目数与文件数一致", count == len(names) == 4, (count, len(names)))

# ---------------- 校验和与发布说明：平台后缀互不覆盖 ----------------

out = ROOT / "out"
out.mkdir()
zip_a = _mk(out / "constant-girl-2.0.0-windows-x64.zip", "payload-a")
zip_b = _mk(out / "constant-girl-2.0.0-macos-arm64.zip", "payload-b")
notes_a = pkg.write_release_notes(out, "ConstantGirl", "2.0.0", "v2.0.0",
                                  [zip_a], "windows", "x64")
notes_b = pkg.write_release_notes(out, "ConstantGirl", "2.0.0", "v2.0.0",
                                  [zip_b], "macos", "arm64")
check("发布说明按平台分文件", notes_a.is_file() and notes_b.is_file()
      and notes_a.name != notes_b.name)
check("发布说明含平台产物清单",
      "constant-girl-2.0.0-windows-x64.zip" in notes_a.read_text(encoding="utf-8")
      and "constant-girl-2.0.0-macos-arm64.zip" in notes_b.read_text(encoding="utf-8"))
sums_a = pkg.write_checksums(out, [zip_a, notes_a], "2.0.0", "windows", "x64")
sums_b = pkg.write_checksums(out, [zip_b, notes_b], "2.0.0", "macos", "arm64")
check("单次校验和按版本与平台分文件",
      sums_a.name == "SHA256SUMS-2.0.0-windows-x64.txt"
      and sums_b.name == "SHA256SUMS-2.0.0-macos-arm64.txt"
      and sums_a.is_file() and sums_b.is_file())
line_a = sums_a.read_text(encoding="utf-8").strip().splitlines()
check("单次校验和格式与哈希正确",
      len(line_a) == 2
      and line_a[0].startswith(pkg.sha256_file(notes_a) + "  ")
      and line_a[1].startswith(pkg.sha256_file(zip_a) + "  "),
      line_a)

# ---------------- 统一 SHA256SUMS.txt（--sums-only） ----------------

_mk(out / "SHA256SUMS-2.0.0-windows-x64.txt.bak", "stale sums")  # 不带 .txt 后缀的干扰项
_mk(out / "SHA256SUMS-2.0.0-macos-arm64.txt", "stale sums")
_mk(out / "stray.bin", "junk")
unified = pkg.write_unified_checksums(out)
expect_names = sorted([zip_a.name, zip_b.name, notes_a.name, notes_b.name])
check("统一校验和只收 zip 与发布说明",
      unified.name == "SHA256SUMS.txt"
      and [l.split("  ")[1] for l in unified.read_text(encoding="utf-8").strip().splitlines()]
      == expect_names,
      unified.read_text(encoding="utf-8"))
check("统一校验和不含单跑文件与零散文件",
      "SHA256SUMS-2.0.0" not in unified.read_text(encoding="utf-8")
      and "stray.bin" not in unified.read_text(encoding="utf-8"))
check("统一校验和哈希可复核",
      all(l.startswith(pkg.sha256_file(out / l.split("  ")[1]) + "  ")
          for l in unified.read_text(encoding="utf-8").strip().splitlines()))

empty_out = ROOT / "empty_out"
empty_out.mkdir()
try:
    pkg.write_unified_checksums(empty_out)
    check("空附件目录大声失败", False, "未抛 SystemExit")
except SystemExit:
    check("空附件目录大声失败", True)

# ---------------- CLI：--sums-only ----------------

cli_out = ROOT / "cli_out"
cli_out.mkdir()
_mk(cli_out / "constant-girl-2.0.0-src.zip", "src")
_mk(cli_out / "RELEASE-NOTES-2.0.0-windows-x64.md", "notes")
proc = subprocess.run(
    [sys.executable, str(pkg.ROOT / "build" / "release" / "package.py"),
     "--sums-only", "--out", str(cli_out)],
    capture_output=True, text=True, env=dict(os.environ, PYTHONUTF8="1"))
check("--sums-only 退出码 0", proc.returncode == 0,
      proc.stdout[-400:] + proc.stderr[-400:])
check("--sums-only 生成 SHA256SUMS.txt",
      (cli_out / "SHA256SUMS.txt").is_file()
      and (cli_out / "SHA256SUMS.txt").read_text(encoding="utf-8").count("\n") == 2)

# ---------------- 结论 ----------------

_log.flush()
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
shutil.rmtree(ROOT, ignore_errors=True)
if failures:
    print(f"[check_release_package] FAILED {len(failures)}/{total}: {failures}")
else:
    print(f"[check_release_package] PASSED {total}/{total}")
print(f"[check_release_package] report: {_report_path}")
sys.exit(1 if failures else 0)
