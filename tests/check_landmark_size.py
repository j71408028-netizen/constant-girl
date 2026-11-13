"""F3 回归守卫：零尺寸地标不得中断报告，失败也不得留下扣点。

用法：``python tests/check_landmark_size.py``

**为什么需要**：地标的 ``size`` 直接作除数（``身体部位 / 地标尺寸``）。CSV 里
一行 ``0`` 就能让整份报告抛 ``ZeroDivisionError``；``nan`` / ``inf`` 更隐蔽——
它们通过 ``float()``，比值区间判断（``< 0.1`` / ``> 50``）对 NaN 恒为假，
于是坏条目一路混进排序、耐久伤害与文本。旧版在生成报告前就把行动点扣掉并
落盘，于是失败后档案里留下「已扣点、没有报告」。

本守卫三部分：

1. **判据**：``is_valid_landmark_size`` 只放行正数且有限的值；
2. **入口**：CSV 读取、挑战包导入、副本载荷与地标编辑框都走同一判据；
3. **计算边界**：即使数据绕过入口，``get_comparisons`` 也不除零；
4. **落盘顺序**：报告引擎抛错时行动点退回内存，档案不落盘。

退出码：0 = 通过；1 = 行为不符。
"""
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logic.quips import get_comparisons  # noqa: E402
from core.models import (CharacterSnapshot, Landmark, Personality,  # noqa: E402
                         is_valid_landmark_size)
from dungeon import scene as dungeon_scene  # noqa: E402
from persistence.landmark_repo import LandmarkRepo, row_to_landmark  # noqa: E402
from services.exploration.context import ExplorationContext  # noqa: E402
from services.state_service import StateService  # noqa: E402

failures = []
total = 0


def check(name, ok, extra=""):
    global total
    total += 1
    print(("  OK   " if ok else "  FAIL ") + name + (f"  <{extra}>" if extra and not ok else ""))
    if not ok:
        failures.append(name)


def _personality():
    return Personality(name="温和", init_intrusion=1.0, depth_intrusion=0.1,
                       init_destruction=1.0, depth_destruction=0.1,
                       sensitivity=1.0, gravity=0.5)


def _lm(name, size, dimension="vertical", frequency="unique"):
    return Landmark(name=name, size=size, dimension=dimension,
                    frequency=frequency)


# ---------------- 1. 尺寸判据 ----------------
print("[1] is_valid_landmark_size")
for value, expected in ((100, True), (0.5, True), ("12.5", True),
                        (0, False), (0.0, False), (-1, False), (-0.5, False),
                        (float("nan"), False), (float("inf"), False),
                        (float("-inf"), False), ("", False), ("abc", False),
                        (None, False), (True, False)):
    check(f"size={value!r} → {expected}",
          is_valid_landmark_size(value) is expected)

# ---------------- 2. CSV 行解析 ----------------
print("[2] row_to_landmark")
for size_text in ("0", "-3", "nan", "inf", "-inf", "", "abc"):
    check(f"size={size_text!r} 的行被拒绝",
          row_to_landmark({"name": "坏行", "size": size_text}) is None)
_valid_row = row_to_landmark({"name": "好地标", "size": "632"})
check("正常行仍能解析", _valid_row is not None and _valid_row.size == 632.0,
      _valid_row)
check("无名称的行被拒绝", row_to_landmark({"name": "  ", "size": "10"}) is None)

# ---------------- 3. 仓库读写：坏行不进内存 ----------------
print("[3] LandmarkRepo.load 丢弃坏行")
_tmp = tempfile.mkdtemp(prefix="cg_landmark_")
_repo = LandmarkRepo(data_dir=_tmp)
_repo.save("t", [_lm("好地标", 100),
                 _lm("零尺寸", 0),
                 _lm("负尺寸", -5),
                 _lm("非数", float("nan")),
                 _lm("无穷", float("inf"))])
_loaded = _repo.load("t")
check("只保留可换算的条目",
      [lm.name for lm in _loaded] == ["好地标"],
      [lm.name for lm in _loaded])

# ---------------- 4. 计算边界 ----------------
print("[4] get_comparisons 不除零")
_parts = {"身高": 100.0, "腿长": 50.0}
try:
    _only_zero = get_comparisons([_lm("零", 0)], _parts)
    _crash = None
except Exception as exc:  # noqa: BLE001 - 这里就是要捕获任何异常
    _only_zero, _crash = None, exc
check("全部是零尺寸地标时返回空而不是抛错",
      _crash is None and _only_zero == [], repr(_crash))

_mixed = get_comparisons(
    [_lm("塔", 100), _lm("零", 0), _lm("非数", float("nan")),
     _lm("无穷", float("inf"))],
    _parts, limit=10)
