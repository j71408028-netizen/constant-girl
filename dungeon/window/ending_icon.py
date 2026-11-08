"""结局图标的共享助手：路径解析与 GPU 纹理上传。

入口页轮播、实时结局与回放共用同一套口径：icon_path 相对副本目录解析
（绝对路径 → 当前副本根 → 自由副本根）；图像等比缩放后贴到透明正方形
画布上，再上传为 ``TextureGpu``。纹理创建须在 GL 就绪后调用。
"""

import os
import re

from PIL import Image


def free_dungeons_root() -> str:
    """自由副本根目录（不经方案的副本都收在这里）。"""
    from paths import data_dir
    return os.path.join(data_dir(), "packs", "scenarios")


def _split_rel(icon_path: str) -> list:
    """把相对路径里的 \\ 与 / 都当作分隔符，并忽略 . / .. 段。"""
    parts = []
    for piece in re.split(r"[\\/]+", str(icon_path)):
        if piece in ("", ".", ".."):
            continue
        parts.append(piece)
    return parts


def resolve_ending_icon(scenario_repo, scenario_id: str, icon_path: str):
    """解析结局图标实际文件路径。

    优先级：绝对路径 → 当前副本根目录 → 自由副本根目录（data/packs/scenarios）。
    返回 None 表示找不到文件。
    """
    icon_path = str(icon_path or "").strip()
    if not icon_path:
        return None
    candidates = []
    if os.path.isabs(icon_path):
        candidates.append(os.path.normpath(icon_path))
    rel_parts = _split_rel(icon_path)
    scenario_id = (scenario_id or "").strip("/\\")
    for base in (scenario_repo.root if scenario_repo is not None else None,
                 free_dungeons_root()):
        if not base or not scenario_id:
            continue
        candidates.append(os.path.normpath(os.path.join(base, scenario_id, *rel_parts)))
    for path in dict.fromkeys(candidates):
        if os.path.isfile(path):
            return path
    return None


def square_icon_canvas(pil, box: int) -> Image.Image:
    """把图标等比缩放后贴到 ``box×box`` 透明画布上（正方形留白口径）。

    只做像素加工、不触 GL，可离线单测。小于 ``box`` 的图不放大。
    """
    pil = pil.convert("RGBA")
    w, h = pil.size
    ratio = min(box / w, box / h) if (w and h) else 0.0
    tw, th = w, h
    if ratio and ratio < 1.0:
        tw, th = max(1, round(w * ratio)), max(1, round(h * ratio))
        pil = pil.resize((tw, th), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    canvas.paste(pil, ((box - tw) // 2, (box - th) // 2))
    return canvas


def load_ending_icon_texture(pil, box: int):
    """把已打开的图标上传为正方形留白的 GPU 纹理。

    ``pil`` 传 None（无图标）静默返回 ``(None, "")``；加载/上传失败返回
    ``(None, 原因)``，由调用方决定日志与降级表现。``box`` 是目标边长
    （像素），调用方按 DPI 换算。须在 GL 就绪后调用（无上下文直调会在
    gladLoadGL 段错误而不是抛异常）。
    """
    if pil is None:
        return None, ""
    from imgui_bundle import hello_imgui
    import numpy as np

    try:
        canvas = square_icon_canvas(pil, box)
        rgba = np.frombuffer(canvas.tobytes(), dtype=np.uint8).reshape(
            canvas.size[1], canvas.size[0], 4)
        return hello_imgui.create_texture_gpu_from_rgba_data(rgba), ""
    except Exception as exc:
        return None, str(exc)
