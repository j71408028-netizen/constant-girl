# developer_tools/ — 人工检查的快捷工具

`developer_tools/` 是**查看资源与行为改动所造成影响的快捷工具**。改完一份资源包（地标 /
描述 / 副本 / 小游戏）或行为包，不必真去开局或进副本，用这里的工具就能把改动的效果直接
摆到眼前：起个小服务刷新看渲染、在独立窗口单跑一个小游戏、对语料跑一次体检、把演化模型
批量模拟出图。

仓库里放开发期脚本的地方有三个，分工如下（速查表见[AGENTS.md §4](../AGENTS.md)）：

| 目录 | 是什么                                                         | 与离线守卫的关系 |
|---|-------------------------------------------------------------|---|
| `tests/` | **常驻自检**：守卫 / 行为 / GUI 冒烟，`python tests/run_checks.py` 自动发现 | ✅ 就是门禁本身 |
| `scripts/` | **可复用工具 + 已落地归档**：真窗口回归、无头模拟、数据迁移、一次性探针留档                   | ⚠️ 不提供自检项，但源码仍被**静态扫描** |
| `developer_tools/` | **人工检查的快捷工具**：看资源包 / 行为包改动的效果                               | ❌ 被三个离线守卫整体排除 |

判据：**「能一眼看到资源 / 行为改动效果」的就放这里**——改完东西反复想"看一眼对不对"的
预览 / 体检工具。一次性用掉就完事、只留档不复用的，去 `scripts/`（例：`scripts/dpg_probe/`）。
注意两边**都不是** `run_checks.py` 的检查项，但 `developer_tools/` 被 `check_entrypoints` /
`check_import_graph` / `check_scenario_naming` 一致排除，而 `scripts/` **不排除**——往
`scripts/` 放东西要守那三个守卫的规则，见 [`scripts/README.md`](../scripts/README.md)。

## 面向谁 / 现状

改动的来源不只有核心开发者：**描述风格与小游戏的改动都可能来自资源开发者**，他们改完也要
有个地方立刻看效果。这些工具当前的开放程度并不一致：

| 工具 | 对应的改动 | 现状 |
|---|---|---|
| `quip_report.py` | 描述风格（quip 语料） | ✅ 描述风格改动可能来自资源开发者，直接可用；判据与主程序描述管理页的「校验」按钮是同一套（`services/exploration/quip_lint.py`）。人改语料用界面更快，脚本与本机 Agent 走 `--json` |
| `quip_draft_bench.py` | 描述素材草稿（出题 / 写 / 收卷 / 校正） | ✅ 题材数据在 `quip_profiles/`，换世界观不用改代码；人写、AI+人审、agent 全自动三条路共用同一套判定。**题面按 DeepSeek 调过、也只在 DeepSeek 上验过，且尚未完全稳定**（见下）。场景卡与题面的口径见 [`quip_profiles/README.md`](quip_profiles/README.md) |
| `minigame_preview.py` | 小游戏 | ✅ 小游戏改动可能来自资源开发者，直接可用 |
| `archive_preview.py` | 角色档案导出 | ⏸ **HTML 档案模板暂不开放**——当前只服务核心开发者调模板，尚不作为资源开发者的扩写点 |
| `evolution_dump.py` | 演化模型 | ✅ 可加载行为包（`--pack` / `--world`）——不用建世界包、不用开局，直接看行为包对演化的覆盖效果；不指定包时只反映核心演化模型自身的改动 |
| `behavior_hooks_report.py` | 行为包钩子 | ✅ 写行为包前先看一眼：按 scope 列出全部可覆盖目标（细度 / 层级 / 签名 / 常量默认值），`--json` 给机器可读目录；`evolution_dump.py --list-hooks` 同一入口 |

## 命名：`<领域>_<输出>.py`

文件名 = **检查领域** + **运行输出**，下划线相连。输出固定四类，它决定工具「怎么把结论
交给你」——也决定要不要落盘：

