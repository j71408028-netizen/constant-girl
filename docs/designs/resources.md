# 资源与包体系

> **这一篇回答什么问题**：程序里「资源」指什么、一共几类、各自长什么样、怎么命名、
> 怎么被索引与比对；以及取材表、描述语料这两类成组数据的细则。挑战包的加密与秘钥
> 见 [challenges.md](challenges.md)，世界包的打包与激活见 [world_packs.md](world_packs.md)。

## 1. 八种资源类型

「资源」指成组、可替换、可打包的内容。类型清单**只声明在** `core/resource_spec.py`
（`RESOURCE_TYPES`）：容器形状、主文件命名、字段清单、id 规则、关联设置键、存储根；
路径定位与读写落在 `persistence/resources/registry.py` 与
`persistence/resources/envelope.py`。

| 类型 | 容器 | 主文件 | 存储 | 打包上限 | 界面选择 | 选择态设置键 | 特色 traits |
|---|---|---|---|---|---|---|---|
| `landmarks` 地标风格 | `csv` | `<id>.csv` | packs | 不限 | 多选 | `selected_styles` | — |
| `quips` 描述风格 | `csv_dir` | `<id>/quips.csv`（+`<id>/config.json`） | packs | 不限 | 多选 | `selected_quip_styles` | realistic / fantasy / anime / scifi |
| `materials` 取材表 | `csv_bundle` | `<id>/names.csv`（成员之首） | static | 1 | 单选 | `material_table` | realistic / fantasy / anime / scifi |
| `scenarios` 副本方案 | `json_dir` | `<id>/config.json` | packs | 不限 | 多选 | — | longform / gameplay / multi_ending（多选） |
| `challenges` 挑战包 | `opaque` | `<id>.chal` | packs | 不限 | 多选 | — | — |
| `behaviors` 行为包 | `py_package` | `<id>/*.py` | static | 1 | 单选 | — | — |
| `topics` 话题表 | `json_array` | `<id>`（无后缀） | packs | 1 | 单选 | — | — |
| `minigames` 小游戏 | `json_dir` | `<id>/manifest.json` | packs | 不限 | 多选 | — | — |

布局一览（`packs` 根 = `data/packs/`，`static` 根 = `data/static/`）：

```
data/packs/landmarks/<id>.csv                # + 兄弟 <id>.meta.json、<id>.addr.json
data/packs/quips/<id>/{quips.csv, config.json}
data/static/materials/<组>/{names,presets,personalities,news}.csv
data/packs/scenarios/<id>/{config.json, images/, components/, audio/}
data/packs/challenges/<id>.chal              # + 兄弟 <id>.meta.json、可选同名 .png 封面
data/static/behaviors/<id>/*.py
data/packs/topics/<id>                       # 单个 JSON 文件，主文件不带后缀
data/packs/minigames/<id>/manifest.json
```

命名规则（对全部类型生效）：

- **类型 id**：`^[a-z][a-z0-9_]*$`，复数形式，同时是自由目录名与世界包内目录名；
- **资源 id**：`^[a-z0-9][a-z0-9._-]{0,63}$`（行为包例外：`^[A-Za-z_][A-Za-z0-9_]*$`，
  要能当 Python 标识符）。新建时由 `registry.suggest_id` 派生——「类型前缀 + 显示名
  slug」（如 `landmark_my_style`），撞名追加序号；前缀只是默认派生约定，不是 id 的
  合法条件，改显示名不改 id；
- **主文件后缀**：只有容器本身需要被外部程序认领时才带后缀（`.csv` 给表格软件、
  `.chal` 是整包、`.py` 是 Python 包）；单个 JSON 文件的主文件**不带后缀**
  （`topics/<id>`），路径本身即资源地址，与同目录的 `.addr.json` / `.meta.json`
  一眼可辨；
- **名字分两层**：资源级显示名 = 信封 `title`（任意语言、可改、不进 id，空则界面
  回落成 id）；条目级显示名 = 载荷里的 `name` / `label`（一个地标、一个话题类型的
  名字），由各自的字段声明管，与资源 id 无关。

## 2. meta 信封（`<id>.meta.json`）

每份资源旁边有一个**兄弟信封**，记资源级元信息：

