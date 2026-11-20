# 角色的时间维度

> **这一篇回答什么问题**：程序未运行期间发生了什么（恢复结算：行动点 / 坐标 /
> 伤亡）、作息节律怎么从行为数据学习、近况新闻怎么选、剪影预览怎么画、档案与
> 角色卡两种导出各包含什么。演化量本身的公式全景在
> [character_evolution.md](character_evolution.md)，空间档案（环境因子 / 区域）在
> [report_selection.md](report_selection.md)。

术语现状：代码符号保留 `offline` 原名（模块 `services/character/offline.py`、
类 `OfflineService`、钩子 key `"offline.*"`、存档字段 `offline_details`），叙述
用「恢复结算 / 间隔时长」；用户可见文案首段仍写作「离线 {时长}」。

## 1. 恢复结算（`services/character/offline.py`）

**触发时机**：只在**加载角色**时发生一次——
`services/exploration/context.py::load_character_state` 调
`OfflineService.recover_offline`，随后依次负向演化、头像兜底、保存。两个界面的
加载入口（`app/window_manager.py::load_character_by_id` 与
`ui/mini/app.py::load_character`）都走这条链；没有应用启动时的全局结算，未载入
的角色不结算。

**计划 / 执行分离**：`build_recover_plan(state)` 是纯函数（只读状态，返回
`OfflineRecoveryPlan`），行为包钩子 `offline.recover_plan` 可整体替换；
`apply_recover_plan` 写回与记演化表仍由服务层负责；文案生成挂
`offline.report_text` 钩子。

**固定契约**：明细窗口 72h、明细精度 2h（`_OFFLINE_WINDOW_HOURS / _OFFLINE_BIN_HOURS`，
是导出图表、演化表与 UI 的跨模块契约）。参数默认值来自
`core/models.py::ModelTuning`（**出身烙印**：创建期派生、终身携带，世界包启停不
触及已有角色）：

| 参数 | 默认 | 含义 |
|---|---|---|
| `step_per_hour` | 0.01 | 基础步进率（步/小时） |
| `exit_amp` / `exit_tau` | 0.05 / 0.9h | 退出残留活动的幅度与衰减时间常数 |
| `recovery_points_per_minute` | 0.5 | 行动点恢复速率（点/分钟） |
| `recovery_decay_per_minute` | 0.01 | 坐标回落速率（深度/分钟） |
| `noise_scale` | 0.1 | 环境噪声系数 |
| `old_step_divisor` | π | >72h 汇总段的步进除数 |
| `rhythm_swing` | 1.0 | 作息调制放大倍率（夹取 0~3） |

覆盖优先级「实例显式参数 > 角色烙印 > 默认」（`OfflineService._model`）。

**三项结算内容**：

1. **行动点恢复**：`int(间隔分钟 × 速率)`，写回经
   `StateService.receive_action_points` 夹取 0~100（100 是自然回复上限）。
2. **坐标回落**：回落目标是**性格初始坐标**（`init_intrusion / init_destruction`），
   不是固定中点——每单位回落量走 `fraction × 深度`、不越过边界，随后夹取
   0.5~4.5（`StateService.decayed_coordinates / clamp_coordinates`，规则详见
   [character_evolution.md](character_evolution.md) §3.4）。无性格则不改坐标。
3. **伤亡步进**，粒度分两段：
   - **最近 72h：2 小时明细**。间隔切桶（偶数整点对齐，`_detail_bins`），每桶
     瞬时步进率 = 活动基线 × `step_per_hour` × 作息调制 + 退出残留：
     基线由个性强度归一（缺省 0.5）；作息调制
     `1.0 + swing × (rhythm.factor_at(桶中点) − 1.0)`（§2）；退出残留是
     `基线 × exit_amp × exp(−退出小时数 / exit_tau)` 的指数快衰减。环境因子从
     角色空间档案学习（值域 [0.1, 1.5]，叠加高斯噪声，
     `services/character/spatial.py::EnvironmentProfile`）。每桶伤亡
     `0.01 × 身高² × 步进 × 破坏性 × 环境因子 × log10(身高)`
     （`core/logic/simulation.py::compute_casualty`），逐桶记
     `OfflineDetail(start_at, end_at, step, casualties, env_factor)`。
   - **>72h 的部分：按天汇总一段**（无明细）：基线 × `step_per_hour` × 24 / π ×
     作息均值 × 天数，伤亡同公式但环境因子取按天平均步进率。

