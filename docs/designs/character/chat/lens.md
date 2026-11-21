# 聊天话题的信息视角（面向作者）

> **这一篇回答什么问题**：一个话题类型除了「聊什么」，还决定了「她此刻被允许知道什么」——
> 哪些存档字段能进提示词、各占多少分量、什么情况下必须挡掉；以及想改某个类型的信息口味时
> 该动哪一条。
> - **想改某个类型给什么信息**：**§4** 的配方表 + **§7** 的调参入口。
> - **想新增一个话题类型**：**§3**（字段注册）→ **§4**（配方）→ **§10**（契约）。
> - **排查「她为什么知道 / 不知道这件事」**：**§2** 的三条硬规则 + **§6** 的账本工具。
>
> 相关页面：话题的坐标、候选与状态机 [README.md](README.md) · 完整人设（报告 / 导出用）
> `services/chat/persona.py` · 演化坐标 [evolution.md](../evolution.md)。

一句话：**类型管两件事——这一刻该聊什么（坐标 / 候选），以及这一刻她可以被允许知道什么
（视角 / 字段 / 预算）**。存档不是每轮全量塞进系统提示词的背景板。

## 1. 这一层怎么工作

```text
存档（CharacterSnapshot / ChatState / 世界态势）
   │  逐条登记，带层级与渲染器
   ▼
ArchiveField：public | contextual | secret        ← 谁有资格看到
   │  由当前话题类型申请（opens / denies / 权重）
   ▼
TopicKind：coord · frame（聊什么）· prompt（怎么写）· 预算 · 是否允许透露
   │  按权重贪心装进预算，同组限量
   ▼
【此刻你注意到的事】（类型名）
   注意力框架一句 + 只属于这个类型的几条事实 + 说话的体裁一句
   ＋ LensTrace（取用了哪些、挡掉了哪些、为什么）
```

分工只有三句话：

- **类型表**是唯一的类型定义：坐标、半径、框架、体裁、开放的字段与预算都在同一条记录里，
  另留整表替换的入口（§10）。
- **字段层只认字段**：字段注册表、渲染器、预算裁剪与账本；它不知道「有哪些话题」，只知道
  「这条类型申请了哪些字段」。
- **身份层只出公开信息**：`build_identity_frame()` 只产出名字、性格、公开介绍与标签；
  完整人设仍然存在，留给报告、导出与一次性聊天参数判定，不进聊天提示词。

没有活跃话题时不是「第十种类型」，而是一个虚拟视角：只看此刻的处境。这样「刚打开聊天还没
起话题」不会反而把全量存档灌进去。

### 1.1 三个文案字段：frame > prompt > focus

| 字段 | 管什么 | 出现在哪 | 不该写什么 |
|---|---|---|---|
| `frame` | 此刻聊什么、注意力落在哪、行为边界 | 视角段标题下第一行（永远在最前）；候选行后半取它的第一小句 | 句长、用词这类写法 |
| `prompt` | 体裁：句长、节奏、用词层级、标点、要不要表情 | 只在视角段最后一行「说话的体裁：…」 | 话题内容、情绪态度 |
| `focus` | 选它之后会更关注什么（信息预告） | 只在候选列表，行首（`信息｜姿态`） | 任何会被当指令执行的内容 |

候选行读作「**会关注什么｜聊起来什么姿态**」，两个字段各占一半；`prompt` 不出现在候选里
——它只影响选中之后的写法，帮不上「选哪个」这个决定。

> 顺序与权重一致：**框架决定聊什么，体裁只决定怎么打字**。所以「挑衅、试探底线、调情、
> 警告赶人」这类内容全归 `frame`；在 `prompt` 里写「语气带压迫感」就是错位，表现是同一
> 类型的注意力范围与说话腔调互相打架（语气忽高忽低）。两者冲突时以框架为准。

## 2. 三条硬规则

### 2.1 分层：没有代码路径可以无条件注入

| 层级 | 含义 | 谁能用 |
|---|---|---|
| `public` | 名字、性格、公开介绍、个性标签 | 身份层恒在；视角不得重复申请 |
| `contextual` | 身高、尺寸能力、已测部位、意志、位置、作息、活动范围、实时情境、新闻、世界态度、结局 | 只有当前话题类型的视角 |
| `secret` | 隐藏介绍、生日 | 视角开放 **且** 允许透露 **且** 好感 ≥ 40 |

