# 副本对话语音（方案级 `voice`，面向作者）

> **这一篇回答什么问题**：方案怎么配朗读、谁念什么句子、用什么嗓子、合成走什么
> 底座、响度怎么分层，以及章节级物理效果怎么接线。**配语音的方案作者**从 §1 /
> §2 进；**排查不出声**的玩家从 §3 / §4 进；想要章节级音效效果的从 §5 进。
> 直接相关页：章节级 `voice_fx` 的字段与预设 [script.md](script.md) §2.4 ·
> 音色解析顺序（含配角账本命中）[characters.md](characters.md) §6 ·
> 编辑器角色页表单 [../scenario_editor.md](../scenario_editor.md)。

## 1. 谁会被念出来

方案的 `speaker_notation` 二选一：`tagged` 会给每句对话标 `@说话人@`（见 Dungeon
窗口文档「说话人写法」），`literary` 用自由文学写法、正文不带标记。**只有带结构化
`speaker` 的台词会念出来**——`tagged` 的对话句有、叙述句与整个 `literary` 方案
没有；语音通道本身与耦合等级无关。

配置在编辑器的**「角色」页**：音色按角色分栏（她的音色 / 主角音色 / 其他角色音色
池），总开关与语速、档位、预听在页首的语音条；改动即自动保存。谁用哪把嗓子按
本局角色名 / 昵称认（解析顺序含配角账本命中，见 [characters.md](characters.md)
§6）。

## 2. 方案字段（`dungeon/schema.py::VOICE_FIELDS`）

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | bool | `true` | 本方案是否朗读；此外还要过玩家侧的**语音总线**（§4，拧到 0 即静音） |
| `voice_her` | str | `zh-CN-XiaoxiaoNeural` | 她的音色（按本局角色名 / 昵称认） |
| `voice_protagonist` | str | `zh-CN-YunxiNeural` | 主角音色（按方案 `protagonist_title`，留空按「主角」认） |
| `voice_other` | list | 三把备用嗓 | 其余角色的音色池，**按名字稳定映射**：同一个配角每局都是同一把嗓子 |
| `rate` | str | `+0%` | 语速（`+10%` / `-20%`；非法写法回退常速） |
| `level` | int | `3` | 音量**档位** 0-4（`0` 静音 / `1` 很轻 / `2` 轻 / `3` 中 / `4` 响；越界夹到 `MAX_VOICE_LEVEL`）。旧版 0-100 `volume` 仍能读入，折算后只写 `level`。语音是混音 0 dB 参考，同档位下比音乐高 6 dB（§4） |

## 3. 合成底座：edge-tts，可选依赖、失败不拖垮一局

合成走 **edge-tts**（微软神经网络语音，**需要联网**，`pip install edge-tts`），
是**可选依赖**：没装或网络失败只在日志里留一条，不出声不该拖垮一局副本——与
背景音乐的降级策略一致。播放复用 `dungeon/audio` 的后端（MCI → pygame → 静音
占位）。

> **失败要说清原因**：合成失败按类记在 `speech.last_synth_error()`——403 / 401
> / 超时 / 时钟 / SOCKS / 代理连不上 / 地址非法。副本的一次性告警与编辑器**预听**
> 都复用它，不再笼统报「网络不可达 / 音色名有误」。

<details>
<summary>合成端点 403 的来龙去脉与本地回退（排查合成失败时展开查）</summary>

2026-10 微软把朗读合成从旧主机 `speech.platform.bing.com` 迁到
`api.msedgeservices.com`，**全球分批铺开**（先是欧洲，10-12 起北美也中招），铺到
哪旧主机就在哪回 **HTTP 403**——所以这与「是不是国区」无关，也不是代码问题：
`edge-tts` 已是最新（7.2.8），时钟与服务端一致，`Sec-MS-GEC-Version` 换
143/146/150/155/160/170 都照样 403。上游修法见 edge-tts **PR #491**（7.2.8 尚未
并入）：**新主机沿用同一个旧令牌，只是改挂 `Ocp-Apim-Subscription-Key`**。本模块
在本地补齐了这一步：