| 输出类别 | 后缀 | 形态 | 落盘 |
|---|---|---|---|
| 打开预览 | `_preview` | 起窗口 / 起本地 HTTP / 控制台交互，人眼看、可实时刷新 | 无 |
| 控制台工作台 | `_bench` | 控制台交互 + 反复产出素材：出题、写、校验、落盘 | 写 `_out/`（或用 `--csv` 指定） |
| 简略报告 | `_report` | 往 stdout 打结论（可 `--json`） | 无 |
| 详细产物 | `_dump` | 出文件：PNG / md / txt / dmp / json | 写 `_out/` |

| 工具 | 领域 | 输出 | 用途 |
|---|---|---|---|
| `archive_preview.py` | 角色档案导出 | 打开预览 | 改 `services/character/archive_export.py` 后起个小服务，F5 即用最新代码重渲染角色档案 |
| `minigame_preview.py` | 小游戏舞台 | 打开预览 | 不进副本，直接在独立 imgui 窗口跑一个小游戏；帧时钟 / 输入层 / 纹理上传与副本同一套 |
| `quip_report.py` | quip 语料 | 简略报告 | 检查 `data/packs/quips/<风格>/` 的 `quips.csv`、`config.json` 类型 meta、标记格式、单条文本排版，以及类型替换的**组合级语法风险**并双向溯源。**一次只查一个风格的一个尺寸档**。判据全在 `services/exploration/quip_lint.py`——主程序描述管理页的「校验」按钮走同一个 `lint_style`，本脚本只负责读盘与呈现。缺省文本只出结论（一条一行，组合级问题附缩进溯源链）；meta 表与语法统计这类调判据用的详细视图只在 `--json` 里。不带风格跑命令会列可选分组（每档的坐标/条目/标记数），加 `--json` 给机器读的同一份清单 |
| `quip_draft_bench.py` | 描述素材草稿 | 控制台工作台 | 按隐坐标轮换场景卡出题、校验、落盘，事后可人工校正坐标。**一次只做一个观测等级**：目标跨等级直接报错，`--band` 挑一个（等级内部自洽，跨等级写出来的东西事后按坐标改不回来；一个等级约 20~100 条，正好是一次写的上限）。**每级 14 格**：(1,4)、(4,1) 两根轴的端点互相否定、不存在；写哪几格看 `status` 的缺口，用 `--cell 档位:主轴:副轴` 指定。三种写手走同一管道：`write` 人逐条写、`draft` AI 生成后人工逐条裁决、`fill` agent 无人值守（带失败原因重试）；`prompt` 只出提示词不调 API。AI 的两条路一次调用写一组（`--batch`，默认 3 条相邻的卡），`--seed` 默认每次随机。题面形态（着重部位 · 动作类型 · 表现手法 · 视角 · 可接触范围）与各字段含义见 [`quip_profiles/README.md`](quip_profiles/README.md)。题材数据在 `quip_profiles/`，`--profile` 切换；判定口径随 profile 走。**题面针对 DeepSeek 调过、也只在 DeepSeek 上验过，尚未完全稳定**：一到两成条目仍要人手改（主要是破坏用词、字数不足），个别批会整格被模型的自我检查污染，破坏性 2 与 3 的边界仍会飘。换后端要重看题面；别一次跑满整档，先跑一格看 |
| `behavior_hooks_report.py` | 行为包钩子 | 简略报告 | 把 `runtime.catalog()` 按 scope 分组打到 stdout（细度 / 层级 / 签名 / 常量默认值），可 `--scope` 过滤、`--json` 机器可读 |
| `lens_preview.py` | 聊天话题视角 | 简略报告 | 改完 `services/chat/topic_kinds.py`（类型定义）或 `topic_lens.py`（字段目录）后，对真实存档逐类型打印"此刻给 AI 的信息"，附取用/挡掉账本；`--kind X --full` 可看整份系统提示词，`--out` 另存到 `_out/lens_preview/` |
| `chat_session_preview.py` | 聊天会话 | 打开预览（控制台） | 在控制台里跟角色**实际聊天**，每轮打印视角账本（取用/挡掉/预算）、话题变化、属性与原始 JSON；`/topic` 锁定类型、`/attitude` 验证隐藏介绍门槛、`/reroll` 同前提重掷。默认在 `_out/` 沙盒里聊，**不写 `data/`** |
| `evolution_dump.py` | 演化模型 | 详细产物 | 演化模型二阶退化模拟（**角点 + 默认性格表**，可 `--pack` / `--world` 加载行为包），出 PNG 与 `report.md`；需要 matplotlib |

