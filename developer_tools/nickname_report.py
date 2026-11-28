"""昵称表抽取碰撞体检：测算从取材表反复抽取昵称时，重复 / 近似重复的统计学情况。

用法:
    python developer_tools/nickname_report.py                    # default 表，文本报告
    python developer_tools/nickname_report.py --group <组名>      # 指定取材表组
    python developer_tools/nickname_report.py --json              # 机器可读全量数据
    python developer_tools/nickname_report.py --min-sim 0.9       # 调近似重复阈值（默认 0.85）
    python developer_tools/nickname_report.py --trials 50000      # 调蒙特卡洛次数（默认 20000）
    python developer_tools/nickname_report.py --show-near 20      # 多列几组近似对（默认 10）

抽取口径与 NameRepo / CreationService 一致：按 nick_weight 加权有放回抽一行，
再用 substitute_N 候选随机填 {1}/{2} 槽位。报告三个互斥层面的碰撞——行级
（抽中同一行）、文本级（渲染文本完全相同）、近似级（归一化后相同或序列
相似度 ≥ --min-sim）。只读 data/ 取材表，不写用户数据，不需要显示器。
"""

import argparse
import itertools
import json
import math
import random
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from persistence.name_repo import NameRepo  # noqa: E402

K_VALUES = (2, 3, 5, 10, 20, 30, 50, 100, 200)
SIM_K = (2, 3, 5, 10, 20, 50, 100)
NEAR_MASS = 0.98


def normalize(text):
    """去符号 / 标点 / 空白 / 大小写用于近似比对；纯符号串退回原文。"""
    out = []
    for ch in unicodedata.normalize("NFKC", text):
        if unicodedata.category(ch)[0] in ("P", "S") or ch.isspace():
            continue
        out.append(ch.casefold())
    result = "".join(out)
    return result if result else text


def _expand(nicks, p):
    """返回 {渲染文本: 概率} 与每行的展开组合数。"""
    text_prob = defaultdict(float)
    combos_per_row = []
    for i, n in enumerate(nicks):
        ks = sorted(n.substitutes)
        combos = 1
        for k in ks:
            combos *= len(n.substitutes[k])
        if ks:
            pools = [n.substitutes[k] for k in ks]
            each = p[i] / combos
            for combo in itertools.product(*pools):
                text = n.text
                for k, v in zip(ks, combo):
                    text = text.replace("{" + str(k) + "}", v)
                text_prob[text.strip()] += each
        else:
            text_prob[n.text.strip()] += p[i]
        combos_per_row.append(combos)
    return text_prob, combos_per_row


def _birthday(sum2, k):
    """抽 k 次至少一次碰撞的泊松近似。sum2 是该层的 Σp²。"""
    return 1.0 - math.exp(-k * (k - 1) / 2.0 * sum2)


def _birthday_sim(sum2, k, rng, pool, weights, trials):
    """从该层的分布实际抽 k 个，统计是否出现重复。"""
    hit = 0
    for _ in range(trials):
        draws = rng.choices(pool, weights=weights, k=k)
        if len(set(draws)) < k:
            hit += 1
    return hit / trials


def compute_stats(group, min_sim, trials, seed):
    nicks = NameRepo().load(group)[3]
    if not nicks:
        return None
    total_w = sum(n.weight for n in nicks)
    p = [n.weight / total_w for n in nicks]
    text_prob, combos_per_row = _expand(nicks, p)

    sum_p2 = sum(x * x for x in p)
    sum_q2 = sum(v * v for v in text_prob.values())

    norm_prob = defaultdict(float)
    norm_of = {}
    for text, q in text_prob.items():
        key = normalize(text)
        norm_of[text] = key
        norm_prob[key] += q
    sum_norm2 = sum(v * v for v in norm_prob.values())

    rng = random.Random(seed)
    texts = list(text_prob)
    qs = list(text_prob.values())
    curve = []
    for k in K_VALUES:
        row = {
            "k": k,
            "row_theory": _birthday(sum_p2, k),
            "text_theory": _birthday(sum_q2, k),
            "row_sim": None,
            "text_sim": None,
        }
        if k in SIM_K:
            row["row_sim"] = _birthday_sim(
                sum_p2, k, rng, range(len(p)), p, trials)
            row["text_sim"] = _birthday_sim(sum_q2, k, rng, texts, qs, trials)
        curve.append(row)

    ranked = sorted(text_prob.items(), key=lambda kv: -kv[1])
    mass, high = 0.0, []
    for text, q in ranked:
        high.append((text, q))
        mass += q
        if mass >= NEAR_MASS:
            break
    near_pairs = []
    for i in range(len(high)):
        t1, q1 = high[i]
        for j in range(i + 1, len(high)):
            t2, q2 = high[j]
            if t1 == t2:
                continue
            if abs(len(t1) - len(t2)) > max(len(t1), len(t2)) * 0.3:
                continue
            ratio = SequenceMatcher(None, t1, t2).ratio()
            if ratio >= min_sim:
                near_pairs.append((ratio, q1, q2, t1, t2))
    near_pairs.sort(key=lambda x: -(x[1] * x[2]))
    sim_only = sum(2 * q1 * q2 for _, q1, q2, t1, t2 in near_pairs
                   if norm_of[t1] != norm_of[t2])

    return {
        "group": group,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "min_sim": min_sim,
        "trials": trials,
        "seed": seed,
        "rows": len(nicks),
        "slot_rows": sum(1 for n in nicks if n.substitutes),
        "total_weight": total_w,
        "weight_min": min(n.weight for n in nicks),
        "weight_max": max(n.weight for n in nicks),
        "variants": sum(combos_per_row),
        "distinct_texts": len(text_prob),
        "sum_p2": sum_p2,
        "sum_q2": sum_q2,
        "sum_norm2": sum_norm2,
        "neff_row": 1.0 / sum_p2,
        "neff_text": 1.0 / sum_q2,
        "neff_norm": 1.0 / sum_norm2,
        "p_exact": sum_q2,
        "p_norm_only": sum_norm2 - sum_q2,
        "p_sim_only": sim_only,
        "p_any": sum_q2 + (sum_norm2 - sum_q2) + sim_only,
        "near_mass": mass,
        "near_pairs": near_pairs,
        "curve": curve,
    }


