# 副本数据模型：章节与触发器（面向作者）

> **这一篇回答什么问题**：方案配置里「章节」和「触发器」能写哪些字段、默认值是什么、条件
> 怎么判、动作怎么执行、写错了校验器会说什么。script 只是这两者的非正式统称。
> - **正在写第一个方案**：先看 §1 分清章节与触发器，再照 §2 / §4 的字段表填。
> - **查某个条件键 / 动作的行为**：§5、§6、§7。
> - **保存被拦住、或副本起不来**：§9 的诊断表。
>
> 相关页面：编辑器界面怎么用 [scenario_editor.md](../scenario_editor.md) · 在场人物与人物表
> [characters.md](characters.md) · AI 每段看到什么（章节备注 / 地点 / 在场行怎么进提示词）
> [prompts.md](prompts.md) · 对话语音 [voice.md](voice.md) · 进入准入
> [admission.md](admission.md) · 地点与参照物 [scene.md](scene.md) · 小游戏
> [minigame.md](minigame.md)。

方案级配置里不属于章节 / 触发器的内容（对话语音、角色设定、进入准入）各有自己的机制文档，
本篇只留指针（§10–§12），不再展开。字段声明的单一真相源是 `dungeon/schema.py`；分层与运行时
数据流见 `docs/dungeon_engine.md`。

## 目录

| 节 | 内容 |
|---|---|
| §1 | 模型边界（章节 vs 触发器） |
| §2 | 章节字段索引 |
| §3 | 章节运行时规则 |
| §4 | 触发器字段索引 |
| §5 | 条件键索引 |
| §6 | 动作注册表 |
| §7 | 章节效果短暂覆盖 |
| §8 | 内部实现：编辑器由哪些窗口组成 |
| §9 | 校验、迁移与持久化 |
| §10 | 指针 → [对话语音](voice.md) |
| §11 | 指针 → [角色设定](characters.md) |
| §12 | 指针 → [进入准入](admission.md) |
| §13 | 场景地标清单（章节级，细则在 [副本内地点](scene.md)） |
| §14 | 拓展用法（手写配置能做什么编辑器不提供的事） |
| §15 | 官方资源（唯一入库的方案） |
| §16 | 作者须知（改写、迁移与自检） |

---

## 1. 模型边界

| 模型 | 职责 | 有没有条件字段 |
|---|---|---|
| **章节 Chapter** | 只描述「身处其中时的环境」：特定背景、持续演化修正、编辑器配色 | **没有** |
| **触发器 Trigger** | 唯一的流程驱动者：条件成立后执行一个动作；进入 / 离开章节也必须由它的「跳转章节」动作执行 | 有 |

背景切换与持续演化修正由**章节属性**承担，动作类型拆成「单步行为」与「章节跳转」两类。

## 2. 章节字段索引

来源：`schema.CHAPTER_FIELDS`（与 `chapters.normalize_chapter` 的产出一致，由 `check_scenario_schema.py` 守卫）。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `name` | str | — | 章节名（**必填**） |
| `color` | color | — | 编辑器自定义配色 `#RRGGBB`（浅色模式基准） |
| `start` | bool | `false` | 起始章节：开副本时自动进入，全局最多一个 |
| `ending` | bool | `false` | 结束章节，见 §3.2 |
| `note` | str | `""` | 备注；会以「当前章节：X（备注）」进提示词（怎么用见 [prompts.md](prompts.md) §10） |
| `cast` | list | — | 本章在场的人物（人物表的 id / 称呼 / 别称）；空 = 不写在场行，见 §11.3 |
| `place` | str | `""` | 地点展示名：窗口与提示词共用，留空不显示 |
| `address` | str | `""` | 取景地址（完整地址）：地点行与展示用，不参与结算 |
| `scene_landmarks` | list | `[]` | 本章在场的独特地标（名称 / 尺寸 / 维度），建议 ≤5 |
| `common_private_name` | str | `""` | 常见地标过滤私有名；空 = 不使用常见地标 |
| `exit_address` | str | `""` | 结局后角色落到的主世界地址；空 = 位置不变 |
| `max_paragraphs` | int | `99` | 节内最大段落数（`chapters.DEFAULT_MAX_PARAGRAPHS`） |
| `overflow_target` | str | `""` | 超限跳转目标；空串 = 离开章节（无章节） |
| `background` | dict | — | 章节背景，见 §2.1 |
| `bgm` | dict | — | 章节背景音乐，见 §2.2 |
| `voice_fx` | dict | — | 章节对话语音的**物理**效果（她 / 其他人两档），见 §2.4 |
| `fixed_text` | dict | — | **固定文本**：本章不走 AI 生成、按现成文本逐段推进，见 §2.5 |
| `sensitivity` | list | — | 身处本章节时持续生效、离开即失效（界面称**持续演化修正**），见 §2.3 |
| `intrusion_delta` | float | `0` | 结束结算：介入度增量（仅 `ending=true`） |
| `destruction_delta` | float | `0` | 结束结算：破坏性增量（仅 `ending=true`） |
| `casualty_step` | float | `0` | 结束结算：伤亡步进（仅 `ending=true`） |
| `action_points_refund` | int | `0` | 结束结算：行动点返还（仅 `ending=true`） |
| `custom_deltas` | dict | — | 结束结算：自定义属性增量（仅 `ending=true`） |
| `icon_path` | str | `""` | 结局图标（相对方案目录，仅 `ending=true`） |

### 2.1 `background`（`schema.BACKGROUND_FIELDS`）

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `image_path` | str | `""` | 背景图，相对副本目录 |
| `smooth_transition` | bool | `true` | 平滑切换 |
| `filter_effect` | enum | `None` | 滤镜键，取值来自 `dungeon/actions.py::VISUAL_FILTERS` |

### 2.2 `bgm`（`schema.BGM_FIELDS`）

进入章节时播放、离开即停的背景音乐；**没配就是不放**（`normalize_bgm` 把缺曲目的
配置归一成空 dict，也不会往每个章节摊一份只有默认值的空配置）。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `path` | str | `""` | 音频文件，相对方案目录（编辑器导入的落在 `<方案>/audio/`）；空串 = 本章节不放音乐 |
| `level` | int | `3` | 音量**档位** 0-4：`0` 静音 / `1` 很轻 / `2` 轻 / `3` 中 / `4` 响（越界夹到 `MAX_BGM_LEVEL`）。旧版 0-100 `volume` 仍能读入，按响度就近折算后**只写 `level`** |
| `loop` | bool | `true` | 循环播放 |
| `fade_seconds` | float | `1.5` | 切换时的淡入淡出秒数（`0` = 硬切） |

> 每档约 6 dB（`audio/buses.STEP_DB`），是人耳能明确分辨的步长。**分层落在总线
> 锚点上**：同一档位下音乐比语音低 6 dB（`audio/buses.BUS_ANCHOR_DB`——音乐锚点
> −6 dB、语音 0 dB），不必每章手填。缺省档是「中」（`3`）。**显式填的档位永远
> 优先**，缺省只决定「没填时听到什么」。档位 → 线性增益的唯一入口是
> `buses.step_gain` / `resolve_gain`（`step_db` 是这套换算的口径来源）。

播放由领域模块 `dungeon/audio/` 承担（**不依赖任何 UI 框架**）：Windows 走
`winmm` 的 MCI（零依赖，mp3/wav/wma 同一套），非 Windows 退到 pygame（装了才用），
两者都不可用时静音降级——**没有声音不该拖垮一局副本**。换曲走「旧曲淡出 → 关 →
新曲从 0 淡入」，同一首曲子重复进入只挪音量、不从头重放；所有设备操作都在一条
后台线程上串行执行，`play()` 只入队就返回，不占帧循环。

MCI 的坑：`play <alias> repeat` 只有 mpegvideo（mp3 等）认，waveaudio（wav）会把整条
命令判成非法——先试 `repeat`，失败就退回普通 play 并把该设备标为「手动续播」，
由工作线程轮询 `status mode` 在曲末从头再放（否则作者写的 `loop: true` 会在第一遍
播完后无声无息地静下去）。

