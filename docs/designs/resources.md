# 资源与包体系（面向作者）

> **这一篇回答什么问题**：程序眼里的「资源」是什么、一共八类、每一类在磁盘上占几个文件、
> 怎么起名、旁边那个 `.meta.json` 有什么用、怎么被列出来；以及你自己最常写的三类素材
> （地标风格、描述语料、取材表）的字段与检查规则。
> - **只想做一份素材**：§1 弄清「一份」怎么算 → §2 挑类型 → §3 起名 → §7 取材表、
>   §8 描述语料，地标的列在 §13。
> - **要把素材打成包发出去**：本页看完接着读 [world_packs/author.md](world_packs/author.md)；加密整包看
>   [challenges.md](challenges.md)。
> - **改程序、想新增一类资源**：§11 内部实现与 §15 契约。
>
> 直接相关：世界包的清单与接管 [world_packs/author.md](world_packs/author.md) · 地标与描述风格的注册地址
> [address_system.md](address_system.md) · 副本方案的字段 [dungeon/script.md](dungeon/script.md)。

## 1. 一份资源怎么算

「资源」是**成组、可替换、可打包**的内容：换一份就换掉整套素材，不用逐条改设置。程序判断
「一份」只看两件事——**容器**（在磁盘上占一个文件还是一个目录）和 **id**（容器叫什么，
也就是它的身份）。内容长什么样，由类型决定。

所以同样是「一份」，形状可以差很远：

- 地标风格是**一个 CSV 文件**：`data/packs/landmarks/chinese_mix.csv`；
- 描述风格是**一个目录**：`data/packs/quips/events/`（里面一张正文表、一份配置）；
- 取材表也是**一个目录**，但里面是四张各管一件事的表：`data/static/materials/default/`。

一份资源最多由三个部件组成：主文件（必需）、配置 JSON（只有目录型容器才有，可选）、
兄弟信封 `<id>.meta.json`（可选；挑战包这种整包加密的类型必需）。三者都放在同一层——
信封永远挨着主文件，不藏进容器里。

> **id 与显示名是两层**。列表里你看到的是显示名（信封 `title`），而设置项、世界包清单、
> 索引和跨表记账用的都是 id。改名只改显示名、不动 id，所以改完不会让你以前的选择失效。

## 2. 八种资源类型

八类资源的形状、存放位置和界面上的选择方式：

| 类型（id） | 界面显示名 | 容器 | 主文件 | 自由目录 | 打包上限 | 界面选择 | 选择态键 | 特色 |
|---|---|---|---|---|---|---|---|---|
| `landmarks` | 地标风格 | `csv` | `<id>.csv` | `packs` | 不限 | 多选 | `selected_styles` | — |
| `quips` | 描述风格 | `csv_dir` | `<id>/quips.csv`（+`config.json`） | `packs` | 不限 | 多选 | `selected_quip_styles` | realistic / fantasy / anime / scifi |
| `materials` | 取材表 | `csv_bundle` | `<id>/names.csv`（四成员之首） | `static` | 1 | 单选 | `material_table` | realistic / fantasy / anime / scifi |
| `scenarios` | 副本方案 | `json_dir` | `<id>/config.json` | `packs` | 不限 | 多选 | — | longform / gameplay / multi_ending（多选） |
| `challenges` | 挑战包 | `opaque` | `<id>.chal` | `packs` | 不限 | 多选 | — | — |
| `behaviors` | 行为包 | `py_package` | `<id>/*.py` | `static` | 1 | 单选 | — | — |
| `topics` | 话题表 | `json_array` | `<id>`（无后缀） | `packs` | 1 | 单选 | — | — |
| `minigames` | 小游戏 | `json_dir` | `<id>/manifest.json` | `packs` | 不限 | 多选 | — | — |

自由目录一览（`packs` 根 = `data/packs/`，`static` 根 = `data/static/`）：

```
data/packs/landmarks/<id>.csv                # + 兄弟 <id>.meta.json、<id>.addr.json
data/packs/quips/<id>/{quips.csv, config.json}
data/static/materials/<组>/{names,presets,personalities,news}.csv
data/packs/scenarios/<id>/{config.json, images/, texts/, audio/, endings/}
data/packs/challenges/<id>.chal              # + 兄弟 <id>.meta.json、<id>.png 封面（可选）
data/static/behaviors/<id>/*.py
data/packs/topics/<id>                       # 单个 JSON 文件，主文件不带后缀
data/packs/minigames/<id>/manifest.json
```

