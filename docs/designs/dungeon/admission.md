# 副本进入准入（面向作者）

> **这一篇回答什么问题**：怎么让一个副本只在「她恰好走到门口、身高也合适」的时候才进得去
> ——入口地址、距离上限、身高区间三个条件怎么填、什么时候判定、被拦下时玩家看到什么。
> - **正在写方案**：看 **§2**（地址条件）与 **§3**（身高条件），两节合起来就是全部规则。
> - **玩家问「为什么进不去」**：看 **§1** 的拒绝文案，对照角色当前位置与身高。
> - **想改判定本身**：看 **§4**。
>
> 相关页面：地址怎么写、怎么配对 [address_system.md](../address_system.md) · 章节内的取景地址
> [scene.md](scene.md) · 方案里其他全局字段 [script.md](script.md)。

准入是**方案级**的：它回答「这一局能不能开」，而不是「进去以后站在哪」。所以它只有三个
条件——门口在哪、离多远算到、身高合不合——不涉及章节、触发器或任何剧情逻辑。

## 1. 什么时候判定，被拦下会怎样

判定发生在**真正开局之前**，具体时机按入口不同：

- **探索模式**：在窗口入口选好方案、点进入之后，扣除 `entry_action_cost` **之前**；
- **挂件版与挑战模式**：在启动副本子进程之前。

被拦下就停在原地：不进副本、**不扣行动点**、不产生任何记录，玩家看到一句说明原因的提示。
三种拒绝文案长这样：

| 情形 | 玩家看到 |
|---|---|
| 不在同一维度 | 「该副本的入口位于「…」，但角色当前地址「…」与入口地址不在同一维度，无法进入。」 |
| 距离超限 | 「…要求距离不超过 3.0 km；角色当前距离在 1.2 km 到 8.0 km 之间（位置精度不足），无法进入。」 |
| 身高不合 | 「该副本要求角色身高不高于 1.5 m，角色当前身高为 12.0 m，无法进入。」 |

**挑战模式没有「当前站在哪」**：挑战包是一局独立的冒险，不走主世界地图，所以地址条件在
那里自动失效，只按身高判定（身高取挑战包里的角色）。

## 2. 地址条件：门口在哪、离多远算到

两个字段配合使用，缺一个就等于没设：

- **入口地址** `entry_address`：主世界里的一扇门，写成完整地址文本
  （格式见 [address_system.md](../address_system.md) §10）；
- **最大距离** `entry_address_max_distance_m`：角色当前地址与这扇门的距离上限。

距离不是精确值，而是一个**区间**：角色的位置可能只精确到某个地域层级，越粗的定位区间越大。
判定用区间的**上界**——只要「最坏情况下也可能超过上限」，就拒绝。这是保守口径：宁可让
玩家再走近一点，也不放一个「其实还挺远」的人进去。

| `entry_address` | `entry_address_max_distance_m` | 结果 |
|---|---|---|
| 留空 | 任意 | 不限制位置（`0` 也无效，因为没有可量的门） |
| 有值 | 留空 | 不限制距离（写了门但不设门槛，等于只做展示） |
| 有值 | `0` | 必须**同址**：两者要落在同一个最细单元 |
| 有值 | 正数 | 距离区间上界不超过它才放行 |

两条边界要记住：

- **角色没有可用地址时不判定**：`position` 为空或解析不了，地址条件直接跳过，不会因为
  「她没记录位置」把人关在外面；
- **入口地址写坏按未配置处理**：解析不了的地址不会拦下任何人，校验器会给一条 warning。
  一个笔误不该让整局对所有人关门。

> 这扇门与章节里的取景地址是两件事：`entry_address` 决定「能不能进」，章节的 `address`
> 决定「进去以后看到哪一带的地标与描述」。同一个方案完全可以入口在城郊、章节取景在市中心。

## 3. 身高条件：做成一道体型门槛

`entry_height_min_m` / `entry_height_max_m` 是闭区间，留空表示该侧不限，判据只有角色当前
身高（米）。既然报告里她会长大，这两个字段最自然的用法是**把「她现在够不够格」写进玩法**：

- 只填下限：长大到某个尺寸之后才进得去；
- 只填上限：只有缩小（或本来就不大）时才钻得进；
- 两个都填：一个体型窗口，超出任何一侧都拒绝。

挑战模式里身高取包内角色，所以同一个方案配不同角色，可能出现「这个包能进、那个包进不去」。

## 4. 内部实现

