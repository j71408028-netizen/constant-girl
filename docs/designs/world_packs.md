# 世界包

> **这一篇回答什么问题**：`.world.zip` 里有什么、怎么生成、导入 / 激活 / 停用 /
> 解散时各资源类型分别发生什么、包内资源与自由资源怎么共存（命名空间），以及
> 在线地址注册表客户端的行为。各资源类型与信封见 [resources.md](resources.md)；
> 行为包的钩子与写法见 [behaviors/dev-guide.md](behaviors/dev-guide.md)。

## 1. 容器与清单

`.world.zip`（`persistence/world_pack.py`）是 zip 归档，清单 `world.json` 是唯一
必需文件：

```
world.json
landmarks/<style>.csv                          # (+ <style>.addr.json、<style>.meta.json)
quips/<style>/{quips.csv, config.json}         # (+ <style>.addr.json、<style>.meta.json)
materials/<组>/{names,presets,personalities,news}.csv
scenarios/<id>/config.json
challenges/<name>.chal                         # 秘钥记录在包内 challenges/keys.json
behaviors/<pack>/*.py
topics/<table>                                 # 整表替换，主文件不带后缀
minigames/<id>/manifest.json
icon.png                                       # 封面，整目录打包自动随行，不进清单
```

`world.json` 字段（`WorldPackManifest`）：

| 字段 | 说明 |
|---|---|
| `format_version` | 清单版本（当前 `1`） |
| `behavior_api` | 可选；行为包契约版本，与运行时不符只警告不阻断 |
| `world_id` | `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` |
| `name` / `version` / `author` / `description` | name 非空；version 默认 `"1.0"` |
| `traits` | 可选，realistic / fantasy / anime / scifi |
| `worlds` | 地址维度命名空间列表（`^[A-Za-z0-9_]{1,48}$`、不重复）；**空 = 整类型接管，非空 = 只接管声明的维度**（见 §5） |
| `settings` | 仅世界块键：`world_setting`（appear / abs_giant / rel_giant）、`seed`、表键（`selected_styles` / `selected_quip_styles` / `material_table`，仅当包拥有该类型时锁定） |
| `resources` | 键 = 类型 id（即包内目录名），值为资源 id 列表；materials / behaviors / topics 上限 1 |

旧版 `quips/<style>` 单文件布局不再接受。

## 2. 生成：两条路径

| 路径 | 入口 | 行为 |
|---|---|---|
| 导出 | `WorldManager.export_pack(world_id)` | 把已部署目录 `data/worlds/<world_id>/` 原样 zip（默认输出 `data/worlds/<world_id>.world.zip`）；纯目录重打包，不改内容 |
| 从当前世界创建 | `WorldManager.create_from_current(...)` | 从自由层选装重组：按 `selected_resources` 收集各类型——scenarios 跳过默认方案；materials 取选中第一组并补齐四成员完整快照；challenges 只拷 `.chal`、**默认不带秘钥**（keys.json 需手动复制）；behaviors 只能单选、自动盖章当前 `behavior_api`；topics 整表落盘；随后随行兄弟信封、写入世界设定与种子；`worlds` 维度从收集到的地标 / 描述风格注册地址取并集派生 |

界面入口：资源中心「＋ 新建」向导（基本信息 + 资源选择两页）。
`.world.zip` 的导入 / 导出目前只在服务层（`import_pack` / `export_pack`）；
手动分享 = 把 `data/worlds/<id>/` 目录压成 `<id>.world.zip`。

## 3. 导入

`WorldManager.import_pack(archive)`：`validate_archive`（缺清单 / 清单非法 /
`missing_members` 成员核对 → `ValueError`）→ 目标 `data/worlds/<world_id>/` 已存在
则拒绝（不覆盖，需先删除旧包）→ 成员路径安全检查（绝对路径、Windows 盘符、含
`..` 的成员拒绝）→ 解压到临时目录再校验一次清单 → `copytree` 落盘，异常回滚。

## 4. 激活与停用

`activate(world_id)`（同一时间只有一个激活包）依次：

1. 校验清单；
2. `world_state.set_active(manifest)`；
3. 行为包：`BehaviorRuntime.load_pack` 清空旧覆盖、逐模块加载注册（机制见
   behaviors/，本页只讲随包携带）；
4. 话题表：包声明了 `topics` 则 `topic_tables.activate` 整表安装，失败或未声明时
   `restore()` 回内置表（API 见 [chat/lens.md](chat/lens.md) §6.1）；
5. 写 `active_world` 与世界块设置并落盘。

各类型的接管方式（读取侧按 `world_state.owns()` 决定读包还是读自由层）：

| 类型 | 激活期间 |
|---|---|
| landmarks / quips | 命名空间合并（§5）；`selected_styles` / `selected_quip_styles` 收敛为「包风格全列 + 保留的自由风格」 |
| materials | 整类型接管（组内缺席成员仍回落内置组）；`material_table` 不在包组则取第一组 |
| scenarios | 整类型接管（默认方案除外） |
| topics | 整表替换 |
| behaviors | 运行时覆盖 |
| challenges / minigames | 包内目录优先解析（挑战包秘钥读包内 `keys.json`） |

