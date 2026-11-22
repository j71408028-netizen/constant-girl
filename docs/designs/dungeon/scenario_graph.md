# 编排图与图校验

> **定位**：章节与触发器之间的**图模型**——到底存在哪些关系、两个可达性口径怎么
> 划界。字段定义见 [script.md](script.md)，校验器的五条图规则（R1–R5）与抑制去重
> 见 [script.md](script.md) §9.1。
> 图的**分析**在 `dungeon/scenario_graph.py` / `dungeon/graph_lint.py`（领域层、纯数据），
> **呈现**在 `ui/scenario/graph_view.py`（编辑器「剧情」页的编排画布，画法与交互见
> [剧本编辑器](../scenario_editor.md) §3）。

## 1. 为什么不止「前置条件」一条关系

分章节之前，触发器是平铺的，互相之间只有 `precondition_names` 一种关系，所以早期的
一版图只画这一种边就够了。分章节之后，决定一次副本能不能走通的实际上有**四条**
互相独立的路径，任何一条断了都不会报错，只会静默不生效：

| 关系 | 从配置哪里读出来 | 断了会怎样 |
|---|---|---|
| 前置条件 | 触发器的 `precondition_names` | 条件永远不成立，触发器永不触发 |
| 章节跳转 | `goto` 动作的 `action_data.chapter` | 目标章节永远进不去 |
| 超限跳转 | 章节的 `overflow_target` | 段落数到上限后无处可去 |
| 条件引用 | 条件键 `选择:<触发器名>` | 计数永远为空，分支永远走不到 |

再加上**归属**关系（触发器靠 `chapter` 字段声明自己属于哪一章），这套结构才完整。
四条路径 + 归属，就是下面这张图模型。

## 2. 图模型（`dungeon/scenario_graph.py`）

`build_graph(config)` 是唯一入口，返回 `ScenarioGraph`。**零外部依赖**——不再需要
`networkx`（强连通分量与可达性都是自实现的）。

### 2.1 节点

| 种类 | id 约定 | 携带的信息 |
|---|---|---|
| `NODE_ROOT` | `root` | 「（无章节）」起点伪节点，代表副本刚开始、还没进入任何章节的状态 |
| `NODE_CHAPTER` | `chapter:<章节名>` | 起始 / 结束 / 固定文本标记、在 `chapters` 里的下标 |
| `NODE_TRIGGER` | `trigger:<触发器名>` | 归一化后的动作类型、所属章节、在 `triggers` 里的下标 |

触发器名与章节名已经是校验器认定的唯一键，所以直接拿名字当 id，不另造一套。

**入口为什么是伪节点而不是起始章节**：运行时 `_enter_start_chapter` 是在
「当前没有章节」时才进入起始章节的。从伪节点出发算可达性，才能同时覆盖
「没有标记起始章节」和「某章节永远进不去」两种情形。

### 2.2 边

| 种类常量 | 展示名 | 方向 | 来源 |
|---|---|---|---|
| `EDGE_ENTRY` | 进入 | `root` → 起始章节 | `chapters[].start` |
| `EDGE_SCOPE` | 归属 | 章节 → 其下的触发器 | `triggers[].chapter` |
| `EDGE_PRECOND` | 前置条件 | 前置触发器 → 触发器 | `triggers[].precondition_names` |
| `EDGE_GOTO` | 章节跳转 | 触发器 → 目标章节 | `goto` 动作的 `action_data.chapter` |
| `EDGE_OVERFLOW` | 超限跳转 | 章节 → 目标章节 | `chapters[].overflow_target` |
| `EDGE_CHOICE` | 条件引用 | 被引用触发器 → 触发器 | 条件键 `选择:<触发器名>` |

`EDGE_SCOPE` 只参与分析，界面上不画箭头——它由泳道归属直接表达（见
[剧本编辑器](../scenario_editor.md) §3 的泳道图）。范围是「任意章节 / 无章节」
（`CHAPTER_ANY` / `CHAPTER_NONE`）的触发器，归属边从 `root` 出发：它们在任何状态下
都可能判定。