**端点回退** `dungeon/audio/speech.py::_endpoint_candidates`：装的那版若仍指向
旧主机，就先生成新主机候选、再挂旧主机作回退（新主机成 403 就自动落回旧主机）；
**已装版本哪天修好了（不再指向旧主机）就不插手**，不去覆盖人家的正确值。成功过
的端点记在 `_working_wss_url`，下次优先复用。改写 `edge_tts` 模块级 `WSS_URL`
是有状态的，所以「换端点 → 合成」整段由 `_endpoint_lock` 串行化。

</details>

<details>
<summary>语音代理的接线与三个坑（配代理排查不出声时展开查）</summary>

**代理由 `speech.set_proxy()` / `resolve_proxy()` 决定**——它委托给
**`core/netproxy`**（语音合成与 AI 文本生成**共用同一份**，设置页就一个「网络
代理」框）。优先级：`settings["net_proxy"]` ＞ 语音专用环境变量
`DUNGEON_TTS_PROXY` / `EDGE_TTS_PROXY` ＞ 通用环境变量 `DUNGEON_NET_PROXY` /
`HTTPS_PROXY` / `HTTP_PROXY` ＞ 直连。

三个容易踩的点：**① 必须显式传给 `edge_tts.Communicate(proxy=...)`**——aiohttp
的 `trust_env` 只对 `http(s)://` 生效，对 `wss://` **不认环境变量**，光挂环境
变量代理，WebSocket 握手仍会走直连；② 没配代理时不传这个关键字（免得老版本
`TypeError`）；③ 代理地址先过 `normalize_proxy()`——缺 scheme 补 `http://`
（否则 aiohttp 抛 `InvalidURL`），**SOCKS 直接拒绝**（不装 `aiohttp-socks` 走
不了，请填代理软件的 HTTP/mixed 端口）。

装配点三处：`app/shell.py`（启动 / 切界面）、
`dungeon/window/base.py::_configure_voice`（**副本跑在独立子进程里，主进程设的
代理带不过来，必须在子进程再设一次**）、设置页保存后立即生效。

</details>

## 4. 音量总线（`dungeon/audio/buses.py`）

副本所有发声的音量单一真相源：三条内容总线挂一条总控
（`master ─ music / voice / sfx`），三层各管各的单位：

| 层 | 谁在用 | 单位 | 范围 |
|---|---|---|---|
| 作者侧「档位」 | 章节 `bgm.level` / 方案 `voice.level` | 档 | `0-4`（静音 / 很轻 / 轻 / 中 / 响） |
| 玩家侧「滑条」 | 设置页（`audio_levels`，副本独占设置） | 电平 | `0-100`（归一后用） |
| 内部「增益」 | 播放后端 | dB | 换算到增益，`-80` 以下视为静音 |

**档位怎么变成响度**：`档位 dB + 总线锚点 dB`——档位表 {0: 静音, 1: −18, 2: −12,
3: −6, 4: 0}（上限 0 dB 是数字满幅，「中」天然比满幅低 6 dB）；锚点 {总控 0,
音乐 −6, 语音 0, 音效 −3}——混音分层落在锚点一张表上，同样的档位音乐天然比语音
轻 6 dB（§2 `level` 行的出处）。

设置页的四条总线滑条（副本独占设置 `audio_levels`，存
`data/user/dungeon_settings.json`）在方案档位之外再乘一次，副本窗口开局时按副本
设置装配总线；播放路径不必逐处传参——增益缺省取实时总线电平，滑条一改三条内容
总线同时跟着变。未接管进程回退恒 100（不衰减）。于是「她说什么」的响度 =
**方案档位 × 总线电平 × 总控电平**。

> **「不想听语音」就是语音电平拧到 0**——原先独立总开关
> `settings["dungeon_voice_enabled"]` 已撤掉。这一档是**真静音**：档位 × 语音电平
> × 总控归零时直接返回，**连合成都不做**（不联网、不占工作线程、离线也不会刷
> 告警），所以「调到 0」等价于旧的「关掉开关」。旧设置文件里残留的键在
> `persistence/settings_repo.py::load` 迁移：关过的折算成语音电平 0，然后删键。

## 5. 章节级物理效果（`voice_fx`）

音色是**谁在说话**（方案级 `voice`）；效果是**她在这个空间里说话会是什么声音**
（章节级 `voice_fx`，她 / 其他人两档）——字段、预设与两级引擎见
[script.md](script.md) §2.4。效果从属于朗读：方案关掉（§2 `enabled=False`）或
玩家把语音电平拧到 0（§4），都是一句都不念，效果自然也不生效。

