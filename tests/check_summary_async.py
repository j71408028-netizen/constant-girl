"""剧情压缩异步流水线自检：切块 / 乱序保序 / 等待落地 / flush 补压缩。

用法：``python tests/check_summary_async.py``
输出：控制台一行 ASCII 结论 + UTF-8 报告文件路径。

覆盖：
1. detach_chunk：满块才切、切出即从缓冲移除、序号递增、不满返回 None；
2. compress_chunk：不碰实例状态，AI 失败回退内部算法；
3. apply_result：后台乱序返回仍按序号写回，概要保持时间顺序；
4. 搭车角色更新与事实卡随异步结果写回，可被 drain；
5. wait_pending：等在途块落地后才返回；
6. flush_chapter：先等在途块，再压缩剩余不满一块的缓冲，概要完整；
7. 同步路径 maybe_compress 仍可用（回放/测试口径不变）。
"""

import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_report_path = os.path.join(tempfile.mkdtemp(prefix="summary_async_check_"), "report.txt")
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


from dungeon.summary import StorySummarizer  # noqa: E402


class _Client:
    """返回可解析的概要 JSON，记录调用次数。"""

    def __init__(self, summary="概括"):
        self.summary = summary
        self.calls = 0

    def generate(self, messages, **kwargs):
        self.calls += 1
        return ('{"summary": "' + self.summary + '", '
                '"facts": ["事实一"], '
                '"character_updates": [{"who": "王店主", "true_name": "王店主"}]}')


# ---------------- 1. detach_chunk ----------------
s = StorySummarizer(block_size=2)
check("不满一块不切", s.detach_chunk() is None)
s.record("dialog", "第一段。", "第一幕")
check("一块差一条也不切", s.detach_chunk() is None)
s.record("dialog", "第二段。", "第一幕")
s.record("dialog", "第三段。", "第一幕")
taken0 = s.detach_chunk()
check("满块切出并带序号/标签",
      taken0 is not None and taken0[0] == 0 and len(taken0[1]) == 2
      and taken0[2] == "第一幕" and [t[1] for t in taken0[1]] == ["第一段。", "第二段。"],
      str(taken0))
taken1 = s.detach_chunk()
check("切出即从缓冲移除（剩余不满不切）", taken1 is None)
check("序号按切块递增", s._next_issue == 1)

# ---------------- 2. compress_chunk ----------------
chunk = taken0[1]
client = _Client()
result0 = s.compress_chunk(chunk, client)
check("compress_chunk 走 AI 且返回三段",
      client.calls == 1 and result0[0] == "概括"
      and result0[1] == ["事实一"] and len(result0[2]) == 1, str(result0))
check("compress_chunk 不碰缓冲/已写回状态",
      s.summaries == [] and s._next_write == 0)


class _BrokenClient:
    def generate(self, messages, **kwargs):
        raise RuntimeError("boom")


broken = s.compress_chunk(chunk, _BrokenClient())
check("AI 失败回退内部算法（概要非空、无事实/更新）",
      bool(broken[0]) and broken[1] == [] and broken[2] == [], str(broken))

# ---------------- 3. apply_result 乱序保序 ----------------
p = StorySummarizer(block_size=1)
for i in range(3):
    p.record("dialog", f"第{i}段。", "第一幕")
segs = [p.detach_chunk() for _ in range(3)]
check("连续切出三块序号 0/1/2", [t[0] for t in segs] == [0, 1, 2])
# 故意倒序返回：2 → 0 → 1
p.apply_result(segs[2][0], segs[2][2], ("概要2", [], []), segs[2][1])
check("后面的块先返回不提前写概要", p.summaries == [], str(p.summaries))
p.apply_result(segs[0][0], segs[0][2], ("概要0", [], []), segs[0][1])
check("序号 0 落地后只写它自己", [x[1] for x in p.summaries] == ["概要0"],
      str(p.summaries))
