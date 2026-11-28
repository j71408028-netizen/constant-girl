# 行为包钩子：角色与结算（面向作者）

> **这一篇回答什么问题**：想改身高怎么抽、坐标怎么推进、恢复结算怎么算，该覆盖哪个目标、
> 签名长什么样、哪些目标故意不开放。
> - **查某个方法能不能覆盖**：直接看各节表格。
> - **想知道为什么某个目标不开放**：看每节末尾的说明，或 [dev-guide.md](dev-guide.md) 的
>   「开放边界」。
>
> 所属机制：[行为包](README.md)（玩家向）· [开发指南](dev-guide.md)。注册方式、签名一致性
> 与层级约定见开发指南的「注册 API」「钩子目录与层级」。本节覆盖四个域：
> `CreationService`（创建期算法与出身烙印）、`StateService`（坐标与行动点）、
> `offline`（恢复计划）、`spatial`（空间先验的调制入口）。

## `CreationService`

| 方法 | 签名 | 说明 |
|------|------|------|
| `generate_random_height` | `() -> float` | 生成一个随机的普通身高（米）。 |
| `calculate_height` | `(option, custom_val, min_slide, max_slide, use_will, greed, rng, personality=None) -> (float, Optional[str])` | 核心身高算法。`option` 为 `"custom"` 或 `"will"`；返回 `(身高, 意愿状态)`，状态取 `"within"` / `"implemented"` / `"failed"` / `None`。 |
| `derive_model_tuning` | `(personality, selected_tags, height, core=None) -> ModelTuning` | 派生**角色出身调制烙印**（since 2.0，`module/strategy`）。创建角色时调用一次，返回值经内部夹取归一（`ModelTuning.sanitize`）后烙进角色档案、终身携带：覆盖它只调制**之后创建**的角色（离线结算参数包络 + 空间/环境先验），不触及已有角色；`origin_world`（出身世界包记录）由程序按激活世界包写入，不经本钩子。默认实现按离线模型常量与空间 TAG 先验表的**当前有效值**派生，行为包也可以整体替换（含 `extra` 自定义键，核心模型忽略、下游钩子可读）。 |

> `get_body_parts`、`core_from_params`、`get_deterministic_rng` 不开放覆盖：它们属于
> 内部编排/辅助逻辑，覆盖 `calculate_height` 等即可间接改变其输出。

### 常量

| 常量 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `nick.anti_repeat_window` | 常量 int | `20` | 掷昵称的**近距防重窗口**：最近多少次掷名之间不重复同一行，`0` 关闭。按键是**表行**（同一行换了槽位内容仍算重复），不是渲染后的文本，也不按模板文本合并（表里有 55 行模板都写作 `{1}{2}`）。窗口跨实例共享、随取材表切换清空，只在进程内存里，不落存档。窗口内行被剔除后重新归一抽取，等价于「掷到就重抽」，成本约为多掷 6%（20 条窗口、当前 1074 行表），换来 20 条内 0 重复、100 条内重复条数降三分之一。窗口大于表内行数时自动退回整池，只失去防重、不会掷空。 |

> 表内重行会被窗口反复挡住，实际起一层**软上限**：头部组合器行份额从 2.52% 掉到
> 1.75%，四桶实测配比会从 30/35/20/15 漂到 31.5/36.3/19.0/13.3。要严格守配比，
> 覆盖这个常量或在权重侧补偿。

## `StateService`

角色状态（坐标 = 介入度/破坏性、行动点数）操作的统一入口。坐标方法分两层：
纯数值运算（接受任意状态来源的数值，报告生成等字典流程可直接使用），
以及快照级操作（传入 `CharacterSnapshot`，有变化时向演化表追加一行）。