| 字段 | 说明 |
|---|---|
| `schema` | `gg.<类型 id>/1` |
| `id` / `title` / `author` / `namespace` / `version` | 身份与署名；`title` 是显示名（改名只写这里）；`version` 默认 `0.0.0` |
| `content_hash` / `updated_at` | 内容摘要（见 §3）与更新时间 |
| `source` | `{kind, origin, rev}`，kind ∈ local / import / server |
| `status` | draft / preview / stable / deprecated（别名 `published` 归一为 `stable`） |
| `tags` / `traits` / `language` | 标签；`traits` 取值来自 `core/resource_spec.py::TRAIT_LABELS` |

规则：字段全可选（读侧 `normalize_envelope` 补默认、**不写回**）；未知字段原样保留；
`opaque` 容器（挑战包）**必须**外加信封，否则无法索引。挑战包的资源 id 是
`x.chal`，信封却是 `x.meta.json`——拼信封路径一律先过 `registry.envelope_id()`
剥掉容器后缀。

「重命名资源」的唯一实现是 `registry.set_title()`：只写信封 `title`，不动目录名、
不动载荷、不进 `content_hash`。id 级改名（`quip_repo.rename_style` /
`landmark_repo.rename_style`）才搬目录，并连带 `.addr.json` 与信封文件一起改名；
删除资源（各 repo 的 delete）都会一并删除信封。

## 3. catalog.json 索引

`data/user/catalog.json`（`persistence/resources/catalog_store.py`）是**缓存，不是
权威**，随时可以从磁盘重建：

```json
{"schema": "gg.catalog/1", "rev": "", "origin": "",
 "entries": {"<类型 id>": [{"id", "title", "author", "namespace", "version",
                            "content_hash", "status", "tags", "traits", "language",
                            "schema"}]}}
```

- 重建：`registry.build_catalog` 全量扫描 → `refresh_catalog` 与缓存比对，**内容没变
  不写盘**；缓存缺失 / 损坏 / schema 不符时重建写回（`load_catalog`）。界面在资源
  中心页触发刷新。
- **content_hash**（`envelope.content_hash`，形如 `sha256:…`）：JSON 容器按规范化
  JSON（排序键 + 紧凑分隔符，重新缩进不算改动）；`csv` / `opaque` 取文件字节；
  目录容器按「相对路径 + 文件哈希」排序串接，跳过 `__pycache__`、`.meta.json`、
  `.bak`。
- `rev` / `origin` 本地恒为空串，预留给服务端接入后的远端游标；本地从不凭空造
  版本号。

## 4. 同步判定（`core/resource_sync.py`）

`compare_entry(local, remote, base_hash)` 只做判定、不联网：

| 条件 | 状态 |
|---|---|
| 两侧都缺 | `in_sync` |
| 仅 remote 缺 | `local_only` |
| 仅 local 缺 | `remote_new` |
| 两侧 content_hash 相同 | `in_sync` |
| 有基线且 local == base_hash | `remote_changed` |
| 有基线且 remote == base_hash | `local_changed` |
| 无基线且两侧不同 | `both_changed`（冲突：宁可多问一次，不替用户裁决覆盖方向） |

基线快照与索引同构（`base_hash_for`）；没有 remote 时全部按 `local_only`。

## 5. Ref：跨表身份（`core/resource_ref.py`）

地标的身份用 `Ref(kind, key)` 表示，落盘形态如
`landmarks:chinese_mix/上海中心大厦`（`kind:scope/name`）。身份只来自声明
（风格 + 显示名），与内存地址、注册地址无关：`dataclasses.replace()` 出的副本照样
算得出身份，改地址不清账。以 Ref 文本为键的表：**耐久表 / 地址表**
（`services/exploration/address_index.py`，键不能归属时退回地标名）与档案导出的
地标悬浮信息表（`services/character/archive_export.py`）。

## 6. 取材表 materials

一个目录四张 CSV（`core/resource_spec.py::MATERIAL_MEMBERS`，顺序即界面展示序，
四成员都可缺席）：

| 成员 | 关键列 | 说明 |
|---|---|---|
| `names.csv` 姓名 | `surname, ppm, name, nick` | surname 与 name 为空的行跳过 |
| `presets.csv` 身材 | `weight, name` + 16 个 `*_ratio` 比例列 | 除 weight 外为 0~2 比例值 |
| `personalities.csv` 性格 | `weight, name, init_intrusion, depth_intrusion, init_destruction, depth_destruction, sensitivity, gravity, skip_base_prob, description` | init / depth 决定角色进入时的介入度与破坏性 |
| `news.csv` 新闻 | `size_category, memorial, intrusion, destruction, text, substitute_1, substitute_2` | 表头顺序即索引优先级顺序 |

