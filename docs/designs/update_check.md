# 更新检查

> **这一篇回答什么问题**：程序怎么查新版本、结果怎么给你、会不会自动检查。
> - **普通玩家**：看 **§1** 就够用。
> - **想动更新相关代码的开发者**：看 **§2** 的实现说明。
>
> 相关页面：界面双模式与外观 [ui_modes.md](ui_modes.md) ·
> 运行时包里「检查更新」启动器的命名契约见 `docs/release.md`。

## 1. 怎么查更新

程序不会自己查更新——启动时不查、不后台轮询、也没有设置键，只有你主动触发才会
发网络请求。两个入口任选：

- **运行时包里的「检查更新」启动器**：双击即可（文件名随平台不同，命名契约见
  `docs/release.md`）；
- **维护子命令** `python main.py check-update`（命中维护子命令时主程序不会启动）。

结果会弹一个小窗：已是最新，或发现新版本（附「打开发布页」按钮）。目前没有自动
安装，到发布页下载新版本、手动覆盖即可。

## 2. 内部实现

- 取数走 GitHub Releases 的 latest API，User-Agent `constant-girl/<APP_VERSION>`，
  超时 10 秒（`services/update_check.py`）。
- 版本号解析支持 `v` 前缀与预发布后缀，预发布序 alpha < beta < rc < 正式；维护
  子命令由 `app/maintenance.py::dispatch` 分发，命中后主程序不启动。
- 结果窗口用纯 tk 实现，不依赖控制台，打包版的 pythonw 环境可用；`apply-update`
  目前只是占位提示，不会自动安装。

## designs 目录

<details>
<summary>designs/ 全目录（wiki 地图）</summary>

**机制目录**

- **dungeon/**：[README](dungeon/README.md)（全景）·
  [script](dungeon/script.md)（章节与触发器字段）·
  [prompts](dungeon/prompts.md)（提示词与上下文）·
  [characters](dungeon/characters.md)（人物表与账本）·
  [voice](dungeon/voice.md)（对话语音）·
  [admission](dungeon/admission.md)（进入准入）·
  [scene](dungeon/scene.md)（地点与参照物）·
  [minigame](dungeon/minigame.md)（小游戏）·
  [components](dungeon/components.md)（显示组件）
- **character/**：[README](character/README.md)（全景）·
  [evolution](character/evolution.md)（介入度 / 深度 / 行动点）·
  [time](character/time.md)（恢复结算 / 作息 / 导出）·
  [chat](character/chat/README.md)（话题与好感 / 紧张度）·
  [lens](character/chat/lens.md)（信息视角细节）
- **behaviors/**：[README](behaviors/README.md)（玩家向）·
  [dev-guide](behaviors/dev-guide.md)（行为包开发）· 钩子契约四篇
  （[logic](behaviors/hooks-logic.md) / [report](behaviors/hooks-report.md) /
  [character](behaviors/hooks-character.md) / [chat](behaviors/hooks-chat.md)）·
  [example-imperial](behaviors/example-imperial.md)（示例包）
- **world_packs/**：[README](world_packs/README.md)（玩家向：启用 / 切换 / 删除）·
  [author](world_packs/author.md)（制作与清单）

**单篇**

[地址系统](address_system.md) · [报告生成](report_selection.md) ·
[资源与包体系](resources.md) ·
[挑战包](challenges.md) ·
[剧本编辑器](scenario_editor.md) · [界面双模式与外观](ui_modes.md) ·
[身材剪影](body_preview.md) ·
[更新检查](update_check.md)（本页）

</details>