### 2.3 `sensitivity[]` 持续演化修正（`schema.SENSITIVITY_FIELDS`）

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `attr` | str | — | 作用属性 |
| `strength` | float | `1.0` | 强度 |
| `objective` | float | `0.0` | 客观影响 |

演化修正量公式（触发器与章节共用 `dungeon.chapters.sensitivity_amount`；界面称
「演化修正量」）：

```
倍率 = 强度 ×（性格值 + 客观影响）
# 破坏性 → 性格重力；介入度 → 性格敏感值；其余属性 → 策略值
#   策略值 = 敏感 × (1 - 归一行动点数) + 重力 × 归一个性强度
#   归一行动点数 = 行动点数/100（因子不小于 0，未知时缺省 0.5）
#   归一个性强度 = skip_base_prob / 5
```

### 2.4 `voice_fx`（`schema.VOICE_FX_FIELDS` / `VOICE_FX_SLOT_FIELDS`）

章节对话语音的**物理**效果，两档分开配：**她（`her`）是巨大声源的物理后果，其他人
（`others`）是普通尺度声源在同一个环境里的后果**。预设名全是物理描述
（巨躯轰鸣、旷野回声、高空遥语），作用于尺度 / 距离 / 空间，不含情绪预设。分档由
`speech.SpeechDirector._speak_job` 按说话人认：她本人走 `her` 档，主角与其余角色走
`others` 档。

没配 = 本章节不加效果（`normalize_voice_fx` 返回空 dict，不摊默认配置）；
`normalize_chapter` 产出的 `voice_fx` 与 `CHAPTER_FIELDS` 的一致性由
`check_scenario_schema.py` 守卫。

```jsonc
"voice_fx": {
  "her":    {"preset": "open_valley",  "intensity": 80},
  "others": {"preset": "trembling_ground", "intensity": 70}
}
```

| 档 | 预设 | 物理含义 |
|---|---|---|
| 她 | `giant_boom` 巨躯轰鸣 | 巨大胸腔与肺量：低频厚重、轻微过载、空气随声缓抖 |
| 她 | `open_valley` 旷野回声 | 声音撞上山体与楼群折回：稀疏的长回声 |
| 她 | `far_above` 高空遥语 | 她在远处/高处：空气吸收吃掉高频、直达成变弱且晚到 |
| 她 | `shaking_air` 震空低鸣 | 庞大身躯搅动空气：低频隆隆裹着缓慢的抖动 |
| 她 | `deafening_close` 近距震耳 | 俯身贴近：过载、低频迅速膨胀、被压实 |
| 其他人 | `room_echo` 室内回响 | 普通嗓门在室内：墙面折回的短回声 |
| 其他人 | `valley_echo` 山谷折回 | 同一个旷野里的折回，比她的更弱更短 |
| 其他人 | `muffled_wall` 隔墙闷响 | 隔着一层建筑结构：高频被吃掉，只剩闷响 |
| 其他人 | `trembling_ground` 震地余波 | 她一动，地面与空气还在抖：台词裹在低频抖动里 |

字段（每档）：`preset`（预设键，非法或**不属于该档**都按「不加效果」处理并给诊断）、
`intensity`（0-100，缺省 60：把预设的基准参数按 `intensity/100` 缩放——**量**跟着变
（湿量、深度、增益、过载、拍数），**频率不跟着变**（抖得快慢由尺度决定））。
其余键是**手改 JSON 才用得上的高级参数**（编辑器只暴露预设 + 强度），取值范围单一
真相源在 `voice_fx.PARAM_RANGES`：`pre_delay` / `muffle_hz` / `low_gain_db` / `drive` /
`rumble_hz` / `rumble_level` / `tremor_hz` / `tremor_depth` / `echo_delay` / `echo_count` /
`echo_decay` / `echo_wet` / `loudness_db`，越界运行时夹取、校验给 warning。

**响度是声明量。** 每个预设在 `voice_fx.PRESETS` 里**声明**目标响度
（`Preset.loudness_db`：dB，相对干声的 RMS 变化），渲染链末尾按实测 RMS 把结果
拉回这个目标，`voice_fx.loudness_target(spec)` 是唯一入口：

- 全部声明值落在 `LOUDNESS_SPREAD_DB` = 9 dB（**= 1.5 个音量档**）的窗口里；每个
  预设的落点与声明值偏差 0.00 dB（`check_voice_fx_loudness.py` 守卫）。
- 声明值一律**不高于**该预设的自然响度，对齐永远是「降」；抬响度看峰值余量
  （`PEAK_CEILING`），余量不足时停在自然响度并在日志说明，**绝不削波**。
- RMS 按**直达声段**量（预延迟偏移 + 干声长度），回声尾巴不算。
- 想调某个效果的响度就改 `loudness_db`，**别靠堆 `drive` / `low_gain_db`**——响度
  会被这条规则拉回目标。作者也可以在档里显式写 `loudness_db` 覆盖声明值
  （夹取到 `LOUDNESS_RANGE`）。

**两级引擎（互不叠加，按本机能力择优）**，实测数字见 Dungeon 架构说明 §4.3：

| 引擎 | 依赖 | 能做什么 | 什么时候用 |
|---|---|---|---|
| 离线渲染（`render`） | 可选解码器 `miniaudio` **或** `soundfile`（+ numpy） | 全部环节：预延迟、空气吸收（低通）、躯体共振（低频增益）、次声隆隆、过载、缓抖、回声 | 有解码器时**一律走它**（采样级精确、跨平台一致） |
| 播放侧近似（`playback`） | **零依赖** | 稀疏延迟分拍 = 回声；音量包络 = 缓抖 | 没有解码器时（Windows MCI 同一文件多路实测可用） |
| 原声（`none`） | — | 无 | 没配效果；或预设纯渲染（`deafening_close`）而本机没解码器——此时日志留一条 |

> **音量烘进样本**：渲染路线产出 WAV，而 MCI 的 waveaudio 设备**不认 `setaudio`**
> （实测错误 261），播放层设不了音量，所以 `voice.level`（档位）与**效果响度**在渲染
> 时都直接换算成线性增益乘进样本。
> 播放侧路线的音量仍走 `track.set_volume`（mp3 设备支持，实测可用）。
> 顺带提醒：作者给 `bgm.path` 选了 `.wav` 时，Windows 上的 BGM 音量/淡入淡出同样
> 不生效（同一条驱动限制），选 `.mp3` 才正常。

> **两个引擎的响度锚点不同**：渲染路线能抬也能降（按声明值精确对齐）；播放侧近似
> **只能降**（峰值就是原声，`PlaybackFx` 抬不动），所以它按 `voice_fx.playback_trim`
> 衰减、目标 ≥ 0 时不衰减。于是两个引擎的**相对**摆幅一致（都是那 1.5 档），
> **绝对**锚点差一个常数——装了 vs 没装解码器的机器上，「巨躯轰鸣比高空遥语响多少」
> 一致，整体电平可能略有不同。

降级与其余能力一致：解码失败 / 缺 numpy / 缺音频后端都只是「少点效果」，
**不拖垮朗读**；效果渲染产物与合成音频同在会话临时目录里，收尾一起清掉。

### 2.5 `fixed_text`（`schema.FIXED_TEXT_FIELDS`，固定文本章节）

让某个章节**不走 AI 生成**、直接播放现成文本，像一般视觉小说那样。`fixed_text.path`
指向方案目录下的一个 `.txt`（编辑器导入的落在 `<方案>/texts/`）；**没配 = 本章照常由
AI 生成**（`normalize_fixed_text` 把缺路径的配置归一成空 dict，不摊默认配置）。
路径统一用正斜杠存，运行时按「方案目录 → 背景解析器候选」依次找文件。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `path` | str | `""` | 文本文件，相对方案目录；空串 = 本章不是固定文本章节 |

**文本怎么读**（解析器 `dungeon/script_text.py`，纯函数、无 IO / UI / AI）：

- **空行分段**：一个**逻辑段落** = 一次步进（一次点击推进），与 AI 段落同构——所以
  节内计数 / 总计数 / 间隔计数都以它为单位；段内换行合成同一段正文，再由内置分句器
  （`dungeon.splitter`）切成**显示段落**逐句上屏，与 AI 段落的呈现完全一致。
