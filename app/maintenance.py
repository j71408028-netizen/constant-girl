"""发行包维护子命令：迁移旧版数据、检查更新。

全部**手动触发**（用户双击启动器或带子命令运行主程序），不挂自动检查。
本模块自带极简 Tk 窗口，不启动主界面、不构建主程序仓库；窗口化打包没有
控制台，所有过程与结果都在窗口里呈现，异常兜底显示 traceback 而不是静默退出。
"""

import datetime
import os
import sys
import tkinter as tk
import traceback
import webbrowser
from tkinter import font as tk_font

from paths import APP_NAME, APP_VERSION, data_dir as _data_dir, ensure_cwd

#: 维护子命令 → 标题。``apply-update`` 是未来一键更新的占位，先给出可读提示。
COMMANDS = ("migrate", "check-update", "apply-update")

_TEXT_BG = "#f5f2ec"
_TEXT_FG = "#2b2b2b"
_ACCENT = "#7a4a21"

_WINDOW_TITLE = {
    "migrate": f"{APP_NAME} · 迁移旧版数据",
    "check-update": f"{APP_NAME} · 检查更新",
    "apply-update": f"{APP_NAME} · 一键更新",
}


def dispatch(argv, runner=None) -> bool:
    """识别 ``argv`` 里的维护子命令；命中则执行并返回 True（主程序不再启动）。

    只认第一个不以 ``-`` 开头、命中 :data:`COMMANDS` 的参数，其余启动方式
    一律返回 False 走主程序。``runner`` 供测试替换实际的命令执行。
    """
    for arg in argv:
        if arg.startswith("-"):
            continue
        if arg in COMMANDS:
            (runner or _run_command)(arg)
            return True
        break
    return False


def _run_command(command: str):
    try:
        if command == "migrate":
            _run_migrate()
        elif command == "check-update":
            _run_check_update()
        else:
            _show_info(_WINDOW_TITLE[command],
                       "一键更新在后续版本提供；当前请到发布页下载新压缩包后，\n"
                       "解压覆盖旧目录（用户数据不受影响），再运行「迁移旧版数据」。\n\n"
                       f"发布页：见「检查更新」窗口的链接。")
    except Exception:
        _show_error(traceback.format_exc())


# ---------------------------------------------------------------------------
# 通用窗口
# ---------------------------------------------------------------------------

def _make_window(title: str) -> tuple:
    root = tk.Tk()
    root.title(title)
    root.withdraw()
    base = tk_font.nametofont("TkDefaultFont").copy()
    base.configure(size=11)
    root.option_add("*Font", base)
    return root, base


def _show_text_window(title: str, text: str, buttons: tuple = (),
                      width=88, height=22):
    """只读文本窗口；``buttons`` 是 ``(文案, 回调)`` 列表，缺省只有「关闭」。"""
    root, _base = _make_window(title)
    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=12, pady=(12, 6))
    widget = tk.Text(frame, wrap="word", width=width, height=height,
                     background=_TEXT_BG, foreground=_TEXT_FG,
                     relief="flat", padx=10, pady=8)
    scroll = tk.Scrollbar(frame, command=widget.yview)
    widget.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    widget.pack(side="left", fill="both", expand=True)
    widget.insert("1.0", text)
    widget.configure(state="disabled")

    bar = tk.Frame(root)
    bar.pack(fill="x", padx=12, pady=(0, 12))
    for label, callback in (buttons or (("关闭", None),)):
        tk.Button(bar, text=label, width=14, padx=6,
                  command=lambda cb=callback: _close_or_call(root, cb)
                  ).pack(side="right", padx=6, pady=4)

    root.update_idletasks()
    root.deiconify()
    root.mainloop()


def _close_or_call(root, callback):
    root.destroy()
    if callback:
        callback()


def _show_error(text: str):
    try:
        _show_text_window(f"{APP_NAME} · 出错了", text)
    except Exception:
        pass


def _show_info(title: str, text: str):
    _show_text_window(title, text)


# ---------------------------------------------------------------------------
# migrate：迁移旧版数据
# ---------------------------------------------------------------------------

def _format_manual(m) -> str:
    lines = []
    for entry in m.manual:
        lines.append(f"- {entry['category']}：{entry['target']}"
                     f" —— {entry['issue']}"
                     + (f"\n  建议：{entry['advice']}" if entry["advice"] else ""))
    return "\n".join(lines)


