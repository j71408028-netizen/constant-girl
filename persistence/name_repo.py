import csv
import os
import random
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from persistence.material_tables import (
    DEFAULT_MATERIAL_TABLE,
    list_groups,
    member_path,
)

#: 昵称里的轮换槽位：``{1}`` → ``substitute_1``。只认数字，``{sur}`` 留给创建期。
_SLOT_RE = re.compile(r"\{(\d+)\}")

#: 候选队列的分隔符：Excel 里手打容易敲成全角，两种都认。
_CANDIDATE_RE = re.compile(r"[,，]")


def _candidates(cell: str) -> Tuple[str, ...]:
    """``"啊啊啊啊, 呜呜呜"`` → 去空、去重、保序的候选元组。"""
    items = (part.strip() for part in _CANDIDATE_RE.split(cell or ""))
    return tuple(dict.fromkeys(item for item in items if item))


@dataclass(frozen=True)
class NickEntry:
    """姓名表里的一个昵称：一行一条，可带 ``{1}`` 轮换槽位与自己的权重。"""

    text: str
    weight: float = 1.0
    substitutes: Dict[int, Tuple[str, ...]] = field(default_factory=dict)

    def render(self, rng: random.Random = random) -> str:
        """填一次槽。单遍替换，候选里再出现花括号也不会被二次展开。"""
        def fill(match: re.Match) -> str:
            values = self.substitutes.get(int(match.group(1)))
            return rng.choice(values) if values else match.group(0)

        return _SLOT_RE.sub(fill, self.text).strip()


def render_nick(entry, rng: random.Random = random) -> str:
    """把一行昵称条目渲染成文本；兼容旧调用方直接传字符串的情况。"""
    if isinstance(entry, NickEntry):
        return entry.render(rng)
    return str(entry) if entry is not None else ""


class NameRepo:
    """姓名表读取器：定位当前取材表组内的 ``names.csv``。"""

    def __init__(self, world_state=None):
        self._world_state = world_state

    def get_groups(self) -> List[str]:
        """返回可用取材表组名（按名称排序）。"""
        return list_groups(world_state=self._world_state)

    def resolve(self, group: Optional[str] = None) -> str:
        """返回指定组内姓名表的完整路径（缺席时已回落到内置组）。"""
        return member_path(group, "names", world_state=self._world_state)

    def load(self, group: Optional[str] = None) -> Tuple[List[str], List[float], List[str], List[NickEntry]]:
        """加载姓名表，返回 (surnames, weights, names, nicks)。

        nick 按 ``nick_weight`` 抽取（缺省 1、非正数不入场），``{1}`` 一类槽位
        由同行的 ``substitute_N`` 轮换取词；缺候选的行整行跳过。
        """
        csv_path = self.resolve(group)
        surnames: List[str] = []
        weights: List[float] = []
        names: List[str] = []
        nicks: List[NickEntry] = []
        if not os.path.exists(csv_path):
            return surnames, weights, names, nicks
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    surname = (row.get('surname') or '').strip()
                    ppm_str = (row.get('ppm') or '').strip()
                    name = (row.get('name') or '').strip()
                    nick = (row.get('nick') or '').strip()
                    if surname:
                        surnames.append(surname)
                        try:
                            weights.append(float(ppm_str) if ppm_str else 1.0)
                        except ValueError:
                            weights.append(1.0)
                    if name:
                        names.append(name)
                    if not nick:
                        continue
                    try:
                        nick_weight = float((row.get('nick_weight') or '').strip() or 1)
                    except ValueError:
                        nick_weight = 1.0
                    if nick_weight <= 0:
                        continue
                    slots: Dict[int, Tuple[str, ...]] = {}
                    for index in sorted({int(n) for n in _SLOT_RE.findall(nick)}):
                        values = _candidates(row.get(f'substitute_{index}', ''))
                        if not values:
                            print(f"姓名表：昵称 {nick!r} 缺 substitute_{index}，跳过这一行")
                            break
                        slots[index] = values
                    else:
                        nicks.append(NickEntry(nick, nick_weight, slots))
        except Exception as e:
            print(f"加载姓名表 {group or DEFAULT_MATERIAL_TABLE} 失败: {e}")
        return surnames, weights, names, nicks
