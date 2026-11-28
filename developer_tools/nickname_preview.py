"""昵称手感预览：按当前权重连抽，看一批真实渲染出来的昵称长什么样。

用法:
    python developer_tools/nickname_preview.py                # 交互：回车再抽 20 个，q 退出
    python developer_tools/nickname_preview.py -n 40          # 每批 40 个
    python developer_tools/nickname_preview.py -c 200 --seed 7  # 只抽一次 200 个并出统计

走的是 NameRepo + weighted_choice 的真实路径（先按 nick_weight 抽行，再填槽），
所以看到的重复率就是玩家会遇到的。注释只取第二段（分类）当标签，省得调权重时
还要在这里维护一份桶口径。只读 data/，不写用户数据。
"""

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from persistence.name_repo import NameRepo, render_nick  # noqa: E402
from persistence.static_table import weighted_choice  # noqa: E402
from services.creation_service import CreationService  # noqa: E402

DEFAULT_BATCH = 20


def tag(nick):
    parts = (nick.note or "").split("｜")
    if len(parts) < 2:
        return "—"
    if parts[1] == "(模板)" and len(parts) > 2:
        return parts[2]
    return parts[1]


def roll(data, rng):
    """按创建期的顺序掷一次：先姓与名，再抽行、填槽、换 {sur}/{given}。"""
    surnames, weights, names, nicks = data
    surname = rng.choices(surnames, weights=weights, k=1)[0] if surnames else "王"
    given = rng.choice(names) if names else "静"
    entry = weighted_choice(nicks, rng=rng)
    text = CreationService.resolve_nick_placeholders(render_nick(entry, rng), surname, given)
    return text, entry


def show_batch(data, rng, size, seen, start):
    """抽一批并逐行打印；本批内重复标 ※，跨批重复标 ‡。"""
    nicks = data[3]
    for i in range(size):
        text, entry = roll(data, rng)
        mark = " "
        if text in seen:
            mark = "‡" if seen[text] == 1 else "※"
        seen[text] += 1
        print(f"  {start + i + 1:>3}. {text:<26} {mark} {tag(entry)}")
    return start + size


def main():
    parser = argparse.ArgumentParser(description="昵称连抽预览")
    parser.add_argument("-n", "--batch", type=int, default=DEFAULT_BATCH,
                        help=f"每批个数（默认 {DEFAULT_BATCH}）")
    parser.add_argument("-c", "--count", type=int, default=0,
                        help="只抽一次、抽这么多个，并打印统计")
    parser.add_argument("--seed", type=int, default=None, help="固定随机种子")
    parser.add_argument("--group", default="default", help="取材表组名")
    args = parser.parse_args()

    data = NameRepo().load(args.group)
    nicks = data[3]
    if not nicks:
        print("表里没有昵称")
        sys.exit(1)
    total_w = sum(n.weight for n in nicks)
    print(f"{args.group}: {len(nicks)} 行，总权重 {total_w:.0f}")

    rng = random.Random(args.seed)
    seen = Counter()

    if args.count:
        texts = [roll(data, rng)[0] for _ in range(args.count)]
        counts = Counter(texts)
        dup = sum(c - 1 for c in counts.values() if c > 1)
        pair = sum(c * (c - 1) for c in counts.values()) / max(1, args.count * (args.count - 1))
        print(f"\n抽 {args.count} 次：不同 {len(counts)} 个，"
              f"重复 {dup} 次（{dup / args.count:.1%}），"
              f"两抽撞名概率 ≈ {pair:.3%}")
        for text, c in counts.most_common(8):
            if c > 1:
                print(f"   x{c} {text}")
        return

    start = 0
    while True:
        start = show_batch(data, rng, args.batch, seen, start)
        try:
            key = input("\n回车继续，q 退出 > ").strip().lower()
        except EOFError:
            print()
            return
        if key in ("q", "quit", "exit"):
            return


if __name__ == "__main__":
    main()
