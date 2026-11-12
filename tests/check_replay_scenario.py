"""自检：回放所属方案的判定链（背景 / 音乐 / 结局图标相对路径的前提）。

用法：``python tests/check_replay_scenario.py``

回放里的素材路径都相对方案目录，认不出 ``scenario_id`` 就一律解析失败。判定链
越明确越优先：调用方显式给的 > 身份记录 ``kind:"meta"`` > user 回放文件名前缀 >
素材反查。最后一级是旧文件兼容层（同名素材会静默错配），前三者都能按住它。
这里用临时方案目录逐级验证，并顺手确认认出来的方案真的能让背景路径解析成功。
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_report_path = os.path.join(tempfile.mkdtemp(prefix="replay_scenario_"), "report.txt")
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


from dungeon import process_log, replay  # noqa: E402
from dungeon.window.background import DungeonBackground  # noqa: E402
from dungeon.window.base import DungeonWindowBase  # noqa: E402


class FakeRepo:
    """临时方案根：``{方案 id: 目录}``。"""

    def __init__(self, dirs):
        self._dirs = dict(dirs)
        self.root = os.path.dirname(next(iter(dirs.values()))) if dirs else ""

    def list_all(self):
        return sorted(self._dirs)

    def exists(self, scenario_id):
        return scenario_id in self._dirs

    def scenario_dir(self, scenario_id):
        return self._dirs.get(scenario_id, "")


class Host(DungeonWindowBase):
    """只带反查所需状态的宿主（不建窗口、不碰素材渲染）。"""

    def __init__(self, repo, scenario_id=None, source_path=""):
        self.scenario_repo = repo
        self.scenario_id = scenario_id
        self.replay_source_path = source_path


def _write(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("x")


root = tempfile.mkdtemp(prefix="scenarios_")
alpha = os.path.join(root, "alpha")
beta = os.path.join(root, "beta")
_write(os.path.join(alpha, "images", "shared.jpg"))
_write(os.path.join(beta, "images", "rain.jpg"))
_write(os.path.join(beta, "music", "theme.mp3"))
repo = FakeRepo({"alpha": alpha, "beta": beta})


def chapter(name="", image=None, music=None):
    return replay.ChapterRecord(
        name=name, step=0,
        background={"image_path": image} if image else {},
        bgm={"path": music} if music else {},
        voice_fx={})


# ---------------- 1. 按素材命中反查 -----------------------------
host = Host(repo)
host._resolve_replay_scenario([chapter("雨夜", "images/rain.jpg", "music/theme.mp3")])
check("背景与音乐都只在 beta 里 → 反查到 beta", host.scenario_id == "beta", host.scenario_id)

host = Host(repo)
host._resolve_replay_scenario([chapter("雨夜", "/images/rain.jpg")])
check("记录里带前导斜杠的相对路径同样认得出", host.scenario_id == "beta", host.scenario_id)

host = Host(repo)
host._resolve_replay_scenario([
    replay.EndingRecord(name="终", text="", icon_path="images/rain.jpg", step=3)])
check("结局图标的相对路径也参与反查", host.scenario_id == "beta", host.scenario_id)

# ---------------- 2. 反查结果真的能让背景落地 ----------------
class _Owner:
    def __init__(self, repo, scenario_id):
        self.scenario_repo = repo
        self.scenario_id = scenario_id


owner = _Owner(repo, None)
resolver = DungeonBackground(owner)
check("反查前：相对路径解析不出来（正是开场不换背景的原因）",
      resolver.resolve_path("images/rain.jpg") is None)
owner.scenario_id = host.scenario_id
check("反查后：相对路径解析到方案目录",
      resolver.resolve_path("images/rain.jpg")
      == os.path.normpath(os.path.join(beta, "images", "rain.jpg")),
      resolver.resolve_path("images/rain.jpg"))

# ---------------- 3. 不猜的情形 ----------------
host = Host(repo, scenario_id="alpha")
host._resolve_replay_scenario([chapter("雨夜", "images/rain.jpg")])
check("调用方给了方案就照用，不按素材覆盖", host.scenario_id == "alpha", host.scenario_id)

host = Host(repo)
host._resolve_replay_scenario([chapter("雨夜", "images/missing.jpg")])
check("素材全都不存在 → 不选方案（交给各处缺省处理）", not host.scenario_id, host.scenario_id)

host = Host(repo)
host._resolve_replay_scenario([chapter("雨夜", os.path.join(beta, "images", "rain.jpg"))])
check("绝对路径不参与反查（本来就不依赖方案目录）", not host.scenario_id, host.scenario_id)

host = Host(repo)
host._resolve_replay_scenario([chapter("空章节")])
check("记录里没有任何素材 → 不选方案", not host.scenario_id, host.scenario_id)

host = Host(repo)
host._resolve_replay_scenario([])
check("空记录列表不崩、不选方案", not host.scenario_id, host.scenario_id)

host = Host(None)
host._resolve_replay_scenario([chapter("雨夜", "images/rain.jpg")])
check("没有方案仓库时静默跳过", not host.scenario_id, host.scenario_id)

# ---------------- 4. 同名素材：命中最多的优先 ----------------
gamma = os.path.join(root, "gamma")
_write(os.path.join(gamma, "images", "shared.jpg"))
_write(os.path.join(gamma, "music", "theme.mp3"))
repo2 = FakeRepo({"alpha": alpha, "gamma": gamma})
host = Host(repo2)
host._resolve_replay_scenario([chapter("雨夜", "images/shared.jpg", "music/theme.mp3")])
check("两个方案都有同名背景时按总命中数择优", host.scenario_id == "gamma", host.scenario_id)

# ---------------- 5. 身份记录（kind:"meta"）优先 ----------------
def meta(scenario_id, assets=()):
    return replay.parse(replay.meta_record(
        scenario={"id": scenario_id, "assets": list(assets)},
        app="2.0.0", saved_at="2026-11-10T10:51:13"))


def resolve(records, scenario_id=None, source_path="", repo_=None):
    host_ = Host(repo_ if repo_ is not None else repo,
                 scenario_id=scenario_id, source_path=source_path)
    host_._resolve_replay_scenario(records)
    return host_


# 素材指向 beta，身份声明的是 alpha：以身份为准（不再猜）
host = Host(repo)
host._resolve_replay_scenario(
    [meta("alpha"), chapter("雨夜", "images/rain.jpg", "music/theme.mp3")], )
check("身份记录优先于素材反查", host.scenario_id == "alpha", host.scenario_id)

check("调用方显式给的方案不被身份记录覆盖",
      resolve([meta("alpha"), chapter("雨夜", "images/rain.jpg")],
              scenario_id="beta").scenario_id == "beta")

check("缺身份记录（旧回放）照旧按素材反查",
      resolve([chapter("雨夜", "images/rain.jpg")]).scenario_id == "beta")

_deleted = resolve([meta("已删掉的方案"), chapter("雨夜", "images/rain.jpg")])
check("身份声明的方案不在本机 → 退化到素材反查",
      _deleted.scenario_id == "beta", _deleted.scenario_id)

check("身份记录没有方案 id 时不当作依据",
      resolve([meta(""), chapter("雨夜", "images/rain.jpg")]).scenario_id == "beta")

check("身份记录 + 材质全无 → 认不出就不选方案",
      not resolve([meta("已删掉的方案"), chapter("空章节")]).scenario_id)

# 文件名兜底：``<方案 id>_回放_<时间戳>.replay.json``
check("旧回放按文件名认方案（记录里没有素材也能认）",
      resolve([chapter("空章节")],
              source_path=os.path.join(root, "gamma_回放_20261110120000.replay.json"),
              repo_=repo2).scenario_id == "gamma")

check("文件名里的方案已不存在 → 继续退化，不乱认",
      not resolve([chapter("空章节")],
                  source_path=os.path.join(root, "delta_回放_20261110120000.replay.json")
                  ).scenario_id)

check("档案回放的文件名是角色名（``<角色名>_回放_<时间>``）→ 不认错方案",
      not resolve([chapter("空章节")],
                  source_path=os.path.join(root, "小雅_回放_20261110120000.replay.json")
                  ).scenario_id)

check("身份记录优先于文件名",
      resolve([meta("alpha")],
              source_path=os.path.join(root, "gamma_回放_20261110120000.replay.json"),
              repo_=repo2).scenario_id == "alpha")

# 素材漂移：路径还在、大小变了 —— 只记一行日志，不弹窗不中断
_logs = []
process_log.subscribe(_logs.append)
_drift = os.path.join(beta, "images", "rain.jpg")
_drift_size = os.path.getsize(_drift)
_drift_host = resolve(
    [meta("beta", [{"path": "images/rain.jpg", "size": _drift_size + 1},
                   {"path": "images/gone.jpg", "size": 1}]),
     chapter("雨夜", "images/rain.jpg")])
process_log.unsubscribe(_logs.append)
check("素材大小对不上时仍然用方案（回放不中断）",
      _drift_host.scenario_id == "beta", _drift_host.scenario_id)
check("素材漂移在过程日志里标一句（含缺失的文件）",
      any("素材与当时不同" in line and "images/rain.jpg" in line
          and "images/gone.jpg" in line for line in _logs), _logs)

_logs = []
process_log.subscribe(_logs.append)
resolve([meta("beta", [{"path": "images/rain.jpg",
                        "size": os.path.getsize(os.path.join(beta, "images", "rain.jpg"))}]),
         chapter("雨夜", "images/rain.jpg")])
process_log.unsubscribe(_logs.append)
check("素材与当时一致时不刷日志",
      not any("素材与当时不同" in line for line in _logs), _logs)

# ---------------- 6. 真实回放文件能反查出方案 ----------------
real_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data")
replay_dir = os.path.join(real_root, "user", "replays")
files = []
if os.path.isdir(replay_dir):
    files = [os.path.join(replay_dir, name) for name in os.listdir(replay_dir)
             if name.endswith(".replay.json")]
# 反查靠素材存在性，而 data/ 里的素材随时会被作者删改：只挑「至少还能命中
# 一个方案目录」的样本断言，全部命不中就跳过——别让素材搬家变成测试失败。
sample = None
if files:
    import json
    from persistence.scenario_repo import ScenarioRepo

    repo = ScenarioRepo(real_root)
    roots = [repo.scenario_dir(sid) for sid in repo.list_all()]
    for path in sorted(files, key=os.path.getmtime, reverse=True):
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        records = replay.parse_all(raw)
        paths = replay.material_paths(records, 16)
        if any(os.path.exists(os.path.join(root, rel))
               for rel in paths for root in roots):
            sample = (path, records)
            break
if sample:
    newest, records = sample
    host = Host(ScenarioRepo(real_root))
    host._resolve_replay_scenario(records)
    check("真实回放文件反查出了方案（有章节背景时）", bool(host.scenario_id),
          (newest, host.scenario_id))
else:
    print("  SKIP 真实回放文件（没有素材还能命中方案目录的样本）")

print("")
print(f"{total - len(failures)}/{total} 通过")
if failures:
    print("失败：" + "、".join(failures))
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
print(open(_report_path, encoding="utf-8").read())
sys.exit(1 if failures else 0)