_names = {cand["landmark"].name for cand in _mixed}
check("坏尺寸地标不进入候选", _names == {"塔"}, _names)
check("比值只由好数据算出",
      all(cand["ratio"] in (1.0, 0.5) for cand in _mixed),
      [cand["ratio"] for cand in _mixed])

# ---------------- 5. 副本章节地标（nan/inf 原本能漏过） ----------------
print("[5] dungeon.scene 地标归一")
_coerce = dungeon_scene._coerce_unique_landmark
check("尺寸 nan 被拒", _coerce({"name": "x", "size": float("nan")}) is None)
check("尺寸 inf 被拒", _coerce({"name": "x", "size": float("inf")}) is None)
check("尺寸 0 被拒", _coerce({"name": "x", "size": 0}) is None)
check("正常尺寸通过", _coerce({"name": "x", "size": 30}) is not None)

# ---------------- 6. 扣点与落盘的顺序 ----------------
print("[6] 报告失败不扣点")


class _RecordingRepo:
    def __init__(self):
        self.saved = []

    def save(self, state):
        self.saved.append(state.action_points)

    def get_avatar_abspath(self, *_args):
        return None


class _StubReports:
    """按需抛错或返回 stuck 的报告引擎替身。"""

    def __init__(self, exc=None, stuck=False):
        self.exc = exc
        self.stuck = stuck
        self.calls = 0

    def generate(self, core, styles):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return {"stuck": {"kind": "no_reachable"} if self.stuck else None}


def _ctx(reports, repo):
    """绕过构造函数组装上下文：本测试只关心编排入口里的扣点与落盘。"""
    ctx = object.__new__(ExplorationContext)
    ctx.catalog = types.SimpleNamespace(
        settings={"comparison_count": 5},
        state_service=StateService,
        character_repo=repo,
    )
    ctx._reports = reports
    return ctx


def _state(points=100):
    return CharacterSnapshot(giantess_id="g", name="测试", height=100.0,
                             action_points=points, personality=_personality())


# 6a. 引擎抛错 → 点数原样退回，档案不落盘
_repo_a, _reports_a = _RecordingRepo(), _StubReports(exc=ZeroDivisionError("boom"))
_state_a = _state()
try:
    ExplorationContext.report_from_core_or_character(
        _ctx(_reports_a, _repo_a), _state_a, [], [], consume_points=True)
    _raised = None
except Exception as exc:  # noqa: BLE001
    _raised = exc
check("引擎异常照常向上传播", isinstance(_raised, ZeroDivisionError), repr(_raised))
check("异常后行动点已退回", _state_a.action_points == 100, _state_a.action_points)
check("异常后没有写入档案", _repo_a.saved == [], _repo_a.saved)

# 6b. 重试耗尽仍是 stuck → 返回 None，点数退回，不落盘
_repo_b, _reports_b = _RecordingRepo(), _StubReports(stuck=True)
_state_b = _state()
_result_b = ExplorationContext.report_from_core_or_character(
    _ctx(_reports_b, _repo_b), _state_b, [], [], consume_points=True,
    resolve_stuck=lambda *args: {"kind": "address", "address": "1e2"})
check("stuck 耗尽返回 None", _result_b is None, _result_b)
check("stuck 耗尽重试了 5 次", _reports_b.calls == 5, _reports_b.calls)
check("stuck 耗尽点数已退回", _state_b.action_points == 100, _state_b.action_points)
check("stuck 耗尽没有写入档案", _repo_b.saved == [], _repo_b.saved)

# 6c. 用户明确放弃（不迁移）→ 扣点照旧落盘，保持原语义
_repo_c, _reports_c = _RecordingRepo(), _StubReports(stuck=True)
_state_c = _state()
_result_c = ExplorationContext.report_from_core_or_character(
    _ctx(_reports_c, _repo_c), _state_c, [], [], consume_points=True)
check("放弃时返回 None", _result_c is None, _result_c)
check("放弃时扣点照常落盘", _repo_c.saved == [75], _repo_c.saved)

# 6d. 点数不足 → 直接返回，不产生任何写入
_repo_d, _reports_d = _RecordingRepo(), _StubReports()
_state_d = _state(points=10)
_result_d = ExplorationContext.report_from_core_or_character(
    _ctx(_reports_d, _repo_d), _state_d, [], [], consume_points=True)
check("点数不足返回 None", _result_d is None, _result_d)
check("点数不足未扣点也未落盘",
      _state_d.action_points == 10 and _repo_d.saved == []
      and _reports_d.calls == 0,
      (_state_d.action_points, _repo_d.saved, _reports_d.calls))

# ---------------- 汇总 ----------------
print()
if failures:
    print(f"FAILED {len(failures)}/{total}: " + "; ".join(failures))
    sys.exit(1)
print(f"PASSED {total}/{total}")
