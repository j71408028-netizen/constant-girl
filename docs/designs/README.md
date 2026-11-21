# designs/：玩家与资源开发者

> **这一组回答什么问题**：这套东西是**怎么设计的**——地标之间怎么算距离、角色怎么随
> 故事演化、资源包能覆盖到什么程度、小游戏怎么接入。玩家想理解系统怎么运作、资源
> 开发者想扩展它，读的是**同一份知识**，所以这两类读者共用本目录。

## 成员

机制 = 目录：目录的 `README.md` 是全景页，细节页从那里进入；未拆分的机制仍是单篇。

| 机制 | 入口 | 主要读者 |
|---|---|---|
| 地址系统 | [address_system.md](address_system.md) | 玩家 + 资源开发者（地标 / 描述风格作者） |
| 报告生成 | [report_selection.md](report_selection.md) | 玩家 + 资源开发者（地标 / 描述风格作者） |
| 副本设计机制 | [dungeon/](dungeon/README.md) | 核心开发者 + 副本方案作者（章节与触发器 / 提示词 / 人物 / 语音 / 准入 / 地点） |
| 角色 | [character/](character/README.md) | 玩家 + 核心开发者 + 行为包 / 话题作者（演化 [evolution.md](character/evolution.md) / 长期行为 [time.md](character/time.md) / 聊天 [chat/](character/chat/README.md)；信息视角细节在 [lens.md](character/chat/lens.md)） |
| 行为包 | [behaviors/](behaviors/README.md) | 玩家 + 世界包 / 行为包作者 |
| 资源与包体系 | [resources.md](resources.md)（挑战包另见 [challenges.md](challenges.md)） | 资源作者 |
| 世界包 | [world_packs/](world_packs/README.md)（制作另见 [author.md](world_packs/author.md)） | 玩家 + 资源作者 |
| 剧本编辑器 | [scenario_editor.md](scenario_editor.md) | 副本方案作者 + 想懂编排机制的人 |
| 界面双模式与外观 | [ui_modes.md](ui_modes.md) | 玩家 + 核心开发者 + 界面改造者 |
| 身材剪影 | [body_preview.md](body_preview.md) | 玩家 + 核心开发者 |
| 更新检查 | [update_check.md](update_check.md) | 玩家 |

跨机制的界面用词（副本、观测等级、耦合等级、性格、资源与行动）见
`docs/terminology.md`；写界面文案、提示词或玩家文档前先查这一页。

## 按任务找入口

| 想做什么 | 从哪读 |
|---|---|
| 理解或调整**报告里地标与描述的选取 / 配对** | [report_selection.md](report_selection.md) |
| 给**地标 / 描述风格**申领、注册地址 | [address_system.md](address_system.md)（§6 注册、§7 申领、§10 格式与组合、§3 配对与距离） |
| 给**副本章节**写地点地址、给副本写参照物地标（尺寸换算用） | [dungeon/scene.md](dungeon/scene.md) |
| 写**副本方案**（章节 / 触发器字段、条件与动作、校验） | 从 [dungeon/README.md](dungeon/README.md) 进，正文在 [dungeon/script.md](dungeon/script.md) |
| 理解或调整**副本里的人物表 / 临时称呼 / 在场与简报** | [dungeon/characters.md](dungeon/characters.md)（含字段说明） |
| 改**AI 每段看到什么 / 怎么记住前情**（初始提示、章节备注、上下文窗口、细节注入） | [dungeon/prompts.md](dungeon/prompts.md) |
| 配置或排查**副本对话语音**（音色 / 语速 / 端点与代理） | [dungeon/voice.md](dungeon/voice.md) |
| 给**副本方案**声明进入条件（入口地址 / 距离 / 身高） | [dungeon/admission.md](dungeon/admission.md) |
| 改**角色数值演化** | 先读 [character/evolution.md](character/evolution.md)（全景），再看可覆盖的代码入口 [behaviors/dev-guide.md](behaviors/dev-guide.md) |
| 调整**角色聊天**的话题类型、好感/紧张度/状态的手感 | [character/chat/README.md](character/chat/README.md)（实现细节在 `docs/dev/chat_delivery.md`） |
| 调整**某类话题下 AI 知道什么 / 不知道什么** | [character/chat/lens.md](character/chat/lens.md)（改完用 `python developer_tools/lens_preview.py` 静态看账，或 `chat_session_preview.py` 边聊边看） |
| **扩展程序行为**而不改主程序 | [behaviors/README.md](behaviors/README.md)（玩家向）→ [behaviors/dev-guide.md](behaviors/dev-guide.md) |
| 理解**资源类型 / 信封 / 索引 / 同步**，或新增一类资源 | [resources.md](resources.md) |
| 做**挑战包**（加密、秘钥、创建 / 导入 / 启动） | [challenges.md](challenges.md) |
| 拿到 / 启用 / 删除**世界包**，弄懂启用期间素材从哪来 | [world_packs/README.md](world_packs/README.md) |
| 打包 / 分享**世界包**，写清单或排查「启用后没生效」 | [world_packs/author.md](world_packs/author.md) |
| 做**小游戏**（副本触发器 + 作者 API） | [dungeon/minigame.md](dungeon/minigame.md) |
| 用**剧本编辑器**（页签 / 编排图 / 校验条 / 素材导入） | [scenario_editor.md](scenario_editor.md) |
| 写**副本显示组件**（钩子 / 参数 / slot 代管区） | [dungeon/components.md](dungeon/components.md) |
| 理解**专业 / 挂件双界面**、主题配色或字体解析 | [ui_modes.md](ui_modes.md) |
| 理解**恢复结算 / 作息 / 近况新闻 / 档案与角色卡导出** | [character/time.md](character/time.md) |
| 理解**创建 / 调身材预设时的剪影预览图**（兼作无头像兜底） | [body_preview.md](body_preview.md) |
| **检查更新**（入口 / 结果窗口 / 会不会自动查） | [update_check.md](update_check.md) |