- **指令行**：逻辑段落的**首行**可以独占一行写一条 `[ ... ]` 指令（只解析、不上屏），
  同时声明*段落类型*与*演化方向*：

```text
[对话 +1]
她低下头，看着掌心里的你。

[互动 破坏性-1]
她的手掌轻轻落下，地面没有裂开。
```

段落类型取值是五种段落类型的中文短名（环境 / 分支 / 对话 / 互动 / 行动；`背景` 同
`环境`，英文键如 `dialog` 也认）。方向可以是 `+1` / `-1` / `0`（同时作用于介入度与
破坏性）、`介入度+1` / `破坏性-1`（只改其中一路）、或 `热度+1`（改 `evolution_attrs`
里声明的自定义属性）；类型与方向可合并写成 `[对话+1]`。

**只有类型与方向都写全的段落才参与属性演化**（`Directive.complete`）；缺任一项的段落
只推进步数（`step_override=0.0` 冻结坐标、自定义属性与步长，**也不产生伤亡**）——让纯
叙述段落安静地过去，需要她长起来的地方才写指令。没写类型的段落按「环境」步长推进且
**不显示类型前缀**（视作纯叙述）；结束章节内一律覆盖为「结局」并冻结，与 §3.2 同一条规则。

**高亮标记**（`dungeon.splitter.HIGHLIGHT_MARK`，语法是成对的 `==`）：对显示层生效，
**以显示段落为渲染单位**——被高亮区盖住的显示段落整段按高亮颜色渲染，标记本身不上屏：

```text
[对话 +1]
==她第一次俯下身，看清了掌心里的他。==人群安静下来，没人敢出声。
```

- 开标记之后进入高亮区，成对的收标记退出；**未闭合的开标记一直作用到逻辑段落末尾**
  （只写一次即是整段高亮）。标记落在句子中间也算——整句都会被高亮。
- 同一套语法对 **AI 生成的句子**同样有效（提示词规则 `coupling.HIGHLIGHT_MARKER_RULE`），
  插入触发器的段落也可以直接写（见 §6 的 `insert`）。
- 回放 / 概要 / 对话历史 / 报告一律剥离标记存净文本（`splitter.strip_display_markers`）；
  回放按 `step_info["highlight"]`（该逻辑段落是否有高亮）复现为整段高亮。

| 规则 | 行为 |
|---|---|
| 进对话历史 | 固定文本段与 AI 段落一样写进 `messages`（规范 JSON 形状，见 `response.canonical_history_entry`），**后续 AI 章节才接得上上下文** |
| 进程缓存 | 脚本按「章节 + 路径」缓存（`engine._script`），进入新章节即作废；换章清空预生成（`_pregen`） |
| 不走 AI | 固定文本章节内不发起流式生成、不做细节探究、不做下一段预生成 |
| `insert` 触发器 | **不支持**：插入段依赖 AI 对话历史与预生成，与文本流冲突，运行时直接跳过（校验器在保存 / 启动前给 warning） |
| 走到末尾 | 段落数用尽 = 与「段落数超限」走**同一个收口**（`engine._finish_script_chapter`）：按 `overflow_target` 跳转（空串 = 离开章节）；结束章节则按章节结算字段生成结局并终止。只收口一次，重复点击不再触发 |
| 文本读不出来 | 文件缺失 / 读取失败 / 没有任何可用段落时降级为**空脚本**（下一次点击直接收口，不卡死会话）；作者侧由校验器在保存与启动前报 `error` 拦住 |

编码按 `utf-8 → gbk → utf-8（容错替换）` 依次尝试（现成的中文文本很可能是 GBK）。
校验器 `validate._validate_fixed_text` 会把文件缺失 / 读不动报成 `error`，
把指令行的未识别记号、越界方向、指向未定义属性的方向、半写指令（缺类型或缺方向）
按类折叠成 `warning`；`max_paragraphs` 小于逻辑段落数、以及文本播完无去向各有一条诊断。

## 3. 章节运行时规则

### 3.1 进出章节与超限

| 规则 | 行为 |
|---|---|
| 进入章节 | 重置节内计数（`DungeonState.chapter_steps`），清除上一章遗留的章节效果覆盖；应用本章的背景、背景音乐、语音效果与持续演化修正 |
| 固定文本章节 | 进入时把脚本推进位置归零（`_reset_script_progress`）并作废预生成；本章按 `fixed_text` 逐段推进而不走 AI，见 §2.5 |
| 离开章节（跳到空目标） | 不清零属性、不切换背景，只是不再有章节效果；**背景音乐会停掉**（音乐是「身处其中」的一部分，留着上一章的曲子只会串味） |
| 音乐随章节走 | 跳到没配 `bgm` 的章节 = 停播；回放记录里带着当时的 `bgm` 配置，回放时按当时的曲目复现，不依赖当前方案 |
| 语音效果随章节走 | `_apply_chapter_voice_fx` 把 `voice_fx` 塞进语音导演（两档：她 / 其他人）；跳到没配效果的章节 = 清空效果（与音乐同一套语义）；回放时按章节进入记录里的当时配置复现（无论进入是起始、跳转还是超限触发） |
| 起始章节 | 唯一的自动进入点；它描述初始状态，不是判定，不违反「章节无条件字段」 |
| 超限跳转 | 节内计数达到 `max_paragraphs` 时，在 `_finish_step` 末尾（触发器判定**之后**）自动跳到 `overflow_target`；空串 = 离开章节 |
| 上限只是兜底 | 触发器的 `goto` / `option` 仍可在达到上限**之前**离开章节 |
| 回放顺序 | 跳转与结束都发生在同一步的 `_finish_step` 中，回放里是「步进记录 → `kind: "chapter"` 记录」 |

### 3.2 结束章节（`ending: true`，原「结束触发器」）

由 `chapters.is_terminating_chapter` / `overflow_jump_target` 统一判定：

1. **不允许跳出或弹选项**：处于结束章节时 `goto` 与 `option` 在 `check_triggers` 中被直接跳过（打印提示，不记入已触发集合）。
2. **所有段落类型一律被覆盖为「结局」，步进为 0**：`_generate_next_text` / `_display_inserted_paragraph` 强制以结局语气生成，显示前缀 `【结局】`；`rules.evolve_attributes(step_override=0.0)` 冻结坐标、自定义属性与步长演化，只累加计数，伤亡步进也为 0。
3. **达到 `max_paragraphs` 后终止**：`overflow_target` 恒为空串，调用 `_terminate_from_ending_chapter` 按章节自身的结算字段生成结局，复用结局生成管线（`EndingHandler._start_ending_generation`）。

旧配置里的 `ending`（结局）触发器**运行时已不再执行**：`actions.ENDING_ACTION` 只为回放
兼容保留，触发时只打印一行提示、当作没触发（不记入已触发集合）；编辑器把存量条目显示为
「结局（旧版·已失效）」且不再提供新建入口，校验器按 `LEGACY_ACTIONS` 报专项 warning。

### 3.3 结局生成与演化修正（`window/ending.py`）

**演化修正汇总** `_apply_sensitivity_mods`：把当前生效的章节 `sensitivity[]` 效果按
属性累加成「属性 → 倍率改变量」，每步演化与触发器结算都带着它进引擎（`engine.py`
的步进调用、`triggers.py` 的结算）。章节默认效果被「章节效果短暂覆盖」（§7
`effect`）改写时以覆盖为准（`triggers.py::_effective_sensitivity_effects` 现算），
离开章节即失效。

**结局生成**（`EndingHandler`）：结束章节达到上限后由 `_terminate_from_ending_chapter`
按章节结算字段组装 `pending_ending`（§3.2），`_start_ending_generation` 起后台线程
流式生成（`temperature=0.9`）：

- 提示按耦合等级取用（`coupling_prompts` 的 `ending_system` / `ending_user`，见
  [prompts.md](prompts.md) §8）；
