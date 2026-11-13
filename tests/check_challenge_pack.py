"""挑战包跨机资源闭环自检（无 GUI、不触 GL）。

用法：``python tests/check_challenge_pack.py``

为什么需要：挑战包曾经只带加密配置，地标按本机风格 id 重载、方案素材（固定
文本 / 背景图 / BGM / 结局图标）完全不出包。接收方没有发送方的自由资源时：
包里那份 ``landmark_data`` 从未被用，固定文本还会被判 error 直接拦住进入
（``dungeon/validate.py::_validate_fixed_text``）。本脚本锁住打包 → 解包 →
解析 → 启动参数这条闭环：

1. ``collect_asset_paths``：只收 ``texts/images/audio/endings`` 下的相对路径，
   绝对路径与 ``..`` 越界一律不收；
2. 建包：zip 里同时有加密配置与 ``assets/`` 条目，载荷的 ``asset_paths``
   只列真实入包的文件；
3. 解包：结构还原成方案目录布局，恶意条目名不会写到目标目录外；
4. 素材解析：``asset_dir`` 顶替后，校验不再报固定文本 error，背景 / BGM /
   结局图标三处都能命中；
5. 地标：``landmarks_from_pack`` 从包内还原，不依赖本机风格仓库。
"""

import json
import os
import sys
import tempfile
import types
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_report_dir = tempfile.mkdtemp(prefix="challenge_pack_check_")
_report_path = os.path.join(_report_dir, "report.txt")
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


from core.models import CharacterSnapshot, Landmark, Personality  # noqa: E402
from dungeon.validate import validate_scenario_config  # noqa: E402
from services.challenges import landmarks_from_pack  # noqa: E402
from services.challenges.pack import (  # noqa: E402
    collect_asset_paths, extract_pack_assets, has_pack_assets)
from services.challenges.service import ChallengeService  # noqa: E402
from ui.hosting.dungeon_child_host import (  # noqa: E402
    _AssetBackedRepo, _scenario_repo_with_assets)
from ui.hosting.dungeon_spawner import launch_dungeon_subprocess  # noqa: E402,F401

CONFIG = {
    "chapters": [
        {"name": "开场", "start": True, "ending": False,
         "fixed_text": {"path": "texts/opening.txt"},
         "background": {"image_path": "images/bg.png"},
         "bgm": {"path": "audio/bgm.mp3"},
         "endings": [{"name": "结局A", "icon_path": "endings/a.png"}]},
        {"name": "空章节", "ending": True},
    ],
    "triggers": [
        {"name": "插曲",
         "background": {"image_path": "images/extra.png"},
         "fixed_text": {"path": "texts/extra.txt"}},
    ],
}

# ---------------- 1. 素材清单口径 ----------------
paths = collect_asset_paths(CONFIG)
check("收集章节与触发器的四类素材",
      paths == sorted(["texts/opening.txt", "images/bg.png", "audio/bgm.mp3",
                       "endings/a.png", "images/extra.png", "texts/extra.txt"]),
      paths)
check("绝对路径不进清单",
      collect_asset_paths({"chapters": [{"bgm": {"path": "C:/temp/x.mp3"}}]}) == [])
check("越界路径不进清单",
      collect_asset_paths({"chapters": [{"bgm": {"path": "texts/../../x.mp3"}}]}) == [])
check("白名单外的目录不进清单",
      collect_asset_paths({"chapters": [{"bgm": {"path": "other/x.mp3"}}]}) == [])
check("空配置不炸", collect_asset_paths({}) == [] and collect_asset_paths(None) == [])

# ---------------- 2. 造发送方环境并建包 ----------------
work = tempfile.mkdtemp(prefix="challenge_pack_src_")
scenario_root = os.path.join(work, "scenarios")
scenario_id = "sc_pack"
scenario_dir = os.path.join(scenario_root, scenario_id)
for rel, content in (("texts/opening.txt", "第一段\n\n第二段\n"),
                     ("texts/extra.txt", "插曲\n"),
                     ("images/bg.png", "png-bytes"),
                     ("images/extra.png", "png-bytes-2"),
                     ("audio/bgm.mp3", "mp3-bytes"),
                     ("endings/a.png", "icon-bytes")):
    target = os.path.join(scenario_dir, *rel.split("/"))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(content)


class _ScenarioRepo:
    """最小方案仓库：建包只用到 load_config 与 asset_dir。"""

    def __init__(self, root, sid):
        self.root = self.write_root = self.read_root = root
        self._sid = sid

    def scenario_dir(self, scenario_id):
        return os.path.join(self.root, scenario_id)

    def asset_dir(self, scenario_id):
        return self.scenario_dir(scenario_id)

    def load_config(self, scenario_id):
        return json.loads(json.dumps(CONFIG))


class _CharacterRepo:
    def load(self, cid):
        return CharacterSnapshot(
            giantess_id=cid, name="测试", nick="", original_height=1.7,
            height=1.7, selected_tags=[], greed=0,
            personality=Personality(name="性格", init_intrusion=1.0,
                                    depth_intrusion=0.0, init_destruction=1.0,
                                    depth_destruction=0.0, sensitivity=0.0))


class _LandmarkRepo:
    def load(self, style):
        return [Landmark(name="塔", size=100.0, dimension="vertical",
                         frequency="unique")]

    def get_styles(self):
        return ["sender_only"]