两个存储根的差别只在「随发行版分发」这件事上：`static` 里放的是随程序一起给出去的取材表
和行为包，`packs` 放其余素材。读写规则一模一样，取哪个根由类型决定，你不用挑。

## 3. 命名规则

四条，对全部类型生效：

- **类型 id**：`^[a-z][a-z0-9_]*$`，复数形式。它同时是自由目录名和世界包内的目录名，
  所以改类型 id 等于改磁盘布局。
- **资源 id**：`^[a-z0-9][a-z0-9._-]{0,63}$`；行为包例外，按 Python 标识符
  `^[A-Za-z_][A-Za-z0-9_]*$`——它真的会被 `import`。
- **新建时自动派生**：显示名折成 ASCII（`slugify`）后加上类型前缀，得到
  `landmark_my_style` / `quip_snow` 这样的 id，撞名追加 `_2`、`_3`。前缀只是默认习惯，
  不是合法条件：手填 `my_style` 一样成立，只要符合上面的正则。中文名派生不出可用字符时
  就只留前缀（`landmark`、`landmark_2`）——显示名照样可以是任意语言。
- **主文件后缀**：只有容器本身需要被别的程序认领时才带后缀（`.csv` 给表格软件、`.chal`
  是整包、`.py` 是 Python 包）。单个 JSON 文件的主文件**不带后缀**（`topics/<id>`），
  路径本身就是资源地址，同目录的 `.addr.json` / `.meta.json` 一眼就能区分。

改名有两条路，别混：界面上的「重命名」只写信封 `title`（id 不变）；id 级改名才会搬目录，
并连带 `.addr.json` 和信封一起改名。后者只有地标风格、描述风格两类有，且不在界面上。

## 4. 信封：资源旁边那张名片

信封是**兄弟文件** `<id>.meta.json`，记的是「这份资源是谁的、什么版本、什么状态」——
载荷里不掺这些。字段全部可选，读的时候缺什么补什么；**补出来的默认值不会写回磁盘**，
你手写的文件不会被程序偷偷改厚。

<details>
<summary>手写信封或核对字段时展开（12 个字段的取值）</summary>

| 字段 | 说明 |
|---|---|
| `schema` | `gg.<类型 id>/1`，缺省按类型补齐 |
| `id` | 资源 id；只做冗余校验，以容器名为准 |
| `title` | 显示名（界面用）；空 = 界面回落成 id |
| `author` / `namespace` / `version` | 署名与版本；`version` 缺省 `0.0.0` |
| `content_hash` | 内容摘要（§5），判断「改没改过」的唯一依据 |
| `updated_at` | 最近一次刷新的时间 |
| `source` | `{kind, origin, rev}`，kind ∈ `local` / `import` / `server` |
| `status` | `draft` / `preview` / `stable` / `deprecated`，别名 `published` 归一为 `stable` |
| `tags` | 自由标签，字符串数组 |
| `traits` | 特色，取值来自统一词表（物理写实 / 奇幻 / 二次元 / 科幻 / 长线剧情 / 游戏为主 / 多结局） |
| `language` | 主语言，字符串 |

</details>

三条硬规则：未知字段**原样保留**（读写一轮不丢你写的东西）；不可读容器（挑战包）**必须**
外加信封，否则元数据无处可放；`content_hash` 只反映载荷，改显示名不算内容改过。

## 5. 索引：`catalog.json` 是缓存，不是账本

`data/user/catalog.json` 把每份资源的元信息汇总成一张表，供列表、筛选和服务端比对使用。
它随时可以从磁盘重建，所以**删掉没有损失**：

```json
{"schema": "gg.catalog/1", "rev": "", "origin": "",
 "entries": {"<类型 id>": [{"id", "title", "author", "namespace", "version",
                            "content_hash", "status", "tags", "traits",
                            "language", "schema"}]}}
```

资源中心面板每次构建时重建一次（内容没变就不写盘，免得天天改文件时间戳）；缓存缺失、
损坏或 schema 不符时直接重建。列表本身目前还是直接扫目录，索引先在后台把形状和刷新跑通。
`rev` / `origin` 在本地恒为空串，预留给将来接服务端时的远端游标——本地不会凭空造版本号。