- 上下文 `_build_story_summary`：状态行（介入度 / 破坏性 / 总伤亡 / 自定义属性）+
  剧情概要（`StorySummarizer.summary_only()` 优先，缺失回退最近步进片段）+ 性格
  描述；生成前先 `flush_chapter` 压完本章余量（§9.4）；
- AI 客户端不可用时只显示「结局：{名字}」，不拖垮收尾。

**收尾链**：正文剥高亮标记 → `_record_ending` 写 `kind:"ending"` 回放记录（只记
一次，带 `icon_path`——配置了图标才算重要结局）→ `_finalize(completed=True)`
（`window/persistence.py`）：`_apply_ending_effects` 结算结局增量——
`intrusion_delta` / `destruction_delta` / `custom_deltas` 直接叠加（坐标统一夹取
0.5~4.5）、`casualty_step` 过伤亡公式、`action_points_refund` 走
`refund_action_points`（无上限）、`exit_address` 结局传送（改写主世界位置的唯一
入口，空 / 解不出的地址一律不动，见 [scene.md](scene.md) §6）——角色记一行
`source="_apply_ending_effects"` 的完整演化，再记重要结局索引、自动保存回放（§9.3）。

## 4. 触发器字段索引

来源：`schema.TRIGGER_FIELDS`。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `name` | str | — | 触发器名（**必填**；`选择:<名字>` 条件键用它） |
| `chapter` | str | `""` | 所在章节（条件的一部分）：空 = 任意章节，`__none__` = 无章节，章节名 = 仅在该章节内 |
| `precondition_names` | list | — | 前置触发器；列表内每个都至少触发过一次 |
| `condition` | dict | — | 条件规则组，见 §5 |
| `repeatable` | bool | `true` | 可重复触发 |
| `action_type` | enum | — | 动作类型，见 §6（旧配置键 `action` / `action_data["type"]` 兼容） |
| `action_data` | dict | — | 动作参数 |

判定顺序见 `TriggerHandler.check_triggers`：**所在章节 → 前置触发器 → 条件规则**，任何一项不满足即跳过。
动作类型的读法只有一处：`actions.trigger_action_type`，依次看 `action_type` → `action` →
`action_data["type"]`，三者并存时以 `action_type` 为准（运行时、校验器、关系图、编辑器列表
都走它）。`action` 在加载时并到 `action_type` 并移除（`scenario_repo._migrate`，
只写规范键）；`normalize_action_type` 只做「动作字段缺失时回退 `action_data["type"]`」，
不做任何旧别名转换。

## 5. 条件键索引

来源：`schema.FIXED_CONDITION_KEYS` / `SERIES_CONDITION_KEY` / `CHOICE_CONDITION_PREFIX`，
求值在 `rules.TriggerRules.evaluate`。

| 键 | 含义 | 可用度量 |
|---|---|---|
| `介入度` / `破坏性` | 演化坐标 | — |
| `总伤亡` | 累计伤亡 | — |
| `总计数` | 副本总步数 | — |
| `间隔计数` | 距上次任意触发器触发后的步数 | — |
| `节内计数` | 进入当前章节后的步数 | — |
| `伤亡数组` | 每步伤亡序列 | `count` / `avg` / `trend` / `last` |
| `选择:<触发器名>` | 该选项触发器的选择记录 | `count` / `ratio` / `trend` / `last` |
| 自定义演化量名 | `evolution_attrs` 中 `type == "custom"` 的属性 | — |

「选择:」记录的值是**选项编号，0 起**（`window/options.py` 把 `enumerate` 的下标
记入 `trigger_choices`，回放同构）。条件里写编号的两处——`ratio` / `trend` 的
`target` 与 `last` 的 `value`——都用这套 0 起编号；编辑器表单的选项行标与条件值
口径一致。`mini_game` 触发器共用这条记录通道，但记的是游戏返回值（达成关数等），
编号空间由游戏自定，校验器不对它做范围检查；选项触发器超出选项数的编号会报 warning。

- 比较符（`CONDITION_COMPARATORS`）：`>=` `<=` `>` `<` `==` `!=`
- 整体关系（`CONDITION_OPERATORS`）：`and` / `or`
- 一层组合：`rules` 的元素还可以是 `{"operator": ..., "rules": [...]}` 的子条件组
  （求值递归），如 `(a或b)且(c或d)` 写作 `{"operator": "and", "rules": [
  {"operator": "or", "rules": [a, b]}, {"operator": "or", "rules": [c, d]}]}`。
  编辑器按「连接符切换处自动加括号」生成该形状；更深嵌套运行时也能求值，
  但编辑器无法完整显示（校验器报 warning）。

### 5.1 演化量与归属（`evolution_attrs[]`）

`schema.EVOLUTION_ATTR_TYPES` 四种：`intrusion` / `destruction` / `casualty`（内置，不可删）
与 `custom`（自定义，可删）。每项可选两个标签字段：

| 字段 | 取值 | 作用 |
|---|---|---|
| `display_state` | `show` / `collapse` / `internal` | 进不进展示组件：`show` 由属性条显示；`collapse` 收起；`internal` 完全不展示（仍参与演化与条件） |
| `owner` | `her` / `protagonist` / `environment` / `other` | 归属：这一项量是谁的 |

`owner` 只是**分组键，不是数值来源**——介入度 / 破坏性 / 总伤亡仍由 `DungeonState`
唯一持有，自定义属性按名字存在 `state.custom_attrs`。它影响三件事：

1. 编辑器「角色」页按归属把量归到角色卡片下（`ui/scenario/character_page.py`）；
2. 系统提示词：自定义属性写了 `owner` 时，`custom_directions` 的说明会带上归属
   （「狂气（归属：她）」），AI 才知道这一路变化是谁身上的（见 [prompts.md](prompts.md) §2）；
3. 日后组件可按归属取用（属性条现在只认 `display_state`）。

未写 `owner` 的旧方案按类型取缺省（`schema.DEFAULT_OWNER_BY_TYPE`：介入度 / 破坏性 /
自定义 → 她，总伤亡 → 环境），**不写回配置**，提示词逐字不变。

## 6. 动作注册表

单一出处：`dungeon/actions.py`（`NEW_ACTIONS` / `ENDING_ACTION` / `ACTION_LABELS` / `VISUAL_FILTERS` / `WINDOW_FX`）。
编辑器、依赖图、回放导出共用，不再各写一份字符串常量。

| 类型 | 展示名 | `action_data` | 状态 |
|---|---|---|---|
| `insert` | 插入文本 | `text, text_type, delayed`（旧配置的 `highlight` 仍认） | 运行时；`delayed` 表示等下一段 AI 段落返回后再显示。高亮不再用字段开关，直接在 `text` 里写 `==...==`（见 §2.5「高亮标记」）；旧的 `highlight: true` 依旧按整段高亮复现，编辑器保存时迁成语法。**固定文本章节内跳过**（插入依赖 AI 对话历史与预生成，与文本流冲突，见 §2.5；校验器给 warning） |
| `option` | 弹出选项 | `prompt, options[{id, prompt, text}]` | 运行时；选择按编号记入 `选择:<名字>` |
| `effect` | 效果覆盖 | `filter, bgm_level, voice_fx, sensitivity, duration` | 运行时；限时改写章节环境（背景滤镜 / 音乐档位 / 语音效果 / 演化修正），`duration` 步后各维度交还章节默认值；只写出来的维度才被覆盖，详见 §7 |
| `fx` | 窗口视效 | `fx, duration, intensity` | 运行时；操作整个会话窗口的瞬时画面（闪光 / 振动 / 反色 / 色差分离），`duration` 为绝对时间（秒，0.1~10），按 `intensity`（0~100）定峰值亮度 / 振幅 / 错位幅度；详见 §7 |
| `goto` | 跳转章节 | `chapter`（空串 = 离开章节） | 运行时；进入目标章节，应用其背景与持续演化修正 |
| `mini_game` | 小游戏挑战 | `game, target_level, win_goto, lose_goto` | 运行时；在会话窗口内覆盖层舞台运行（`dungeon/window/minigame/`，ESC=无结果中止）；步进暂停，结果经 `finish(won, result)` 回传后按 `win_goto`/`lose_goto` 跳转（空串=原地继续），无结果=原地继续。结果随触发器记录落盘，回放不进游戏直接复现 |
| `none` | 条件标记 | `{}` | 运行时；无动作，只标记条件成立，供其他触发器作前置条件 |
| `ending` | 结局（旧配置） | — | **已删除**：运行时直接跳过（与 `background` / `sensitivity` 同走未知动作路径），仅回放兼容（旧存档按记录复现结局）；编辑器显示「旧版·已失效」，新方案由「结束章节」承担 |
| `background` / `sensitivity`（早期拼写 `sensitive`） | 旧版·已失效 | — | **运行时不认识**：不在注册表里，落入「未知的触发器动作类型」通用路径（不执行、不记入已触发集合、不重置间隔计数，只打印一行提示） |

