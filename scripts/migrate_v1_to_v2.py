"""v1.0.0 → 2.0 数据目录迁移的开发者命令行入口。

转换内核在 :mod:`services.migration_v1_to_v2`；发行包里的玩家入口走
``app/maintenance.py``（打包版目录的「迁移旧版数据」启动器），本脚本只服务
源码开发场景。

用法::

    python scripts/migrate_v1_to_v2.py                    # 预览
    python scripts/migrate_v1_to_v2.py --apply            # 落盘
    python scripts/migrate_v1_to_v2.py --report plan.md   # 另存 Markdown 清单
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from services.migration_v1_to_v2 import (apply as apply_migration,  # noqa: E402
                                         preview, report_markdown)


def _write_report(m, applied: bool, path: str):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(report_markdown(m, applied))
    print(f"清单已写入 {path}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="v1.0.0 → 2.0 数据目录迁移")
    parser.add_argument("--data-dir", default=os.path.join(REPO_ROOT, "data"),
                        help="数据目录（默认仓库内 data/）")
    parser.add_argument("--apply", action="store_true",
                        help="真正落盘（先整目录备份）")
    parser.add_argument("--report", default="", help="把变更与待办写成 Markdown")
    args = parser.parse_args(argv)
    data_dir = os.path.abspath(args.data_dir)
    if not os.path.isdir(data_dir):
        raise SystemExit(f"数据目录不存在：{data_dir}")

    print(f"数据目录：{data_dir}" + ("（预览）" if not args.apply else ""))
    plan = preview(data_dir)
    if not plan.changes:
        print("\n0 处变更（数据已是当前形状）")
        if plan.manual:
            print(f"另有 {len(plan.manual)} 项需人工处理，见上方或 --report 输出")
        if args.report:
            _write_report(plan, args.apply, args.report)
        return 0
    if not args.apply:
        print(f"\n共 {len(plan.changes)} 处变更、{len(plan.manual)} 项需人工处理；"
              f"未落盘，加 --apply 执行")
        if args.report:
            _write_report(plan, args.apply, args.report)
        return 0

    print(f"\n共 {len(plan.changes)} 处变更，开始落盘")
    worker = apply_migration(data_dir)
    print(f"\n完成：{len(worker.changes)} 处变更；备份在 {worker.backup_dir}")
    if worker.manual:
        print(f"另有 {len(worker.manual)} 项需人工处理，见上方或 --report 输出")
    if args.report:
        _write_report(worker, args.apply, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
