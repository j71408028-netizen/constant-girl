"""挑战包域：加密挑战包的创建、存储、秘钥管理与数据导入（§4.2 步骤 3 自
``challenge_service.py`` 与 ``helpers.py`` 的挑战包半边归位）。

挑战包是包含地标 / 描述风格 / 方案素材等数据的加密压缩包，通过秘钥保护内容
安全；数据导入侧（``imports``）把包内容写回地标 / 描述仓库，启动侧用
``landmarks`` 还原包内地标、``pack`` 解出方案素材。
"""

from services.challenges.imports import (
    challenge_pack_titles, get_challenge_packs,
    import_landmark_challenge_pack, import_quip_challenge_pack, unique_display,
)
from services.challenges.landmarks import landmarks_from_pack
from services.challenges.service import ChallengeService