旧版动作（`background` / `sensitivity` / `ending`）的三处处理：运行时跳过、触发器列表
显示为「旧版·已失效」（无表单，只能删除）、校验器 `validate.LEGACY_ACTIONS` 在**编辑器
保存时与副本启动前**报专项 warning。

### 6.1 判定顺序与轮次

**一轮 = 一次步进收尾（或会话启动）+ 它派生的全部结算重判**（选项选择、小游戏结算）。
重判共享「本轮已触发」集合（`_round_fired`，见 `triggers._begin_trigger_round`），
**同一触发器一轮内至多生效一次**——结算后条件仍成立的触发器不会立刻重发（选项连弹、
视效 / 插入重复发放被结构性挡住），其他触发器可以接力；新一轮从下一次步进收尾开始。

派发按 `actions.ACTION_POSITIONS` 的固定顺序逐位进行，**同位置至多生效一个**
（同位置内按配置顺序取第一个满足条件且配置有效的触发器；配置无效被跳过不占配额）：

| 位置 | 动作 | 理由 |
|---|---|---|
| 1 | `fx` | 纯视觉、不等结果，画面反应永远最先 |
| 2 | `option` / `mini_game` | 模态动作先占位；同一次判定里两者至多其一 |
| 3 | `goto` | 之后的 effect / insert 落在新章节（effect 先于 goto 会被换章清除，等于白放） |
| 4 | `effect` | 章节效果短暂覆盖（背景滤镜 / 音乐音量 / 语音效果 / 演化修正） |
| 5 | `insert` | 插入段落 |
| 6 | `none` | 条件标记最后才立：依赖它的触发器最早下一轮可见，**瞬时条件（如精确匹配）不要依赖 none 前置链** |

被接纳的触发器**立即清空 `间隔计数`**——同轮后续位置里 `间隔计数>=1` 的条件必然为假，
与"同位置至多一个"互相强化。回放不判定，只按记录复现。

## 7. 章节效果短暂覆盖（`effect`）

章节是「身处其中时的环境」（§3）；`effect` 动作给它加一层**限时覆盖**：触发后临时
接管其中若干维度，走完 `duration` 步再交还章节默认值。覆盖项的解析与合成规则集中在
`dungeon/overrides.py`（运行时、校验器、编辑器共用同一份口径），运行时状态在
`dungeon/window/triggers.py`。

| 维度 | 键 | 取值 |
|---|---|---|
| 背景滤镜 | `filter` | 滤镜键（`actions.VISUAL_FILTERS`）或空串（这段期间清除滤镜）；无背景图时忽略 |
| 音乐档位 | `bgm_level` | 0~4 整数档位（兼容旧 `bgm_volume` 的 0~100，按响度就近折算）；只改档位不换曲，章节没配音乐时忽略 |
| 语音效果 | `voice_fx` | 与章节 `voice_fx` 同形（`her` / `others` 两档）；空对象 = 这段期间不加效果 |
| 演化修正 | `sensitivity` | 与章节 `sensitivity` 同形的数组；空数组 = 这段期间没有演化修正 |

| 规则 | 行为 |
|---|---|
| 触发 | 入队 `effect_overrides`，每步在 `_finish_step` 里消耗 1 步（`_apply_effect_overrides`） |
| 逐维度 | 一条覆盖只改它写出来的维度，其余沿用章节（或更早的覆盖） |
| 后触发优先 | 同维度多条并存时取最后触发的那条；到期逐条回退 |
| 恢复 | 每次入队 / 到期都按当前生效集合整体重算，各维度落到章节默认值（不是抄旧值回去） |
| 换章 | 立即清空全部未到期覆盖，并落到新章节默认 |
| 回放 | 按记录原样复现覆盖（重新入队，不判定条件） |

滤镜键的单一出处是 `actions.VISUAL_FILTERS`（与 `DungeonBackground.apply_filter` 的键同步，
`background.py` 的 PIL 映射在导入时校验一致性）。

### 7.1 窗口视效（`fx`，`dungeon/window/fx.py`）

与章节效果覆盖的背景滤镜相对：这组视效操作**整个会话窗口**而非背景图，以**绝对时间**
（秒）消退，与步进无关。视效键的单一出处是 `actions.WINDOW_FX`
（`fx.py` 导入时校验，校验器按同清单检查配置）。

| 键 | 画法 |
|---|---|
| `flash` 闪光 | 顶层绘制列表一块全窗白色矩形，不透明度从峰值线性退到 0 |
| `shake` 振动 | 把根窗口整体按衰减正弦偏移挪位（背景反向补偿，屏幕位置纹丝不动） |
| `invert` 反色 | 帧末 `glReadPixels` 抓一帧当前画面（整窗真实像素）→ 像素工作者反相 → 半透明覆盖层按时长退场 |
| `rgb_split` 色差分离 | 同一套快照管线：R/G/B 通道按强度错位相加成一张覆盖层图像 |

| 规则 | 行为 |
|---|---|
| 派发 | `fx` 在判定顺序中排第一位（§6.1）：纯视觉、不等结果，同轮其他动作照常 |
| 阻塞性 | 无：触发即播放、立即返回，期间流式生成与上屏、音频播放、切换背景等一切照常 |
| 时长 | `duration` 绝对时间（秒，解析失败 / 越界夹回 0.1~10），帧时钟按 `time.monotonic` 计时 |
| 强度 | `intensity` 0~100：闪光 / 反色峰值不透明度、振动幅度、色差错位幅度（低强度保底可见） |
| 重触发 | 同类互斥（重触发顶掉旧的），不同类可叠加（如闪光 + 振动） |
| 换章 | 不清除：视效本身只有亚秒到数秒寿命，到期自消 |
| 抓帧失败 | 反色 / 色差分离退回处理当前背景图；连背景都没有则放弃本次视效（打印提示） |
| 回放 | 回放记录原样重放一次（不判定条件，按时长重演） |

## 8. 内部实现：编辑器由哪些窗口组成

> 这一节是给维护编辑器的人看的：哪个窗口负责哪一页、哪些操作会自动保存。**只写方案配置的
> 作者可以整段跳过**——上面的字段表已经覆盖了你需要知道的一切。

