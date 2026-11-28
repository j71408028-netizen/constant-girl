"""昵称抽取配比统计：按注释头给行分组，算权重占比与「供水」（组合数）是否匹配。

用法::

    python developer_tools/nickname_buckets.py                  # 按配额桶（注释首段）
    python developer_tools/nickname_buckets.py --by family      # 按第二段的族
    python developer_tools/nickname_buckets.py --top 30         # 族列表多列几行
    python developer_tools/nickname_buckets.py --targets "精制=300,粗制=350,人名=200,垃圾=150"
    python developer_tools/nickname_buckets.py --targets 300,350,200,150 --check
    python developer_tools/nickname_buckets.py --json

分类口径
--------

``nick_note`` 按 ``｜`` 切三段：``桶｜族｜说明``。

- **桶**（首段）：``精制`` / ``粗制`` / ``垃圾`` / ``人名``，抽取配额的唯一依据。
  前三值是质量档，``人名``是署名归属——一条昵称里有主人、名字在正文里，就记
  ``人名``，不再记它够不够精制。首段因此不是纯质量列，而是配额列。
- **族**（第二段）：这一行属于哪个池或哪一类，如 ``事业``、``纯名池·日式汉字：16 人``、
  ``西式可爱×尾巴：6 名 × 32 尾``。族只描述内容，不决定配额。
- **说明**（第三段起）：散文，只给人看，不参与任何统计。

桶是**逐行标的**，不从族推导：``事业`` 里带署名的行写 ``人名｜事业｜…``，没署名的
存量吐槽写 ``精制｜事业｜…``，两者配额不同、加槽策略也不同。早期版本用族推导，
整族强行归桶，把 36 行无署名的 ``事业`` 也塞进了人名配额。

只读 ``data/`` 取材表，不写盘。目标配比从命令行传，不写死在代码里——改权重不该
连带改工具。
"""

import argparse
import json
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from persistence.name_repo import NameRepo  # noqa: E402

QUOTA = ("精制", "粗制", "人名", "垃圾")
NAME_SERIES = ("人名（非直接引用）", "运营账号", "事业")
NAME_MARKERS = ("纯名池", "窄口", "×机构", "×头衔", "×事业尾", "×甜", "×尾巴")
SEP = "｜"


def split_note(note):
    """注释切三段：``(桶, 族, 说明)``；缺段返回空串，不抛异常。"""
    parts = (note or "").split(SEP)
    pad = parts + [""] * (3 - len(parts))
    return pad[0].strip(), pad[1].strip(), SEP.join(pad[2:]).strip()


def bucket_of(note):
    """配额桶：首段原样返回；不在四值里时由调用方报警。"""
    return split_note(note)[0]


def family_of(note):
    return split_note(note)[1]


def is_name_row(note):
    """族段是否属署名族（人名系列或它们的池）。**仅用于诊断**，不参与分桶。"""
    family = family_of(note)
    return family in NAME_SERIES or any(mark in family for mark in NAME_MARKERS)


def combos_of(entry):
    """这一行能渲染出多少个文本（各槽候选数的乘积，无槽位算 1）。"""
    total = 1
    for key in sorted(entry.substitutes):
        total *= len(entry.substitutes[key])
    return total


def collect(nicks, by):
    """把行按 ``by`` 分组，返回 [(组名, 行数, 权重, 组合数)]。"""
    if by == "family":
        key_of = lambda n: family_of(n.note) or "（族段为空）"
        order = ()
    else:
        key_of = lambda n: bucket_of(n.note) or "（首段为空）"
        order = QUOTA

    groups = OrderedDict()
    for n in nicks:
        key = key_of(n)
        row = groups.setdefault(key, [0, 0.0, 0])
        row[0] += 1
        row[1] += n.weight
        row[2] += combos_of(n)

    keys = list(groups)
    if order:
        keys.sort(key=lambda k: (order.index(k) if k in order else len(order), k))
    else:
        keys.sort(key=lambda k: (-groups[k][1], k))
    return [(k, groups[k][0], groups[k][1], groups[k][2]) for k in keys]


def parse_targets(text, order):
    """``精制=300,粗制=350`` 或按分组顺序的 ``300,350,200,150``。"""
    if not text:
        return {}
    if "=" in text:
        targets = {}
        for item in text.replace("，", ",").split(","):
            item = item.strip()
            if not item:
                continue
            name, _, value = item.partition("=")
            targets[name.strip()] = float(value)
        return targets
    values = [float(v) for v in text.replace("，", ",").split(",") if v.strip()]
    if len(values) != len(order):
        raise ValueError(f"位置写法要给 {len(order)} 个值（{ '、'.join(order) }），"
                         f"收到 {len(values)} 个")
    return dict(zip(order, values))


