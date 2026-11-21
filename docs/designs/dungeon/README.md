# 副本（Dungeon）设计机制

> 这一目录收编副本侧的**设计机制**文档：方案怎么写、运行期怎么保证「谁是谁、谁在场、
> 怎么不变」。读者是核心开发者 + 副本方案作者。
> 副本子项目的**开发文档**（架构分层、窗口运行时、宿主边界、历史档案）在
> `docs/Dungeon/`（入口 `README.md`）——按本组「不外指」的约定，那边只以
> 纯文本路径出现，不放链接。

| 文档 | 回答什么问题 |
|---|---|
| [script.md](script.md) | 方案配置里**章节与触发器**的字段索引（数据模型）：字段怎么写、条件键与动作有哪些、校验报什么 |
| [prompts.md](prompts.md) | **AI 每段看到什么**：系统提示与用户提示各装什么、历史窗口与剧情压缩、人物 / 细节 / 尺度怎么注入、选项 / 结局等副产物调用 |
| [characters.md](characters.md) | 人物表字段（主角 / `cast[]` / `intro_as`）、注入规则与运行期角色账本：谁在场、身份揭示与合并、人物简报 |
| [voice.md](voice.md) | 方案对话语音：音色字段、合成底座（端点 / 代理 / 失败原因）、音量总线与章节物理效果接线 |
| [admission.md](admission.md) | 方案进入准入：入口地址、距离与身高区间的字段与判定口径 |
| [scene.md](scene.md) | 副本内地点与参照物：章节地址、地标候选池、尺寸换算与出口传送 |
| [minigame.md](minigame.md) | 小游戏触发器：运行时、包格式与作者 API（小游戏作者） |
| [components.md](components.md) | 显示组件：钩子契约、参数声明与夹取、注册与加载链、slot 代管区、窗口级浮层（组件作者） |

## 玩法结构的一条主线

- **script.md 定结构**：章节描述「身处其中时的环境」，触发器是唯一的流程驱动者；
- **prompts.md 定 AI 看到什么**：每段收到哪些文字、哪些设定会随剧情滑出窗口——人物的
  状态投影与「谁在场」也在这一层拼装；
- **characters.md 定人物**：人物表是初始设定，运行期账本持有状态，提示词每段投影
  「此刻谁在场」；
- **voice.md / scene.md / admission.md 是三个外围机制**：朗读与空间效果、章节地点与
  尺寸换算、以及进入前的准入判定；
- **components.md 定窗口版式**：方案声明显示组件，文本主组件用 slot 代管区给
  状态栏 / 过程日志留位。

写方案从 [script.md](script.md) 进；只关心角色就先读 [characters.md](characters.md)；
想让 AI 记住某段设定、或排查「它怎么忘了」，从 [prompts.md](prompts.md) 进。

## designs 目录

<details>
<summary>designs/ 全目录（wiki 地图）</summary>

**机制目录**

- **dungeon/**：[README](README.md)（本页）·
  [script](script.md)（章节与触发器字段）·
  [prompts](prompts.md)（提示词与上下文）·
  [characters](characters.md)（人物表与账本）·
  [voice](voice.md)（对话语音）·
  [admission](admission.md)（进入准入）·
  [scene](scene.md)（地点与参照物）·
  [minigame](minigame.md)（小游戏）·
  [components](components.md)（显示组件）
- **chat/**：[README](../chat/README.md)（话题与好感 / 紧张度）·
  [lens](../chat/lens.md)（信息视角细节）
- **behaviors/**：[README](../behaviors/README.md)（玩家向）·
  [dev-guide](../behaviors/dev-guide.md)（行为包开发）· 钩子契约四篇
  （[logic](../behaviors/hooks-logic.md) / [report](../behaviors/hooks-report.md) /
  [character](../behaviors/hooks-character.md) / [chat](../behaviors/hooks-chat.md)）·
  [example-imperial](../behaviors/example-imperial.md)（示例包）
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
