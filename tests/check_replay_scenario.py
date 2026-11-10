"""自检：回放反查所属方案（背景 / 音乐 / 结局图标相对路径的前提）。

用法：``python tests/check_replay_scenario.py``

回放文件只存记录、不带方案标识，而记录里的素材路径都相对方案目录。少了这一步
反查，回放开场既不换背景也不放音乐（路径解析失败，画面停在入口那张图）。这里
用临时方案目录验证反查规则，并顺手确认反查出来的方案真的能让背景路径解析成功。
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


from dungeon import replay  # noqa: E402
from dungeon.window.background import DungeonBackground  # noqa: E402
from dungeon.window.base import DungeonWindowBase  # noqa: E402


class FakeRepo:
    """临时方案根：``{方案 id: 目录}``。"""

    def __init__(self, dirs):
        self._dirs = dict(dirs)
        self.root = os.path.dirname(next(iter(dirs.values()))) if dirs else ""

    def list_all(self):
        return sorted(self._dirs)

    def scenario_dir(self, scenario_id):
        return self._dirs.get(scenario_id, "")


class Host(DungeonWindowBase):
    """只带反查所需状态的宿主（不建窗口、不碰素材渲染）。"""

    def __init__(self, repo, scenario_id=None):
        self.scenario_repo = repo
        self.scenario_id = scenario_id


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

# ---------------- 5. 真实回放文件能反查出方案 ----------------
real_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data")
replay_dir = os.path.join(real_root, "user", "replays")
newest = None
if os.path.isdir(replay_dir):
    files = [os.path.join(replay_dir, name) for name in os.listdir(replay_dir)
             if name.endswith(".replay.json")]
    if files:
        newest = max(files, key=os.path.getmtime)
if newest:
    import json
    from persistence.scenario_repo import ScenarioRepo

    with open(newest, encoding="utf-8") as handle:
        raw = json.load(handle)
    records = replay.parse_all(raw)
    host = Host(ScenarioRepo(real_root))
    host._resolve_replay_scenario(records)
    has_background = any(isinstance(r, replay.ChapterRecord) and r.background.get("image_path")
                         for r in records)
    check("真实回放文件反查出了方案（有章节背景时）",
          bool(host.scenario_id) or not has_background,
          (newest, host.scenario_id))
else:
    print("  SKIP 真实回放文件（data/user/replays 下没有样本）")

print("")
print(f"{total - len(failures)}/{total} 通过")
if failures:
    print("失败：" + "、".join(failures))
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
print(open(_report_path, encoding="utf-8").read())
sys.exit(1 if failures else 0)
