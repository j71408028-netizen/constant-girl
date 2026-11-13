"""挑战包导入：列出可用挑战包与把地标/描述数据导入对应仓库。

原 ``services/helpers.py`` 拆散归位（§4.2 步骤 3），与 ChallengeService 同包；
包内建包说明见 ``services/challenges/__init__.py``。
"""

import os

from services.challenges.service import ChallengeService


def get_challenge_packs(settings_repo):
    cm = ChallengeService(settings_repo)
    if not cm.has_any_valid_key():
        return []
    return cm.get_available_packs()


def challenge_pack_titles(settings_repo, packs) -> dict:
    """``{包文件名: 显示名}``；只读兄弟信封，不打开包。"""
    cm = ChallengeService(settings_repo)
    return {name: cm.pack_title(name) for name in packs}


def _open_challenge_pack(settings_repo, pack_name):
    cm = ChallengeService(settings_repo)
    file_path = os.path.join(cm.storage_dir, pack_name)
    result = cm.try_open_with_keys(file_path)
    if result is None:
        raise ValueError(f"无法读取挑战包 '{pack_name}'，未找到对应秘钥")
    data, _, _ = result
    if not data:
        raise ValueError("挑战包数据为空")
    return data


def import_landmark_challenge_pack(settings_repo, pack_name, repo):
    from core.models import Landmark, is_valid_landmark_size
    data = _open_challenge_pack(settings_repo, pack_name)
    styles = data.get("landmark_styles", [])
    raw_data = data.get("landmark_data", {})
    if not styles or not raw_data:
        raise ValueError("该挑战包中没有地标数据")
    imported_count = 0
    for style in styles:
        raw = raw_data.get(style, [])
        if not raw:
            continue
        landmarks = []
        skipped = 0
        for item in raw:
            try:
                landmark = Landmark(**item)
            except (TypeError, ValueError):
                skipped += 1
                continue
            # 包内容来自别人的机器：尺寸无效的条目留在仓库里会让之后的
            # 每份报告都失败，导入时就丢掉。
            if is_valid_landmark_size(landmark.size):
                landmarks.append(landmark)
            else:
                skipped += 1
        if skipped:
            print(f"[挑战包] {style}: 跳过 {skipped} 条尺寸或字段无效的地标")
        if not landmarks:
            continue
        repo.save(style, landmarks)
        imported_count += len(landmarks)
        if style not in repo.get_styles():
            repo.create_style(style)
    return imported_count


def import_quip_challenge_pack(settings_repo, pack_name, repo):
    data = _open_challenge_pack(settings_repo, pack_name)
    styles = data.get("quip_styles", [])
    raw_data = data.get("quip_data", {})
    if not styles or not raw_data:
        raise ValueError("该挑战包中没有描述数据")
    imported_count = 0
    for style in styles:
        raw = raw_data.get(style, {})
        if not raw:
            continue
        converted = {}
        for size_cat, matrix in raw.items():
            converted[size_cat] = {}
            for key, qlist in matrix.items():
                if "_" in key:
                    parts = key.split("_")
                    if len(parts) == 2:
                        converted[size_cat][(int(parts[0]), int(parts[1]))] = qlist
                    else:
                        converted[size_cat][key] = qlist
                else:
                    converted[size_cat][key] = qlist
            imported_count += sum(len(qlist) for qlist in converted[size_cat].values())
        repo.save(style, converted)
        if style not in repo.get_styles():
            repo.create_style(style)
    return imported_count
