"""检查更新自检：版本比较与 GitHub Releases 拉取（HTTP 全部打桩，不联网）。

用法：``python tests/check_update_check.py``
输出：控制台一行 ASCII 结论 + UTF-8 报告文件路径。

覆盖：
1. 版本解析：纯版本 / ``v`` 前缀 / ``beta`` / 预发布号 / 坏输入；
2. 版本比较：落后、相同、领先；预发布序 alpha < beta < rc < 正式；
   解析失败一侧按最旧处理；
3. ``fetch_latest_release``：成功响应、HTTP 403/404、连接失败、非 JSON、
   缺 ``tag_name`` —— 失败一律是带可读文案的 :class:`UpdateCheckError`；
4. ``ReleaseInfo`` 结构：版本号、tag、发布页、附件名清单（一键更新预留形状）。
"""

import io
import json
import os
import sys
import tempfile
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_report_path = os.path.join(tempfile.mkdtemp(prefix="update_check_"), "report.txt")
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


from services.update_check import (ReleaseInfo, UpdateCheckError,  # noqa: E402
                                   compare_versions, fetch_latest_release,
                                   parse_version, releases_api_url)

# ---------------- 版本解析 ----------------

check("纯版本解析", parse_version("2.0.0") == ((2, 0, 0), (3, 0)))
check("v 前缀解析", parse_version("v2.0.0") == ((2, 0, 0), (3, 0)))
check("beta 后缀解析（当前 APP_VERSION 写法）",
      parse_version("2.0.0 beta") == ((2, 0, 0), (1, 0)))
check("预发布号解析", parse_version("2.0.0-beta.1") == ((2, 0, 0), (1, 1)))
check("rc 解析", parse_version("2.0.0-rc.2") == ((2, 0, 0), (2, 2)))
check("坏输入返回 None",
      parse_version("") is None and parse_version("abc") is None
      and parse_version("2.0") is None and parse_version(None) is None)

# ---------------- 版本比较 ----------------

check("beta 落后于正式版", compare_versions("2.0.0 beta", "2.0.0") == -1)
check("相同版本（v 前缀不影响）", compare_versions("2.0.0", "v2.0.0") == 0)
check("正式版领先于 beta", compare_versions("2.0.0", "1.9.9") == 1)
check("补丁版本落后", compare_versions("2.0.0", "2.0.1") == -1)
check("预发布号有序", compare_versions("2.0.0-beta.1", "2.0.0-beta.2") == -1)
check("rc 领先于 beta", compare_versions("2.0.0-rc.1", "2.0.0-beta.9") == 1)
check("alpha 落后于 beta", compare_versions("2.0.0-alpha.1", "2.0.0-beta.1") == -1)
check("解析失败一侧按最旧处理",
      compare_versions("dev", "2.0.0") == -1
      and compare_versions("2.0.0", "dev") == 1
      and compare_versions("dev", "dev") == 0)

# ---------------- fetch_latest_release（打桩） ----------------

API = releases_api_url()
check("API 地址来自 APP_REPO_URL", API.endswith("/constant-girl/releases/latest"))


class _FakeResponse(io.IOBase):
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self, *args):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def opener_ok(request, timeout=None):
    return _FakeResponse(json.dumps({
        "tag_name": "v2.0.1",
        "name": "2.0.1",
        "html_url": "https://github.com/j71408028-netizen/constant-girl/releases/v2.0.1",
        "published_at": "2026-12-01T00:00:00Z",
        "assets": [{"name": "constant-girl-2.0.1-windows-x64.zip"},
                   {"name": "constant-girl-2.0.1-src.zip"},
                   "bad-entry"],
    }).encode("utf-8"))


def opener_http_error(request, timeout=None):
    raise urllib.error.HTTPError(API, 403, "rate limited", None, io.BytesIO(b""))


def opener_url_error(request, timeout=None):
    raise urllib.error.URLError("connection refused")


def opener_bad_json(request, timeout=None):
    return _FakeResponse(b"<html>not json</html>")


def opener_no_tag(request, timeout=None):
    return _FakeResponse(b'{"message": "Not Found"}')


release = fetch_latest_release(opener=opener_ok)
check("成功拉取：版本号去 v", release.version == "2.0.1")
check("成功拉取：tag / 标题 / 发布页", release.tag == "v2.0.1"
      and release.title == "2.0.1"
      and release.html_url.endswith("/releases/v2.0.1"))
check("成功拉取：附件名清单（一键更新预留形状）",
      release.asset_names == ("constant-girl-2.0.1-windows-x64.zip",
                              "constant-girl-2.0.1-src.zip"))

for opener, fragment in (
        (opener_http_error, "403"),
        (opener_url_error, "无法连接"),
        (opener_bad_json, "检查更新失败"),
        (opener_no_tag, "Release")):
    try:
        fetch_latest_release(opener=opener)
        check(f"失败路径 {fragment} 抛 UpdateCheckError", False, "未抛异常")
    except UpdateCheckError as exc:
        check(f"失败路径 {fragment} 给出可读文案", fragment in str(exc), str(exc))

info_shape = ReleaseInfo(version="2.0.0", tag="v2.0.0", title="2.0.0",
                         html_url="https://example.com",
                         published_at="2026-11-13T00:00:00Z",
                         asset_names=("a.zip",))
check("ReleaseInfo 字段齐全",
      info_shape.version == "2.0.0" and info_shape.tag == "v2.0.0"
      and isinstance(info_shape.asset_names, tuple))

# ---------------- 结论 ----------------
_log.flush()
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
if failures:
    print(f"[check_update_check] FAILED {len(failures)}/{total}: {failures}")
else:
    print(f"[check_update_check] PASSED {total}/{total}")
print(f"[check_update_check] report: {_report_path}")
sys.exit(1 if failures else 0)