| 文件 | 职责                                                                                                                                                                              |
|---|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ui/scenario/chapter_trigger_mgr.py` | 章节与触发器**合并列表**（「剧情」页的默认标签）：章节行加粗并按自定义颜色着色，其下缩进行是本章节触发器；「任意章节 / 无章节」的触发器排在最后。底部是新建章节 / 新建触发器与共用的编辑、删除、上移、下移                   |
| `ui/scenario/chapter_dlg.py` | 章节编辑：配色色板 + 手填 hex、起始 / 结束标记、最大段落数与超限跳转、**在场人物多选（人物表成员，勾上才算本章在场）**、**地点与取景（地点名 / 取景地址带注册地址选择器与实时解析提示 / 本章地标三态取用 / 结束章节的出口地址）**、背景导入、背景音乐（曲目 / **档位** / 循环 / 淡入淡出）、**对话语音物理效果（她 / 其他人两档的预设 + 强度 + 只读「响度 ±dB」+ 预听）**、**固定文本（导入 / 编辑 / 清除 + 实时解析预览）**、演化修正增删、结束章节的结局结算与图标 |
| `ui/scenario/trigger_dlg.py` | 触发器编辑：基础信息（名称 / **动作类型下拉** / 所在章节 / 前置条件 / 可再次触发）固定在上方，动作参数放在**明亮卡片**里（表单按「标签列 / 控件列」对齐、下拉统一用 OptionButton，卡片吃掉窗口剩余高度、超出才内部滚动，`条件标记` 收起整个动作区）；窗口固定 640x660；动作类型含 `插入文本` / `选项分支` / `章节效果覆盖`（四个覆盖维度：滤镜 / 音乐档位 / 语音效果 / 演化修正）/ `窗口视效` / `跳转章节` / `小游戏挑战` / `条件标记`；触发条件改为**可点击的文字预览行 + 单行编辑控件**，含 `节内计数` 条件键；**固定文本章节内 `插入文本` 无独立按钮，改为在类型说明里提示会被跳过** |
| `ui/scenario/asset_import.py` | 背景 / 结局图标 / 背景音乐导入的共用实现（裁剪入库、相对路径；音频落 `<方案>/audio/`，不裁剪）；固定文本（`.txt` / `.md`）的导入 / 读写 / 默认路径（落 `<方案>/texts/`）                                                                   |
| `ui/scenario/text_editor_dlg.py` | 固定文本编辑器：多行编辑正文 + 实时预览（逻辑段落数、每段的指令与是否演化、解析警告）                                                                                                                                    |
| `ui/scenario/sc_frame.py` | 方案级配置：**页签 通用 / 角色 / 剧情 / 组件**，顶栏第二层是**常驻校验条**（错误 / 警告计数 + 第一条问题 + 各页签问题数，点开看全部诊断并可跳转定位）；通用页放耦合等级、进入准入（方案地址 + 距离上限 + 身高区间）、进入消耗、初始提示与段落分类提示。**剧情页**用分段切换三个标签：「章节与触发器」列表 /「章节编排」/「触发器依赖」，互不并存 |
| `ui/scenario/character_page.py` | **角色页**：人物卡片（她 / 主角 / 环境 / 其他角色）+ **主角身份背景**与**人物表卡片列表**（重要角色 / 群像的增删排序、定位切换、按定位换一套字段：重要角色是别称 / 称她为 / 身份背景，群像是代词 / 作用 / 说话方式，两档都有音色）+ 方案级语音条（总开关、语速、档位、预听）；主角与人物表、音色都防抖自动保存；页内「演化量」视图是同一批演化量的平铺表（可再按归属过滤），由 `evolution_attributes.py` 提供 |
| `ui/scenario/evolution_attributes.py` | 演化量视图：按归属筛选的列表（名称 / 归属 / 类型 / 展示状态 / 初始值 / 倍率 / 偏移率）、自定义属性与内置属性的编辑对话框；过滤只影响显示，保存永远写回完整列表 |
| `ui/scenario/component_mgr.py` | 显示组件卡片化管理（开关与参数改动自动保存）                                                                                                                                                          |
| `ui/scenario/graph_view.py` | **剧情页「章节编排」/「触发器依赖」共用的只读画布**（与「章节与触发器」列表互斥）：章节编排是章与章流程图，触发器依赖是泳道图（节点按依赖分层）；面板自带图层开关、导出报告与「帮助」对话框（图例 / 画图示意），但视图由剧情页传入、内部不切换；只读，不写盘。校验结论不在这里显示，由顶栏校验条统一承担，面板只提供 `focus_path()` 定位。模型与规则见 Dungeon 编排图文档 `scenario_graph.md` |
| `ui/scenario/diagnostics.py` | 诊断的展示口径（纯函数）：按 `Diagnostic.path` 的根键把诊断归到页签（`TAB_*`），供顶栏校验条计数、挑选第一条与跳转定位 |

配色与调序：

- 章节配色以 `#RRGGBB` 存配置（浅色模式基准），深色模式下由 `chapters.shade_for_mode` 提亮 35%；触发器行沿用所属章节的颜色，无归属的用弱化色。
- 触发器只与同组内相邻的触发器交换，越过章节行即到达章节收尾（不跨章节移动）；章节与相邻章节交换，其下触发器按章节归组自动跟随。
- 新建触发器默认落在当前选中的章节里；编辑章节改名时，指向它的触发器作用域与 `跳转章节` 目标一并改名。
- 删除章节会在确认框里列出将被一并删除的触发器；确认后一起删除，仍指向该章节的 `跳转章节` 目标会收到警告（配置不会被自动改写）。

## 9. 校验、迁移与持久化

### 9.1 校验器

`validate.validate_scenario_config(config, scenario_dir=None)` 返回结构化诊断
（`Diagnostic(level, path, message)`，error / warning / info 三级）。

| 诊断级别 | 覆盖示例 |
|---|---|
| `error` | 悬空 goto / overflow_target、无起始章节、空选项列表、固定文本文件缺失 / 读不动 / 没有可用段落（需传 `scenario_dir`）、人物表的称呼 / 别称撞车或 `id` 重复（会让说话人与音色串台）、临时称呼与成员称呼 / 主角称呼撞车、配角缺少称呼、`speaker_notation="literary"` 方案的作者正文（初始提示 / 背景 / 章节提示 / 插入文本）里出现 `@说话人@`（不许混用） |
| `warning` | 多起始章节、结束章节内的 option / goto、废弃动作与旧版字段、条件键 / 比较符 / 度量非法、演化量的展示状态 / 归属取值非法、转移矩阵行缺失与权重越界、背景图 / 结局图标缺失（需传 `scenario_dir`）、固定文本的指令行未识别记号 / 方向越界 / 指向未定义属性 / 半写（缺类型或缺方向）、`max_paragraphs` 小于逻辑段落数、固定文本章节内放 `insert`、人物表的 `role` / `pronoun` 取值非法、章节 `cast` 指向表里不存在的成员、描述字段超长、`speaker_notation` 取值非法 |
| `info` | 无结局路径（`ending_policy: "open"` 时不再提示）、旧版顶层字段、未知顶层键、`voice` 未知子键、固定文本播完本章无去向、重要角色超过 6 个 |

**`ending_policy`**（顶层，`required` / `open`，默认 `required`）：作者对「本方案要不要结局」的显式声明。
`required` 时没有结束章节、也没有「结局」触发器会给出 info；声明 `open`（开放式方案）即消除该提示。
它只影响校验提示，运行时行为仍由结束章节 / 结局触发器决定。

接入点：

| 时机 | 位置 | 力度 |
|---|---|---|
| 编辑器保存 | `ScenarioRepo.save_config()` | 诊断记入 `last_diagnostics`，编辑器弹窗汇总 error |
| 副本启动前 | `window/base.py::_load_session_config()` | error 级阻止进入 |
| 离线批量 / CI | `scripts/scenario_validate.py` | error 退出码 1 |

上面三行是**字段级**规则（某个键写错了、某个文件不存在）。**结构级**的检查——章节与
触发器之间的依赖、可达性、跳转闭合、循环依赖——由五条**图校验**规则承担
（建图 `dungeon/scenario_graph.py::build_graph`，判据 `dungeon/graph_lint.py::lint_graph`）：

| # | 规则 | 级别 | `path` | 判据 |
|---|---|---|---|---|
| R1 | 章节走不到 | `warning` | `chapters[i].name` | 该章节不在**章节可达性**集合里（从根沿进入 / 跳转 / 超限 / 归属边前向可达，忽略一切条件与前置） |
| R2 | 走不到任何结束章节 | `warning` | `chapters` | 结束章节存在，但一个都不在可达集合里 |
| R3 | 前置永远无法成立 | `warning` | `triggers[i].precondition_names` | 前置所在章节不可达，或前置自身处于死锁分量 |
| R4 | 自跳转 | `warning` | `triggers[i].action_data.chapter` | `goto` 目标等于自身所在章节（运行时会跳过） |
| R5 | 循环依赖 | `warning` | `triggers[i].precondition_names` | 前置分量没有「种子」成员——强连通分量内每个成员都有分量内前置，整环互锁永远激活不了 |

可达性口径：

- **章节可达性**（`ScenarioGraph.chapter_reachability`）：只走结构边，忽略条件与
  前置——乐观估计，不因条件写错而误报；讲「走不到」的规则一律只用这一条。
