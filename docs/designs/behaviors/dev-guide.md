# 行为包开发指南

> 面向行为包作者与维护者；玩家向说明见 [README.md](README.md)。
>
> 角色演化模型的完整设计（量、公式、已验证动态特性）见
> [character_evolution.md](../character_evolution.md)；
> 覆盖 `StateService` 坐标/深度方法前建议先阅读该文档。

行为包（Behavior Pack）是世界包中的一种资源类型，允许世界包作者在激活该世界包期间
覆盖核心算法的实现，而无需修改主程序代码。可覆盖范围包括：

- `CreationService` / `StateService` 的部分静态方法；
- `core/logic/`（`sizing` / `quips` / `simulation` / `text` 四个子模块，
  `core/logic/__init__.py` 再导出全部公开名）中除 `get_size_category` 外的
  全部模块函数，以及 `PREDEFINED_TAGS` 常量（注册键是与文件位置无关的
  `"logic.xxx"` 字面量契约）；
- `profile`（`services/character/profile_text.py`，档案派生层的文本化出口）：作息与
  空间偏好的可读结论与实时提示（见 [hooks-logic.md](hooks-logic.md) 的 `profile` 组）。
  scope 同样是与文件位置无关的字面量契约——以后新域按此模式扩展。
- `offline`（`services/character/offline.py`，恢复结算）：纯计划
  `offline.recover_plan` 与展示文案 `offline.report_text`；计划收到的模型参数
  快照来自角色出身烙印（见下文三层模型）。执行与持久化仍由服务层负责
  （见 [hooks-character.md](hooks-character.md) 的 `offline` 组）。
- `report`（`services/exploration/arbiter.py` 报告选取仲裁 +
  `services/exploration/report.py` 报告引擎）：车道窗口 / 联合分 /
  近匹配提拔是模块策略；仲裁模型参数与引擎的伤亡 / 耐久参数是
  `report.model.*` 常量钩子。硬闸、物理走查与 stuck 判定不开放；
  描述选句 `select_quip_with_budget` 不在开放面
  （见 [hooks-report.md](hooks-report.md) 的 `report` 组）。
- `chat`（`services/chat/`，聊天提示词与投递节奏）：世界语境、话题候选 /
  措辞、关系与聊天习惯文案、三轴坐标、主动搭话门槛与回复延迟是模块策略，
  节奏数值是 `chat.model.*` 常量钩子。JSON 协议、消息状态机、话题状态机、
  持久化与关系转移图不开放（见 [hooks-chat.md](hooks-chat.md) 的 `chat` 组）。

结算模型参数与空间 / 环境先验的调制**不经运行时钩子**：它们经
`CreationService.derive_model_tuning` 在创建角色时烙印（出身层，见下文）。

**核心规则**：

- 行为包以**文件夹**为存储单位，一个世界包最多附带**一个**行为包；
- 行为包**不能单独启用**，只能随世界包激活；停用、解散或删除世界包后覆盖自动
  清空、恢复默认行为，不需要重启程序；
- 目录内每个 `.py` 模块都会在激活时加载，且必须定义 `register(runtime)` 入口；
- **任意代码执行**：行为包本质是 Python 代码，会在激活时于本机执行。只应加载
  来自可信来源的世界包，如同对待一般软件一样。

程序在 `data/static/behaviors/imperial_units/` 提供了一个现成示例：把显示单位从
米 / 千米改为英尺 / 英里。想快速了解行为包长什么样，可直接阅读它（完整代码见
[example-imperial.md](example-imperial.md)）。

## 钩子分组

可覆盖目标按 scope 分组：[hooks-character.md](hooks-character.md)（`CreationService`、
`StateService`、`offline`、`spatial`）、[hooks-report.md](hooks-report.md)（`report`）、
[hooks-logic.md](hooks-logic.md)（`logic`、`profile`）、[hooks-chat.md](hooks-chat.md)
（`chat`）。完整示例见 [example-imperial.md](example-imperial.md)。

## 开放边界：三层开放模型

可覆盖目标分三层，这条边界与层级 / 契约元数据并行生效：

| 层 | 内容 | 生效方式 |
|---|---|---|
| 世界规则 | `report.*`（含 `report.model.*` 常量）、`StateService` 坐标/行动点、`logic.*`、`offline.recover_plan` / `report_text`、`profile.*` 文本化 | 运行时钩子，随世界包启停 |
| 角色出身 | 结算参数与空间/环境先验的调制烙印（`ModelTuning`） | `CreationService.derive_model_tuning` 创建时烙印，终身携带 |
| 角色习性 | rhythm / spatial 演化表学习 | 模型内部，参数封闭（不开放） |

