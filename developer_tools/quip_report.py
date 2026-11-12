"""quip 类型 meta 读取 + 类型替换静态检查 + 疑似语法问题溯源。

用法:
    python developer_tools/quip_report.py 风格名 尺寸档 [--data-dir DIR] [--json] [--all]
                                          [--no-grammar] [--samples N]
    python developer_tools/quip_report.py [风格名] [--json]     # 只列可选分组

**一次只检查一个风格的一个尺寸分组**（尺寸档 = small/medium/large/huge/colossal）：
全量跑一遍结论太多，逐组看才读得动。风格或尺寸档少给一个，脚本打印"可选分组清单"
后退出；多给则报错退出。

本脚本只负责**读盘与呈现**；判据全在 ``services/exploration/quip_lint.py``，主程序
描述管理页的「校验」按钮走同一个 :func:`lint_style`，两处结论不会分叉。检查内容见
那个模块的说明（meta 声明 / 标记格式 / 类型替换 / 组合级接缝 / 单条文本排版）。

输出两种形态：缺省是给人扫一眼的简略结论（一条一行，组合级问题附缩进的溯源链），
详细视图（meta 表、语法统计）只在 ``--json`` 里——那是调判据的人要看的，改语料的
人用界面的诊断框更快。退出码：发现 error 级问题返回 1，否则 0（便于挂进自检门禁）；
分组选错返回 2。

可见范围：只检查所选尺寸档，所以"某细分编号全风格没人用""某体型档结构坏"这类结论
只在该档被检查时才会出现——不要把它当成整个风格的总检。
"""

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.exploration.quip_lint import (  # noqa: E402
    SIZE_CATS, TAG_RE, format_extra, format_loc, lint_style,
)


def load_style_file(style_dir):
    """读 ``<风格>/quips.csv`` 与 ``config.json``，返回 (data, error)。

    返回形状沿用分析器使用的 ``{尺寸档: {"介入度_破坏性": [条目]}}``，配置放进 ``_meta``。
    CSV 的坏行跳过；配置解析失败直接报错。

    这里不复用 ``QuipRepo.load`` / ``read_quips_csv``：那两处遇到坏坐标键会抛异常，
    或把空正文行当坏行丢掉，而"坐标写坏""正文为空"正是本工具要报的错——读取阶段先
    兜住，校验器才看得见它们。
    """
    csv_path = os.path.join(style_dir, "quips.csv")
    if not os.path.isfile(csv_path):
        return None, f"找不到 {csv_path}"
    try:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError as e:
        return None, f"CSV 读取失败：{e}"
    style_name = os.path.basename(style_dir)
    data = {}
    for row in rows:
        try:
            size = str(row.get("size_category") or "").strip()
            intrusion = int(str(row.get("intrusion") or "").strip())
            destruction = int(str(row.get("destruction") or "").strip())
        except (TypeError, ValueError):
            continue
        text = row.get("text")
        if not size or text is None:
            continue
        item = {
            "text": text,
            "style": str(row.get("style") or "").strip() or style_name,
        }
        try:
            item["step"] = float(str(row.get("step") or "").strip())
        except (TypeError, ValueError):
            item["step"] = 0.0
        summary = str(row.get("summary") or "").strip()
        if summary:
            item["summary"] = summary
        data.setdefault(size, {}).setdefault(
            f"{intrusion}_{destruction}", []).append(item)
    config_path = os.path.join(style_dir, "config.json")
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data["_meta"] = json.load(f)
        except json.JSONDecodeError as e:
            return None, f"config.json 解析失败（行 {e.lineno} 列 {e.colno}）：{e.msg}"
        except OSError as e:
            return None, f"config.json 读取失败：{e}"
    return data, None


def collect_groups(data_dir, styles):
    """每个风格各尺寸档的坐标数/条目数/标记数。只统计，不做检查。"""
    groups = []
    for style in styles:
        data, err = load_style_file(os.path.join(data_dir, style))
        if err:
            groups.append({"style": style, "error": err, "sizes": []})
            continue
        if not isinstance(data, dict):
            groups.append({"style": style, "error": "顶层不是对象", "sizes": []})
            continue
        sizes = []
        for size in SIZE_CATS:
            matrix = data.get(size)
            if not isinstance(matrix, dict) or not matrix:
                continue
            entries = tags = 0
            for quip_list in matrix.values():
                if not isinstance(quip_list, list):
                    continue
                entries += len(quip_list)
                for item in quip_list:
                    text = item if isinstance(item, str) else (
                        item.get("text") if isinstance(item, dict) else None)
                    if isinstance(text, str):
                        tags += len(TAG_RE.findall(text))
            sizes.append({"size": size, "coords": len(matrix),
                          "entries": entries, "tags": tags})
        groups.append({"style": style, "error": None, "sizes": sizes})
    return groups