`active_world` 存在 `data/user/resource_settings.json`；副本子进程由
`paths.active_world_id()` 直接读文件感知（不依赖父进程传参），小游戏包解析同源；
程序启动时 `app/shell.py::bootstrap` 恢复激活态（失败仅警告并摘掉该键）。

`deactivate()`：从设置仓库重读自由设置整体覆盖 → 摘掉 `active_world` →
`BehaviorRuntime.reset()` → `topic_tables.restore()` 还原内置表。停用后包仍保留在
`data/worlds/`。

## 5. 命名空间：包内与自由共存（`persistence/style_universe.py`）

只作用于带注册地址的 `landmarks` / `quips`，按清单 `worlds` 字段分三种形态：

| 清单 `worlds` | 读取范围 |
|---|---|
| 未激活任何包 | 全部自由目录 |
| 激活且 `worlds` 为空 | **仅包内**（整类型接管，包外风格一律不可见） |
| 激活且 `worlds` 非空 | 包内全部 + 自由目录中「与包内不同名、且注册地址维度不在声明维度内（或未注册地址）」的风格 |

同名冲突一律**包内遮蔽**自由层（id 只做身份，没有改名机制）；读单风格的目录由
`style_read_dir` 决定：包内有主文件读包，合并模式下包内没有读自由目录；未声明
`worlds` 时即使包缺该风格也指向包目录（保持「包外风格一律不可见」）。

## 6. 解散

`WorldManager.dissolve(world_id)`（资源中心删除卡片的三选之一：解散到自由资源 /
不解散直接删 / 取消）：激活中先停用 → 各类型资源转存自由层 → 包 `settings` 里被
锁定的值并入自由设置 → 删包目录。

- 目标同名冲突时改名为 `<id>_<world_id slug>[_<version slug>]`，仍冲突追加
  `_2`、`_3`…；
- 各类型去向：landmarks / quips 连 `.addr.json` 一起搬；materials 整组并回写设置；
  scenarios 枚举包目录（覆盖激活期间新建的方案，跳过默认方案）；challenges 连包内
  秘钥注册进本地 `challenge_keys.json`；behaviors 整目录复制回
  `data/static/behaviors/`；topics 落 `data/packs/topics/<table>`；minigames 落
  `data/packs/minigames/`；
- 信封写回：按清单找包内 `<id>.meta.json`，写到**改名后目标 id** 的兄弟位置；
  目标已有信封不覆盖。

## 7. 在线地址注册表客户端（`services/worlds/address_registry.py`）

- 注册表本体是 GitHub Gist 上的 `registry.json`（地址与格式见
  [address_system.md](address_system.md) §5）；客户端负责下载、缓存与查询。
- 本地缓存 `data/user/address_registry.json`，形状
  `{data, fetched_at, gist_updated_at}`。
- **下载时机**：只在 UI 操作触发——文本管理的地址对话框打开时尝试下载（失败回落
  缓存）；**执行注册时必须联网重新下载成功**且地址已申领（`find_entry` 规范化逐字
  匹配），离线一律拒绝；地标编辑器的子地址下拉同样在打开时刷新。应用启动与激活
  世界包**不**触发下载。
- 离线：缓存可供查询 / 搜索（`search_entries` / `claimed_descendants` /
  `child_options`），不能用于注册。

## 8. 文件 / 函数索引

| 要点 | 位置 |
|---|---|
| 容器布局与清单模型 / 校验 | `persistence/world_pack.py::WorldPackManifest` / `validate_archive` / `load_manifest_file` |
| 成员核对 | `persistence/resources/registry.py::missing_members` |
| 导入 / 导出 / 创建 / 激活 / 停用 / 解散 | `services/worlds/service.py::WorldManager.import_pack` / `export_pack` / `create_from_current` / `activate` / `deactivate` / `dissolve`（内部 `_collect_resources` / `_copy_envelopes` / `_target_name` / `_restore_envelopes`） |
| 激活态持久化 | `persistence/resource_settings_repo.py`（`resource_settings.json`）；子进程感知 `paths.active_world_id` |
| 命名空间合并 | `persistence/style_universe.py::namespace_merge` / `merged_styles` / `style_read_dir`；维度判定 `core.address_model::world_of` / `valid_world_id` |
| 话题表装卸 | `services/chat/topic_tables.py::declared_table` / `activate` / `restore` |
| 行为包加载 | `core/behavior_runtime.py::BehaviorRuntime.load_pack` / `resolve_behavior_source`；`BEHAVIOR_API_VERSION` |
| 地址注册表客户端 | `services/worlds/address_registry.py::download_registry` / `load_cache` / `save_cache` / `find_entry` / `search_entries` |
| 界面入口 | `ui/resources/__init__.py`（新建向导 `WorldPackCreateDialog`；启用 / 停用 / 删除三选） |