「身份层只能出公开字段」是写在注释里的契约，也有自检直接断言「隐藏介绍 / 位置 / 已测尺寸 /
新闻不出现在身份层」，所以「手滑加进去」会红。

### 2.2 预算：类型之间真的在抢位置

每个视角有字符预算，只约束字段文本；标题、框架、体裁行不被裁——「怎么说话」是必须的，
「知道多少」才是可裁的。

- 排序分 = 视角给的权重 × 字段自身分量；
- 同组（`self / body / life / world / private / place`）最多 **2** 条，防止世界类字段霸占
  整个预算；
- 放不下就**整条挡掉**，不把一句话砍成半句（剩余空间小于最小碎片即停止塞）；
- 挡掉必须留原因：`empty / denied / gated / budget / group-cap / unregistered`。

所以「疏离时话少、信息也少」是可验证的：`aloof` 预算 `320` 字、只开两条字段；`spar` 预算
`820` 字、世界态度与新闻排在最前。

### 2.3 审计：每次渲染都有一本账

渲染返回「文本 + 账本」：账本里是取用清单（字段、分数、字数）、挡掉清单（字段、原因）、
字段总量与整段长度，一行摘要就能读完。界面里还没有调试面板，排查线上穿帮要靠 §6 的两个
工具。

## 3. 字段注册表

<details>
<summary>全部存档字段的层级、分组、内容与分量（新增话题或排查「这条事实从哪来」时展开）</summary>

| id | 层 | 组 | 内容 | 分量 |
|---|---|---|---|---|
| `pub.name` / `pub.personality` / `pub.intro` / `pub.tags` | public | identity | 身份层四件套（由身份层渲染） | — |
| `self.size` | contextual | self | 身高 + 体型类别一句 | 3.0 |
| `self.scale` | contextual | body | 尺寸能做什么 / 不能做什么（互动尺度） | 1.4 |
| `self.edge` | contextual | self | 介入度、破坏性的定性描述 | 1.5 |
| `self.measured` | contextual | body | 已测量、心里有数的部位尺寸 | 2.0 |
| `self.will` | contextual | self | 她对自己这个规模的感觉 | 1.0 |
| `self.greed` | contextual | self | 「再大一点」的念头强度（0 不渲染） | 1.0 |
| `self.rhythm` | contextual | life | 从活动记录学到的作息 | 1.0 |
| `self.spatial` | contextual | life | 常活动地带与环境偏好 | 1.0 |
| `self.live` | contextual | life | 实时情境（时段 + 所在这一带） | 1.2 |
| `self.position` | contextual | place | 当前地址（紧凑格式） | 1.0 |
| `world.news` | contextual | world | 关于她的最近一条新闻（截 120 字） | 2.0 |
| `world.stance` | contextual | world | 外界对她的定性态度（五档语义） | 1.5 |
| `world.endings` | contextual | world | 已达成的重大事件（最近 3 条） | 1.2 |
| `world.travel` | contextual | world | 旅居过的世界包名（最近 3 条） | 1.0 |
| `private.hidden` | **secret** | private | 隐藏介绍，以「平时不主动说」的口吻给出 | 2.5 |
| `private.birthday` | **secret** | private | 生日 | 0.6 |

新增字段 = 加一条注册 + 在需要的视角里挂上；忘了挂，它就永远不会出现。

</details>

## 4. 视角配方

<details>
<summary>18 个类型各开哪些字段、多少预算、是否透露（改信息口味时展开）</summary>

坐标顺序为好感 / 紧张度 / 状态；「透露」为真时 secret 字段才可能进预算。

