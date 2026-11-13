"""维护入口自检：子命令分发与运行时迁移全链（夹具数据在系统临时目录）。

用法：``python tests/check_maintenance_entry.py``
输出：控制台一行 ASCII 结论 + UTF-8 报告文件路径。

覆盖：
1. ``app.maintenance.dispatch``：三个子命令命中即执行、未知命令与纯参数
   不拦截主程序启动；
2. 运行时迁移（走 :mod:`services.migration_v1_to_v2` 的公开 API）：
   v1 形状夹具 → 预览发现变更 → 落盘（备份目录存在、十步产物为当前形状）→
   第二遍预览 0 处变更（幂等）→ 备份覆盖回滚后恢复旧形状。

不创建 Tk 窗口：``dispatch`` 经 ``runner`` 注入执行，迁移只调内核 API，
窗口层（确认 / 报告 / 打开目录按钮）留给发行包人工验收。
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_report_path = os.path.join(tempfile.mkdtemp(prefix="maintenance_entry_"),
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


from app.maintenance import COMMANDS, dispatch  # noqa: E402
from services.migration_v1_to_v2 import (apply as apply_migration,  # noqa: E402
                                         preview, report_markdown)

# ---------------- 子命令分发 ----------------

calls = []
runner = calls.append

check("空参数走主程序", dispatch([], runner=runner) is False and not calls)
check("纯旗标不拦截", dispatch(["--mini-game-host"], runner=runner) is False)
check("未知位置参数不拦截", dispatch(["unknown-mode"], runner=runner) is False)
check("migrate 命中并执行", dispatch(["migrate"], runner=runner) is True
      and calls == ["migrate"])
check("check-update 命中", dispatch(["check-update"], runner=runner) is True
      and calls[-1] == "check-update")
check("apply-update 占位可路由", dispatch(["apply-update"], runner=runner) is True
      and calls[-1] == "apply-update")
check("旗标后的子命令仍命中",
      dispatch(["--verbose", "migrate"], runner=runner) is True
      and calls[-1] == "migrate")
check("子命令表完整", tuple(sorted(COMMANDS))
      == ("apply-update", "check-update", "migrate"))


# ---------------- 运行时迁移全链 ----------------

def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)


root = tempfile.mkdtemp(prefix="maintenance_entry_data_")
data = os.path.join(root, "data")
_write_json(os.path.join(data, "user", "settings.json"), {
    "name_table": "A", "news_table": "A", "preset_table": "A",
    "personality_table": "A",
    "theme_mode": "Dark", "quip_rate_factor": 1.0, "voice_proxy": "http://x",
    "selected_styles": ["ChineseMix"], "selected_quip_styles": ["Events"],
    "api_url": "https://example.invalid/v1",
})
_write_json(os.path.join(data, "packs", "landmarks", "ChineseMix.json"),
            [{"name": "高楼", "size": 150}, {"name": "大桥", "size": 2000}])
_write_json(os.path.join(data, "packs", "quips", "Events.json"),
            {"small": {"1_1": ["第一条描述"], "1_2": ["第二条描述"]}})
for member in ("names", "presets"):
    os.makedirs(os.path.join(data, "static", member), exist_ok=True)
with open(os.path.join(data, "static", "names", "A.csv"), "w",
          encoding="utf-8-sig", newline="") as handle:
    handle.write("name,\n张三,\n李四,\n")
with open(os.path.join(data, "static", "presets", "A.csv"), "w",
          encoding="utf-8-sig", newline="") as handle:
    handle.write("height,weight\n170,60\n")
_write_json(os.path.join(data, "user", "endings.json"),
            {"records": [{"dungeon_id": "_default", "ending": "normal"}]})

plan = preview(data)
check("预览发现变更", len(plan.changes) > 0, len(plan.changes))
check("预览不落盘（旧地标文件还在）",
      os.path.isfile(os.path.join(data, "packs", "landmarks", "ChineseMix.json")))

worker = apply_migration(data)
check("落盘后变更数不少于预览（信封步只在落盘时补一条）",
      len(worker.changes) >= len(plan.changes),
      (len(worker.changes), len(plan.changes)))
check("落盘比预览多的只有信封补写",
      len(worker.changes) - len(plan.changes) <= 1
      and any("信封" in detail for _step, detail in worker.changes))
check("整目录备份存在",
      worker.backup_dir and os.path.isdir(worker.backup_dir)
      and os.path.isfile(os.path.join(worker.backup_dir, "packs", "landmarks",
                                      "ChineseMix.json")))
check("地标风格已转 CSV",
      os.path.isfile(os.path.join(data, "packs", "landmarks", "chinese_mix.csv"))
      and not os.path.exists(os.path.join(data, "packs", "landmarks",
                                          "ChineseMix.json")))
check("描述风格已转目录布局",
      os.path.isfile(os.path.join(data, "packs", "quips", "events", "quips.csv"))
      and os.path.isfile(os.path.join(data, "packs", "quips", "events",
                                      "config.json")))
check("取材表已归组",
      os.path.isfile(os.path.join(data, "static", "materials", "A", "names.csv"))
      and os.path.isfile(os.path.join(data, "static", "materials", "A",
                                      "presets.csv")))
check("设置分家完成",
      os.path.isfile(os.path.join(data, "user", "resource_settings.json")))
check("结局索引已改 scenario_id",
      json.load(open(os.path.join(data, "user", "endings.json"),
                     encoding="utf-8"))["records"][0].get("scenario_id") == "default")
check("旧主文件移入 v1-legacy",
      os.path.isdir(os.path.join(data, "migrated", "v1-legacy")))
check("报告可渲染", report_markdown(worker, True).startswith("# v1.0.0 → 2.0"))

second = preview(data)
check("第二遍预览 0 处变更（幂等）", len(second.changes) == 0,
      [detail for _step, detail in second.changes][:5])

# 回滚：把备份覆盖回去，确认恢复旧形状
shutil.rmtree(data)
shutil.copytree(worker.backup_dir, data)
check("回滚后旧地标文件恢复",
      os.path.isfile(os.path.join(data, "packs", "landmarks", "ChineseMix.json")))
check("回滚后转换产物不在",
      not os.path.exists(os.path.join(data, "packs", "landmarks",
                                      "chinese_mix.csv")))

# ---------------- 结论 ----------------
_log.flush()
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
if failures:
    print(f"[check_maintenance_entry] FAILED {len(failures)}/{total}: {failures}")
else:
    print(f"[check_maintenance_entry] PASSED {total}/{total}")
print(f"[check_maintenance_entry] report: {_report_path}")
sys.exit(1 if failures else 0)
