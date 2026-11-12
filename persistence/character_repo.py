import datetime
import os
import re
import shutil
from dataclasses import asdict
from typing import Optional

from core import imaging
from core.models import CharacterSnapshot
from .json_store import load_json_with_backup, write_json_atomic

#: 角色 id 中名字部分的长度上限（给时间戳与去重后缀留余量，远低于路径长度限制）
_ID_NAME_MAX = 48
#: 目录名里不能出现的字符：路径分隔符、Windows 保留字符、控制字符。
#: 显示名可以任意，id 要能当目录名——两者的边界就在这里。
_ID_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_ID_UNDERSCORE_RUN = re.compile(r"_{2,}")
#: 名字抠空后的兜底（纯符号 / 纯点号的名字仍然要能有档案目录）
_ID_FALLBACK = "角色"


def id_segment(name: str) -> str:
    """显示名 → 可安全用作目录名的一段文本（保留中文，不做 slug 化）。"""
    text = _ID_ILLEGAL_CHARS.sub("_", str(name or ""))
    text = _ID_UNDERSCORE_RUN.sub("_", text)
    # 结尾的点与空格在 Windows 上会被静默截掉，首尾的装饰字符一并去掉
    text = text.strip(" ._")[:_ID_NAME_MAX]
    return text.strip(" ._")


def make_id(name: str, now: Optional[datetime.datetime] = None, taken=()) -> str:
    """按显示名派生角色 id：``<名字段>_<时间戳>``，撞车时追加序号。

    显示名仍原样保存在 ``CharacterSnapshot.name``；id 只作目录名与容器键
    （档案、聊天、回放都按它找路径），所以这里把路径语义收紧。名字里的
    ``/`` 不会再切出嵌套目录，Windows 保留字符也不会让保存直接失败。
    """
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    base = id_segment(name) or _ID_FALLBACK
    candidate = f"{base}_{stamp}"
    used = {str(item) for item in (taken or ())}
    index = 2
    while candidate in used:
        candidate = f"{base}_{stamp}_{index}"
        index += 1
    return candidate


class CharacterRepo:
    def __init__(self, data_dir: str = "data"):
        self._dir = os.path.join(data_dir, "archives")

    @property
    def states_dir(self) -> str:
        return self._dir

    def _character_path(self, giantess_id: str) -> str:
        return os.path.join(self._dir, giantess_id)

    def _data_file_path(self, giantess_id: str) -> str:
        return os.path.join(self._character_path(giantess_id), "info.json")

    def save(self, state: CharacterSnapshot):
        state.updated_at = datetime.datetime.now().isoformat()
        char_dir = self._character_path(state.giantess_id)
        os.makedirs(char_dir, exist_ok=True)
        # 角色档案与副本方案同待遇：原子写 + 覆盖前留 .bak，
        # 保存中途崩溃/断电不会把档案截断清零
        write_json_atomic(os.path.join(char_dir, "info.json"), asdict(state))

    def load(self, giantess_id: str) -> Optional[CharacterSnapshot]:
        data = load_json_with_backup(self._data_file_path(giantess_id))
        if data is None:
            return None
        return CharacterSnapshot.from_dict(data)

    def save_avatar(self, giantess_id: str, source_path: str, low_resolution: bool = False) -> str:
        char_dir = self._character_path(giantess_id)
        avatar_dir = os.path.join(char_dir, "avatar")
        os.makedirs(avatar_dir, exist_ok=True)
        existing = [f for f in os.listdir(avatar_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp'))]
        next_num = 1
        if existing:
            nums = []
            for f in existing:
                base = os.path.splitext(f)[0]
                if base.isdigit():
                    nums.append(int(base))
            if nums:
                next_num = max(nums) + 1
        ext = os.path.splitext(source_path)[1] or '.png'

        if low_resolution:
            try:
                from PIL import Image
                img = Image.open(source_path)
                if getattr(img, "is_animated", False):
                    img.seek(0)
                resized = imaging.resize_low_resolution(img)
                if resized.mode not in ("RGB", "RGBA"):
                    resized = resized.convert("RGB")
                dest = os.path.join(avatar_dir, f"{next_num}.png")
                resized.save(dest, "PNG")
                return f"avatar/{next_num}.png"
            except Exception:
                pass

        dest = os.path.join(avatar_dir, f"{next_num}{ext}")
        shutil.copy2(source_path, dest)
        return f"avatar/{next_num}{ext}"

    def get_avatar_abspath(self, giantess_id: str, avatar_path: str) -> str:
        if not avatar_path:
            return ""
        if os.path.isabs(avatar_path):
            return avatar_path
        return os.path.join(self._character_path(giantess_id), avatar_path)

    def delete(self, giantess_id: str) -> bool:
        char_dir = self._character_path(giantess_id)
        if not os.path.exists(char_dir):
            return False
        shutil.rmtree(char_dir)
        return True

    def list_ids(self):
        if not os.path.exists(self._dir):
            return []
        return [d for d in os.listdir(self._dir)
                if os.path.isdir(os.path.join(self._dir, d))
                and os.path.exists(os.path.join(self._dir, d, "info.json"))]