| 类型 | `focus`（候选里给 AI 看） | 开放字段（权重） | 预算 | 透露 |
|---|---|---|---|---|
| `open`（无话题） | 此刻的处境 | live 1.2 · position 1.0 · size 0.8 · news 0.7 · rhythm 0.5 | 520 | — |
| `daily` 初识/日常 | 眼前的小事与对方的近况 | live 1.3 · position 1.0 · size 0.8 · rhythm 0.8 · news 0.4 · birthday 0.3 | 700 | 否 |
| `spar` 博弈/施压 | 外界的反应、规则与底线 | stance 1.7 · news 1.5 · edge 1.5 · size 1.2 · measured 0.8（deny hidden/birthday） | 820 | 否 |
| `flirt` 暧昧/亲昵 | 你自己那点没说出口的事 | hidden 1.9 · will 1.0 · live 1.0 · birthday 0.8 · size 0.6（deny news/stance） | 820 | **是** |
| `reflect` 思辨/抽离 | 你怎么看自己身上发生的变化 | will 1.5 · size 1.3 · edge 1.2 · rhythm 1.0 · endings 0.8（deny news） | 780 | 否 |
| `body` 身体/尺寸 | 你自己的尺寸与身体感受 | measured 2.0 · scale 2.2 · size 1.8 · edge 1.0 · live 0.5（deny news/stance/hidden） | 780 | 否 |
| `memory` 回忆/沉重 | 你们共同经历过的事 | endings 1.8 · hidden 1.2 · will 1.2 · spatial 0.8（deny news/measured） | 820 | **是** |
| `guard` 戒备/恐惧 | 这个人是否危险 | stance 1.8 · news 1.2 · edge 1.3 · size 0.8 · position 0.7（deny hidden/birthday） | 720 | 否 |
| `aloof` 疏离/客套 | 只有最基本的处境 | live 0.6 · size 0.5 | 320 | 否 |
| `showoff` 自得/炫耀 | 你有多大、能做什么 | size 2.0 · measured 1.8 · scale 1.6 · edge 1.6 · stance 0.8（deny hidden/news） | 780 | 否 |
| `sharing` 分享/发梗 | 他会不会也觉得这个好笑 | live 1.2 · position 0.4（deny news/stance/size/measured/hidden/birthday） | 260 | 否 |
| `talk` 闲谈/看法 | 一件跟她无关、但她有看法的事 | news 1.0 · will 0.8 · stance 0.4（deny hidden/birthday/measured） | 460 | 否 |
| `mundane` 学习/工作 | 普通人的一天怎么过 | live 1.4 · rhythm 1.0 · position 0.8 · spatial 0.5（deny news/stance/hidden/size/measured/edge） | 480 | 否 |
| `elders` 客套/应答 | 像被长辈问话一样应付 | live 0.6（deny news/stance/endings/hidden/birthday/size/measured） | 240 | 否 |
| `plan` 打算/规划 | 你接下来打算怎么办 | will 1.6 · spatial 1.2 · position 0.8（deny news/stance/hidden） | 520 | 否 |
| `encounter` 异界见闻 | 别处传来的留言，或你碰见过的东西 | travel 2.2 · news 1.0 · position 0.8（deny hidden/birthday/measured） | 560 | 否 |
| `observation` 个人观察 | 城市与山川怎么长的，人遇到危险会怎么做 | position 1.6 · spatial 1.4 · edge 1.2 · news 0.8 · size 0.6（deny hidden/birthday/stance） | 720 | 否 |
| `hobby` 个人爱好 | 你自己愿意花时间的事 | spatial 1.4 · rhythm 1.2 · live 1.0 · position 0.6（deny news/stance/endings/hidden/birthday/size/measured） | 540 | 否 |
| `desire` 个人欲望 | 你真正想要、但未必说得出的事 | hidden 1.8 · will 1.6 · greed 1.2（deny news/stance/measured/size） | 700 | **是** |

试运行批次（`sharing` 之后九条）都只回答「聊什么」，不带个人状态：`elders` 甚至只给一条
实时情境，靠体裁成型；`encounter` 用到了为它新增的旅居世界字段，`desire` 用到了贪念；
`hobby` 没有专属字段，靠常活动范围与作息侧写，所以框架里明确要求「别新编一个爱好」。

四类口味差别一眼可见：外部压力型（`spar` / `guard` / `showoff`）要世界态度、新闻与影响面，
私事关死；自我审视型（`body` / `reflect` / `memory`）要身体、意志、经历，新闻关死；关系型
（`daily` / `flirt` / `aloof`）从「眼前的小事」到「没说出口的事」到「什么都不给」；日常
话题型只给生活侧写，身体数据基本关闭。

</details>

### 4.1 体裁（`prompt`）

`prompt` 只描述**怎么打字**，不描述态度与话题，渲染在视角段最后一行。同一个角色在 `reflect`
下写长句书面语、在 `aloof` 下能一个字回答，这是体裁差别，不是人格变了。

<details>
<summary>话题类型与无话题视角的体裁初始值（写新类型或调整语气时展开）</summary>

