# -*- coding: utf-8 -*-
"""昵称占位符自检：取材表里的 {sur}/{given} 在掷昵称时按本轮姓/名渲染。

用法：``python tests/check_nick_placeholder.py``
纯逻辑，不建窗口、不联网、不碰 data/。

行为锁：
- 单次扫描替换，两个占位符可任意顺序、重复出现；
- 未知花括号、普通文本原样保留；空昵称仍返回空；
- 与姓名表一起掷出时用**同一轮**的姓/名替换，缺列回落也照样渲染。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.creation_service import CreationService  # noqa: E402

failures = []
total = 0


def check(name, ok, extra=""):
    global total
    total += 1
    print(("  OK   " if ok else "  FAIL ") + name
          + (f"  <{extra}>" if extra and not ok else ""))
    if not ok:
        failures.append(name)


resolve = CreationService.resolve_nick_placeholders

# ---------------- 1. 纯渲染 ----------------

check("两个占位符按姓/名替换",
      resolve("{sur}家小{given}", "王", "静") == "王家小静")
check("占位符可重复且顺序不限",
      resolve("{given}·{sur}·{given}", "欧阳", "娜娜") == "娜娜·欧阳·娜娜")
check("未知花括号与普通文本原样保留",
      resolve("{nick}/{sur}/{foo}!{given}", "王", "静")
      == "{nick}/王/{foo}!静")
check("旧占位符 {name} 已不再识别，原样保留",
      resolve("{name}", "王", "静") == "{name}")
check("空昵称仍返回空", resolve("", "王", "静") == "")
check("空姓/名时对应占位符替换为空串",
      resolve("[{sur}][{given}]", "", "") == "[][]")
check("无占位符的昵称不变",
      resolve("404NotStudent", "王", "静") == "404NotStudent")


# ---------------- 2. 掷姓名昵称时同轮渲染 ----------------

class FakeNameRepo:
    """只实现 CreationService 用到的 load 接口，姓名表内容固定。"""

    def __init__(self, surnames=("王",), weights=(1.0,),
                 names=("静",), nicks=()):
        self.surnames = list(surnames)
        self.weights = list(weights)
        self.names = list(names)
        self.nicks = list(nicks)

    def load(self, group=None):
        return self.surnames, self.weights, self.names, self.nicks


def roll(surnames=("王",), weights=(1.0,), names=("静",), nicks=()):
    return CreationService(name_repo=FakeNameRepo(
        surnames, weights, names, nicks)).generate_random_name_nick()


for pattern, expected in (
        ("{sur}{given}酱", "王静酱"),
        ("小{given}", "小静"),
        ("{sur}家的{given}", "王家的静"),
        ("叫我{given}大人", "叫我静大人"),
        ("固定昵称", "固定昵称")):
    name, nick = roll(nicks=(pattern,))
    check(f"掷出「{pattern}」→「{expected}」",
          name == "王静" and nick == expected, f"name={name} nick={nick}")

name, nick = roll(nicks=())
check("昵称表缺席时仍返回空昵称", name == "王静" and nick == "")

name, nick = roll(surnames=("欧阳",), names=("娜娜",),
                  nicks=("{sur}{given}",))
check("复姓/双字名也用同一轮值替换",
      name == "欧阳娜娜" and nick == "欧阳娜娜", f"nick={nick}")

name, nick = roll(surnames=(), weights=(), names=(),
                  nicks=("{sur}{given}",))
check("姓/名回落到王、静时占位符照样渲染",
      name == "王静" and nick == "王静", f"name={name} nick={nick}")

print()
if failures:
    print(f"[check_nick_placeholder] FAILED {len(failures)}/{total}: "
          + "; ".join(failures))
    sys.exit(1)
print(f"[check_nick_placeholder] PASSED {total}/{total}")