| 方法                         | 签名 | 说明                                                      |
|----------------------------|------|---------------------------------------------------------|
| `clamp_coordinates`        | `(intrusion, destruction) -> (float, float)` | 把介入度/破坏性夹取到统一的 0.5~4.5 大边界。以下的坐标操作方法都应用此大边界。            |
| `shift_coordinates`        | `(intrusion, destruction, intrusion_delta, destruction_delta) -> (float, float)` | 按原始坐标增量平移坐标（副本结局增量等场景）。                                 |
| `advance_coordinates`      | `(personality, intrusion, destruction, step, depth_intrusion=None, depth_destruction=None) -> (float, float)` | 按故事步进推进坐标（坐标 += 步进 × 深度）；未传显式深度时沿用性格初始深度。报告事件与负向演化共用。                 |
| `evolve_depths`        | `(personality, depth_intrusion, depth_destruction, step, intrusion=None, destruction=None) -> (float, float)` | 坐标演化后的深度演化：先按敏感值/重力扣除，再向初始值恢复；传入坐标时叠加不适应性衰减。 |
| `decay_depths`         | `(personality, depth_intrusion, depth_destruction, depth_intr, depth_destr, intrusion=None, destruction=None) -> (float, float)` | 不适应性衰减的纯计算：坐标贴到 0.5/4.5 边界后，对应深度按 `0.4 ^ (|步进| × (1 - 归一个性强度))` 收敛；仅衰减，不负责敏感/重力扣除。 |
| `apply_landmark_switch`    | `(personality, intrusion, destruction, to_frequency) -> (float, float)` | 地标切换（含首次匹配）时的性格调整：切换到 common 介入度 + 敏感值，切换到 unique 介入度 - 敏感值；破坏性达到 3 以上时，切换到 unique 破坏性 + 重力，切换到 common 破坏性 - 重力。 |
| `decayed_coordinates`      | `(personality, intrusion, destruction, fraction) -> (float, float)` | 闲置衰减的纯计算：仅当坐标越过性格边界（初始值 - 0.5 × 性格深度）时向边界回落 fraction 个深度。 |
| `apply_negative_evolution` | `(state) -> None` | 行动点数不足（<50）时应用负向演化：介入深度取 -1 - 0.5 × 性格敏感值（由敏感值直接控制），破坏深度取 -1 - 0.5 × 性格重力；深度演化叠加不适应性衰减；有变化时向演化表追加一行（步进取本次负向步进之和）。 |
| `apply_step_decay`         | `(state, fraction=0.1) -> None` | 闲置衰减（角色面板逗留每分钟 fraction=0.1），有变化时向演化表追加一行。              |
| `nudge_depths`         | `(state, axis, direction, amount=0.02) -> Optional[(float, float)]` | 聊天 effect 的深度微调：`axis` 取 intrusion/destruction，`direction` 取 -1/0/1；单次幅度很小，接近 ±5 时衰减；只改深度、不写演化表，返回 `(旧值, 新值)` 或 `None`。 |
| `consume_action_points`    | `(state, cost) -> bool` | 消耗行动点数；点数不足返回 `False`。                                  |
| `receive_action_points`    | `(state, amount) -> int` | 自然回复行动点数（恢复结算、角色面板逗留恢复），夹取到 0~100，返回实际变化量。 |
| `refund_action_points`     | `(state, amount) -> int` | 返还行动点数（副本结算、报告解锁返还等），不设 100 上限，返回实际变化量。 |
| `recover_action_points`    | `(state) -> None` | 在角色面板逗留时，根据性格恢复行动点数（内部调用 `receive_action_points`，覆盖前者会自动生效）。 |

## `offline`（恢复计划）

结算拆成两层：`offline.recover_plan` 只读取状态并返回
`OfflineRecoveryPlan`，不写状态、不记演化；`OfflineService` 把计划写回角色并
追加演化行。展示文案同为模块策略：`recover_offline` 把实际恢复的行动点与
间隔时长交给 `offline.report_text` 生成并返回。`OfflineModel` 是计划函数收到
的模型参数快照，**由角色出身烙印构造**（`OfflineModel.from_tuning
(state.model_tuning)`，创建期经 `CreationService.derive_model_tuning` 派生并
已夹取；8 项结算默认值见 `core/models.py::ModelTuning`）。72 小时明细窗口与
2 小时精度同时是导出图表、演化表和 UI 的跨模块契约，固定不开放。