def _fmt_prob(value):
    return f"{value * 100:.4f}%" if value < 0.01 else f"{value * 100:.2f}%"


def format_report(stats, show_near):
    s = stats
    lines = [
        f"取材表组: {s['group']}    有效条目: {s['rows']} 行"
        f"（带槽位 {s['slot_rows']}）    总权重: {s['total_weight']:.0f}",
        f"权重范围: {s['weight_min']:.4f} ~ {s['weight_max']:.4f}"
        f"    可渲染文本组合: {s['variants']}    不同文本: {s['distinct_texts']}",
        "",
        "有效池（等概率折算条目数）",
        f"  行级   N_eff = {s['neff_row']:>8.1f}    两抽命中同一行 {_fmt_prob(s['sum_p2'])}",
        f"  文本级 N_eff = {s['neff_text']:>8.1f}    两抽得到相同昵称 {_fmt_prob(s['sum_q2'])}",
        f"  归一   N_eff = {s['neff_norm']:>8.1f}    去符号 / 大小写后相同 {_fmt_prob(s['sum_norm2'])}",
        f"  约 50% 概率出现重复所需抽取次数：行级 ≈ {1.177 * math.sqrt(s['neff_row']):.0f} 次，"
        f"文本级 ≈ {1.177 * math.sqrt(s['neff_text']):.0f} 次",
        "",
        "抽 k 次「至少一次重复」的概率（理论近似 / 蒙特卡洛）",
        f"  {'k':>4} {'行级理论':>11} {'行级模拟':>11} {'文本级理论':>12} {'文本级模拟':>12}",
    ]
    for row in s["curve"]:
        rs = f"{row['row_sim'] * 100:>10.2f}%" if row["row_sim"] is not None else "         —"
        ts = f"{row['text_sim'] * 100:>11.2f}%" if row["text_sim"] is not None else "          —"
        lines.append(
            f"  {row['k']:>4} {row['row_theory'] * 100:>10.2f}% {rs} "
            f"{row['text_theory'] * 100:>11.2f}% {ts}"
        )
    lines += [
        "",
        f"近似重复（相似度阈值 {s['min_sim']:.2f}，仅统计覆盖 {s['near_mass'] * 100:.0f}% "
        "概率质量的高权重文本，近似层为下界）",
        f"  归一化后相同但文本不同: {_fmt_prob(s['p_norm_only'])}",
        f"  高相似但归一化不同:     {_fmt_prob(s['p_sim_only'])}"
        f"（{len(s['near_pairs'])} 对）",
        f"  任一层碰撞合计:         {_fmt_prob(s['p_any'])}"
        f"（精确 {_fmt_prob(s['p_exact'])}）",
    ]
    if s["near_pairs"]:
        lines.append("  最典型的近似对（按两抽概率质量排序）:")
        for ratio, q1, q2, t1, t2 in s["near_pairs"][:show_near]:
            lines.append(
                f"    sim={ratio:.2f} ({_fmt_prob(q1)}, {_fmt_prob(q2)})  {t1!r} ≈ {t2!r}"
            )
    lines += [
        "",
        f"参数: seed={s['seed']}  trials={s['trials']}  生成于 {s['generated_at']}",
    ]
    return "\n".join(lines)


def to_json(stats):
    s = dict(stats)
    s["near_pairs"] = [
        {"sim": round(r, 3), "p1": q1, "p2": q2, "a": t1, "b": t2}
        for r, q1, q2, t1, t2 in stats["near_pairs"]
    ]
    for row in s["curve"]:
        for key in ("row_theory", "text_theory", "row_sim", "text_sim"):
            if row[key] is not None:
                row[key] = round(row[key], 6)
    for key in ("sum_p2", "sum_q2", "sum_norm2", "p_exact", "p_norm_only",
                "p_sim_only", "p_any", "near_mass"):
        s[key] = round(s[key], 8)
    return json.dumps(s, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="测算昵称表反复抽取的重复 / 近似重复统计")
    parser.add_argument("--group", default="default",
                        help="取材表组名（默认 default）")
    parser.add_argument("--json", action="store_true",
                        help="输出机器可读的全量数据")
    parser.add_argument("--min-sim", type=float, default=0.85,
                        help="近似重复的序列相似度阈值（默认 0.85）")
    parser.add_argument("--trials", type=int, default=20000,
                        help="生日曲线的蒙特卡洛次数（默认 20000）")
    parser.add_argument("--seed", type=int, default=42,
                        help="随机种子（默认 42，保证可复现）")
    parser.add_argument("--show-near", type=int, default=10,
                        help="文本报告列出的近似对数量（默认 10）")
    args = parser.parse_args()

    if not 0 < args.min_sim <= 1:
        parser.error("--min-sim 需在 (0, 1] 之间")
    if args.trials < 1:
        parser.error("--trials 需为正整数")

    stats = compute_stats(args.group, args.min_sim, args.trials, args.seed)
    if stats is None:
        parser.error(f"取材表组 {args.group!r} 没有可用昵称条目")
    print(to_json(stats) if args.json else format_report(stats, args.show_near))


if __name__ == "__main__":
    main()