**写回**（`apply_recover_plan`）：`state.offline_details` **整表替换**为最近一次
结算的明细；累计伤亡累加；有变化时追加演化行
（`source="recover_evolution"`）。文案 `build_offline_report`：间隔 ≥90 分钟按
小时显示，片段依次为时长、行动点恢复、步进、新增伤亡；间隔无效返回空串。

**在线时的对照路径**（不是结算）：两界面的角色面板每 60s 执行
`StateService.recover_action_points`（恢复量 `int(1 + 0.3 × 个性强度)`）与
`apply_step_decay(state, 0.1)`（每分钟向性格边界回落 0.1 个深度，见
[character_evolution.md](character_evolution.md) §3.4 / §3.6）。负向演化在加载
结算后紧随（行动点 ≥50 跳过，§3.5）。

## 2. 作息学习与外推（`services/character/rhythm.py`）

- **样本**：演化表中 `step > 0` 且时间可解析的行，每行一次活动样本；累进
  **7×12 网格**（星期 × 一天 12 个 2 小时桶，偶数整点对齐，与结算明细同规则），
  只累样本数与步进和。
- **权重**（`_learned_weights`）：每桶均值按 `K=6/(6+样本数)` 向全局均值收缩；
  相对全局的比值再乘**昼夜先验** `_default_day_night`（白天正弦隆起、傍晚下斜、
  凌晨 0.6 下限），夹取 [0.15, 2.5]——作息不归零、单桶不爆炸。无样本时整表
  退化为纯昼夜先验。
- **不持久化**：每次消费都从演化表现场学习（`RhythmService` 无写盘路径）；模型
  的持久化事实来源就是演化表本身。
- **查询与外推**：`factor_at(dt)` 单时刻查表；`forecast(now, horizon_hours=72)`
  产出未来 72h 的 2 小时桶序列（星期维度循环外推，无衰减项）——外推能力已实现，
  当前主程序消费的是 `factor_at` 与权重网格。
- **消费方**：恢复结算逐明细桶取中点调制（§1）；档案简介的「作息观察」段
  （`profile_text.py::describe_rhythm`，样本 <24 措辞降级）；聊天的实时提示
  （`rhythm_now_hint`：样本 <6 静默，因子 ≥1.3 活跃 / ≤0.7 歇息）。作息不参与
  任何准入判定。

## 3. 近况新闻（`services/news/`）

数据源是取材表组的 `news.csv` 成员（列与回落链见 [resources.md](resources.md)
§6），utf-8-sig 读入、`text` 为空的行丢弃，实例级缓存（换组才失效）。

**门控**（`NewsService.choose_for_load`，加载角色后触发，专业版弹「早报」对话框，
挂件版不弹）：9 点前不弹 → 当日已弹过不弹（`state.news_checked_at`）→ 间隔
≥7 天强制「杂物新闻」（`saved_at` 取本次加载前的 `updated_at`）→ 掷
`info_update_rate`（设置档位 0.25 / 0.5 / 0.75 / 1.0，默认 0.5），未中走杂物。

**索引选取**（`_indexed_article`，每次至多 1 条）：按表头顺序逐层收窄——
`size_category` 必须**精确**命中身高分档（`core/logic/sizing.py::get_size_category`）；
`memorial` 期望生日或当日节日（元旦 / 愚人节 / 儿童节 / 万圣节），不中则忽略该
条件；`intrusion / destruction` 取四舍五入 0~4 格上的**最近值**。候选优先选与
`state.last_news` 正文不同的条目；索引失败回落杂物新闻（`size_category` 为空的
行）。渲染替换 `{name}` / `{nick}`，`{a}` / `{b}` 从 substitute 列的逗号队列
随机取一（占位符规则见 [resources.md](resources.md) §6）。

## 4. 剪影预览（`services/preview/`）

「剪影」= 按身材部位参数画出的**正面少女剪影图**（PNG），用于未上传立绘时的
头像兜底；输入只有 `body_parts` 与 `height`，与作息 / 新闻无数据关系。

- **部位参数表** `_PART_PARAMS`：14 项比例参数（步长 / 腿长 / 臂长 / 胸宽 /
  脚长 / 脚踝 / 膝盖 / 大腿与小臂直径 / 手掌 / 食指长与直径 / 指缝 / 指纹），
  各带 (min, max, step)。
