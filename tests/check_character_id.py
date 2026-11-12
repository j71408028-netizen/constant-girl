"""F2 回归守卫：角色显示名不得直接组成档案路径。

用法：``python tests/check_character_id.py``

**为什么需要**：``giantess_id`` 是档案目录名（``data/archives/<id>/``）与聊天
容器的键，而它曾经由「显示名 + 时间戳」拼成。名字里带 ``/`` 就切出嵌套目录，
``list_ids()`` 再也枚举不到；Windows 的保留字符还会让保存直接异常。

本守卫三部分：

1. **id 派生**：``make_id`` 把路径语义收紧（分隔符 / Windows 保留字符 /
   控制字符 / 结尾的点与空格），名字抽空时兜底，同秒撞名追加序号；
2. **两条建角色链**：探索的 ``CharacterAssembler`` 与副本的
   ``_create_character_from_session`` 给出带斜杠、带保留字符的名字后，
   档案仍是一层目录且可枚举，``state.name`` 原样保留显示名；
3. **报告 / 回放文件名**：同一处兜底要贯通到档案里的文件名，不能再用裸名字。

退出码：0 = 通过；1 = 行为不符。
"""
import datetime
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from core.models import Personality  # noqa: E402
from dungeon.window.persistence import DungeonPersistence  # noqa: E402
from persistence.character_repo import CharacterRepo, id_segment, make_id  # noqa: E402
from services.exploration.character import CharacterAssembler  # noqa: E402

failures = []
total = 0

#: 任何平台都不能出现在目录名 / 文件名里的字符
RESERVED = set('<>:"/\\|?*')


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


def _core(name):
    return {
        "name": name, "nick": "", "original_height": 1.6,
        "height": 30.0, "body_parts": {"身高": 30.0},
        "personality_obj": _personality(),
        "base_intrusion": 1.0, "base_destruction": 1.0,
        "greed": 0.0, "will": False, "will_status": None,
        "selected_tags": [], "intro_hidden": "", "intro_visible": "",
        "birthday": "", "uploaded_image": None,
        "total_casualties": 0.0, "position": "",
    }


# ---------------- 1. id 派生 ----------------
_stamp = datetime.datetime(2026, 11, 12, 21, 30, 15)
check("名字段只把分隔符折成下划线",
      make_id("甲/乙", now=_stamp) == "甲_乙_20261112213015", make_id("甲/乙", now=_stamp))
for raw in ("甲\\乙", "甲:乙", "甲*乙", "甲?乙", '甲"乙', "甲<乙", "甲>乙", "甲|乙"):
    got = make_id(raw, now=_stamp)
    check(f"保留字符被替换：{raw}", not (set(got) & RESERVED), got)
check("控制字符被替换", not (set(make_id("甲\n乙", now=_stamp)) & {"\n"}), "换行仍在")
check("结尾的点与空格不会留在 id 里",
      make_id("甲. . ", now=_stamp).startswith("甲_"), make_id("甲. . ", now=_stamp))
check("纯点号名字回落到兜底",
      make_id("..", now=_stamp) == f"角色_20261112213015", make_id("..", now=_stamp))
check("空名字回落到兜底",
      make_id("   ", now=_stamp).startswith("角色_"), make_id("   ", now=_stamp))
_long = make_id("长" * 80, now=_stamp)
check("名字段有长度上限", len(id_segment("长" * 80)) <= 48, len(id_segment("长" * 80)))
check("超长名字仍带时间戳", _long.endswith("_20261112213015"), _long)
check("同秒撞名追加序号",
      make_id("甲", now=_stamp, taken={f"甲_20261112213015"}) == "甲_20261112213015_2")
check("显示名本身不被改写（纯函数）",
      id_segment("甲/乙") == "甲_乙")

# ---------------- 2a. 探索链 ----------------
repo = CharacterRepo(tempfile.mkdtemp(prefix="char_id_explore_"))
_tmp_assembler = CharacterAssembler(repo, {}, world_state=None)
state = _tmp_assembler.character_from_core_or_report(_core("甲/乙"))
check("探索：显示名原样保留", state.name == "甲/乙", state.name)
check("探索：id 不含路径分隔符", not (set(state.giantess_id) & RESERVED), state.giantess_id)
check("探索：档案可被枚举", repo.list_ids() == [state.giantess_id], repo.list_ids())
check("探索：档案目录只有一层",
      os.listdir(repo.states_dir) == [state.giantess_id]
      and os.path.isfile(os.path.join(repo.states_dir, state.giantess_id, "info.json")),
      os.listdir(repo.states_dir))

# 同秒内名字只差一个保留字符：规范化后同名，不能互相覆盖
_second = _tmp_assembler.character_from_core_or_report(_core("甲:乙"))
check("探索：规范化后同名也不覆盖",
      _second.giantess_id != state.giantess_id and len(repo.list_ids()) == 2,
      repo.list_ids())

# ---------------- 2b. 副本链 ----------------
repo2 = CharacterRepo(tempfile.mkdtemp(prefix="char_id_dungeon_"))


def _session(name, repo=None):
    session = types.SimpleNamespace(
        name=name, nick="", original_height=1.6, height=30.0,
        body_parts={"身高": 30.0}, personality=_personality(), greed=0.0,
        tags=[], intro_hidden="", intro_visible="",
        character_repo=repo, _pending_exit_position="",
        dungeon_state=types.SimpleNamespace(
            intrusion=1.0, destruction=1.0, total_casualties=0.0,
            depth_intrusion=None, depth_destruction=None),
    )
    session._create_character_from_session = types.MethodType(
        DungeonPersistence._create_character_from_session, session)
    return session


char = _session("丙/丁:戊", repo2)._create_character_from_session()
check("副本：显示名原样保留", char.name == "丙/丁:戊", char.name)
check("副本：id 不含路径分隔符", not (set(char.giantess_id) & RESERVED), char.giantess_id)
repo2.save(char)
check("副本：档案可被枚举", repo2.list_ids() == [char.giantess_id], repo2.list_ids())

# 没有仓库也不该炸（旧替身 / 自检路径传 character_repo=None）
_bare = _session("丙/丁", None)._create_character_from_session()
check("副本：无仓库时仍给出可用 id",
      not (set(_bare.giantess_id) & RESERVED) and _bare.giantess_id.startswith("丙_丁_"),
      _bare.giantess_id)

# ---------------- 3. 档案内的文件名 ----------------
def _source(relative):
    with open(os.path.join(ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


persistence_src = _source(os.path.join("dungeon", "window", "persistence.py"))
check("档案文件名不直接用裸名字", "{char.name}_" not in persistence_src)
check("回放与报告文件名都走 id_segment",
      persistence_src.count("id_segment(char.name)") == 2,
      persistence_src.count("id_segment(char.name)"))
check("探索报告文件名走 id_segment",
      "id_segment(name)" in _source(os.path.join("ui", "exploration", "report.py")))
check("挂件报告文件名走 id_segment",
      "id_segment(name)" in _source(os.path.join("ui", "mini", "report_view.py")))

# ---------------- 结论 ----------------
print()
if failures:
    print(f"[check_character_id] FAILED {len(failures)}/{total}: " + "; ".join(failures))
    sys.exit(1)
print(f"[check_character_id] PASSED {total}/{total}")