一句话：世界包能改「世界如何运转」，不能重写「她是谁」（取舍论证见
`docs/dev/architecture.md` §2.6）。

- **世界规则可以换**：坐标演化、选取仲裁（`report.*`）、恢复结算
  （`offline.recover_plan`，收到的 model 即来自角色烙印）都是「世界如何运转」
  的算法，覆盖它们不重新解释角色已学到的东西。
- **角色出身只在创建时烙印**：结算参数与空间 / 环境先验以 `ModelTuning` 烙印在
  档案里（`CreationService.derive_model_tuning` 派生，内部 sanitize 夹取归一，
  `origin_world` 记录出身世界包），存量角色读档回退默认，不随世界包启停变化。
- **角色习性不可重写**：作息学习（`RhythmService`）与空间 / 环境 / 偏好学习
  （`spatial.py` 学习层）的参数——半衰期、平滑伪计数、收缩强度、调制夹取、
  成熟度阻尼等——不开放。
- 聊天域（`chat.*`）按同一原则开放：可追加世界语境、改话题候选与措辞、调整
  聊天手感，不可改写角色的既有身份事实；见 [hooks-chat.md](hooks-chat.md)。

## 开发流程

### 第 1 步：编写行为模块

在静态目录 `data/static/behaviors/<pack>/` 下创建文件夹（`<pack>` 只能由字母开头，
后跟字母、数字或下划线），在其中编写 `.py` 模块。

每个模块需定义 `register(runtime)` 入口函数；程序激活世界包时会加载全部模块并
把全局行为运行时传入：

```python
# data/static/behaviors/my_pack/height_rules.py
from services.creation_service import CreationService


def my_calculate_height(option, custom_val, min_slide, max_slide,
                        use_will, greed, rng, personality=None):
    # ...自定义身高算法...
    return 3.0, "within"


def register(runtime):
    # target 传字符串或静态方法对象均可
    runtime.override(CreationService.calculate_height, my_calculate_height)
```

覆盖实现必须与被覆盖函数保持**相同的参数顺序、默认值与返回约定**，否则会导致
运行时参数错位或下游解析失败。可覆盖的目标及签名见下文各分组页
（[hooks-character.md](hooks-character.md)、[hooks-report.md](hooks-report.md)、
[hooks-logic.md](hooks-logic.md)、[hooks-chat.md](hooks-chat.md)）。

### 第 2 步：把行为包声明进世界包

创建世界包时在资源页**单选**该行为包，清单会自动写入；也可以直接手写
`world.json`：

```json
{
  "format_version": 1,
  "behavior_api": 2,
  "world_id": "my_world",
  "name": "我的世界",
  "version": "1.0",
  "resources": {
    "behaviors": ["my_pack"]
  }
}
```

`behavior_api` 声明包面向的行为包契约版本（整数，当前为 `2`）。未声明按
`1` 处理；低于 / 高于当前版本都只在激活诊断中警告、不阻断。程序内
「从当前世界创建」的世界包会自动盖章当前版本。

目录结构：

```
data/static/behaviors/my_pack/     # 静态开发副本（文件夹）
├── height_rules.py
└── state_tuning.py

data/worlds/<world_id>/
├── world.json
└── behaviors/
    └── my_pack/                   # 随世界包启用的副本
        ├── height_rules.py
        └── state_tuning.py
```

### 第 3 步：激活世界包并验证

激活世界包后，覆盖立即生效——无论调用方是 `CreationService.x(...)` 这样的静态
调用（`ui` 中的直接引用也在内），还是通过 `context.creation_service` 等实例调用，
都会使用覆盖实现。停用或解散世界包后自动恢复默认行为；切换世界包时会先卸载
旧包再加载新包，不会串包。

### 打包与分发

- 分发：把 `data/worlds/<world_id>/` 目录打包为 `<world_id>.world.zip`
  （服务层 `WorldManager.export_pack`；清单、激活与命名空间的完整机制见
  [../world_packs/author.md](../world_packs/author.md)）；
- 解散世界包时，行为包会自动转存回 `data/static/behaviors/`（目录名冲突则
  追加世界包名与版本号）。

## 注册 API