`content_hash` 的口径按容器分：JSON 容器按**规范化 JSON** 算（排序键、紧凑分隔符，所以
重新缩进或换行不算改动）；`csv` 与 `.chal` 取文件字节；目录型容器按「相对路径 + 文件哈希」
排序串接，跳过 `__pycache__`、`.meta.json` 与 `.bak`。

> **取材表是个例外**：它是四张表组成的组，但哈希只算主文件 `names.csv`。只改
> `news.csv` 的话哈希不变——同步功能接上之前，别拿哈希判断取材表改没改过。

## 6. 同步状态：两份索引碰面时的六种结论

同步现在只做**判定**，不联网、不传文件。拿本地索引、远端索引、上次同步的基线快照三者
一比，每条资源落进六种状态之一：

| 条件 | 状态 | 含义 |
|---|---|---|
| 两侧都缺 | `in_sync` | 没有这条 |
| 只有本地有 | `local_only` | 还没发布 |
| 只有远端有 | `remote_new` | 还没下载 |
| 两侧哈希相同 | `in_sync` | 一致 |
| 有基线，本地等于基线 | `remote_changed` | 远端改过 |
| 有基线，远端等于基线 | `local_changed` | 本地改过 |
| 没有基线且两侧不同 | `both_changed` | 冲突：宁可多问一次，也不替用户决定覆盖方向 |

没有远端索引时，全部按 `local_only` 处理——这正是「还没接服务端」的正常状态，不算错误。
`both_changed` 不给自动解法：两边都可能是对的，交给使用者裁决。

> 现状：同步面板还没有，六态判定目前只有自检在用；资源中心顶部的「在线资源 / 社区」
> 两个页签也是占位。

## 7. 取材表：四张表共用一套坐标系

一个目录四张 CSV，顺序即界面展示顺序，四张都可以缺席：

| 成员 | 关键列 | 说明 |
|---|---|---|
| `names.csv` 姓名 | `surname, ppm, name, nick` | 三列各自收集：哪格空着就不贡献那条。`ppm` 是姓的抽样权重（缺省 1，非数字也按 1） |
| `presets.csv` 身材 | `name` + 15 个 `*_ratio` 比例列 | 比例列必须全部填、取值在 0 与 2 之间（越界按该字段默认值补，空着则整行跳过）；`weight` 可选，缺省 1 |
| `personalities.csv` 性格 | `name` + `init_intrusion, depth_intrusion, init_destruction, depth_destruction, sensitivity, gravity, skip_base_prob, description` | init / depth 决定角色进入时的介入度、破坏性与每单位步进深入多少；数值列缺一格整行跳过（`gravity` 例外，旧表没有按 0） |
| `news.csv` 新闻 | `size_category, memorial, intrusion, destruction, text, substitute_1, substitute_2` | 表头顺序即索引优先级顺序 |

**为什么只能整组换**：四张表共用一套角色状态坐标系——新闻表的索引列（尺寸档、介入度、
破坏性）正是其他三张表产出的状态，所以单表混搭会让索引对不上内容。资源设置里也只占一个
键（`material_table`），切换就是整组切换。

**缺席会回落**，所以只覆盖一两张表是可行的：组内缺哪个成员，就依次往下找
`data/static/materials/<组>/` → 非 `default` 组再找 `.../default/`；全都没有就按空表处理，
不抛异常。取材表的选择行会标出哪些成员是回落来的。

**新闻怎么取一条**：按表头顺序逐层收窄——`size_category` 必须精确命中（不中直接放弃）；
`memorial` 对不上就忽略这个条件；`intrusion` / `destruction` 把状态值四舍五入到 0～4 的
整数格、取最近值。`text` 里的 `{name}` / `{nick}` 和 `substitute_1/2`（逗号分隔、随机取一）
是渲染用的，不参与索引。

## 8. 描述语料：`quips.csv` 与 `config.json`

描述风格目录里两件东西：`quips.csv` 存正文，`config.json` 存这一风格的配套声明。

- **`quips.csv`**：列 `size_category, intrusion, destruction, text, style, step, summary`，
  前四列必填。`size_category` 只有五个取值：`small` / `medium` / `large` / `huge` /
  `colossal`。每行一个条目，运行时按「尺寸档 + (介入度, 破坏性)」分组取用；`text` 里的
  类型标记（`[c:3:街道]` 这类）会从替换池里挑词填进槽位。