- **触发器可达性**：在前者基础上加入前置 AND 语义——前置边收缩成强连通分量后在
  DAG 上迭代到不动点，分量要有「无分量内前置的种子成员」才可能激活；R5 的判据就
  是无种子的分量。
- `选择:` 条件引用（`EDGE_CHOICE`）两条口径都**不参与**：被引用触发器没触发只是
  计数为 0，是可以被比较的合法值，不是「到不了」。

**抑制与去重**：

- R1 / R2 都要求「至少一个起始章节」且「至少有一条跳进章节的边」（`goto`，或指向
  章节的 `overflow_target`；空 `overflow_target` 是「超限后离开章节」，不算接线）。
  还没接线的骨架方案不刷可达性诊断；没有起始章节时顶层已有一条 error，不重复报。
- 没有可达的结束章节时，结束章节不再逐条报 R1（R2 的措辞更准确，同一个原因不刷
  两遍）；只要**有一个**结束章节可达，其余走不到的结束章节照旧按 R1 报。
- R2 与既有的「方案里根本没有结束章节」info 不是一回事：前者结束章节存在但走不到，
  后者直接没有。

**同位置动作竞争**（`ACTION_POSITIONS` 同位 + 同作用域）**不进校验器**——严格判断
「两条的条件会不会撞车」需要求解器；`same_position_groups()` 只按位分组，由编辑器
编排图呈现（见 [../scenario_editor.md](../scenario_editor.md) §3）。

接入：`validate_scenario_config()` 在 `_validate_triggers` 之后调用
`lint_graph(build_graph(config))`，三元组并入同一份诊断列表（`graph_lint` 不
import `validate`，由本模块包成 `Diagnostic`），保存方案 / 启动副本前 / 离线批量
校验三处自动覆盖。图模型与两个可达性口径的实现见
`docs/designs/dungeon/scenario_graph.md` §2。

### 9.2 迁移与兼容

| 项 | 行为 |
|---|---|
| `ScenarioRepo._migrate` | 以原配置为底稿补齐字段，未知键（含 `components`）原样保留；缺失的 `chapters` 补成 `[]`，每个触发器补 `chapter: ""`；旧写法 `components` 列表里的文本家族成员提升到 `text_component` 字段并从列表移除 |
| `chapters.normalize_chapter` | 补齐 `ending` / `max_paragraphs` / `overflow_target` 与结束章节结算字段（旧章节默认 `ending=false`、上限 99、超限离开章节） |
| 旧配置行为 | 迁移后所有既有触发器都是「任意章节」，也不自动创建章节 |
| 旧版 `background` / `sensitivity` 动作 | **不再执行**，配置本身不被改写，需要清理时在编辑器里删除 |
| 旧 `ending` 动作 | **运行时不再执行**（仅回放兼容，见 §6）；新做结局请改用「结束章节」 |
| 演化配置链路 | `window/base.py::_init_session` 把 `transition_matrix` 与 `section_steps` 传给 `EvolutionRules`（同时注入 `StateService.decay_depths`）；这条链路由 `check_scenario_schema.py` 守卫 |

### 9.3 回放记录

| 记录 | 说明 |
|---|---|
| 普通步进（无 `kind`） | `text` 一律是剥离显示层标记的净文本；`highlight` 记「本段有高亮」，回放按整段高亮复现（显示层的高亮单位是显示段落，回放只出整段）；`type_prefix` 是当时的显示前缀（空串 = 本段不显示前缀，固定文本里没声明类型的段落就是这样），缺失时回放按 `type` 现算、`ending_chapter` 为真时按「结局」；`display_text` 只在原文带 `@说话人@` / `==` 时才写（原文与净文本相同就不写这个键），回放靠它还原说话人与高亮——说话人决定这一句念不念、念谁的声音，净文本里没有。方案声明 `speaker_notation="literary"` 时正文不会出现 `@说话人@`，该键只在高亮时写；记法版本另见 `kind:"meta"` 的 `speaker_notation` |
| `kind: "chapter"` | 章节进入，带当时的 `background` / `bgm` / `voice_fx`，回放不依赖当前方案。**章节进入只有这一种写法**：起始章节、`goto` 触发器、超限跳转都写它，触发器记录只说「谁触发了跳转」 |
| `kind: "trigger"` | 触发器触发，回放时走 `_replay_trigger`；分支动作额外带 `choice_index` / `choice_text` / `option_prompt`、`game_result` / `choice_value`、`ending_text` |
| `kind: "characters"` | 文件头部的人物账本快照（`_init_replay` 整本还原成只读视图），不参与步进，也不进档案导出的正文 |
| `kind: "ending"` | 结局正文 + `icon_path`：回放到此为止（再点一次关窗）。旧回放没有这条记录，末段即结束 |
| `kind: "meta"` | 文件头部的**回放身份**：`scenario`（`id` / `content_hash` / `version_tag` / `assets`）+ `app` + `saved_at`，另有 `version` 标记录语法版本（`replay.META_VERSION`，当前读取侧不解释）；`speaker_notation` 记方案当时的说话人写法（可选兼容键，旧回放没有 = 不知道），让回放自解释记法版本。不参与步进，也不进档案导出 |

记录的语法在 `dungeon/replay.py`：`classify()` / `parse()` / `parse_all()` 产出 Record
（`StepRecord` / `ChapterRecord` / `TriggerRecord` / `CharactersRecord` /
`EndingRecord` / `ScenarioRecord`），窗口层只吃 Record，不再各自 `dict.get`。
写侧同一个模块：`meta_record()` 产出身份记录，`material_paths()` 给出记录里用到的
方案素材路径（写 `meta.assets` 与读侧反查共用这一份），`display_text_field()` 决定
步进记录要不要写 `display_text`（原文剥完标记与净文本相同就不写）。约定：

- **内嵌配置复用配置侧归一器**（`normalize_background` / `normalize_bgm` /
  `normalize_voice_fx` / `trigger_action_type`）：记录里存的是当时的环境，重新拼成
  配置时必须与编辑器写出的同形（legacy `volume` 折算成档位、非法预设归一为
  「不加效果」、只写在 `action_data.type` 里的动作类型照样认）；
- **容错在解析层**：缺键给默认、类型不符给默认，整条坏记录（非字典 / 未知
  `kind` / 没有正文的步进）返回 `None` 由调用方跳过——一条脏记录不该让整段
  回放卡在半路（回放文件来自「所有文件」选择框，内容不由本程序保证）；
- **`effect` 覆盖的时长以步计**：实时在 `_finish_step` 里消耗，回放没有那一步，
  所以 `_replay_step` 每段收尾同样消耗一次（否则滤镜 / 语音 / 音乐音量一旦被
  覆盖就持续到换章）；
- **旧格式在 `parse_all` 收敛**：早前的 `goto` 触发器记录把目标章节的环境写在
  `chapter_background` / `chapter_bgm` / `chapter_voice_fx` 三个平级键上，读入时
  展开成「`ChapterRecord` + `TriggerRecord`」两条，读取方只认章节记录这一种形态；
- **显示层标记只落在 `display_text` 里**：`text` 是净文本，回放重播时不认识
  `@说话人@`（`tagged` 记法才有）——少了 `display_text`，对话句一律不出声
  （`_speak_item` 拿不到 `speaker`）；`literary` 记法方案正文不带标记、本就不逐句
  朗读。写侧只在这一段确实带标记时才写它（`display_text_field`，三个写入点：
  AI 段落 `step_info`、固定文本段落、插入段落），解析侧反过来只要「剥完标记正好
  等于 `text`」才采信，对不上按净文本播；旧记录没有这个字段，照旧逐句渐显、只是
  不念。
- **选项 / 小游戏在回放里是一行文本**：实时弹窗（选项）与独立界面（小游戏）在回放里
  不重现，改在故事区补一行「【选择】…」（内容 = 当时选的那条）/「【小游戏】…」
  （返回值摘要），并占一次点击。这两行**只活在回放显示层**：不写进记录，也不参与
  「回放 → 配置」的反向改写——`to_config_fragment` 只看 `TriggerRecord` 的动作本身，
  所以回放转录文本时不会凭空多出一段。