### 2.3 两个可达性口径（关键约定）

图校验只报 warning 与 info 也要守住不误报，因此有两条口径，别混用：

- **章节可达性**（`chapter_reachability()`）：只走 `entry` / `goto` / `overflow` /
  `scope`，**忽略一切条件与前置**。这是乐观估计——结构上到得了就算到得了，
  不会因为条件写错而误报。讲「走不到」的规则一律只用这一条。
- **触发器可达性**（`trigger_reachability()`）：在上面基础上加入 `precond` 的
  AND 语义。先把前置边收缩成强连通分量，再在 DAG 上迭代到不动点；一个分量要能激活，
  必须**存在一个成员没有分量内的前置**（"种子"）。整环互锁、没有种子的分量永远激活
  不了——这正是「循环依赖」的判据。

`EDGE_CHOICE` 两条口径都**不参与**：被引用的触发器没触发只意味着计数为 0，
是可以被比较的合法值，不是"到不了"。

### 2.4 泳道与章节层投影

- `lanes` 按编辑器的顺序给出泳道：每个章节一条，顺序同 `chapters`；「任意章节 / 无章节」
  的触发器合成最后一条。每条泳道里是节点 id 序列。
- `chapter_view_edges()` 把图投影到**章节层**：`goto` 边折算成「触发器所在章节 → 目标
  章节」，用于「章节编排」视图（章与章之间的流程图）。
- `same_position_groups()` 把 `ACTION_POSITIONS` 同位、同作用域、且**不止一条**的触发器
  分好组（`PositionGroup`），供编辑器呈现同位置竞争（不进校验器，判据见
  [script.md](script.md) §9.1）。它只分组，不下结论。

## 3. 边界（明确不做什么）

- **不写盘**：全程只读方案配置，产出的是诊断与图形。
- **不做条件求解**：只见「条件是否为空」，不判断两个非空条件是否重叠（判据与
  口径见 [script.md](script.md) §9.1）。
- **不替代既有规则**：图校验是**追加**的五条，`validate.py` 原有的字段级、资产存在性、
  旧版字段等规则一条不动。
- **不再依赖 `networkx` / `graphviz`**：两者已从 `requirements.txt` 移除，打包也不再
  需要系统 `dot` 二进制。
- `lint_graph(graph)` 只产出 `(level, path, message)` 三元组、不 import `validate`，
  由 validate 侧包成 `Diagnostic`。

## 4. 自检

| 脚本 | 覆盖 | 命令 |
|---|---|---|
| `tests/check_scenario_graph.py` | 离线（可进 CI 门禁）：节点与四类边构造、两个可达性口径、强连通分量与种子判定、五条规则各命中一次、骨架方案不刷可达性诊断、同位置竞争只分组不报红、正常方案零诊断、`path` 与既有诊断体系一致 | `python tests/check_scenario_graph.py` |
| `tests/check_scenario_editor_diagnostics.py` | 离线：编辑器顶栏校验条的展示口径——路径根键与页签归属（含 `chapters@名字` / `triggers@名字` 这类虚路径）、计数与门面挑选、只剩提示时不报警 | `python tests/check_scenario_editor_diagnostics.py` |

GUI 侧没有独立的守卫脚本：画布只做呈现，逻辑全在领域层的两个模块里，那部分已被上面
的离线自检覆盖。手工看效果用
`python tests/run_checks.py --smoke`（进编辑器，剧情页依次切到「章节编排」「触发器依赖」）。

## 相关

- 字段与动作的权威定义：[script.md](script.md)（`dungeon/schema.py` 是单一真相源）。
- 触发器判定顺序、同位置至多生效一个：[script.md](script.md) §6.1。
- 编辑器画布、诊断分组与校验条：[剧本编辑器](../scenario_editor.md) §3–§4。
- 分层与守卫：`docs/architecture.md` §1、`tests/check_import_graph.py`。