- 判定是一段**纯逻辑**（`dungeon/admission.py::check_entry_requirements`），窗口入口、挂件
  入口与校验器共用同一份实现；它只接收地址文本与身高，不碰 UI、存档或服务层，因此三个入口
  不会各判一套。
- 字段归一化在同一处：留空、非数字、负数、`NaN` 一律折成「不限」；地址必须能被完整解析，
  否则视作未配置。编辑器、持久化迁移与校验器共用同一组键名
  （`entry_address` / `entry_address_max_distance_m` / `entry_height_min_m` /
  `entry_height_max_m`）。
- 距离区间来自地址关系计算（`core.address_model.py::relate`），与报告里判断「地标够不够近」
  用的是同一个口径。

## 5. 拓展用法

- **`0` 米做定点门**：把入口地址选到最细一级、距离填 `0`，就得到一个「必须站在这里」的
  门。适合做成某个具体地点的入口（洞口、电梯口），而不是一整片区域。
- **只填下限当成长门槛**：不必写满区间，一个下限就够表达「她现在还不够大」。配合 `0`
  距离，就是「长到这个尺寸、并且走到这个地方」的组合条件。
- **同一方案配多个挑战包**：身高条件在挑战模式下取包内角色，于是同一份方案可以做成一扇
  「小体型能进、大体型被拒」的门，用不同角色打包即可。

## 6. 参数表

<details>
<summary>四项准入字段的类型、默认值与判定顺序（写方案或排查误拦时展开）</summary>

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `entry_address` | str | `""` | 入口完整地址；留空 = 不限位置 |
| `entry_address_max_distance_m` | float | `None` | 距离上限（米）；留空 = 不限，`0` = 必须同址 |
| `entry_height_min_m` | float | `None` | 身高下限（米）；留空 = 不限 |
| `entry_height_max_m` | float | `None` | 身高上限（米）；留空 = 不限 |

判定顺序：先地址（维度不同 → 区间上界超限），再身高（低于下限 → 高于上限），命中第一个
不满足的条件就返回对应文案。四项都在剧本编辑器的「通用」页里可填，地址一栏旁边有选择按钮，
可以从注册表里点选。

</details>

## 7. 作者须知

- 地址写坏只会 warning，不会拦人——但也就等于这道门没生效，写方案后请直接跑一次编辑器
  的校验条。
- 想用地址条件，必须**同时**给 `entry_address` 与距离；只给距离不会有任何效果。
- 改动后跑 `python tests/check_scenario_admission.py`（地址距离、身高区间、校验器诊断与
  仓库迁移都在里面）。

## designs 目录

<details>
<summary>designs/ 全目录（wiki 地图）</summary>

**机制目录**

- **dungeon/**：[README](README.md)（全景）·
  [script](script.md)（章节与触发器字段）·
  [prompts](prompts.md)（提示词与上下文）·
  [characters](characters.md)（人物表与账本）·
  [voice](voice.md)（对话语音）·
  [admission](admission.md)（本页）·
  [scene](scene.md)（地点与参照物）·
  [minigame](minigame.md)（小游戏）·
  [components](components.md)（显示组件）
- **character/**：[README](../character/README.md)（全景）·
  [evolution](../character/evolution.md)（介入度 / 深度 / 行动点）·
  [time](../character/time.md)（恢复结算 / 作息 / 导出）·
  [chat](../character/chat/README.md)（话题与好感 / 紧张度）·
  [lens](../character/chat/lens.md)（信息视角细节）
- **behaviors/**：[README](../behaviors/README.md)（玩家向）·
  [dev-guide](../behaviors/dev-guide.md)（行为包开发）· 钩子契约四篇
  （[logic](../behaviors/hooks-logic.md) / [report](../behaviors/hooks-report.md) /
  [character](../behaviors/hooks-character.md) / [chat](../behaviors/hooks-chat.md)）·
  [example-imperial](../behaviors/example-imperial.md)（示例包）
- **world_packs/**：[README](../world_packs/README.md)（玩家向：启用 / 切换 / 删除）·
  [author](../world_packs/author.md)（制作与清单）

**单篇**

[地址系统](../address_system.md) · [报告生成](../report_selection.md) ·
[资源与包体系](../resources.md) ·
[挑战包](../challenges.md) ·
[剧本编辑器](../scenario_editor.md) · [界面双模式与外观](../ui_modes.md) ·
[身材剪影](../body_preview.md) ·
[更新检查](../update_check.md)

</details>