- **`config.json`**：`schema` 是 `gg.quips.config/1`（也接受旧的 `gg.quips/1`），
  主体是 `custom_types`——`c` / `d` / `e` 三个自定义类型各自的 `name`、`subtypes` 细分、
  `allow_confusion`（是否允许邻近坐标混淆改选）。未知键原样保留；`schema` 比程序支持的
  版本新时拒绝编辑，提示先升级应用。

静态检查只有一套判据（`lint_style`），四层：**meta**（类型名称、细分、`allow_confusion`）、
**格式**（未知类型字母、空内容、非数字编号、游离括号、坏坐标键、未知占位符）、
**替换**（内容池是否可用、混淆能否走到）、**接缝**（候选词与模板在标记边界上的字形冲突、
同槽位形态是否一致）。命令行体检（`python developer_tools/quip_report.py`）和描述管理页
的「校验」按钮调的是同一个函数，结论不会分叉；两边都**一次只查一个尺寸档**——全量结论
长到读不动。

## 9. 选择态：现在用的是哪一份

「装了」和「在用」是两件事。选择态单独存在 `data/user/resource_settings.json`，资源中心
里改一下立即落盘，不用点保存：

| 键 | 管什么 | 缺省 |
|---|---|---|
| `selected_styles` | 参与生成的地标风格（多选） | `["chinese_mix"]` |
| `selected_quip_styles` | 参与生成的描述风格（多选） | `["events"]` |
| `material_table` | 当前取材表组（单选） | `default` |

两条会让人意外的规则：

- **同一维度互斥**：已选风格里只要有一条带注册地址，两栏风格列表就按那个维度筛——你换
  选另一维度的风格时，会顺手把不同维度的已选风格剔掉（地标风格先于描述风格决定维度）。
  没注册地址的风格不受这条限制。
- **空选有兜底**：地标风格全取消会自动回退默认风格；描述风格允许留空（那就只用通用旁白）。

世界包启用期间，它拥有的取材表会把 `material_table` 锁住（下拉变灰），世界设定与种子也会
在设置页锁上——这些值以包的清单为准。

## 10. 跨表身份：`Ref`

一条内容的稳定身份写成 `类型:容器/名字`，例如 `landmarks:chinese_mix/上海中心大厦`。
它只由**声明**（风格 + 显示名）算出，跟内存地址、注册地址都无关：复制一份对象照样算得出
同一条身份，改地址也不会把以前的账弄丢。

按 `Ref` 文本记账的表有三处：地标耐久、地址表、档案导出里的地标悬浮信息表。所以改地标
名字等于换身份（旧账不再对应），改地址不算。

## 11. 内部实现

- **一份声明派生所有出口**：类型、容器、字段、id 规则、上限、选择键全部来自
  `core/resource_spec.py::RESOURCE_TYPES`；路径定位、成员核对、界面可打包清单都从它算出来。
  新增一类资源 = 一份声明 + 一个 repo + 一处界面接入，不会出现同一份清单在多处各写一遍。
- **路径只有一个出口**：所有资源路径都从注册表模块拼，主文件的**写路径恒为自由目录**——
  编辑器不会把素材写进世界包。唯一的例外是显示名：启用中的包拥有该类型时，改名写的是
  包内那份信封，因为你说的是「这个包里的这份资源叫什么」。
- **坏文件不拦启动**：读表失败按空表处理；列表里的坏条目跳过并打印；`validate_resource`
  只产出诊断、不改文件，是否致命由调用方决定。读一份资源时也从不「顺手修好」它。
- **索引与诊断的现状**：索引在资源中心构建时刷新；资源校验与同步判定已实现但没有界面
  出口，目前只有自检在跑。
- **哈希的边界**：取材表只算 `names.csv`（§5），目录型容器的哈希会随目录里任何非信封
  文件变化——包括你放进去的草稿。

## 12. 拓展用法

界面上没写、但实际成立的四件事，全部只动你的数据：

- **手写信封补元信息**：`author` / `version` / `status` / `tags` / `traits` / `language`
  界面上没有编辑入口，直接写进 `<id>.meta.json` 就行——索引会照单收下，界面取显示名时
  也读同一份信封。`status` 写 `published` 会被当成 `stable`。