p.apply_result(segs[1][0], segs[1][2], ("概要1", [], []), segs[1][1])
check("序号补齐后按时间顺序全部写回",
      [x[1] for x in p.summaries] == ["概要0", "概要1", "概要2"],
      str(p.summaries))
check("重复写回同一序号不重复追加",
      (p.apply_result(segs[1][0], segs[1][2], ("重复", [], []), segs[1][1]),
       [x[1] for x in p.summaries])[1] == ["概要0", "概要1", "概要2"])

# ---------------- 4. 搭车更新与事实卡写回 ----------------
a = StorySummarizer(block_size=1)
a.record("dialog", "胆怯的声音说：我就是王店主。", "第一幕")
seg = a.detach_chunk()
a.apply_result(seg[0], seg[2], result0, seg[1])
check("异步写回合并事实卡", a.facts == ["事实一"], str(a.facts))
batch = a.drain_character_updates()
check("异步写回带正文锚点的角色更新并可 drain",
      len(batch) == 1 and "王店主" in batch[0][0]
      and batch[0][1][0]["true_name"] == "王店主", str(batch))
check("取走后清空", a.drain_character_updates() == [])

# ---------------- 5. wait_pending ----------------
w = StorySummarizer(block_size=1)
w.record("dialog", "慢段。", "第一幕")
wseg = w.detach_chunk()
check("等待时确实有在途块", w._next_write < w._next_issue)


def _late_write():
    time.sleep(0.15)
    w.apply_result(wseg[0], wseg[2], ("慢概要", [], []), wseg[1])


threading.Thread(target=_late_write, daemon=True).start()
w.wait_pending()
check("wait_pending 等到在途块写回才返回",
      w._next_write == w._next_issue and len(w.summaries) == 1,
      f"write={w._next_write} issue={w._next_issue} sum={w.summaries}")
t0 = time.monotonic()
w.wait_pending()
check("无在途块时 wait_pending 立即返回",
      time.monotonic() - t0 < 0.05)

# ---------------- 6. flush_chapter 先等后压 ----------------
f = StorySummarizer(block_size=2)
f.record("dialog", "甲段。", "第一幕")
f.record("dialog", "乙段。", "第一幕")
fseg = f.detach_chunk()  # 块 0 在途
f.record("dialog", "丙段。", "第二幕")  # 剩余不满一块
fc = _Client("后台概要")


def _bg_compress():
    res = f.compress_chunk(fseg[1], fc)
    time.sleep(0.2)  # 制造延迟：flush 必须先等它
    f.apply_result(fseg[0], fseg[2], res, fseg[1])


threading.Thread(target=_bg_compress, daemon=True).start()
f.flush_chapter("第二幕", ai_client=_Client("剩余概要"))
check("flush 等在途块 + 压缩剩余，概要完整且有序",
      [x[1] for x in f.summaries] == ["后台概要", "剩余概要"],
      str(f.summaries))

# ---------------- 7. 同步路径仍可用 ----------------
sync = StorySummarizer(block_size=2)
sync.record("dialog", "一。", "第一幕")
sync.record("dialog", "二。", "第一幕")
sync.maybe_compress(2, ai_client=_Client("同步概要"))
check("同步 maybe_compress 仍写回概要（回放/测试口径）",
      len(sync.summaries) == 1 and sync.summaries[0][1] == "同步概要",
      str(sync.summaries))
sync.record("dialog", "三。", "第一幕")
sync.flush_chapter("第一幕", ai_client=_Client("尾部概要"))
check("同步 flush_chapter 压缩剩余",
      len(sync.summaries) == 2 and sync.summaries[1][1] == "尾部概要",
      str(sync.summaries))

print(f"\n[check_summary_async] {'PASSED' if not failures else 'FAILED'} "
      f"{total - len(failures)}/{total}")
print(f"[check_summary_async] report: {_report_path}")
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
print(("ALL PASS" if not failures else "FAILURES: " + ", ".join(failures))
      + f"  report: {_report_path}")
sys.exit(1 if failures else 0)