def build(group, by, targets, top):
    nicks = NameRepo().load(group)[3]
    if not nicks:
        return None
    total_w = sum(n.weight for n in nicks)
    rows = [(name, count, weight, combos)
            for name, count, weight, combos in collect(nicks, by)]

    if by == "family" and top and len(rows) > top:
        head, tail = rows[:top], rows[top:]
        rows = head + [("其他 %d 族" % len(tail),
                        sum(r[1] for r in tail), sum(r[2] for r in tail),
                        sum(r[3] for r in tail))]

    bad_quota = [n for n in nicks if bucket_of(n.note) not in QUOTA]
    signed_outside = [n for n in nicks
                      if is_name_row(n.note) and bucket_of(n.note) != "人名"]
    outside_by_family = {}
    for n in signed_outside:
        family = family_of(n.note).split("：")[0]
        outside_by_family[family] = outside_by_family.get(family, 0) + 1
    unmatched_cross = sorted({
        family_of(n.note).split("：")[0] for n in nicks
        if "×" in family_of(n.note) and bucket_of(n.note) != "人名"})

    return {
        "group": group,
        "by": by,
        "rows": len(nicks),
        "total_weight": total_w,
        "total_combos": sum(combos_of(n) for n in nicks),
        "groups": [
            {"name": name, "rows": count, "weight": round(weight, 4), "combos": combos,
             "weight_share": round(weight / total_w, 6),
             "combos_share": round(combos / max(1, sum(r[3] for r in rows)), 6),
             "target": targets.get(name),
             "delta": round(weight - targets[name], 4) if name in targets else None}
            for name, count, weight, combos in rows
        ],
        "bad_quota": len(bad_quota),
        "signed_outside": {"rows": len(signed_outside),
                           "by_family": outside_by_family},
        "unmatched_cross": unmatched_cross,
    }


def format_table(report):
    s = report
    label = "配额桶（注释首段）" if s["by"] == "bucket" else "族（注释第二段）"
    lines = [
        f"取材表组: {s['group']}    有效条目: {s['rows']} 行"
        f"    总权重: {s['total_weight']:.2f}    组合总数: {s['total_combos']}",
        f"分组口径: {label}",
        "",
        f"  {'分组':<16}{'行数':>6}{'行占比':>8}{'权重':>10}{'权重占比':>9}"
        f"{'目标':>8}{'偏差':>9}{'组合数':>8}{'组合占比':>9}{'供水比':>7}",
    ]
    for g in s["groups"]:
        target = f"{g['target']:.0f}" if g["target"] is not None else "—"
        delta = f"{g['delta']:+.2f}" if g["delta"] is not None else "—"
        ratio = g["combos_share"] / g["weight_share"] if g["weight_share"] else 0.0
        lines.append(
            f"  {g['name'][:14]:<16}{g['rows']:>6}{g['rows'] / s['rows']:>7.1%}"
            f"{g['weight']:>10.2f}{g['weight_share']:>8.1%}"
            f"{target:>8}{delta:>9}{g['combos']:>8}{g['combos_share']:>8.1%}{ratio:>7.2f}")
    lines.append("")
    lines.append(f"  密度 c = 组合总数 / 总权重 = "
                 f"{s['total_combos'] / s['total_weight']:.2f}"
                 "（供水比 1.00 表示某组的组合供给与权重同步；< 1 是权重给多了，"
                 "> 1 是槽位给多了）")

    if s["by"] == "bucket":
        if s["bad_quota"]:
            lines.append(f"  ! 首段不在 精制 / 粗制 / 人名 / 垃圾 里的行: "
                         f"{s['bad_quota']} 行")
        if s["signed_outside"]["rows"]:
            dist = "、".join(f"{k} {v} 行"
                            for k, v in sorted(s["signed_outside"]["by_family"].items()))
            lines.append(f"  署名族里配额不在人名的行: {s['signed_outside']['rows']} 行"
                         f"（{dist}）——族只描述内容，配额逐行判")
        if s["unmatched_cross"]:
            names = "、".join(s["unmatched_cross"][:4])
            more = "…" if len(s["unmatched_cross"]) > 4 else ""
            lines.append(f"  另有 {len(s['unmatched_cross'])} 个族名带 × 的族配额不在人名："
                         f"{names}{more}（尾饰 / 的字短条这类不是姓名派生；"
                         "哪一行其实是姓名×尾饰，就把首段改成人名）")
    return "\n".join(lines)


def check_targets(report):
    bad = [g for g in report["groups"]
           if g["target"] is not None and abs(g["delta"]) > 0.05]
    for g in report["groups"]:
        if g["target"] is not None:
            mark = "OK  " if abs(g["delta"]) <= 0.05 else "FAIL"
            print(f"  {mark} {g['name']:<8} 权重 {g['weight']:>8.2f}  "
                  f"目标 {g['target']:>6.0f}  偏差 {g['delta']:+.2f}")
    return not bad


def main():
    parser = argparse.ArgumentParser(
        description="昵称抽取配比统计：按注释头分组，算权重与组合供给")
    parser.add_argument("--group", default="default", help="取材表组名（默认 default）")
    parser.add_argument("--by", choices=("bucket", "family"), default="bucket",
                        help="分组口径：bucket 配额桶（首段，默认）/ family 族（第二段）")
    parser.add_argument("--targets", default="",
                        help='目标权重，如 "精制=300,粗制=350,人名=200,垃圾=150"'
                             " 或按分组顺序的 300,350,200,150")
    parser.add_argument("--check", action="store_true",
                        help="按 --targets 校验，偏差超过 0.05 时退出码 1")
    parser.add_argument("--top", type=int, default=20,
                        help="--by family 时列前多少个族（默认 20，其余合并）")
    parser.add_argument("--json", action="store_true", help="输出机器可读数据")
    args = parser.parse_args()

    order = QUOTA if args.by == "bucket" else ()
    try:
        targets = parse_targets(args.targets, order)
    except ValueError as exc:
        parser.error(str(exc))
    if args.check and not targets:
        parser.error("--check 需要同时给 --targets")

    report = build(args.group, args.by, targets, args.top)
    if report is None:
        parser.error(f"取材表组 {args.group!r} 没有可用昵称条目")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print(format_table(report))
    if targets:
        print("\n目标校验")
        if not check_targets(report):
            sys.exit(1)


if __name__ == "__main__":
    main()