def print_group_menu(data_dir, groups, example):
    """打印可选分组：一个风格一行，每档给 ``坐标/条目/标记``。"""
    print(f"[quip-check] 描述目录：{data_dir}")
    print("[quip-check] 一次只检查一个风格的一个尺寸档。"
          "可选分组（每档：坐标/条目/标记）：")
    width = max((len(g["style"]) for g in groups), default=0)
    if not groups:
        print("  （这里没有可检查的风格目录）")
    for g in groups:
        if g["error"]:
            print(f"  ◆ {g['style']}：读不了（{g['error']}）")
        elif not g["sizes"]:
            print(f"  ◆ {g['style']}：无已知尺寸档数据")
        else:
            cells = " · ".join(
                f"{s['size']} {s['coords']}/{s['entries']}/{s['tags']}"
                for s in g["sizes"])
            print(f"  {g['style']:<{width}}  {cells}")
    if example:
        print(f"[quip-check] 例：python developer_tools/quip_report.py {example} small")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="quip 类型 meta 读取 + 类型替换静态检查 + 疑似语法问题溯源")
    parser.add_argument("styles", nargs="*",
                        help="风格目录名 + 尺寸档（如 events small）；只给风格或都不给则列分组")
    parser.add_argument("--data-dir", default=None,
                        help="描述目录（含 <风格>/quips.csv），缺省为 <仓库根>/data/packs/quips")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--all", action="store_true",
                        help="展开 info 级问题（缺省清单只列 error/warn，摘要仍报 info 数）")
    parser.add_argument("--no-grammar", action="store_true",
                        help="跳过类型替换的组合级语法检查（只看格式与 meta）")
    parser.add_argument("--samples", type=int, default=3,
                        help="每条聚合结论最多列出的溯源样例数（缺省 3）")
    args = parser.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = args.data_dir or os.path.join(repo_root, "data", "packs", "quips")
    if not os.path.isdir(data_dir):
        print(f"[quip-check] 描述目录不存在：{data_dir}")
        return 2

    all_styles = sorted(
        f for f in os.listdir(data_dir)
        if os.path.isdir(os.path.join(data_dir, f))
        and not f.startswith(".") and f != "__pycache__")
    styles = list(args.styles)

    if len(styles) > 2:
        print(f"[quip-check] 一次只查一组（风格 + 尺寸档），收到 {len(styles)} 个参数："
              f"{'、'.join(styles)}")
        print_group_menu(data_dir, collect_groups(data_dir, all_styles), None)
        return 2

    if len(styles) < 2:
        # 少给参数：只给清单，不跑全量（全量结论读不动）
        groups = collect_groups(data_dir, styles[:1] or all_styles)
        if args.json:
            print(json.dumps({"data_dir": data_dir, "groups": groups},
                             ensure_ascii=False, indent=2))
        else:
            example = styles[0] if styles else next(
                (g["style"] for g in groups if g["sizes"]), None)
            print_group_menu(data_dir, groups, example)
        return 0

    style, size = styles
    if size not in SIZE_CATS:
        print(f"[quip-check] 尺寸档 {size!r} 不是 {'/'.join(SIZE_CATS)}")
        print_group_menu(data_dir, collect_groups(data_dir, [style]), style)
        return 2

    data, err = load_style_file(os.path.join(data_dir, style))
    if err:
        print(f"[quip-check] 风格 {style}：{err}")
        return 2
    if not isinstance(data, dict):
        print(f"[quip-check] 风格 {style}：顶层不是对象")
        return 2
    report = lint_style(style, data, size_cat=size,
                        with_grammar=not args.no_grammar,
                        max_samples=max(0, args.samples))

    counts = report.counts
    findings = report.sorted_findings()
    # info 级缺省不展开（--all 才列）；计数照常统计，避免"悄悄少报"
    shown = findings if args.all else [f for f in findings if f.level != "info"]
    hidden_info = 0 if args.all else counts["info"]

    if args.json:
        # 全局混淆开关只用于解读 meta（不改变静态检查结论），文本模式不需要
        try:
            with open(os.path.join(repo_root, "data", "user", "settings.json"),
                      "r", encoding="utf-8") as f:
                enable_confusion = json.load(f).get("enable_confusion")
        except (OSError, json.JSONDecodeError):
            enable_confusion = None
        grammar_stats = {}
        if report.stats:
            grammar_stats = {k: v for k, v in report.stats.items() if k != "rules"}
            for k, v in report.stats["rules"].items():
                grammar_stats[f"rule:{k}"] = v
        print(json.dumps({
            "data_dir": data_dir,
            "style": style,
            "size": size,
            "enable_confusion": enable_confusion,
            "all_levels": args.all,
            "meta": {style: report.meta_view()},
            "grammar_stats": grammar_stats,
            "findings": [f.as_dict() for f in shown],
            "hidden_info": hidden_info,
            "counts": counts,
        }, ensure_ascii=False, indent=2))
        return 1 if counts["error"] else 0

    print(f"[quip-check] 描述目录：{data_dir}")
    print(f"[quip-check] 检查范围：风格 {style} ｜ 尺寸档 {size}（只此一组）")
    if args.no_grammar:
        print("[quip-check] 类型替换·组合级语法检查：已跳过（--no-grammar）")
    print(f"[quip-check] ===== 问题清单（风格 {style} / 尺寸档 {size}）=====")
    if not shown:
        print("  未发现问题" if not hidden_info else "  本档无 error/warn（info 级见 --all）")
    for f in shown:
        snippet = f.loc.get("snippet") if f.loc else None
        print(f"  [{f.level.upper()}][{f.kind}] {format_loc(f.loc)}  {f.message}"
              + (f"  片段：{snippet}" if snippet else ""))
        for line in format_extra(f.extra):
            print(line)
    tail = f"（另有 info={hidden_info} 条未展开，加 --all 显示）" if hidden_info else ""
    print(f"[quip-check] 汇总：error={counts['error']} warn={counts['warn']} "
          f"info={counts['info']}{tail}")
    if any(f.extra and f.extra.get("samples") for f in shown):
        print(f"[quip-check] 每条组合结论最多列 {max(0, args.samples)} 条样例"
              f"（--samples N 调整，--samples 0 只要结论）")

    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