编辑器两处都能预听：章节对话框两档各一个「预听」按钮 + 只读「响度 ±dB」标签；
方案编辑器的音色行可试听音色与档位——预听与副本用同一套合成 + 效果
（`dungeon/audio/preview.py::VoicePreview`，零 UI 依赖）。

<details>
<summary>voice_fx 接线速查（改效果链或排查效果不生效时展开查）</summary>

| 环节 | 位置 |
|---|---|
| 换章时切效果（没配 = 清空） | `dungeon/window/triggers.py::_apply_chapter_voice_fx`；当前生效值挂在 `dungeon/window/base.py::current_voice_fx` |
| 按说话人分档 | `dungeon/audio/speech.py::_speak_job`（她 → `her` 档，否则 `others`） |
| 施加效果 | 播放前按预设走 `dungeon/audio/voice_fx.py::render_wav`（离线渲染）/ `PlaybackFx`（分拍 + 音量包络）/ 原声 |
| 响度对齐 | 预设声明的 dB × 渲染链末尾按实测 RMS 对齐，再守峰值；播放侧按 `playback_trim` 衰减 |
| 能力与降级 | `voice_fx.has_effect / decoder_name / playback_plan`；不可用时每个预设只提示一次 |
| 回放复现 | 章节进入只写 `kind: "chapter"` 一条记录，带着当时的 `voice_fx`；对话句的说话人靠步进记录的 `display_text` 还原（净文本里没有 `@说话人@`，缺这个字段就不念） |

</details>

## 6. 内部实现

- **线程模型**沿用 `dungeon/audio`：唯一一条后台线程串行处理「合成 → 播放」，
  `speak()` 只入队就返回，**新台词打断旧台词**（翻页时不该念上一页的），超长
  台词（300 字）跳过，会话收尾收工并清掉临时音频。
- **触发与装配时机**：显示单元定稿时触发朗读
  （`dungeon/window/ui.py::_speak_item`，叙述句无 `speaker` 直接返回）；音色装配
  在会话进入与回放各做一次（`dungeon/window/base.py::_configure_voice`）。

<details>
<summary>守卫（改语音链路前展开看）</summary>

`python tests/check_audio_chain.py`：说话人分音色 / 队列 / 两档效果 / 三条引擎
路径 / 降级 / BGM 缺坏文件收尾（假合成器 + 替身后端，不出声不联网）。

</details>

## 7. 拓展用法

本节收录界面上没有说明、但程序实际支持的用法：

- **语音专用环境变量**：`DUNGEON_TTS_PROXY` / `EDGE_TTS_PROXY` 可以不经设置页给
  语音合成单独指代理，优先级介于设置项与通用环境变量之间（§3 的优先级表）——
  适合临时排查「只有语音不通」的场景。

## designs 目录

<details>
<summary>designs/ 全目录（wiki 地图）</summary>

**机制目录**

- **dungeon/**：[README](README.md)（全景）· [script](script.md)（章节与触发器字段）·
  [characters](characters.md)（人物表与账本）· [voice](voice.md)（对话语音，本页）·
  [admission](admission.md)（进入准入）· [scene](scene.md)（地点与参照物）·
  [minigame](minigame.md)（小游戏）· [components](components.md)（显示组件）
- **chat/**：[README](../chat/README.md)（话题与好感 / 紧张度）·
  [lens](../chat/lens.md)（信息视角细节）
- **behaviors/**：[README](../behaviors/README.md)（玩家向）·
  [dev-guide](../behaviors/dev-guide.md)（行为包开发）· 钩子契约四篇
  （[logic](../behaviors/hooks-logic.md) / [report](../behaviors/hooks-report.md) /
  [character](../behaviors/hooks-character.md) / [chat](../behaviors/hooks-chat.md)）·
  [example-imperial](../behaviors/example-imperial.md)（示例包）

**单篇**

[地址系统](../address_system.md) · [报告生成](../report_selection.md) ·
[角色演化](../character_evolution.md) · [资源与包体系](../resources.md) ·
[挑战包](../challenges.md) · [世界包](../world_packs.md) ·
[剧本编辑器](../scenario_editor.md) · [界面双模式与外观](../ui_modes.md) ·
[角色的长期行为](../character_time.md) · [身材剪影](../body_preview.md) ·
[更新检查](../update_check.md)

</details>
