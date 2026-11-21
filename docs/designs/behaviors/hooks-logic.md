# 行为包钩子：尺寸与文本（面向作者）

> **这一篇回答什么问题**：尺寸怎么格式化、伤亡怎么算、屏蔽词与地标对比怎么判、档案里的
> 作息与空间描述怎么措辞——这些「全流程共用的小函数」各自的签名与覆盖后果。
> - **想换单位 / 换文案 / 换伤亡口径**：看 `logic` 组对应行。
> - **想改档案里的观察段落**：看 `profile` 组的返回约定（空串表示整行省略）。
>
> 所属机制：[行为包](README.md)（玩家向）· [开发指南](dev-guide.md)。注册方式、
> 签名一致性与层级约定见开发指南的「注册 API」「钩子目录与层级」。

## `logic`（模块函数与常量）

默认实现的位置：与副本 / 结算共用的基础设施算法（`apply_size_unlock_updates` /
`compute_environment_factor` / `compute_casualty` / `format_size` /
`length_unit_label` / `should_skip_by_part_tags` / `contains_blocked_word` /
`get_comparisons`）在 `core/logic/`；报告侧描述专属的（`PREDEFINED_TAGS` /
`replace_quip_tags` / `build_size_description`）在
`services/exploration/quips.py`。key 都是公开契约，与文件位置无关。
描述选句 `select_quip_with_budget` 已收回为内部函数，不再接受行为包覆盖。

| 目标 | 签名 / 形态 | 说明                                                                                         |
|------|------|--------------------------------------------------------------------------------------------|
| `logic.PREDEFINED_TAGS` | `List[str]` | 预定义标签常量。覆盖可注册列表值，或返回列表的可调用对象；读取入口为 `logic.get_predefined_tags()`。                          |
| `apply_size_unlock_updates` | `(unlocks, updates, info_update_rate=0.5) -> Dict[str, str]` | 写入部位解锁信息。                                                                                  |
| `compute_environment_factor` | `(text) -> float` | 按文本中的环境关键词给出伤亡环境系数。                                                                        |
| `compute_casualty` | `(height, step, destruction, text, env_factor=None) -> float` | 计算一段文本的伤亡增量。                                                                               |
| `format_size` | `(size, base_size=None) -> str` | 尺寸格式化（米 / 千米，含小数位对齐），全流程共用。                                                                |
| `length_unit_label` | `() -> str` | 当前基础长度单位标签（默认“米”），供界面输入/单位标签显示。覆盖 `format_size` 换单位时，一般也覆盖本函数让输入标签一致。 |
| `replace_quip_tags` | `(quip_text, style, size_cat, detail_pools, quips_working=None, intr=None, dest=None, enable_confusion=False, allow_confusion_map=None) -> str` | 替换描述中的 `[类型:编号:文本]` 标记。                                                                    |
| `should_skip_by_part_tags` | `(part, selected_tags, p) -> bool` | 在构造对比时，按与部位展示有关的个性标签添加偏好。                                                                  |
| `contains_blocked_word` | `(text, blocked_words) -> bool` | 判断文本是否包含任一屏蔽词（大小写不敏感的子串匹配）。覆盖后地标匹配、描述匹配与副本提示词过滤都会生效。 |
| `get_comparisons` | `(landmarks, body_parts, order="match", limit=5, selected_tags=None, skip_base_prob=0.0, selected_parts=None, blocked_words=None) -> List[Dict]` | 寻找最接近的地标对比。名称含屏蔽词的地标会被跳过（内部调用 `contains_blocked_word`）。                                                                                |
| `build_size_description` | `(quip_result) -> str` | 由报告正文中的一条尺寸对比结果构造解锁描述。 |                                                                     |

## `profile`（档案派生层文本化，模块函数）

消费方：角色档案导出的「作息与活动范围观察」块、聊天人设与系统提示词。
返回约定：**纯文本多行（不含 HTML）**；实时提示在样本不足 / 零证据时返回**空串**
（消费方据此整行省略）。默认实现会按样本成熟度自动降级措辞，覆盖实现建议保留该约定。

| 目标 | 签名 | 说明 |
|------|------|------|
| `profile.describe_rhythm` | `(evolution, now=None) -> str` | 作息历史结论（活跃/安静时段、周末与工作日差异、成熟度措辞）；无样本返回空串。 |
| `profile.rhythm_now_hint` | `(evolution, now=None) -> str` | 作息实时提示：当前时刻活跃期 / 休整期各一行措辞，平常时段与样本不足时返回空串。 |
| `profile.describe_spatial` | `(profile, position="") -> str` | 空间偏好历史结论：常活动地带、环境偏好、手工活动区域。`profile` 是 `services.character.spatial.build_spatial_profile` 的装配结果。 |
| `profile.spatial_now_hint` | `(profile, position="") -> str` | 空间实时提示：当前位置相对偏好的评价 + 环境口语化描述；零证据返回空串。 |

## 覆盖示例

换掉预定义标签常量（`logic.PREDEFINED_TAGS` 是常量细度钩子，`impl` 必须是列表或返回列表
的可调用对象）：

```python
TAGS = ["温柔", "冷淡", "古典", "野性"]


def register(runtime):
    runtime.override("logic.PREDEFINED_TAGS", TAGS)
```

想让比较句里不出现某个地标名，覆盖 `logic.contains_blocked_word` 即可——地标匹配、描述
匹配与副本提示词过滤会一起生效。

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
- **behaviors/**：[README](../behaviors/README.md)（玩家向）·
  [dev-guide](../behaviors/dev-guide.md)（行为包开发）· 钩子契约四篇
  （[logic](../behaviors/hooks-logic.md)（本页） / [report](../behaviors/hooks-report.md) /
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