## 产物统一写 `_out/`（整目录不入库）

落盘产物都进 **`developer_tools/_out/`**，按工具分子目录：

| 子目录 | 来源 |
|---|---|
| `_out/evolution/` | `evolution_dump.py`（`--out` 可改写别处；带 `--pack` / `--world` 时嵌一层 `pack_<名>/`，与基线目录并排对比） |
| `_out/lens_preview/` | `lens_preview.py --out <文件名>`（不传 `--out` 时只打 stdout） |
| `_out/chat_session_preview/` | `chat_session_preview.py`：`sandbox/<角色ID>/` 是会话用的数据副本（档案 + 聊天记录，`--fake` 另开 `sandbox_fake/`），`logs/` 存放 `--log` 写出的会话记录 |
| `_out/quip_draft/` | `quip_draft_bench.py`：默认 CSV（`<profile>.csv`）、`write` 存的草稿 `drafts-*.jsonl`、`plan --out` 的题面 |

好处：根 `.gitignore` **一行**就够（`/developer_tools/_out/`）——新增工具无论写多少种后缀
的产物都不必再动忽略规则。`_out/` 本身不入库，克隆后不存在，首次运行时由脚本自动创建
（`evolution_dump.py` 靠 `--out` 目录的 `mkdir(parents=True, exist_ok=True)`）。

**预览 / 报告类工具不落盘**：`archive_preview.py` 只起 HTTP 服务、`quip_report.py` 只打
stdout，都不产生需要排除的文件。例外是 `chat_session_preview.py`：它需要一份可写的
数据副本才能真聊，默认把档案复制到 `_out/chat_session_preview/sandbox/`（仍在 `_out/`
之内，不碰 `data/`），`--data-dir` 才会改用别处。

`_bench` 本来就是产出工具，落盘是常态：`quip_draft_bench.py` 默认写
`_out/quip_draft/<profile>.csv`，要读写仓库里的现成语料必须显式 `--csv`。

## 新增文件请照这 8 条

1. **文件头必须有模块 docstring**：第一行一句话说清"这是干什么的"，接着写**可直接复制
   的用法**（含 `python developer_tools/xxx.py` 全路径）、产物落在哪、有什么前置条件
   （依赖 / 需要显示器 / 会读哪些数据）。
2. **命令行用 argparse**，`--help` 能看全用法。纯探针可以不收参数，但 docstring 里得写清
   怎么跑、预期看到什么。
3. **不依赖 CWD**：仓库根用 `Path(__file__).resolve().parents[1]` 或 `paths.py` 定位；
   产物**一律写 `_out/<工具名>/`**，别在仓库根或脚本目录撒文件。
4. **打印中文时建议显式 UTF-8**：Windows 控制台与重定向管道的默认编码不一致，多行中文
   输出容易出现乱码。`quip_report.py` 在模块开头加了
   `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`，照抄即可（仓库其余部分
   没有这个习惯，所以这条是「建议」而非「必须」）。
5. **只读用户数据**：`data/` 是用户数据区（见 `docs/dev/architecture.md` §2.2），这里的工具
   不写它——要落文件就写 `_out/` 或系统临时目录。清理产物用
   `shutil.move(..., tempfile.mkdtemp())`，**不要 `rm`**。