- **整组替换**：四张表共用一套角色状态坐标系——新闻表的索引列正是其他表产出的
  状态（`size_category` 来自身材表的身高分档，`intrusion` / `destruction` 来自性格
  演化），所以只能整组换、不能单表混搭；资源设置里也只占一个键（`material_table`）。
- **缺席回落**（`persistence/material_tables.py::member_path`）：组内缺的成员依次
  回落 `<data>/static/materials/<组>/…` → 非 `default` 组再回落
  `<data>/static/materials/default/…`；全缺按空表处理，不抛异常。只覆盖一两张表
  不必复制整套，新增成员类型也不必迁移存量组。
- **news 取行**（`services/news/__init__.py`）：按表头顺序逐层收窄——`size_category`
  精确命中（不中放弃）；`memorial` 不中则忽略该条件；`intrusion` / `destruction`
  按状态值四舍五入到 0–4 整数格、取**最近值**。`text` 里的 `{name}` / `{nick}` 与
  `substitute_1/2`（逗号分隔、随机取一替换）不是索引字段。

## 7. 描述语料与静态检查

- `quips/<id>/quips.csv`：正文长表，列 `size_category, intrusion, destruction, text,
  style, step, summary`（前四者必填），每行一个条目，运行时按
  `(尺寸档, 介入度_破坏性)` 分组。
- `quips/<id>/config.json`：`_meta.custom_types`（自定义类型字母 c/d/e 的名称、细分、
  `allow_confusion`）与后续匹配配置；未知键原样保留（`persistence/quip_repo.py::load_meta`
  / `save_meta`）。
- 静态检查只有一套判据：`services/exploration/quip_lint.py::lint_style`——meta 声明、
  标记格式、替换池、接缝语法、单条文本排版五类。命令行体检
  `developer_tools/quip_report.py` 与描述管理页的「校验」按钮都调它，口径不分叉；
  **一次只查一个风格的一个尺寸档**。

## 8. 相关页

- 挑战包（加密、秘钥、导入与启动）：[challenges.md](challenges.md)
- 世界包（打包、激活、命名空间）：[world_packs.md](world_packs.md)
- 行为包：[behaviors/README.md](behaviors/README.md)；话题表条目形状与整表替换：
  [chat/lens.md](chat/lens.md) §6.1；小游戏包：[dungeon/minigame.md](dungeon/minigame.md)。

## 9. 文件 / 函数索引

| 要点 | 位置 |
|---|---|
| 类型声明（单一真相源） | `core/resource_spec.py::RESOURCE_TYPES` / `MATERIAL_MEMBERS` / `TRAIT_LABELS` |
| 路径定位 / id 派生 / 信封路径 / 校验出口 | `persistence/resources/registry.py::free_dir` / `read_path` / `suggest_id` / `envelope_id` / `validate_resource` |
| 信封缺省与内容哈希 | `persistence/resources/envelope.py::ENVELOPE_DEFAULTS` / `normalize_envelope` / `content_hash` |
| 显示名读写（改名唯一实现） | `registry::title_of` / `display_name` / `set_title` |
| catalog 读写与重建 | `persistence/resources/catalog_store.py::load_catalog` / `refresh_catalog`；条目形状 `registry::catalog_entry` |
| 同步六态 | `core/resource_sync.py::compare_entry` / `diff_catalogs` / `base_hash_for` |
| Ref 身份 | `core/resource_ref.py::Ref.scoped` / `Ref.parse` |
| 取材表回落链 | `persistence/material_tables.py::member_path` / `DEFAULT_MATERIAL_TABLE` / `present_members` |
| 选择态存储 | `persistence/resource_settings_repo.py::RESOURCE_SETTING_DEFAULTS` / `RESOURCE_SETTINGS_KEYS` |
| news 索引 | `services/news/__init__.py::NewsService._indexed_article` / `NEWS_COLUMNS` |
| quips config 读写 | `persistence/quip_repo.py::load_meta` / `save_meta` |
| 语料静态检查 | `services/exploration/quip_lint.py::lint_style` / `scan_text_style` |