class _SettingsRepo:
    def load(self):
        return {}

    def save(self, settings):
        pass


storage = os.path.join(work, "challenges")
service = ChallengeService(_SettingsRepo(), _CharacterRepo(), _LandmarkRepo(),
                           None, _ScenarioRepo(scenario_root, scenario_id),
                           data_dir=work)
key = service.create_challenge("c1", ["sender_only"], scenario_id,
                               "简介", "pack_a", title="包A")
pack_path = os.path.join(service.storage_dir, "pack_a.chal")
check("包文件已生成", os.path.isfile(pack_path), pack_path)

with zipfile.ZipFile(pack_path) as zf:
    names = set(zf.namelist())
check("zip 内有加密配置条目", "challenge_data.bin" in names, sorted(names))
check("zip 内有全部素材条目",
      {"assets/" + p for p in paths} <= names, sorted(names))
check("has_pack_assets 认得素材条目", has_pack_assets(pack_path) is True)

data = service.open_challenge(pack_path, password=key)
check("载荷列出真实入包的素材",
      data.get("asset_paths") == paths, data.get("asset_paths"))
check("载荷保留了地标数据", "塔" in json.dumps(data.get("landmark_data"), ensure_ascii=False))

# ---------------- 3. 解包到干净目录 ----------------
asset_root = tempfile.mkdtemp(prefix="challenge_pack_dst_")
count = service.extract_assets(pack_path, asset_root)
check("解出的文件数与清单一致", count == len(paths), count)
check("解包后按方案目录布局落盘",
      all(os.path.isfile(os.path.join(asset_root, *p.split("/"))) for p in paths))

# 恶意条目名：不能写到目标目录之外
evil_zip = os.path.join(work, "evil.chal")
outside = os.path.join(work, "outside.txt")
with zipfile.ZipFile(evil_zip, "w") as zf:
    zf.writestr("assets/../../outside.txt", "evil")
    zf.writestr("assets/texts/../ok.txt", "ok")
extract_pack_assets(evil_zip, asset_root)
check("越界条目不会写到目标目录外", not os.path.exists(outside), outside)

# ---------------- 4. 素材解析（asset_dir 顶替） ----------------
repo = _ScenarioRepo(scenario_root, scenario_id)
backed = _AssetBackedRepo(repo, asset_root)
check("asset_dir 指向解包目录", backed.asset_dir(scenario_id) == asset_root)
check("scenario_dir 仍走原仓库",
      backed.scenario_dir(scenario_id) == os.path.join(scenario_root, scenario_id))
check("无素材目录时原样返回仓库",
      _scenario_repo_with_assets(repo, "") is repo)

diags = validate_scenario_config(CONFIG, scenario_dir=backed.asset_dir(scenario_id))
errors = [d for d in diags if getattr(d, "level", "") == "error"]
check("包内素材齐全时校验无 error", not errors,
      [str(d) for d in errors])

from dungeon.window.ending_icon import resolve_ending_icon  # noqa: E402

check("结局图标经 asset_dir 命中",
      resolve_ending_icon(backed, scenario_id, "endings/a.png")
      == os.path.join(asset_root, "endings", "a.png"))

# 子进程里那套包一层的仓库也要能被背景 / 文本解析用上
from dungeon.window.background import DungeonBackground  # noqa: E402

owner = types.SimpleNamespace(scenario_repo=backed, scenario_id=scenario_id)
bg = types.SimpleNamespace(owner=owner)
resolved = DungeonBackground.resolve_path(bg, "images/bg.png")
check("背景图经 asset_dir 命中",
      resolved == os.path.normpath(os.path.join(asset_root, "images", "bg.png")),
      resolved)

from dungeon import script_text  # noqa: E402

script, error = script_text.load_script_file(
    os.path.join(asset_root, "texts", "opening.txt"))
check("固定文本可读且有段落",
      script is not None and bool(script.paragraphs), error)

# ---------------- 5. 地标来自包内 ----------------
pack_landmarks = landmarks_from_pack(data, None)
check("包内地标被还原", [lm.name for lm in pack_landmarks] == ["塔"],
      [lm.name for lm in pack_landmarks])
check("无本机上下文时缺地址地标按 portable",
      pack_landmarks[0].address_mode == "portable")

exact_data = json.loads(json.dumps(data))
exact_data["landmark_data"]["sender_only"][0].update(
    {"address": "1e3_1e2@W-A", "address_mode": "exact"})
exact = landmarks_from_pack(exact_data, None)
check("自带完整地址的地标原样采用",
      exact[0].address_mode == "exact" and exact[0].address == "1e3_1e2@W-A",
      (exact[0].address_mode, exact[0].address))
check("包内尺寸非法的条目被丢弃",
      landmarks_from_pack({"landmark_styles": ["s"],
                           "landmark_data": {"s": [{"name": "坏", "size": 0,
                                                    "dimension": "vertical",
                                                    "frequency": "unique"}]}}) == [])
check("空载荷不炸", landmarks_from_pack({}) == [] and landmarks_from_pack(None) == [])

# ---------------- 结论 ----------------
_log.flush()
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
if failures:
    print(f"[check_challenge_pack] FAILED {len(failures)}/{total}: {failures}")
else:
    print(f"[check_challenge_pack] PASSED {total}/{total}")
print(f"[check_challenge_pack] report: {_report_path}")
sys.exit(1 if failures else 0)