| 目标 | 类型 | 签名 / 默认 | 说明 |
|------|------|------|------|
| `offline.recover_plan` | 函数 | `(state, now, model) -> Optional[OfflineRecoveryPlan]` | 生成恢复计划。返回 `None` 表示时间戳无效或没有可结算时长。计划字段：`action_point_gain`（请求恢复量）、`intrusion` / `destruction`（结算后坐标，`None` 表示不改）、`details`（明细，`None` 表示保留现有明细）、`step`、`casualties`（本次新增伤亡）。 |
| `offline.report_text` | 函数 | `(state, plan, elapsed_minutes, action_point_gain) -> str` | 把一次结算转成展示文案，`plan` 为 `None` 返回空串。`elapsed_minutes` 是距上次结算的分钟数，`action_point_gain` 是执行层实际恢复的行动点（已受自然回复上限约束）；步进/伤亡增量取自计划。 |

覆盖 `offline.recover_plan` 可调用 `runtime.default("offline.recover_plan")` 复用
默认计划后再改字段。执行层会夹取坐标、把行动点恢复量交给
`StateService.receive_action_points`（自然上限 100），并按 `recover_evolution`
来源标签记录演化（历史演化行的字符串标签，入口本身已删）；这些执行语义不开放。

## `spatial`（空间档案学习层）

空间 / 环境先验的调制入口是**创建期烙印**（覆盖
`CreationService.derive_model_tuning`，返回值里的 `spatial_priors` 四标量与
`env_prior_shares` 7 元份额），不再提供运行时常量钩子；份额形状在烙印端校验
（非法值回退均匀兜底并经 `[BehaviorPack]` 通道警告一次）。TAG 默认表
（`services/character/spatial.py` 的 `TAG_SPATIAL_PRIORS` / `TAG_ENV_PRIORS`）
只是默认派生的数据来源，直接 import 只能拿到默认值。

学习层参数（EWMA 半衰期、平滑伪计数、调制夹取、成熟度阻尼等）不开放——
它们重新解释角色的到访与沉淀历史，见 [dev-guide.md](dev-guide.md) 的
「开放边界：三层开放模型与角色身份稳定性」。

## 覆盖示例

把抽到的高度封顶，其余逻辑仍用默认实现：

```python
# data/static/behaviors/my_pack/height_rules.py
from core.behavior_runtime import get_runtime
from services.creation_service import CreationService


def capped_height(option, custom_val, min_slide, max_slide,
                  use_will, greed, rng, personality=None):
    default = get_runtime().default("CreationService.calculate_height")
    height, status = default(option, custom_val, min_slide, max_slide,
                             use_will, greed, rng, personality)
    return min(height, 20.0), status


def register(runtime):
    runtime.override(CreationService.calculate_height, capped_height)
```

## designs 目录

<details>
<summary>designs/ 全目录（wiki 地图）</summary>

**机制目录**

- **dungeon/**：[README](../dungeon/README.md)（全景）·
  [script](../dungeon/script.md)（章节与触发器字段）·
  [prompts](../dungeon/prompts.md)（提示词与上下文）·
  [characters](../dungeon/characters.md)（人物表与账本）·
  [voice](../dungeon/voice.md)（对话语音）·
  [admission](../dungeon/admission.md)（进入准入）·
  [scene](../dungeon/scene.md)（地点与参照物）·
  [minigame](../dungeon/minigame.md)（小游戏）·
  [components](../dungeon/components.md)（显示组件）
- **character/**：[README](../character/README.md)（全景）·
  [evolution](../character/evolution.md)（介入度 / 深度 / 行动点）·
  [time](../character/time.md)（恢复结算 / 作息 / 导出）·
  [chat](../character/chat/README.md)（话题与好感 / 紧张度）·
  [lens](../character/chat/lens.md)（信息视角细节）
- **behaviors/**：[README](../behaviors/README.md)（玩家向）·
  [dev-guide](../behaviors/dev-guide.md)（行为包开发）· 钩子契约四篇
  （[logic](../behaviors/hooks-logic.md) / [report](../behaviors/hooks-report.md) /
  [character](../behaviors/hooks-character.md)（本页） / [chat](../behaviors/hooks-chat.md)）·
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