| 类型 | 体裁 |
|---|---|
| `open`（无话题） | 短句、口语，想到什么说什么 |
| `daily` | 短句、口语、句子松散，允许语气词与少量网络用语 |
| `spar` | 短、收得干净，陈述句与命令句，少语气词、不用表情符号 |
| `flirt` | 短句、跳着说，半句与省略号，语气词多 |
| `reflect` | 长句、偏书面语，可自问自答与破折号，不用网络用语 |
| `body` | 短句、分得碎，动词与具体名词多，节奏慢 |
| `memory` | 句子偏长、节奏慢，省略号与停顿，口语但克制 |
| `guard` | 极短，常只有几个字，陈述与命令，不解释 |
| `aloof` | 能一个字就不写一句，书面、客气，无语气词 |
| `showoff` | 短句、节奏快，可夸张反问，口语 |
| `sharing` | 一两句、短跳、没头没尾，网络用语与缩写，标点能省就省 |
| `talk` | 句子完整、节奏平，可比喻反问，不用烂梗也不说教 |
| `mundane` | 平铺直叙，句子完整，具体名词多，少形容词 |
| `elders` | 礼貌短句，万能回答，不反问、不接话头 |
| `plan` | 中等长度、陈述为主，「打算」「准备」「还没想好」 |
| `encounter` | 叙述为主、句子偏长，可插一句判断，不用「系统 / 设定」 |
| `observation` | 中等长度，以看到的东西为主，具体名词多，判断放在后面 |
| `hobby` | 松、口语，说细节不说意义，可以停顿补一句「就是……」 |
| `desire` | 句子可以断，说到一半停住；少解释、不承诺 |

三组的口味也跟着分成三档：外部压力型偏短促克制，自我审视型偏长句书面，关系型从松散口语
到极简客套。

</details>

## 5. 与坐标、候选的关系

坐标决定**此刻哪些类型够得着**（半径过滤 + 重复惩罚，见 [README.md](README.md) §4）；视角
决定**够得着的类型各自给什么信息**。两者不交叉：视角不读坐标来选字段，也不会因为坐标高就
多给。

唯一的耦合是 secret 字段的好感门槛 `40`：坐标不够，即便类型允许透露也拿不到——「关系到了
+ 聊到了」两个条件都要满足。

候选列表每行现在是两段：信息预告（`focus`）+ 姿态（`frame` 的第一小句）。

```text
  - spar（博弈/施压）：外界的反应、规则与底线｜你在掂量对方：他敢到哪一步、外面的世界又是怎么议论你的
  - flirt（暧昧/亲昵）：你自己那点没说出口的事｜你想让他多知道一点你，但不会一次说完
```

于是 **AI 选类型 = 选一套关注点 + 一副姿态 + 一套写法**（写法在选中之后生效）。这也让
「换了话题她还在念同一份简历」这类穿帮在机制上消失。

## 6. 内部实现

- **切换有一轮延迟**：视角按「当前活跃话题的类型」渲染，而 AI 在回复里才决定切换，所以
  新类型的信息从下一轮起生效；第一轮仍用旧视角（或虚拟的无话题视角）。
- **账本只进测试与预览工具**：`python developer_tools/lens_preview.py` 逐类型打印真实存档
  的账，`python developer_tools/chat_session_preview.py 角色ID` 真发消息、逐轮打印本轮
  那本账（`/lens` 看原文、`/topic KIND` 锁死类型、`/attitude` 验门槛、`/reroll` 重掷）。
  会话在 `_out/` 沙盒里跑，不写 `data/`。
- **记忆摘要单独注入**：更早聊天的摘要仍作为独立系统消息跟在系统提示词后，没有做成字段
  ——它是「前情」而不是「此刻注意到的事」，塞进视角会挤占预算。
- **字段权重是静态表**：不随坐标强度连续变化（「极高紧张度」不会让 `spar` 多给一条新闻）。
- **位置只挂在部分视角**：位置属于「处境」而非「人格」，`body` / `memory` / `showoff` 等
  刻意不给（聊身体和回忆时不需要知道邮编）；若实际对话里她「忘了自己在哪」，把它挂到该
  视角即可，不是机制缺陷。

## 7. 拓展用法

- **只覆盖一两张表**：世界包里放一份裁剪过的 `topics` JSON，只写想改的那几条类型也合法
  ——整表替换的是「这张表」，不是逐条合并，所以最小做法是把内置表导出后改完再放回去。
- **用内置表当基版**：导出「当前话题表」拿到的一定是完整 18 条（内置表 id 为 `default`），
  改完按 §10 的容器形状放回世界包即可，不需要手写全表。
