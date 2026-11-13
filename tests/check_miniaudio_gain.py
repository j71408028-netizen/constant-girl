"""miniaudio 供数自检：每块乘的增益必须与它自己的位置对齐，不出声、不碰设备。

用法：``python tests/check_miniaudio_gain.py``
输出：控制台一行 ASCII 结论 + UTF-8 报告文件路径。

覆盖：
1. 逐块增益按块偏移取样本（第二块不能被乘成整段开头的采样）；
2. 供数总长等于片段长度、块边界落在帧边界上；
3. 循环：第二轮同样从零开始且音量按当时的值走；
4. 满音量直通与 0 音量静音两档口径不变；
5. numpy 缺席时的降级口径（0 静音、其余直放）不变；
6. 音量在供数途中变化：已吐出的块不受影响，之后的块按新值算。

自检刻意不经过 ``start()``：那里会真的开一个 ``PlaybackDevice``。回调协议
只要求 generator 先 ``next()`` prime、之后用 ``send(帧数)`` 索要下一块，
这里直接照这个协议驱动 :meth:`MiniaudioTrack._voice`。
"""

import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_report_path = os.path.join(tempfile.mkdtemp(prefix="miniaudio_gain_"), "report.txt")
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


from dungeon import audio as audio_mod  # noqa: E402

CHANNELS = 1


def pcm(samples):
    """S16 单声道样本 → 交错字节。"""
    return struct.pack("<%dh" % len(samples), *samples)


def unpack(raw):
    return list(struct.unpack("<%dh" % (len(raw) // 2), raw))


def pull(track, frames, loop=None, limit=64):
    """照回调协议驱动一次播放，返回吐出的每一块样本。

    ``frames`` 是每块索要的帧数，``loop`` 缺省跟 ``MiniaudioTrack.start`` 一致
    （一次性语音不循环），``limit`` 只是防呆上限。generator 耗尽（非循环播完）
    时停止。
    """
    voice = track._voice(bool(loop))
    next(voice)                    # prime：第一次 send 才真正开始供数
    chunks = []
    for _ in range(limit):
        try:
            raw = voice.send(frames)
        except StopIteration:
            break
        chunks.append(unpack(raw))
    voice.close()
    return chunks


check("numpy 可用时按样本逐个乘增益（本项只决定后续分支）",
      audio_mod._numpy() is not None)


# ---------------- 1. 逐块偏移：审计里的最小复现 ----------------
_track = audio_mod.MiniaudioTrack(pcm((100, 200, 300, 400)), 1, 24000)
_track.set_volume(0.5)
_chunks = pull(_track, 2)           # 每块 2 帧，整段 4 帧 → 两块后播完
check("4 样本按 2 帧供数会吐出两块", len(_chunks) == 2, _chunks)
check("第一块按自身位置乘增益（100,200 → 50,100）",
      _chunks and _chunks[0] == [50, 100], _chunks)
check("第二块按自身位置乘增益（300,400 → 150,200，不是 50,100）",
      len(_chunks) == 2 and _chunks[1] == [150, 200], _chunks)

# ---------------- 2. 供数总长与块边界 ----------------
_STEREO = [10, -10, 20, -20, 30, -30, 40, -40, 50, -50]     # 5 帧 × 2 声道
_track = audio_mod.MiniaudioTrack(pcm(_STEREO), 2, 24000)
_track.set_volume(1.0)
_chunks = pull(_track, 2)
_flat = [s for chunk in _chunks for s in chunk]
check("循环外的整段供数不丢样本、不重复", _flat == _STEREO, (_flat, _chunks))
check("整段供完后 generator 自行耗尽（不循环）", len(_chunks) == 3, _chunks)

_track = audio_mod.MiniaudioTrack(pcm([1, 2, 3, 4, 5]), 1, 24000)
_chunks = pull(_track, 3)
_flat = [s for chunk in _chunks for s in chunk]
check("块长不是整帧时按整帧截断（不出现半帧）",
      _flat == [1, 2, 3, 4, 5] and all(len(c) in (3, 2) for c in _chunks),
      _chunks)

# ---------------- 3. 循环：第二轮仍从位置 0 起算 ----------------
_track = audio_mod.MiniaudioTrack(pcm((100, 200, 300, 400)), 1, 24000)
_track.set_volume(0.5)
_voice = _track._voice(True)
next(_voice)
_sent = [_voice.send(2) for _ in range(3)]      # 两块一轮 + 第二轮的第一块
_voice.close()
_round2 = unpack(_sent[2]) if len(_sent) > 2 else []
check("循环时第二轮的第一块同样从头取样本（50,100）",
      _round2 == [50, 100], (_round2, [unpack(s) for s in _sent]))

# ---------------- 4. 满音量与静音两档 ----------------
_track = audio_mod.MiniaudioTrack(pcm((100, 200, 300, 400)), 1, 24000)
_track.set_volume(1.0)
_chunks = pull(_track, 2)
check("满音量直通：原样吐出、逐块都不改样本",
      _chunks == [[100, 200], [300, 400]], _chunks)

_track = audio_mod.MiniaudioTrack(pcm((100, 200, 300, 400)), 1, 24000)
_track.set_volume(0.0)
_chunks = pull(_track, 2)
check("0 音量：每块都是静音（不是只有第一块是 0）",
      _chunks == [[0, 0], [0, 0]], _chunks)

# ---------------- 5. numpy 缺席的降级口径 ----------------
_track = audio_mod.MiniaudioTrack(pcm((100, 200, 300, 400)), 1, 24000)
_track._samples = None             # 模拟本机没装 numpy
_track.set_volume(0.0)
check("没有 numpy 时 0 音量整块静音",
      _track._apply_gain(pcm((300, 400)), 4) == b"\x00" * 4)
_track.set_volume(0.5)
check("没有 numpy 时非 0 音量直放（已知降级）",
      _track._apply_gain(pcm((300, 400)), 4) == pcm((300, 400)))

# ---------------- 6. 供数途中改音量 ----------------
_track = audio_mod.MiniaudioTrack(pcm((100, 200, 300, 400)), 1, 24000)
_track.set_volume(0.5)
_voice = _track._voice(False)
next(_voice)
_first = unpack(_voice.send(2))
_track.set_volume(1.0)
_second = unpack(_voice.send(2))
_voice.close()
check("已吐出的块按当时的音量，之后的块按新音量",
      _first == [50, 100] and _second == [300, 400], (_first, _second))

# ---------------- 结论 ----------------
_log.flush()
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
if failures:
    print(f"[check_miniaudio_gain] FAILED {len(failures)}/{total}: {failures}")
else:
    print(f"[check_miniaudio_gain] PASSED {total}/{total}")
print(f"[check_miniaudio_gain] report: {_report_path}")
sys.exit(1 if failures else 0)