- **步进记录的呈现是播放，不是打印**：回放把 `text` 按内置分句器切成显示段落，
  走与实时同一条限速游标（首段逐字上屏、其余等点击），因此回放的阅读节奏与
  当场游玩一致；没有正文的记录（章节进入 / 跳转 / 覆盖 / 视效）不占点击，
  `_replay_next_step` 会把它们随一次点击连续落地。
- **回放文件自带身份**：`kind:"meta"` 记下所属方案的 `id`、`content_hash`（整方案
  摘要，只回答「是不是同一版方案」）与 `assets`（记录里用到的图 / 音频的相对路径
  + 当时字节数，最多 8 条，用来发现同名文件被重新导入）。素材本身**不拷进回放**，
  仍然只有记录里那一份。加载时的判定链是「调用方显式传入 > `meta.scenario.id`（且
  方案还在）> user 回放文件名前缀 `_回放_` > 素材反查」，最后一级只照顾不认识
  `meta` 的旧文件；`assets` 大小对不上只记一行过程日志，不弹窗、不中断回放。

反向出口 `to_config_fragment(record)` 把 `ChapterRecord` 还原成
`{name, background, bgm, voice_fx}`、`TriggerRecord` 还原成
`{name, action_type, action_data}`（只写规范动作键，见 §4），供「回放 → 配置」的
回溯改写使用；步进 / 账本快照 / 结局正文 / 身份记录在配置里没有对应字段，返回 `None`。

**落盘与保存时机**（`window/persistence.py`，统一收尾 `_finalize`）：

| 项 | 行为 |
|---|---|
| 文件位置 | 探索模式写角色档案 `data/archives/<角色id>/回放/<角色名>_回放_<时间戳>.replay.json`，同时落一份报告 `<角色名>_副本报告_<时间戳>.txt`；挑战模式 / 无角色写 `data/user/replays/<方案id>_回放_<时间戳>.replay.json`，不创建 / 更新角色 |
| 载荷 | 身份记录（`kind:"meta"`）→ 人物账本快照（`kind:"characters"`）→ 记录本体（`_replay_payload`）；原子写（覆盖不留备份） |
| 自动保存 | 结局触发即保存（`auto_save_replay` 开时，成功后不弹框）；开关默认关 |
| 手动保存 | 玩家在收尾确认「保存」或点面板「立即保存」，完成后弹「保存成功」；探索模式无角色时先询问是否创建角色（拒绝即本次不保存） |
| 未完成退出 | **不落盘**：不结算结局增量、不写 `data/user/endings.json`、不记挑战达成、不保存回放与报告 |

### 9.4 剧情压缩（提示词上下文）

段落历史怎么压成「剧情概要」、多久压一块、概要 / 事实卡 / 关键事件各占多少预算，属于
提示词的上下文管理，整节移到 [副本提示词](prompts.md) §4——连同「对话历史窗口 + 概要」
怎么一起拼成 AI 的记忆。

---

## 10. 对话语音（方案级 `voice`）

方案级音色配置、合成底座（edge-tts 端点 / 代理 / 失败原因）、玩家侧音量总线与
章节级物理效果的接线见[副本对话语音](voice.md)；
章节 `voice_fx` 的字段与预设见 §2.4。

## 11. 角色设定（方案级：主角 + 人物表）

主角两字段、人物表 `cast[]` 各字段（含 `intro_as`）、章节 `cast` 在场声明、
注入规则与运行期账本的说明见[副本角色系统](characters.md)。
本篇只保留演化量的 `owner` 归属（§5.1，条件键视角）。

## 12. 进入准入（方案级）

入口地址 / 距离 / 身高区间的字段与判定口径见
[副本进入准入](admission.md)。

---

## 13. 场景地标（章节级）

独特地标内联在章节 `scene_landmarks` 里，常见地标按章节 `common_private_name`
过滤私有名：字段形状、候选池规则与校验口径见
[副本内地点与参照物](scene.md)。

- 两者都缺省为空：什么都没配的章节没有候选池，不产生换算句，也不回落全量；
- 地标条目默认 `dimension=vertical`，`horizontal` 时 `horizontal_type` 默认
  `length`；条目全部按独特地标（unique）换算；
- 方案级 `scene_landmarks` 与章节级 `landmarks` 白名单已退役，读到即忽略
  （校验器报 warning 提示迁移）；
- 清单只喂尺寸换算句，不参与章节推进与结局判定。

## 14. 拓展用法

界面上没有明说、但配置本身支持的用法：

- **用「超限即离开」做过场章节**：把 `max_paragraphs` 设小、`overflow_target` 留空，章节
  走满段落数就自动离开（不是跳去别处，而是回到「无章节」），适合做完一段独白 / 演出就收。
- **复制方案目录做并行版本**：把 `data/packs/scenarios/<id>/` 整个复制成新 id 再改，两条线
  互不影响；比在同一份配置上反复覆盖安全，也便于对比两版差异。
- **手写 `config.json` 批量改**：编辑器存盘会补齐缺失字段、保留不认识的键，所以可以先用
  脚本统一改一批（比如给所有触发器加同一个条件），再回编辑器里检查校验条。

提示词层面的玩法（把 `note` 当持续提示、长期禁令写进初始提示、手写
`section_prompts.global`）见 [副本提示词](prompts.md) §10。

## 15. 官方资源

官方入库的方案目前只有一个：**回稳会志**（`default`，资源信封 `stable`、署名 XiaoCui、
版本 1.0），随发行版提供，可直接开局，也可当模板复制改：

| 方案 | 规模 | 用途 |
|---|---|---|
| 回稳会志（`default`） | 6 章节 / 26 触发器 | 官方示例，章节、选项分支、结局与固定文本都有用到 |

仓库代码树里另有 `huiwen_huizhi_ai`（5 章节 / 26 触发器）与 `juying_lincheng`
（12 章节 / 54 触发器）两个开发草稿，信封为 `draft`、未署名、`0.0.0`，**未入库、不随
发行版发布**。本地调试时可以拿它们看更大规模的编排（后者触发器依赖最密），但它们不是
官方样本，文档里的默认行为一律以回稳会志为准。

## 16. 作者须知

- **旧动作不再执行**：`background` / `sensitivity` 类动作在运行时已停用（配置不会被自动
  改写，需要清理请在编辑器里删）；旧 `ending` 动作只保留回放兼容，新结局请用「结束章节」。
- **迁移不猜你的意图**：旧配置迁移后所有触发器都是「任意章节」，也不会自动创建章节。
- **改名会连带改引用**：章节改名时，指向它的触发器作用域与 `跳转章节` 目标一起改；删除章节
  则只会给悬空跳转一条警告，不会替你改写目标。
- **未知键保留但不保证生效**：手写字段不会被存盘删除，是否被读取取决于当前 schema——写完
  请让校验条跑一遍。
- **交付前自检**：`python tests/run_checks.py check_scenario_schema check_scenario_graph
  check_scenario_admission`，或离线批量跑 `python scripts/scenario_validate.py`（error
  退出码 1）；编排图上的可达性结论由 `check_scenario_graph` 守卫。

## designs 目录

<details>
<summary>designs/ 全目录（wiki 地图）</summary>

**机制目录**

- **dungeon/**：[README](README.md)（全景）·
  [script](script.md)（本页）·
  [prompts](prompts.md)（提示词与上下文）·
  [characters](characters.md)（人物表与账本）·
  [voice](voice.md)（对话语音）·
  [admission](admission.md)（进入准入）·
  [scene](scene.md)（地点与参照物）·
  [minigame](minigame.md)（小游戏）·
  [components](components.md)（显示组件）
- **character/**：[README](../character/README.md)（全景）·
  [evolution](../character/evolution.md)（介入度 / 深度 / 行动点）·
  [time](../character/time.md)（恢复结算 / 作息 / 导出）·
  [chat](../character/chat/README.md)（话题与好感 / 紧张度）·
  [lens](../character/chat/lens.md)（信息视角细节）
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