- **`settings.json` 的 `world_stance`**：不改话题表也能整体挪动紧张度，让某些类型更容易 /
  更难出现——这是玩家侧唯一能调的聊天手感旋钮。

## 8. 参数表

<details>
<summary>预算、门槛与分组的全部常量（排查「为什么这条没进来」时展开）</summary>

| 常量 / 位置 | 值 | 作用 |
|---|---|---|
| 视角预算 `TopicKind.budget` | `240～820` | 每条类型各自不同，见 §4 |
| `GROUP_CAP` | `2` | 同组字段最多进几条 |
| `MIN_FIELD_CHARS` | 最小碎片 | 剩余空间低于它就停止塞 |
| `HIDDEN_INTRO_ATTITUDE` | `40` | secret 字段的好感门槛 |
| `WORLD_CONTEXT_LIMIT` | `1200` | 世界背景段落上限（行为包可追加） |
| 组名 | `self / body / life / world / private / place` | 同组限量的分组依据 |

</details>

## 9. 官方资源

内置话题表就是 §4 的 18 条类型，外加一个虚拟的无话题视角（只在还没起话题时使用）。没有
单独的「视角资源」——视角是类型的一部分，能替换的只有整张话题表。

## 10. 作者须知

<details>
<summary>改类型、加字段、换整表时要守的契约（出问题时先看这一节）</summary>

- **加字段**：先在字段注册表登记（含层级、分组、渲染器），再在需要的类型 `opens` 里挂上；
  漏注册在守卫里报 `unregistered`，不会静默丢弃。
- **`denies` 与 `opens` 不能自相矛盾**：同一字段既开又挡，结构校验直接拒绝。
- **secret 字段的两道门**：类型必须允许透露，且好感达标；只开 `disclosure` 不调门槛不会
  生效，反之亦然。
- **改整表**：容器是一份 JSON 数组，元素形状与导出格式一致，主文件不带后缀；校验不过会
  拒绝装载且不改动现有表，加载失败只回退内置表，不影响包内其它资源。
- **别在会话中途换表**：同一轮两次取表可能拿到不同内容；只在世界包加载时换。
- **导出再导入必须能原样往返**：带 `virtual` 的条目会被摘出来当兜底、不参与候选，所以整表
  往返不会丢条目，也不会把它塞进候选。
- **改完跑守卫**：`python tests/run_checks.py check_chat_topic_lens check_chat_topics
  check_chat_topic_selection check_chat_effects check_profile_text`。

</details>

## designs 目录

<details>
<summary>designs/ 全目录（wiki 地图）</summary>

**机制目录**

- **dungeon/**：[README](../../dungeon/README.md)（全景）·
  [script](../../dungeon/script.md)（章节与触发器字段）·
  [prompts](../../dungeon/prompts.md)（提示词与上下文）·
  [characters](../../dungeon/characters.md)（人物表与账本）·
  [voice](../../dungeon/voice.md)（对话语音）·
  [admission](../../dungeon/admission.md)（进入准入）·
  [scene](../../dungeon/scene.md)（地点与参照物）·
  [minigame](../../dungeon/minigame.md)（小游戏）·
  [components](../../dungeon/components.md)（显示组件）
- **character/**：[README](../README.md)（全景）·
  [evolution](../evolution.md)（介入度 / 深度 / 行动点）·
  [time](../time.md)（恢复结算 / 作息 / 导出）·
  [chat](README.md)（话题与好感 / 紧张度）·
  [lens](lens.md)（本页）
- **behaviors/**：[README](../../behaviors/README.md)（玩家向）·
  [dev-guide](../../behaviors/dev-guide.md)（行为包开发）· 钩子契约四篇
  （[logic](../../behaviors/hooks-logic.md) / [report](../../behaviors/hooks-report.md) /
  [character](../../behaviors/hooks-character.md) / [chat](../../behaviors/hooks-chat.md)）·
  [example-imperial](../../behaviors/example-imperial.md)（示例包）
- **world_packs/**：[README](../../world_packs/README.md)（玩家向：启用 / 切换 / 删除）·
  [author](../../world_packs/author.md)（制作与清单）

**单篇**

[地址系统](../../address_system.md) · [报告生成](../../report_selection.md) ·
[资源与包体系](../../resources.md) ·
[挑战包](../../challenges.md) ·
[剧本编辑器](../../scenario_editor.md) · [界面双模式与外观](../../ui_modes.md) ·
[身材剪影](../../body_preview.md) ·
[更新检查](../../update_check.md)

</details>