| 方法 | 说明 |
|------|------|
| `runtime.override(target, impl)` | 注册对某个可覆盖目标的实现。`target` 可以是 `"logic.compute_casualty"` 这样的字符串，也可以是 `CreationService.calculate_height` / `logic.compute_casualty` 等被包装的函数对象（带 `__hook_key__`）。函数覆盖的 `impl` 必须可调用且接受原函数的全部具名参数（或以 `**kwargs` 兜底）；常量覆盖的 `impl` 须为同类型值或返回该值的可调用对象。不满足时该条注册在激活时被拒绝并记入启用诊断。 |
| `runtime.resolve_value(key)` | 读取常量细度目标的有效值（覆盖实现可调用则调用取值；无覆盖返回默认值）。 |
| `runtime.default(target)` | 返回被覆盖前的默认实现。覆盖函数内部如需复用默认逻辑，可调用 `runtime.default(target)(...)`。 |
| `runtime.reset()` | 清空全部覆盖（一般由程序自动调用，模块内无需使用）。 |
| `runtime.catalog()` | 返回全部可覆盖目标的元数据（见下节），供开发工具与行为包作者查询。 |

## Hook 目录与层级

`runtime.catalog()` 返回按 key 排序的元数据列表：

| 字段 | 说明 |
|------|------|
| `key` | 稳定注册键 |
| `scope` | key 的第一段 |
| `kind` | `function` / `const` |
| `layer` | `infra` / `module` / `content` |
| `contract` | `point` / `strategy` / `data` |
| `since` | 进入目录的版本 |
| `deprecated` | 是否计划废弃 |
| `params` | 函数细度的具名参数；常量为空列表 |
| `default` | 常量为注册默认值；函数为默认实现的函数名 |

层级按语义所有权划分，不按文件目录：

| 层级 / 契约 | 开放方式 | 典型目标 |
|------|------|------|
| `infra/point` | 固定流程中的单个算法点 | `logic.*` 数值核、`StateService` 坐标 / 行动点原语 |
| `infra/data` | 固定流程中的模型参数（数值 / 表） | `report.model.*` |
| `module/strategy` | 模块门面的决策策略，返回决策或计划 | `profile.*`、`offline.recover_plan`、`report.*`、`chat.*`、`CreationService.derive_model_tuning`（创建期烙印）；后续 `news.*` |
| `content/data` | 数据表、文案、阈值 | `logic.PREDEFINED_TAGS` |
| 核心不变式 | 不开放，不进入目录 | 坐标夹取、AP 上限、JSON 协议、消息状态机、持久化、习性学习参数 |

> 全目录 `since` 以 **2.0** 为基线。

## 注意事项

- **任意代码执行**：行为包本质是 Python 代码，会在激活时于本机执行。只应加载来自可信
  来源的世界包，如同对待一般软件一样。
- **签名一致性**：覆盖实现的参数与返回值约定必须与原静态方法一致。激活时运行时
  会校验：签名缺少默认实现要求的具名参数、或多出默认实现不提供的必填参数，都会被
  拒绝并记入启用诊断，避免参数错位到运行中才暴露。
- **错误隔离**：某个行为模块加载或注册失败时，异常只影响该模块（其余行为模块与
  默认行为不受影响），原因（含异常类型与文本）记入启用诊断。
- **常量覆盖**：`logic.PREDEFINED_TAGS` 是常量细度钩子（`behavior_const` 注册），
  必须用字符串键 `"logic.PREDEFINED_TAGS"` 注册，`impl` 可为列表值或返回列表的
  可调用对象（其他类型被拒绝）。数值常量允许 int / float 互通；可调用对象在每次
  读取时重新求值，返回值类型与默认值不符会回退默认值并记入诊断。程序统一通过
  `logic.get_predefined_tags()` 读取。
- **重复注册**：同一 key 被多个模块或同一模块多次注册时，最后一条生效，启用诊断
  给出警告。
- **启用诊断**：激活行为包时，`load_pack` 逐条校验注册并产出诊断报告
  （`BehaviorLoadReport`）：接管了哪些 key、未知 key / 签名或类型不符的拒绝原因、
  模块加载失败等，经 `[BehaviorPack]` 通道打印；导航栏会显示接管项数或诊断异常
  计数，悬停世界包信息可展开完整诊断（接管清单 / API 版本 / 警告）。坏注册只
  拒绝该条，不影响包内其余注册。
- **API 版本**：`world.json` 的 `behavior_api` 声明包面向的契约版本（当前
  `2`）。未声明按 `1` 处理并提示；低于 / 高于当前版本只警告不阻断。
- **能力边界（副本）**：副本演化主体公式 `dungeon/rules.py::evolve_attributes`
  没有行为钩子——副本路径只通过注入的 `StateService.decay_depths` 受行为包
  影响；段步进、转移矩阵与章节演化修正属于方案配置，不应由行为包重复表达。
  副本子进程会随激活世界包加载同一个行为包，父进程已有的钩子在副本内同样生效。
