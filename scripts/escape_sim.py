# -*- coding: utf-8 -*-
"""escape_giantess py 版逻辑链无头回归（无需显示器，进 ``checks.yml`` 门禁）。

三段，都不建渲染上下文：

1. **关卡生成**：连续生成 N 关（两主题），校验出口格、出生点身体可站、连通区不塌；
2. **随机走位**：用桩 API 实跑 update()（走位 + 投弹），压移动 / 危险 / 结算 / 重开，
   只要求不抛异常；
3. **结算 payload**：分别强制一次胜、一次负，断言 ``api.finish`` 收到的形状。

第 3 段是确定性的：让随机 bot 自己打到第 30 关要靠运气，所以直接把玩家摆到出口
再推一帧，验的是 ``win_level`` / ``lose`` → ``finish`` 这条回传链，而不是 bot 的水平。

与 ``dungeon_autopilot.py --scene mini-game-escape`` 的分工：那条验渲染链路（离屏
纹理上传 / 每帧绘制 / 中止），本脚本验关卡生成与整局玩法逻辑，因此能进 PR 的离线矩阵。

种子默认固定，让门禁失败可复现；``--seed random`` 走真随机，用来拓宽探索面。
"""
import argparse
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data", "packs", "minigames", "escape_giantess"))

import game as g  # noqa: E402
from dungeon.window.minigame.stage import _PILCanvas  # noqa: E402

DEFAULT_SEED = 1234
TARGET_LEVEL = 30
#: 随机走位阶段的帧预算（约 40 秒游戏内时间，实测 3 秒左右）
MAX_PLAY_FRAMES = 2400
DT = 1 / 60.0


class StubApi:
    """headless 桩：offscreen 真画（PIL），draw_* 全 no-op，按键可注入。"""

    def __init__(self):
        self.keys = set()
        self.finished = None
        self.hud_text = ""

    width = 1280
    height = 800

    def key_down(self, key):
        return key in self.keys

    def mouse_pos(self):
        return (0, 0)

    def mouse_down(self, button=0):
        return False

    def finish(self, result=None):
        """与 ``dungeon.window.minigame.base.GameAPI.finish`` 同签名（单参）。"""
        if self.finished is None:
            self.finished = (dict(result) if isinstance(result, dict)
                             else {"level": result})

    def hud(self, text):
        self.hud_text = text

    def notify(self, message):
        pass

    def read_state(self, key):
        return None

    def draw_rect(self, *a, **k):
        pass

    def draw_round_rect(self, *a, **k):
        pass

    def draw_circle(self, *a, **k):
        pass

    def draw_line(self, *a, **k):
        pass

    def draw_polygon(self, *a, **k):
        pass

    def draw_text(self, *a, **k):
        pass

    def draw_image(self, *a, **k):
        pass

    def offscreen(self, width, height, bg=None):
        return _PILCanvas(width, height, bg=bg, root=os.path.dirname(
            os.path.join(ROOT, "data", "packs", "minigames", "escape_giantess")))


def _parse_seed(value):
    if value == "random":
        return int.from_bytes(os.urandom(8), "big")
    return int(value)


def _settle(game_inst, api, max_frames=120):
    """把当前横幅推完，返回 ``api.finish`` 收到的 payload（未结算返回 None）。"""
    for _ in range(max_frames):
        game_inst.update(DT)
        if api.finished is not None:
            return api.finished
        if game_inst._banner is not None:
            game_inst._end_timer = 0.0   # 跳过横幅等待，下一帧结算
    return None


def check_generation(rnd):
    """连续生成多关，校验硬约束。"""
    themes = {"city": 0, "flesh": 0}
    for lv in (1, 3, 5, 8):
        for _ in range(6):
            for _retry in range(120):     # 与 _start_level 同款重试
                gen_rng = g.mulberry32(rnd.randrange(1 << 32))
                if gen_rng() < 0.5:
                    g._gen_city(gen_rng, lv)
                    themes["city"] += 1
                else:
                    g._gen_flesh(gen_rng, lv)
                    themes["flesh"] += 1
                if g._find_spawn_and_exit(gen_rng):
                    break
            else:
                raise AssertionError(f"lv{lv}: 120 次重试内无可用关卡")
            assert g._S.get_tile(*g._S.exit_pos) == g.EXIT, "出口格必须是 EXIT"
            p = g._S.player
            assert g._S.body_stands(p["tx"], p["ty"]), "出生点身体站不下"
            # 大开区面积下限（原版 findSpawnAndExit 的 0.6 可达比例已保证，
            # 这里再验一次 largestOpenArea 不塌）
            assert g._largest_open_area() > 100 * g.SCALE, "连通区异常小"
    print("gen ok, themes:", themes, flush=True)