def _format_changes(m, limit=400) -> str:
    lines = []
    current = None
    for step, detail in m.changes[:limit]:
        if step != current:
            lines.append(f"\n[{step}]")
            current = step
        lines.append(f"  · {detail}")
    if len(m.changes) > limit:
        lines.append(f"\n（其余 {len(m.changes) - limit} 处变更见报告文件）")
    return "\n".join(lines)


def _run_migrate():
    """预览 → 确认 → 备份落盘 → 报告窗口。"""
    from services.migration_v1_to_v2 import apply as apply_migration, preview, \
        report_markdown

    # 沿用主程序启动逻辑：旧应用目录整体搬迁 + packs/static 引导。
    ensure_cwd()
    data_dir = _data_dir()

    plan = preview(data_dir)
    if not plan.changes:
        text = "数据已是当前格式，无需迁移。"
        if plan.manual:
            text += "\n\n另有需要人工处理的事项：\n\n" + _format_manual(plan)
        _show_info(_WINDOW_TITLE["migrate"], text)
        return

    summary = (f"检测到 v1.0.0 旧格式数据，共 {len(plan.changes)} 处待转换"
               f"，另有 {len(plan.manual)} 项需要人工处理。\n\n"
               "落盘前会把整个数据目录备份到同级 rollback 目录，"
               "备份完成后自动开始转换。\n\n"
               + _format_changes(plan, limit=30)
               + "\n\n要现在开始迁移吗？")
    confirmed = {"value": False}
    _show_text_window(
        _WINDOW_TITLE["migrate"] + "（确认）", summary,
        buttons=(("取消迁移", None),
                 ("开始迁移", lambda: confirmed.__setitem__("value", True))))
    if not confirmed["value"]:
        return

    progress, label = _make_window(_WINDOW_TITLE["migrate"])
    tk.Label(progress, text="正在迁移旧版数据（已先整目录备份）…",
             padx=28, pady=18).pack()
    progress.update()

    worker = apply_migration(_data_dir())
    report_path = os.path.join(_data_dir(), f"migration-report-{_stamp()}.md")
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(report_markdown(worker, True))
    progress.destroy()

    text = (f"迁移完成：{len(worker.changes)} 处变更已落盘。\n"
            f"备份目录：{worker.backup_dir}\n"
            f"报告文件：{report_path}\n")
    if worker.manual:
        text += ("\n以下内容需要人工处理（详见报告）：\n\n"
                 + _format_manual(worker))
    buttons = (("关闭", None),
               ("打开报告", lambda: _open_file(report_path)))
    if worker.backup_dir:
        buttons = (("关闭", None),
                   ("打开报告", lambda: _open_file(report_path)),
                   ("打开备份目录", lambda: _open_file(worker.backup_dir)))
    _show_text_window(_WINDOW_TITLE["migrate"], text, buttons=buttons)


def _stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d%H%M%S")


def _open_file(path: str):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606
        elif sys.platform.startswith("darwin"):
            import subprocess
            subprocess.Popen(["open", path])  # noqa: S603
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])  # noqa: S603
    except OSError:
        pass


# ---------------------------------------------------------------------------
# check-update：检查更新
# ---------------------------------------------------------------------------

def _run_check_update():
    from services.update_check import (UpdateCheckError, compare_versions,
                                       fetch_latest_release)

    try:
        release = fetch_latest_release()
    except UpdateCheckError as exc:
        _show_info(_WINDOW_TITLE["check-update"],
                   f"检查更新失败：\n{exc}\n\n"
                   "请确认网络可用后重试，或直接访问发布页。")
        return

    status = compare_versions(APP_VERSION, release.version)
    if status < 0:
        verdict = (f"发现新版本：{release.version}"
                   f"（当前 {APP_VERSION}）。\n\n"
                   "请到发布页下载对应平台的压缩包，解压覆盖旧目录"
                   "（用户数据不受影响）。")
    elif status > 0:
        verdict = (f"当前版本 {APP_VERSION} 比已发布的 {release.version} 更新"
                   "（可能是开发版）。")
    else:
        verdict = f"已是最新版本（{APP_VERSION}）。"

    text = (f"当前版本：{APP_VERSION}\n"
            f"最新版本：{release.version}\n"
            f"发布标题：{release.title}\n\n{verdict}")
    _show_text_window(
        _WINDOW_TITLE["check-update"], text,
        buttons=(("关闭", None),
                 ("打开发布页", lambda: webbrowser.open(release.html_url))))
