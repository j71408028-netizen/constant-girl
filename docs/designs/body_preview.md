# 身材剪影

> **这一篇回答什么问题**：创建角色、调整身材预设时那张随参数实时变化的剪影图
> 是什么、按哪些比例参数画出来；它还有一个次要身份——没上传头像时的兜底头像。
> - **普通玩家**：看 **§1** 就知道它是怎么回事；调身材预设时查 **§2** 的参数清单。
> - **想改绘制效果的开发者**：看 **§3** 的实现说明。
>
> 相关页面：界面双模式与外观 [ui_modes.md](ui_modes.md)（挂件参数面板） ·
> 档案与角色卡导出 [character_time.md](character_time.md)。

## 1. 剪影是什么、什么时候出现

「剪影」是按她的身材比例参数画出的**正面少女剪影图**（PNG）。它首要的用途是
**把身材参数画给你看**：创建角色时（专业界面创建对话框）和挂件版参数面板调整
身材预设时，14 项比例参数每动一项，画出来的身形就跟着变——看着图调，比对着
数字盲调直观得多。

它还有一个次要身份：你还没给她上传头像时，剪影会顶上当头像用——创建角色和
载入角色时都有这层兜底，设置里的开关叫「身材预览头像」（键
`use_preview_image_as_avatar`）。

> 剪影**不是**角色头像：她真正的头像是你上传的图片——上传时的裁剪、之后的更换、
> 档案页里的形象展示，是另一套东西，不在这篇范围内。剪影只负责「按参数画出
> 身材」这一件事。

画剪影只看她的 `body_parts`（身材比例参数）和 `height`，与作息、新闻这些数据
完全无关。

## 2. 身材比例参数清单

共 14 项比例参数，都是相对身高的比例值，不是绝对尺寸。创建角色、编辑身材预设时，
每一项滑块的可调范围和步进如下：

<details>
<summary>14 项身材参数的含义、范围与步进（调身材预设时展开查）</summary>

| 参数 | 表示什么 | 可调范围 | 步进 |
|---|---|---|---|
| 步长 | 一步跨出的长度 | `0.50～1.50` | `0.005` |
| 腿长 | 腿的长度 | `0.40～0.60` | `0.005` |
| 臂长 | 手臂的长度 | `0.30～0.50` | `0.005` |
| 胸宽 | 胸部的宽度 | `0.20～0.40` | `0.005` |
| 脚长 | 脚的长度 | `0.10～0.20` | `0.005` |
| 脚踝高度 | 脚踝离地的高度 | `0.03～0.16` | `0.005` |
| 膝盖高度 | 膝盖离地的高度 | `0.20～0.35` | `0.005` |
| 大腿直径 | 大腿的粗细 | `0.10～0.20` | `0.005` |
| 小臂直径 | 小臂的粗细 | `0.03～0.08` | `0.005` |
| 手掌长度 | 手掌的长度 | `0.05～0.16` | `0.005` |
| 食指长度 | 食指的长度 | `0.02～0.09` | `0.005` |
| 食指直径 | 食指的粗细 | `0.002～0.020` | `0.0001` |
| 指缝宽度 | 相邻手指之间的缝宽 | `0.0005～0.0100` | `0.00005` |
| 指纹宽度 | 指纹纹路的宽度 | `0.0001～0.0020` | `0.00001` |

</details>

## 3. 内部实现

- 绘制配方 `services/preview/__init__.py::BodyPreviewPainter` 只描述「画什么」，
  经 6 个图元原语（椭圆 / 多边形 / 线段等）输出，不依赖 tkinter；PIL 画布
  `BodyPreviewPilCanvas` 复刻 Tk 平滑样条的采样规则，线宽按设计宽等比放大。
- 成图常量：450×800、透明底、4 倍超采样后 Lanczos 缩回；暗色模式下对亮通道做
  0.15 亮度衰减（读 `core/appearance.py`）；配色是服务层字面量 `VIEW_*`（与主题
  token 逐值一致，避免反向依赖 UI）。入口 `render_preset_preview_image` 出预设
  预览，`render_body_preview_image / render_body_preview_to_file` 按角色身材
  成图。
- 专业界面创建对话框另有一份同款画法副本（差异仅暗色衰减）——改绘制配方要两处
  同步。

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
[角色演化](character_evolution.md) · [资源与包体系](resources.md) ·
[挑战包](challenges.md) ·
[剧本编辑器](scenario_editor.md) · [界面双模式与外观](ui_modes.md) ·
[角色的长期行为](character_time.md) · [身材剪影](body_preview.md)（本页） ·
[更新检查](update_check.md)

</details>