- **渲染**：绘制配方 `BodyPreviewPainter` 只描述「画什么」，经 6 个图元原语
  （椭圆 / 多边形 / 线……）输出——不依赖 tkinter；PIL 画布
  `BodyPreviewPilCanvas` 复刻 Tk 平滑样条的采样规则，线宽按设计宽等比放大。
  导出常量 450×800、透明底、4 倍超采样后 Lanczos 缩回；暗色模式对亮通道做
  0.15 亮度衰减（读 `core/appearance.py`）。配色是服务层字面量
  `VIEW_*`（与主题 token 逐值一致，避免反向依赖 UI）。
- **入口与消费**：`render_body_preview_image / render_body_preview_to_file /
  render_preset_preview_image`；创建期与加载期的头像兜底
  （`ensure_avatar_for_state`，开关 `use_preview_image_as_avatar`），挂件参数
  面板直接预览预设。专业界面创建对话框里有一份同款画法副本（差异仅暗色衰减）。

## 5. 档案导出（`services/character/archive_export.py`）

`export_character_mhtml(state, file_path, show_casualties=True)` 把角色打包成
**单文件 HTML** wiki 档案页：图片内嵌 data URI、样式 / 脚本同文件，浏览器直接
打开。模板骨架在 `assets/templates/archive_template.{html,css,js}`，进程内缓存 +
`string.Template` 占位替换。素材取自 `data/archives/<角色id>/`：`avatar/`（图墙，
按修改时间新→旧）、`报告/*.txt`、`回放/*.replay.json`。

| 分区 | 内容 |
|---|---|
| Infobox | 昵称 / 身高 / 生日 / 创建与更新时间 / 标签 / 最新形象图 |
| 灾害分析 | 介入度 / 破坏性指标条（满刻度 4.5，绿→黄→红；深度趋势 ≥±0.25 判增强 / 收敛）+ 分档解读 + 演化统计图 + 应对指南 |
| 人物简介 | 可见简介与隐藏折叠卡、性格名与描述、**作息与活动范围观察段**（`profile_text.py::describe_rhythm` + 空间档案 `describe_spatial`）、达成事件、形象图墙 |
| 物理信息 | wiki 式尺寸表（`ALL_PART_NAMES` ∩ `body_parts`），有解锁情报的部位悬浮显示 |
| 测量报告 | 双栏阅读器（左时间索引右正文），行分类规则与报告面板同套；`show_casualties=False` 时过滤「本报告总计」行 |
| 事件记录 | 副本回放逐条渲染：触发器 / 章节 / 结局卡 + 步进段徽章（背景 / 分支 / 对话 / 互动 / 行动） |

- **演化统计图**（`_build_evolution_chart`，内联 SVG）：只统计**最近 72h**、36 个
  2h 桶（与结算明细同一对齐规则）；恢复结算行优先采用 `state.offline_details`
  的绝对时间区间并入各桶，无明细的旧档按昼间均摊；左轴累计伤亡（单调三次插值，
  不出现「伤亡回落」）、右轴单桶步进（Catmull-Rom 平滑）。
- **应对指南**：疏散范围 = 身高 × 分档系数（<0.5m→2、<1.5→5、<2.5→10、<3.5→18、
  否则 30），无秩序范围 = 疏散范围 × 介入度 / 10；定位单元边长 > 身高 ×100 时
  附加「定位可能不精确」警告。
- **地标悬浮信息**：存档字段 `landmark_durability`（耐久表）与
  `landmark_addresses` 的键是地标的声明身份（`Ref` 文本
  `landmarks:<风格id>/<显示名>`，与地址无关——改地址不清零耐久，Ref 身份见
  [resources.md](resources.md) §5）；导出侧 `Ref.parse` 还原显示名、同名多地址
  合并，报告正文里的地标名替换为悬浮链接。耐久文案阈值：≤0 已损毁 / <0.5 残破 /
  <1.0 受损 / 否则完好。

## 6. 角色卡导出（`services/exploration/export.py`）

角色卡是**机器可读的创建数据搬运格式**（JSON，`version: "2.0"`），供「导入角色
卡」重建角色，**不含任何时间维度内容**（无演化表 / 坐标 / 伤亡 / 结算明细 /
报告 / 回放）：

| 字段 | 内容 |
|---|---|
| `name / nick / original_height / birthday / tags` | 身份与外观 |
| `intro_hidden / intro_visible` | 隐藏与可见简介 |
| `personality_data / preset_data` | 完整性格对象与身材预设比例（从 `body_parts + height` 反解，预设名「名字的身材」） |
| `image_b64` | 头像内嵌 base64 |
| `origin_world` / `world_history` | 出身世界；世界履历仅在开关开启且非空时导出（履历本身始终记录，开关只控制导出） |