6. **不加运行期依赖**：只用 `requirements.txt` 里已有的（`imgui_bundle` / `Pillow` / …）。
   确实需要私有依赖（如 `evolution_dump.py` 的 matplotlib）就在 docstring 里写明，并在
   import 处给一句可读的安装提示，而不是抛原始 `ImportError`。
7. **命名**：顶层工具叫 `<领域>_<输出>.py`（`quip_report.py`，不要 `check2.py`；后缀只准
   `_preview` / `_bench` / `_report` / `_dump` 四种）。`_preview` 是「看效果就走」，`_bench`
   是「反复出题—写—校验—落盘」的工作台，两者都不改变用户数据。带下划线前缀的特殊集合（如 `scripts/dpg_probe/`
   的 `_probe_*`）另有自己的约定，写在它那一侧的 README 里。
8. **要长期维护的判定逻辑搬进 `services/` 或 `tests/`**：这里可以"很笨"，但别让门禁反过来
   import developer_tools。描述语料的判据在 `services/exploration/quip_lint.py`（命令行与
   主程序共用），回归在 `tests/check_quip_lint.py`，已挂 `tests/run_checks.py`——新增检查项
   请改那两处，不要在本目录再养一份只在命令行生效的判定。

## 入库范围

入库的是**脚本本体**与 `quip_profiles/` 里的样板。不入库的两类（规则见根 `.gitignore`）：

- `_out/`（整目录；目前只有 `evolution_dump.py` 的 PNG / md 与 `quip_draft_bench.py` 的 CSV / jsonl）
- `quip_profiles/*.json` 中除 `template.json` 以外的题材数据（一个题材就是一位作者的口径，各写各的）

`__pycache__/`、`*.pyc` 全局已忽略。

## 附录：现有文件的 module docstring 覆盖

规范第 1 条是硬要求，本目录 8 个 `.py` 目前 **全部有模块 docstring**，新增文件请保持。
核对方法：

```bash
python - <<'PY'
import ast, pathlib
for p in sorted(pathlib.Path("developer_tools").rglob("*.py")):
    if "__pycache__" in str(p):
        continue
    if ast.get_docstring(ast.parse(p.read_text(encoding="utf-8"))) is None:
        print("无 docstring:", p)
PY
```

## 已迁出的东西

`dpg_probe/`（DPG 原生崩溃的一次性调查留档）2026-10-08 起搬到
[`scripts/dpg_probe/`](../scripts/dpg_probe)——它自述「只存档不复用」，既不是资源 / 行为改动
的入口、也不会反复拿来"看"，不符合本目录的判据。其产物随之落 `scripts/_out/dpg_probe/`，
说明见 [`scripts/README.md`](../scripts/README.md)。DPG 专属的 5 支探针已在 2026-11-09
随 `dearpygui` 依赖移除一并删除，只留通用的 Windows 原生崩溃工具。

`quip_filler.py`（旧「描述填充」GUI）2026-08 起曾在本目录，随目录清理删除。它的 GUI 部分
**没有恢复**：选题、AI 提示词组装、响应容错解析、保存前校验这四件事已经并进
`quip_draft_bench.py`（`draft` / `fill` / `prompt`），且不再依赖 customtkinter。
`quip_profiles/` 是纯数据目录，不是工具，不受「`<领域>_<输出>.py`」命名约束。其中只有
`template.json`（通用起点，从作者本机的 `giantess.json` 复制）入库；具体的题材数据各人写各人的，
已在根 `.gitignore` 里排除。档位的名字与区间（`small`…`colossal`）由主程序
`core/logic/sizing.py` 定，profile 只填每档的 `can` / `anchor` / `limits`，`doctor` 会与主程序比对；
写哪几档随题材，缺档位不报错，只提示。
