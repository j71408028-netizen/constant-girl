"""检查更新：GitHub Releases 查询与版本比较。

只在用户显式触发（「检查更新」入口 / ``check-update`` 子命令）时发起网络请求；
不做启动自动检查，也不做后台轮询。本模块只负责取数与比较，展示由
``app/maintenance.py`` 承担；返回的 :class:`ReleaseInfo` 结构同时为将来的
一键更新预留（版本号、下载页、附件名清单）。
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from paths import APP_REPO_URL, APP_SLUG, APP_VERSION

#: 请求超时（秒）。
DEFAULT_TIMEOUT = 10.0


class UpdateCheckError(Exception):
    """检查失败（网络不可达、限流、响应不是合法的 Release JSON）。"""


@dataclass(frozen=True)
class ReleaseInfo:
    """一次 Release 查询的结果。"""

    #: 版本号（tag 去掉前导 ``v``，如 ``2.0.0``）。
    version: str
    #: 原始 tag（如 ``v2.0.0``）。
    tag: str
    #: 发布标题。
    title: str
    #: Releases 页面地址（浏览器打开用）。
    html_url: str
    #: 发布时间（ISO 8601，GitHub 原样返回）。
    published_at: str
    #: 附件文件名清单（一键更新按 ``<slug>-<ver>-<os>-<arch>.zip`` 匹配）。
    asset_names: tuple


def releases_api_url() -> str:
    """GitHub Releases latest 的 API 地址。"""
    return APP_REPO_URL.replace("https://github.com/", "https://api.github.com/repos/") \
        + "/releases/latest"


def parse_version(text) -> tuple:
    """把版本字符串解析成可比较元组 ``(核心三元组, 预发布段)``。

    支持 ``2.0.0``、``v2.0.0``、``2.0.0 beta``、``2.0.0-beta.1``、``2.0.0-rc.2``
    等写法；预发布排序为 alpha < beta < rc < 正式。无法解析返回 ``None``。
    """
    if not isinstance(text, str):
        return None
    text = text.strip().lstrip("vV").strip()
    match = re.match(
        r"^(\d+)\.(\d+)\.(\d+)"
        r"(?:[-.\s]?(alpha|beta|rc)(?:[-.\s]?(\d+))?)?$",
        text, re.IGNORECASE)
    if not match:
        return None
    core = tuple(int(part) for part in match.groups()[:3])
    label = (match.group(4) or "").lower()
    number = int(match.group(5) or 0)
    rank = {"alpha": 0, "beta": 1, "rc": 2}.get(label, 3)
    return core, (rank, number)


def compare_versions(current, latest) -> int:
    """比较两个版本：落后返回 -1，相同返回 0，领先返回 1。

    无法解析的一侧按「最旧」处理；两侧都无法解析视为相同。
    """
    parsed_current = parse_version(current)
    parsed_latest = parse_version(latest)
    if parsed_current is None or parsed_latest is None:
        if parsed_current is None and parsed_latest is None:
            return 0
        return 1 if parsed_latest is None else -1
    if parsed_current < parsed_latest:
        return -1
    if parsed_current > parsed_latest:
        return 1
    return 0


def fetch_latest_release(timeout: float = DEFAULT_TIMEOUT,
                         opener=None) -> ReleaseInfo:
    """查询 GitHub 最新 Release；失败抛 :class:`UpdateCheckError`（文案可读）。

    ``opener`` 供测试注入；缺省用 :func:`urllib.request.urlopen`。
    """
    url = releases_api_url()
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{APP_SLUG}/{APP_VERSION}",
    })
    try:
        open_url = opener or urllib.request.urlopen
        with open_url(request, timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = "（请求过于频繁或受限，请稍后再试）" if exc.code in (403, 429) else ""
        raise UpdateCheckError(f"GitHub 返回 HTTP {exc.code}{detail}") from exc
    except urllib.error.URLError as exc:
        raise UpdateCheckError(f"无法连接 GitHub：{exc.reason}") from exc
    except (OSError, ValueError) as exc:
        raise UpdateCheckError(f"检查更新失败：{exc}") from exc

    if not isinstance(data, dict) or not isinstance(data.get("tag_name"), str):
        raise UpdateCheckError("GitHub 响应不是有效的 Release 信息")
    tag = data["tag_name"].strip()
    assets = data.get("assets")
    asset_names = tuple(
        item.get("name", "") for item in assets
        if isinstance(item, dict) and item.get("name")) if isinstance(assets, list) else ()
    return ReleaseInfo(
        version=tag.lstrip("vV"),
        tag=tag,
        title=str(data.get("name") or tag),
        html_url=str(data.get("html_url") or APP_REPO_URL + "/releases/latest"),
        published_at=str(data.get("published_at") or ""),
        asset_names=asset_names,
    )