从已加载角色导出走 `build_export_card_from_state`（缺性格或身材反解失败抛
`ValueError`）；落盘为 UTF-8 JSON，挂件版扩展名强制 `.chara.json`。与档案导出
共用同一个文件对话框，按扩展名分流：`.html` → 档案，`.json` → 角色卡。

## 7. 文件 / 函数索引

| 要点 | 位置 |
|---|---|
| 结算触发（加载角色时） | `services/exploration/context.py::load_character_state` |
| 结算计划（纯函数 / 钩子） | `services/character/offline.py::build_recover_plan / apply_recover_plan / build_offline_report` |
| 结算执行与参数覆盖链 | `services/character/offline.py::OfflineService.recover_offline / _model / _TUNING_FIELDS` |
| 72h / 2h 固定契约 | `services/character/offline.py::_OFFLINE_WINDOW_HOURS / _OFFLINE_BIN_HOURS / _detail_bins` |
| 基线 / 退出残留 / 作息调制 / 噪声 | `services/character/offline.py::_activity_baseline / _exit_residual_rate / _swing_factor / _offline_noise_std / _rhythm_mean` |
| 出身烙印（结算 8 参默认值） | `core/models.py::ModelTuning / sanitize`；派生 `services/creation_service.py::CreationService.derive_model_tuning` |
| 结算明细与计划数据类 | `core/models.py::OfflineDetail / OfflineRecoveryPlan` |
| 行动点 / 坐标 / 负向演化 | `services/state_service.py::StateService.receive_action_points / decayed_coordinates / clamp_coordinates / recover_action_points / apply_step_decay / apply_negative_evolution`（公式见 [character_evolution.md](character_evolution.md) §3） |
| 伤亡公式 | `core/logic/simulation.py::compute_casualty` |
| 环境因子（结算消费） | `services/character/spatial.py::EnvironmentProfile`（档案见 [report_selection.md](report_selection.md)） |
| 作息学习 / 权重 / 昼夜先验 | `services/character/rhythm.py::RhythmService.learn_from_evolution / _learned_weights / _default_day_night` |
| 作息查询与外推 | `services/character/rhythm.py::RhythmService.factor_at / forecast`、`build_rhythm_forecast` |
| 作息文本化（档案 / 聊天消费） | `services/character/profile_text.py::describe_rhythm / rhythm_now_hint / build_live_context` |
| 新闻服务（门控 / 索引 / 渲染） | `services/news/__init__.py::NewsService.choose_for_load / _indexed_article / _pick_different / _render` |
| 新闻弹窗与档位 | `ui/exploration/news_dlg.py::NewsDialog`、`ui/settings/__init__.py::INFO_UPDATE_OPTIONS` |
| 身高分档（新闻索引用） | `core/logic/sizing.py::get_size_category` |
| 剪影配方 / PIL 画布 / 入口 | `services/preview/__init__.py::BodyPreviewPainter / BodyPreviewPilCanvas / render_body_preview_image / render_body_preview_to_file` |
| 剪影头像兜底 | `services/exploration/character.py::ensure_avatar_for_state`、`services/creation_service.py::CreationService._render_body_preview_to_temp` |
| 档案导出主入口 / 分区 | `services/character/archive_export.py::export_character_mhtml / _build_infobox / _build_analysis_section / _build_bio_section / _build_sizes_section / _build_reports_section / _build_replays_section` |
| 演化统计图（消费 offline_details） | `services/character/archive_export.py::_build_evolution_chart / _collect_evolution_events / _monotone_points / _catmull_points` |
| 应对指南 / 地标悬浮 | `services/character/archive_export.py::_build_guide_block / _evacuation_coef / _landmark_popup_info / _link_landmarks / _durability_text` |
| 地标耐久键生成（报告期写表） | `services/exploration/address_index.py::AddressIndex.durability_key`、`core/resource_ref.py::Ref.scoped / Ref.parse` |
| 角色卡导出 | `services/exploration/export.py::build_export_card_data / build_export_card_from_state`；落盘 `app/window_manager.py::export_character_card_to_path / export_character_card_from_state`、`ui/mini/app.py::_export_card` |
| 角色持久化（结算字段落盘） | `persistence/character_repo.py::CharacterRepo.save / load`（`data/archives/<id>/info.json`） |
