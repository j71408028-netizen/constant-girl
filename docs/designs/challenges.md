# 挑战包

> **这一篇回答什么问题**：`.chal` 里有什么、秘钥怎么管、创建 / 导入 / 启动的流程，
> 以及启动时地标与素材怎么从包里还原。类型声明与信封见 [resources.md](resources.md)；
> 副本准入与方案的素材解析见 [dungeon/admission.md](dungeon/admission.md) 与
> [dungeon/script.md](dungeon/script.md)。

## 1. 包内有什么

`.chal` 是一个 zip，两部分：

- `challenge_data.bin`：加密后的 JSON（`pack_data`）——`version`（`"2.0"`）、`intro`、
  `character_id`、`character_data`、`landmark_styles`、`landmark_data`、`scenario_id`、
  `scenario_config`、`asset_paths`、`created_at`（描述不进包）；
- `assets/…`：方案引用的明文素材，只收 `texts` / `images` / `audio` / `endings`
  四类目录下、配置引用到且磁盘真实存在的文件（`collect_asset_paths` 扫
  `fixed_text.path` / `background.image_path` / `bgm.path` / `icon_path` 与
  `chapters[].endings[].icon_path`；方案目录外的绝对路径一律不收）。

加密：JSON 经 PBKDF2-HMAC-SHA256（10 万轮，盐 = 16 字节 IV）派生密钥，
HMAC-SHA256 分块密钥流异或；文件头 `MAGIC_V2` 校验（兼容旧逐字节格式）。

## 2. 秘钥

- 本地注册表 `data/user/challenge_keys.json`：`{包基名(不含 .chal): 64 位 hex}`，
  全仓唯一不可再生数据，原子写 + `.bak`；并同步到环境变量
  `GIANTESS_CHALLENGE_KEYS`。
- 世界包附带挑战包时，秘钥随包记录在包内 `challenges/keys.json`（同形状）。
- 能解 = 持有秘钥者；`try_open_with_keys` 用全部已注册秘钥逐个试开。秘钥不对或
  数据损坏报「秘钥不正确或数据损坏」；没有注册秘钥报「未找到秘钥，请先创建或
  导入」。
- 读元数据（`get_challenge_meta`：intro / 角色名 / scenario_id）不需要区分哪个秘钥
  属于哪个包，试开成功即取。

## 3. 创建

挑战页填显示名 → 资源 id（`registry.suggest_id` 派生或手填，`valid_id_of` 校验）→
选角色 + 地标风格组 + 剧本 + 简介 → `create_challenge(...)`：

- 同名 `.chal` **拒绝覆盖**（秘钥注册后旧包无法再生）；
- 写临时 zip 后 `os.replace` 原子落盘到 `data/packs/challenges/<id>.chal`，注册秘钥，
  显示名写兄弟信封；
- **秘钥只返回给作者一次**：分享 = `.chal` 文件 + 秘钥两者都给。

## 4. 导入与启动

- **导入**（`import_pack(source_path, key)`）：先用秘钥试开验证，通过后复制到存储
  目录并注册秘钥；秘钥不对直接报「导入失败，秘钥不正确」。
- **启动**：`resolve_pack_path` 解析位置（世界包附带目录优先，其次自由目录）→
  `_extract_assets` 把素材解到**临时目录**（不落进方案目录，会话结束删除；解出的
  目录结构与方案目录一致，直接顶替方案目录参与相对路径解析；`assets/../../x` 类
  越界条目跳过不抛错）→ 地标不走本机仓库重载，`landmarks_from_pack` 直接从包内
  `landmark_data` 还原：`address_mode=="exact"` 且带地址的原样用；缺地址的按
  「同风格同名本机地标 → 本机地址索引 → 都没有则标 `portable`」补齐。
- **包内容回灌本机仓库**：`import_landmark_challenge_pack` /
  `import_quip_challenge_pack` 把包内资源写回自由层（尺寸无效的地标条目在导入时
  丢弃）。

## 5. 界面与守卫

- 玩家入口是主界面的「挑战模式」；作者入口在挑战页（创建）。
- 索引与校验：`opaque` 容器纳入索引时必须外加兄弟 `<id>.meta.json`
  （`registry.validate_resource` 报 `missing_envelope`）；可选同名 `.png` 封面。

## 6. 文件 / 函数索引

| 要点 | 位置 |
|---|---|
| 创建 / 打开 / 秘钥注册 / 加解密 | `services/challenges/service.py::create_challenge` / `open_challenge` / `try_open_with_keys` / `_register_key` / `_encrypt` / `_decrypt` |
| 素材收集 / 打包 / 解压 | `services/challenges/pack.py::collect_asset_paths` / `pack_assets` / `extract_pack_assets` |
| 包内地标重建（exact / portable） | `services/challenges/landmarks.py::landmarks_from_pack` |
| 包内容回灌 | `services/challenges/imports.py::import_landmark_challenge_pack` / `import_quip_challenge_pack` |
| 秘钥落盘 | `data/user/challenge_keys.json`（`service.py::_keys_file_path`） |