## 本组文档的写法：机制 = 目录

- 单篇超过约 300 行，或一篇内出现 3 种以上不同查表任务（找流程 / 查签名 / 查格式规范）
  → 拆为目录；
- 目录的 `README.md` 独立成页，保持线性叙事（玩家 / 使用者读到这页为止）；细节页
  才允许查表型，从全景页链接进入；
- 目录有两种：单一机制长出来的**机制目录**（`chat/`、`world_packs/`、`behaviors/`，
  README 是该机制的全景页）；一组相关机制的**域目录**（`dungeon/`、`character/`，
  README 讲这组机制怎么配合、各自从哪进）；
- 未拆分的机制仍是单篇，按下方「叙述骨架与代码引用」组织（见
  [dungeon/components.md](dungeon/components.md)）；
- 拆分提交为纯移动（利于 git rename 跟踪），措辞修订另起提交；
- 链接指文件不指标题（锚点跨生成器不稳定），跨组引用用相对链接，别复制正文。

### 叙述骨架与代码引用

机制叙述页按统一骨架组织，页面之间结构可预期；「清单即产品」的页（字段索引、
钩子契约）允许合并标注，不强行拆节——但**简介路由与 designs 目录尾节照旧要有**，
只是把「参数表 / 作者须知」并进字段表本身，不再另起空节。骨架自上而下：

> **这一篇回答什么问题**（简介：各类读者从哪节进 + 顶部直接挂 2-3 个最重要相关页，
> 行内链接）→ 机制各节 → 内部实现（生命周期 / 容错 / 进程级事实等主线外细节集中
> 一节）→ 拓展用法（界面上没有说明、但实际受支持，或玩家 / 作者巧思可以充当的
> 用法）→ 参数表（作者要写的声明格式与全值折叠表）→ 官方资源（内置清单概览）→
> 作者须知（钩子 / 字段 / 守卫契约，需要深读的作者最后进）→ designs 目录（无编号
> 尾节）。

- 页面标题标注读者类型，两种写法分开处理：面向**作者**的页（作者要照着写声明 /
  契约的工具文档）标题带「（面向作者）」；其余页写成**游玩说明文**——主线讲玩家 /
  使用者「什么时候经历什么、能做什么」，实现代码只作为参考文献引用，不做实现代码
  的简要版交代。
- 机制叙述主语是程序 / 窗口 / 方案，不是模块；「什么时候发生什么」句式。
- 实现上的手法、便利与限定（独立子进程、轮询探测、复用、容错口径等）**不前置**：
  先讲读者会看到的行为与规则（系统浅色 / 深色各用哪套配色、启动全程先看到什么），
  再补充实现手法与原因。
- 拓展用法只收**用户数据层**的用法（方案 / 资源目录、导出文件、环境变量、外部
  组件包目录等）：改源码、改 `assets/` 等程序内部的做法不收——发行版本不暴露
  这些，做了也容易出错、无法跟随更新。
- 实现定位只在读者正需要进代码的点上引用，每节 ≤2 处，写短的 `路径.py::符号`；
  **页尾「文件 / 函数索引」废除**——一个功能涉及的文件太多，索引等于白放。
- 主线与细节分层：大体机制走正文叙述；两三行的推论 / 边界用 `>` 引用块；查表与
  实现细节（≥10 行的表、守卫细项、机制推论清单）用 `<details><summary>` 折叠，
  summary 必须写明「什么人来查什么」。
- 精确数值（阈值 / 公式 / 枚举值 / 键位表）与作者要写进配置的字面、要创建的
  文件名、可执行命令保留在叙述里，不稀释。
- 页尾统一挂 designs 目录：`<details>` 折叠的全目录地图，组内每页都有链接；
  各子目录相对路径不同，改完跑 `python tests/check_docs_links.py`。

### 改完怎么立刻看效果

- 行为包 / 演化公式：`python developer_tools/evolution_dump.py`（见
  [character/evolution.md](character/evolution.md) §8）。
- 小游戏：`python tests/check_minigame.py`，真渲染见
  `python scripts/dungeon_autopilot.py --scene mini-game-py`。
- 各类开发者工具的入口见 `developer_tools/README.md`。

## 相关组

- 要在**副本里**用这些机制（章节 / 触发器 / 小游戏触发器）：副本子项目文档
  入口在 `docs/Dungeon/README.md`；副本设计机制收在本组 [dungeon/](dungeon/README.md)。
- 要改**程序本身**（分层、契约、提交规范）：程序开发文档入口在 `docs/dev/README.md`。
- 某个**特定风格**的创作工作流**不在本目录**（判据 4）——风格所需的补充步骤随风格
  自身的特质不同，写下来只对一种风格成立，因此该由风格自身的维护约定承担。
