"""挑战包内的地标：从载荷构造副本要用的 ``Landmark`` 列表。

挑战包自带 ``landmark_data``（创建时从发送方仓库导出），但宿主一直以来是拿
包里的 ``landmark_styles`` 去**本机仓库**重载——接收方没有这些风格时副本
就只剩本机默认风格的地标，包里那份数据从未参与。本模块把包内数据直接还原
成地标，并以发送方同款方式补齐地址：

- 包内条目已带完整地址（``address_mode == "exact"``）时原样采用；
- 缺地址的按「同风格同名的本机地标 → 本机地址索引 → 风格注册地址」补齐；
- 补不上就标 ``portable``（尺寸与名字照常参与对比，只是不参与地址相配）。

补出来的地址和 ``AddressPlanner.landmarks_for_export`` 一样是**完整地址**：
副本会话在子进程里跑，那里没有地标仓库，解析不了相对后缀。
"""

from dataclasses import replace

from core.models import Landmark, is_valid_landmark_size
from services.exploration.address_index import MODE_EXACT

_LANDMARK_FIELDS = tuple(Landmark.__dataclass_fields__)


def _entry_landmark(item) -> "Landmark | None":
    """``landmark_data`` 的单条 → ``Landmark``；字段/尺寸不合法返回 None。"""
    if not isinstance(item, dict):
        return None
    try:
        landmark = Landmark(**{k: v for k, v in item.items()
                               if k in _LANDMARK_FIELDS})
    except (TypeError, ValueError):
        return None
    return landmark if is_valid_landmark_size(landmark.size) else None


def _local_by_style(context):
    """``{风格 id: [Landmark]}``：本机同风格地标，供缺地址的包内条目对照。"""
    repo = getattr(getattr(context, "catalog", None), "landmark_repo", None)
    table = {}
    for style in getattr(context, "selected_styles", None) or []:
        try:
            table[style] = list(repo.load(style)) if repo is not None else []
        except Exception:
            table[style] = []
    return table


def _local_address(context, landmark):
    """按本机地址索引解析同名地标的完整地址；解析不出来返回空串。"""
    index = getattr(context, "address_index", None)
    if index is None:
        return ""
    try:
        return index.address(landmark) or ""
    except Exception:
        return ""


def landmarks_from_pack(data: dict, context=None) -> list:
    """把 ``landmark_data`` 还原成副本载荷用的地标列表。

    ``context`` 是宿主侧探索上下文（只读其 ``selected_styles`` /
    ``address_index``）；不传时包内条目要么自带地址，要么按 portable 处理。

    返回的每条地标都是 ``address_mode == "exact"``（带完整地址）或
    ``"portable"``，与 ``landmarks_for_export`` 的导出契约一致。
    """
    if not isinstance(data, dict):
        return []
    raw = data.get("landmark_data") or {}
    if not isinstance(raw, dict):
        return []
    styles = [s for s in (data.get("landmark_styles") or []) if s] or list(raw)
    local_table = _local_by_style(context) if context is not None else {}

    result = []
    for style in styles:
        local_by_name = {lm.name: lm for lm in local_table.get(style) or []}
        for item in raw.get(style) or []:
            landmark = _entry_landmark(item)
            if landmark is None:
                continue
            if (landmark.address_mode or "").strip().lower() == MODE_EXACT \
                    and (landmark.address or "").strip():
                result.append(landmark)
                continue
            address = ""
            twin = local_by_name.get(landmark.name)
            if twin is not None:
                address = _local_address(context, twin)
            if not address:
                address = _local_address(context, landmark)
            if address:
                result.append(replace(landmark, address=address,
                                      address_mode=MODE_EXACT))
            else:
                result.append(replace(landmark, address="",
                                      address_mode="portable"))
    return result


__all__ = ["landmarks_from_pack"]