- **只覆盖一两张表**：新建一个取材表组，只放 `news.csv`，其余三张自动回落到内置 `default`。
  也可以直接往 `default` 组里添文件，但那个目录只在首次启动时从发布包拷一次、之后不会再
  被覆盖，官方以后对内置组的更新也就进不来了——长期用还是自己建一组。
- **给挑战包加封面**：在 `.chal` 旁边放一张同名 `.png`（`<id>.png`），列表里就用它当图标。
  信封不管这张图，画坏了删掉即可。
- **手写一张话题表**：`data/packs/topics/<id>` 放一个 JSON 数组（形状与内置表相同，见
  [chat/lens.md](chat/lens.md) §6.1），资源中心就能选它打包；内置表导出的条目能原样
  导回。注意主文件不带后缀。

## 13. 参数表

作者要写的形状都在这里；副本方案自己的字段不重复，见 [dungeon/script.md](dungeon/script.md)。

<details>
<summary>各类载荷的字段与 CSV 列全表（照表填素材、核对表头时展开）</summary>

**地标风格 `landmarks`**（CSV 表头）

| 列 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `name` | str | 必填 | 地标显示名，同一风格内唯一 |
| `size` | number | 必填 | 米；`vertical` 记高度，`horizontal` 记长度 / 宽度 |
| `dimension` | str | `vertical` | `vertical` / `horizontal` |
| `frequency` | str | `unique` | `unique` 独特地标 / `common` 常见地标 |
| `horizontal_type` | str | `length` | 仅 `horizontal` 有意义：`length` / `width` |
| `address` | str | 空 | 注册地址（见 [address_system.md](address_system.md)） |
| `address_mode` | str | 空 | 空 / `inherit` / `portable` / `exact` / `relative` |

**描述风格 `quips`**（`quips.csv` 表头）：`size_category`（必填）、`intrusion`（必填，整数）、
`destruction`（必填，整数）、`text`（必填）、`style`、`step`（数值）、`summary`。
`config.json` 见 §8。

**取材表 `materials`**（四成员，均可缺席）

| 成员 | 列 |
|---|---|
| `names.csv` | `surname, ppm, name, nick` |
| `presets.csv` | `name` + `height_ratio, leg_ratio, foot_length_ratio, arm_span_ratio, index_finger_ratio, palm_length_ratio, chest_width_ratio, thigh_diameter_ratio, forearm_diameter_ratio, index_finger_diameter_ratio, fingerprint_width_ratio, finger_gap_ratio, knee_height_ratio, ankle_height_ratio, stride_ratio`（`weight` 可选） |
| `personalities.csv` | `name, init_intrusion, depth_intrusion, init_destruction, depth_destruction, sensitivity, gravity, skip_base_prob, description`（`weight` 可选） |
| `news.csv` | `size_category, memorial, intrusion, destruction, text, substitute_1, substitute_2` |

性格表七个数值列会被夹进各自区间：`init_intrusion` / `init_destruction` 取 0～4，
`depth_intrusion` / `depth_destruction` / `sensitivity` / `gravity` 取 −5～5，
`skip_base_prob` 取 0～5；写超范围不会报错，只会被改成最近的边界。

**话题表 `topics`**（JSON 数组，一个条目一个话题类型）：`id`（必填）、`label`、`coord`
（必填，三分量：好感 / 紧张 / 状态）、`radius`、`prompt`、`focus`、`frame`、`opens`、
`denies`、`budget`、`disclosure`（默认 false）、`tags`、`priority`（默认 0）、`cooldown`
（默认 0.0）、`virtual`（兜底视角，默认 false）。

**小游戏 `minigames`**（`manifest.json`）：`id`（必填，且要与目录名一致）、`name`（必填）、
`backend`（目前只有 `py`）、`entry`（默认 `game.py`）、`params`（参数声明列表）。

**行为包 `behaviors`**：目录内的 `.py` 就是全部内容，没有清单；包名要能当 Python 标识符。

</details>

## 14. 官方资源

随程序一起给出去的内置素材（都在 `data/packs/` 与 `data/static/` 下，发行版首次启动时
就位）：

