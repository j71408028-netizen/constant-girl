# 角色：她身上的数据与三份机制

> **这一目录回答什么问题**：「她」——常驻的那个角色——身上有哪些数据、数值怎么演化、
> 关掉程序的时光怎么结算、聊天怎么运转。读者是玩家 + 核心开发者 + 行为包 / 话题作者。
> **划界**：副本方案里「一局的人物表与运行期账本」（主角称呼、`cast[]` 配角、在场与
> 揭示）是另一套系统，见 [../dungeon/characters.md](../dungeon/characters.md)——她本人
> 跨方案复用，不属于任何方案；创建 / 调身材预设时的剪影预览是界面机制，见
> [../body_preview.md](../body_preview.md)。
>
> 术语基准：「潜质 / 深度 / 介入度」三层，权威口径见 `docs/terminology.md` 与
> [evolution.md](evolution.md) 开头的三层术语说明。

| 文档 | 回答什么问题 |
|---|---|
| [evolution.md](evolution.md) | **数值演化**：介入度 / 破坏性为什么漂、性格三参数怎么调制、行动点怎么花怎么回、贴边为什么不失控 |
| [time.md](time.md) | **长期行为**：关掉程序期间的恢复结算、作息节律怎么学出来、近况新闻、档案与角色卡两种导出 |
| [chat/README.md](chat/README.md) | **聊天**：按玩家身份分的线程、好感 / 紧张度 / 状态三轴、话题类型与世界效果；信息视角细节在 [chat/lens.md](chat/lens.md) |

## 她身上的数据分两层存储

- **创建设定（角色卡）**：名字 / 昵称 / 原始身高 / 生日 / 标签 / 简介 / 性格数据 /
  身材预设 / 头像 / 出身世界，创建时定下来；跨存档搬运靠角色卡导出
  （[time.md](time.md) §5）。性格数据在创建时派生成「出身烙印」参数，伴随角色终身
  （默认值登记在 [time.md](time.md) §1 的折叠表）。
- **运行档案（`data/archives/<角色id>/`）**：游玩产生的状态——演化记录、当前
  介入度 / 破坏性与行动点、伤亡、离线明细、报告与回放、形象图集、空间档案。整份档案
  可以导出成单文件 HTML 页（[time.md](time.md) §4）。

作息表不单独存文件，每次用到时从演化记录现场统计（[time.md](time.md) §2）。

## 三份机制怎么分工

- **evolution.md 定数值怎么动**：五条路径（生成报告、进副本、地标切换、闲置回落、
  载入结账）共用 0.5~4.5 的统一边界，敏感值 / 重力 / 个性强度决定方向与速率；
- **time.md 定她不在场时发生什么**：载入那一刻一次结清行动点、坐标与伤亡；作息与
  近况新闻都从她自己的经历里长出来；
- **chat/ 定她说什么**：线程按玩家身份隔离，三轴筛话题，回复后最多执行一个世界效果。

想调数值手感从 [evolution.md](evolution.md) §8 进；排查「关掉的日子算得对不对」从
[time.md](time.md) §1 进；给聊天加话题 / 改世界态势从 [chat/README.md](chat/README.md)
§10 进。

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
- **character/**：[README](README.md)（本页）·
  [evolution](evolution.md)（介入度 / 深度 / 行动点）·
  [time](time.md)（恢复结算 / 作息 / 导出）·
  [chat](chat/README.md)（话题与好感 / 紧张度）·
  [lens](chat/lens.md)（信息视角细节）
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