def check_random_play(game_inst, api, rnd):
    """随机走位压一段：不要求赢，只要求不抛异常；自然结算后照真实会话之外的方式重开。"""
    frames = settled = 0
    keys = ["w", "a", "s", "d"]
    while frames < MAX_PLAY_FRAMES and api.finished is None:
        # 简单 bot：每 0.4s 换一个随机方向，偶尔投弹
        if frames % 24 == 0:
            api.keys.clear()
            api.keys.add(keys[rnd.randrange(4)])
        if frames % 97 == 0:
            api.keys.add("space")
        else:
            api.keys.discard("space")
        game_inst.update(DT)
        frames += 1
        if game_inst._banner is not None:
            game_inst._end_timer = 0.0   # 跳过横幅等待
        if api.finished is not None:
            settled += 1
            result = api.finished
            print("settle:", result, flush=True)
            # 真实会话在结算时就结束了；这里重开来继续压后续关卡
            api.finished = None
            game_inst._reset_run()
            game_inst._start_level(result.get("level", 1) + 1)
            game_inst._sync_hud()
    assert frames > 60, "模拟帧数异常少（过早卡死）"
    print(f"play ok, frames={frames} settled={settled}", flush=True)


def check_settlement(game_inst, api):
    """强制一次胜、一次负，断言回传 payload 的形状（这是当初改签名时漏掉的地方）。"""
    # 胜利：玩家占 1 格（BODY=1），摆到出口再推一帧即可触发 win_level
    api.finished = None
    game_inst._reset_run()
    game_inst._start_level(TARGET_LEVEL)
    assert g._S.level == TARGET_LEVEL, "目标关没摆上"
    ex, ey = g._S.exit_pos
    assert g._S.body_stands(ex, ey), "出口格应可站"
    g._S.player.update({"tx": ex, "ty": ey, "sx": ex, "sy": ey,
                        "px": float(ex), "py": float(ey), "t": 1.0, "moving": True})
    won = _settle(game_inst, api)
    assert won is not None, "胜利没有结算"
    # 不冻结整个 payload 的形状（游戏往后可以加字段），只钉住语义：
    # level 是返回值，胜负判定靠有无 reason
    assert won.get("level") == TARGET_LEVEL, f"胜利应回传目标关：{won}"
    assert "reason" not in won, f"胜利不该带失败原因：{won}"
    print("win ok:", won, flush=True)

    # 失败：payload 必须带 reason，关卡号是当前关
    api.finished = None
    game_inst._reset_run()
    game_inst._start_level(1)
    game_inst.lose("sim")
    lost = _settle(game_inst, api)
    assert lost is not None, "失败没有结算"
    assert lost.get("level") == 1 and lost.get("reason") == "sim", \
        f"失败 payload 不对：{lost}"
    print("lose ok:", lost, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="escape_giantess 无头逻辑回归")
    parser.add_argument("--seed", default=str(DEFAULT_SEED),
                        help=f"随机种子（默认 {DEFAULT_SEED}，固定值保证可复现）；"
                             "传 random 走真随机")
    args = parser.parse_args(argv)
    seed = _parse_seed(args.seed)
    # 局的关卡是 _start_level 里用全局 random 生成的，也要一起定住才谈得上可复现；
    # bot 用独立流，免得它的抽样被玩法内部的随机消耗带偏。
    random.seed(seed)
    rnd = random.Random(seed ^ 0x5EED)
    print(f"seed: {seed}", flush=True)

    check_generation(rnd)

    api = StubApi()
    game_inst = g.EscapeGiantessGame()
    game_inst.api = api
    game_inst.setup({"target_level": TARGET_LEVEL})
    check_random_play(game_inst, api, rnd)
    check_settlement(game_inst, api)

    print("SIM_DONE", flush=True)


if __name__ == "__main__":
    main()