| 类型 | id | 一句话 |
|---|---|---|
| 地标风格 | `chinese_mix` | 中文混合地标（30 条常见 + 15 条独特），带 `2e6_3e5_5e4@RW-CN1` 注册地址，也是地标风格全不选时的回退 |
| 地标风格 | `extension` | 从卡门线到地球直径这类极大尺度条目，适合当换算参照物 |
| 描述风格 | `events` | 事件式叙述，三套自定义类型（对象 / 身体形容 / 后果）都用上了，描述风格缺省选它 |
| 描述风格 | `pixel_game` | 像素游戏式观测记录口吻，`custom_types` 保持默认 |
| 取材表 | `default` | 姓名 / 身材 / 性格 / 新闻四张表齐全，同时是所有组缺席成员的回落目标 |
| 行为包 | `imperial_units` | 把长度显示换成英制的示例包（内部仍按米算，只改显示） |
| 副本方案 | `default` | 内置默认方案，不可打包、不可删除 |
| 小游戏 | `escape_giantess` / `reaction` | 「逃离巨大娘」（按关卡推进）与「点击反应」（打满目标命中数） |
| 话题表 | `default` | 没有对应文件，指向代码里的内置话题表，永远可打包 |

## 15. 作者须知

<details>
<summary>写素材之前值得知道的契约（改到类型声明、路径或信封时对照）</summary>

1. **类型声明是唯一真相源**：容器、主文件、字段、id 规则、打包上限、选择键都在
   `core/resource_spec.py::RESOURCE_TYPES`。改表头前先看那里，别按本页抄第二遍。
2. **id 不可改**：界面的「重命名」只写显示名；要换 id 只能新建一份再搬内容。id 不只出现在
   路径里，还写进世界包清单、设置项与 `Ref` 记账。
3. **信封三条硬规则**：字段全可选、读侧补默认但不写回；未知字段原样保留；不可读容器
   （`opaque`）必须外挂信封。
4. **改名不算内容改过**：`content_hash` 只算载荷；所以显示名可以随便改，`set_title` 是
   改名的唯一实现。
5. **整组才是「一份」**：取材表四张表共用坐标系，不能单表混搭；缺席回落不等于可以乱配。
6. **校验只报不修**：`validate_resource` 给诊断，不改文件、不决定是否阻断；读侧遇到坏条目
   一律跳过并打印，不让一条坏数据拖垮整类资源。
7. **守卫**：`python tests/run_checks.py check_resource_spec check_resource_settings check_resource_display`；
   改语料或取材表再加 `check_quip_lint check_quip_repo`。

</details>

## designs 目录

<details>
<summary>designs/ 全目录（wiki 地图）</summary>

**机制目录**

- **dungeon/**：[README](dungeon/README.md)（全景）·
  [script](dungeon/script.md)（章节与触发器字段）·
  [characters](dungeon/characters.md)（人物表与账本）·
  [voice](dungeon/voice.md)（对话语音）·
  [admission](dungeon/admission.md)（进入准入）·
  [scene](dungeon/scene.md)（地点与参照物）·
  [minigame](dungeon/minigame.md)（小游戏）·
  [components](dungeon/components.md)（显示组件）
- **chat/**：[README](chat/README.md)（话题与好感 / 紧张度）·
  [lens](chat/lens.md)（信息视角细节）
- **behaviors/**：[README](behaviors/README.md)（玩家向）·
  [dev-guide](behaviors/dev-guide.md)（行为包开发）· 钩子契约四篇
  （[logic](behaviors/hooks-logic.md) / [report](behaviors/hooks-report.md) /
  [character](behaviors/hooks-character.md) / [chat](behaviors/hooks-chat.md)）·
  [example-imperial](behaviors/example-imperial.md)（示例包）
- **world_packs/**：[README](world_packs/README.md)（玩家向：启用 / 切换 / 删除）·
  [author](world_packs/author.md)（制作与清单）

**单篇**

[地址系统](address_system.md) · [报告生成](report_selection.md) ·
[角色演化](character_evolution.md) · [资源与包体系](resources.md)（本页） ·
[挑战包](challenges.md) ·
[剧本编辑器](scenario_editor.md) · [界面双模式与外观](ui_modes.md) ·
[角色的长期行为](character_time.md) · [身材剪影](body_preview.md) ·
[更新检查](update_check.md)

</details>
