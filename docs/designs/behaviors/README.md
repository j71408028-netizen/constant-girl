# 行为包

> **这一篇回答什么问题**：世界包里的「行为包」到底是什么、激活后你会看到什么变化、怎么启用、
> 为什么程序要提醒你它是一段会被执行的代码。
> - **只想搞懂它在做什么**：看 **§1～§2**。
> - **想确认安全或排查「行为包诊断异常」**：看 **§3** 与 **§4**。
> - **想自己写一个**：读完这页去 [dev-guide.md](dev-guide.md)（面向作者）。
>
> 相关页面：怎么打包与启用世界包 [world_packs/README.md](../world_packs/README.md) ·
> 清单里怎么写行为包 [world_packs/author.md](../world_packs/author.md)。

行为包是世界包可选携带的一小段 Python 代码。世界包激活期间，它会改掉程序里一些原本固定的
算法——比如身高怎么抽、尺寸用什么单位显示、恢复结算怎么算、报告里地标和描述怎么配对。

可以把它理解成世界包的「规则层」：世界包里的地标、描述、副本方案是**内容**，行为包改变的
是程序处理这些内容的**方式**。

## 1. 它换掉了什么

| 被改动的部分 | 你可能会看到 |
|---|---|
| 角色创建 | 身高生成的分布与「意愿」判定方式变化 |
| 尺寸显示 | 单位从米 / 千米换成英尺 / 英里（随包自带的示例） |
| 坐标与行动点 | 报告后坐标的推进、行动点回复与消耗的手感变化 |
| 恢复结算 | 回到程序时这段间隔里累积的恢复量、坐标变化与明细文案 |
| 报告选取 | 地标与描述的配对、事件描述的挑选、伤亡与耐久估算 |
| 档案文本 | 「作息与活动范围观察」、实时提示的措辞 |
| 聊天 | 通讯媒介、世界背景、话题候选与措辞、回复节奏与主动搭话门槛 |

它**不会**改写角色已经成立的东西：名字、性格、学到的作息与活动习惯、履历。世界包对角色
出身参数的影响只发生在**创建角色时**，已有角色不会因为启停世界包而性情大变。

> 一句话记法：世界包能改「世界如何运转」，不能重写「她是谁」。

## 2. 怎么启用

- 行为包**不能单独启用**，只能随世界包一起激活。在「设置 → 世界包」里激活、停用或解散
  世界包即可。
- 一个世界包最多携带**一个**行为包；它随 `<world_id>.world.zip` 分发，不需要单独安装。
- 激活后，导航栏底部的世界包信息会显示「行为已更改 N 项」；鼠标停上去可以展开接管清单、
  行为包 API 版本与警告。
- 停用、解散或切换到别的世界包后，覆盖**立即清空**、恢复默认行为，不需要重启。
- 解散世界包时，里面的行为包会自动转存回 `data/static/behaviors/`，不会丢。
- 进入副本时，副本进程也会加载同一个行为包，副本内的行为与主界面一致。

## 3. 安全提醒

行为包本质是 Python 代码，激活时会在你的电脑上执行。只应激活来自可信来源的世界包，如同
对待一般软件一样。程序不会自行联网下载或安装行为包。

如果某个行为模块加载失败或注册不合法，只有那一条会被跳过并记入诊断（导航栏显示
「⚠ 行为包诊断异常」），其余行为与默认行为照常工作——坏插件不该让整个程序陪葬。

## 4. 内部实现

- **加载时机**：激活世界包时加载包内每个 `.py` 模块，逐个调用其 `register()` 入口注册
  覆盖；切换世界包时先卸载旧包再加载新包，不会串包。
- **覆盖是全局的**：无论调用方是静态调用还是通过服务实例调用，都会拿到覆盖实现，所以不
  存在「界面上生效、副本里没生效」的两套行为。
- **诊断通道**：注册被拒绝的原因（未知 key、签名不符、类型不符、模块异常）都进诊断报告，
  经 `[BehaviorPack]` 通道打印，同时在导航栏计数。
- **副本侧**：副本子进程随激活世界包加载同一个行为包；它拿到的是同一份钩子表，但副本的
  演化主体公式本身不开放（见 [dev-guide.md](dev-guide.md) 的「能力边界」）。

## 5. 拓展用法

- **手动把一个行为包目录放进 `data/static/behaviors/<pack>/`**：不需要等别人打包，创建
  世界包时在资源页就能直接选中它（目录名只能字母开头，后跟字母、数字或下划线）。
- **把示例包复制一份当模板改**：`data/static/behaviors/imperial_units/` 是一个能跑的完整
  例子，改里面的常数与函数就是最小的自定义行为包。
- **同一个世界包换行为包测试**：停用 → 换 `world.json` 里的名字 → 重新激活即可，不需要
  重启程序。

## 6. 参数表

<details>
<summary>world.json 里与行为包有关的字段（手写清单或排查「没生效」时展开）</summary>

| 字段 | 取值 | 说明 |
|---|---|---|
| `resources.behaviors` | `["<pack>"]` | 数组，但最多一个元素；多写不会都生效 |
| `behavior_api` | 整数，当前 `2` | 包面向的行为包契约版本；未声明按 `1` 处理，高于 / 低于只在激活诊断里警告，不阻断 |

目录布局：静态开发副本在 `data/static/behaviors/<pack>/`，随世界包启用的副本在
`data/worlds/<world_id>/behaviors/<pack>/`。

</details>

## 7. 官方资源

程序自带一个示例：`data/static/behaviors/imperial_units/`，把显示单位从米 / 千米改成英尺 /
英里。完整源码见 [example-imperial.md](example-imperial.md)。

四个域的契约页：[角色与结算](hooks-character.md) · [报告](hooks-report.md) ·
[尺寸与文本](hooks-logic.md) · [聊天](hooks-chat.md)。

## 8. 作者须知

行为包作者要守的契约（模块入口、签名一致性、错误隔离、常量覆盖、API 版本）全部在
[dev-guide.md](dev-guide.md)，这里不重复。

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
- **chat/**：[README](../chat/README.md)（话题与好感 / 紧张度）·
  [lens](../chat/lens.md)（信息视角细节）
- **behaviors/**：[README](README.md)（本页）·
  [dev-guide](dev-guide.md)（行为包开发）· 钩子契约四篇
  （[logic](hooks-logic.md) / [report](hooks-report.md) /
  [character](hooks-character.md) / [chat](hooks-chat.md)）·
  [example-imperial](example-imperial.md)（示例包）
- **world_packs/**：[README](../world_packs/README.md)（玩家向：启用 / 切换 / 删除）·
  [author](../world_packs/author.md)（制作与清单）

**单篇**

[地址系统](../address_system.md) · [报告生成](../report_selection.md) ·
[角色演化](../character_evolution.md) · [资源与包体系](../resources.md) ·
[挑战包](../challenges.md) ·
[剧本编辑器](../scenario_editor.md) · [界面双模式与外观](../ui_modes.md) ·
[角色的长期行为](../character_time.md) · [身材剪影](../body_preview.md) ·
[更新检查](../update_check.md)

</details>
