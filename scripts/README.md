# scripts/ — 可复用工具 + 已落地归档

这个目录放**不进 `tests/` 常驻自检**的开发者工具：既包括还在用的可复用工具，也包括
一次性用掉、保留备查的归档（数据迁移脚本、原生崩溃探针）。常驻自检（守卫 / 行为 /
GUI 冒烟）在 `tests/`，由 `python tests/run_checks.py` 统一驱动；另有一批查看资源 / 行为
改动影响（人工检查）的工具在 `developer_tools/`。三者分工见根目录 README
「开发与架构（速查）」。

> **本目录的源码仍会被离线守卫静态扫描。** `check_entrypoints` / `check_import_graph` /
> `check_scenario_naming` 的跳过表里只有 `developer_tools`，没有 `scripts`。放这里的脚本要
> 守「第一方 import 存在」「未知顶层名」「scenario 旧标识符」这些规则——目前只为
> `escape_sim.py` 的 `game` 开了一个口子（`tests/check_entrypoints.py` 的
> `UNDECLARED_ALLOWED`）。迁移脚本不再单独开白名单，旧标识符一律从 `dungeon.terms`
> 取常量。

## 持续维护

| 脚本 | 性质 | 用途 |
|---|---|---|
| `dungeon_autopilot.py` | 真窗口自动驾驶 | 副本窗口全生命周期回归（15 场景，需显示器）：构造 → `run()` → 步进 → 关闭 → 落盘。最强回归，`--in-process` 连跑全部场景，`--scene <名> --isolate` 单跑。**进 CI**（`.github/workflows/gui-smoke.yml`，跳 `text-components` 实跑 14 个） |
| `escape_sim.py` | 无头模拟（**进 CI**：`checks.yml`） | escape_giantess 小游戏逻辑回归（无显示器可跑）：关卡生成硬约束（出口 / 出生点可站 / 连通区不塌）→ 随机走位压一段 → 强制一次胜、一次负校验 `api.finish` 的 payload 形状。种子默认固定（`--seed N`，`--seed random` 走真随机），保证门禁可复现。与 `dungeon_autopilot --scene mini-game-escape`（只验渲染链路）互补 |
| `child_dpi_probe.py` | 探针（**不判红**） | 副本子进程 DPI 感知：拉两个子进程打印各自的 `GetDpiForSystem()` 与注册表 `AppliedDPI`，人工对照。原 `tests/check_dungeon_child_dpi.py`——"感知探针应等于 AppliedDPI"的前提在真机不成立（本机 168 vs 192），当门禁只会长期报红，2026-10-13 迁来 |
| `platform_api_report.py` | 报告（**不判红**） | Windows 专有 API 落点清单，发布 macOS 前过一眼。原 `tests/check_platform_compat.py`；它原先兼守的"模态对话框不得构造期裸 `grab_set()`"判红约束已归 `tests/check_modal_grabs.py` 专职（AST 版 + 行为分支），2026-10-13 迁来 |
| `scenario_validate.py` | 批量校验（**CI 显式调用**） | 副本方案配置批量校验（`validate_scenario_config`，含资产存在性），有 error 退出码 1。原 `tests/check_scenarios.py`——它校验的是 `data/` 下的用户方案而不是仓库代码：本地编辑自己的方案出错会弄红 `run_checks.py`，CI 的干净检出里没有这些方案、永远不红，方向反了；且会被 `run_checks.py` 与 CI 显式 step 各跑一遍。2026-10-13 迁来，`tests/` 只留代码守卫 |

## 数据迁移（v1.0.0 → 当前）

`migrate_from_v1.py` 是**唯一**的数据迁移入口，取代了原先按单项改动切分的
`migrate_resource_ids.py` / `migrate_scenario_naming.py` / `migrate_snapshot_evolution.py`
（后三者已删除：它们只覆盖当时的某一处破坏性更改，对 v1.0.0 的完整目录跑一半就会停，
残留的中间状态还会让后续步骤走错分支）。

    python scripts/migrate_from_v1.py                    # 预览，只打印变更与待办
    python scripts/migrate_from_v1.py --apply            # 落盘（先整目录备份）
    python scripts/migrate_from_v1.py --report out.md    # 变更 + 人工清单写 Markdown

- 幂等：第二次跑输出「0 处变更」。落盘前把整个 `data/` 复制到
  `<data>.rollback-<时间戳>/`，回滚就是把它覆盖回去；单文件改写另留 `.bak`，
  被替换的旧文件移到 `data/migrated/v1-legacy/`。
- 十步按依赖排序：设置分家 → 取材表 → 地标风格 → 描述风格 → 副本方案 → 世界包
  （含 `.world.zip` 重打包）→ 角色档案 → 行为包 → 结局索引 → 资源信封。目录改名
  在引用改写之前，信封最后补，因为内容哈希依赖最终内容。
- 资源 id 与引用统一走 `core/resource_spec.valid_id_for`，旧名映射表只有一张
  （`ChineseMix → chinese_mix`、`Events → events`、`_default → default`、
  `巨影临城 → juying_lincheng`）。
- `--report` 产出的「需要人工处理」表是交付物的一部分：**改不动的部分不会被静默
  跳过**。涉及旧的 `theme_mode`、性格表步长量纲、`view_mode → coupling_level`
  的语义猜测、失效的触发器动作（`background` / `sensitivity` / `ending`）、
  缺失章节模型、以及回放文件（`.replay.json` 不做改写）。

`dungeon/settings.py`、`persistence/scenario_repo.py` 等模块自身仍保留就地兼容读
（打开旧目录时自动归一化），迁移脚本负责把它们一次性推到当前形状，两者不冲突。

## 已落地归档（留档备查，不再演进）

| 脚本 / 目录 | 性质 | 说明 |
|---|---|---|
| `dpg_probe/` | 一次性调查留档 | DPG 2.3.1 原生崩溃（首帧 `0xC0000005`）追查的现场工具，**只存档不复用**。原在 `developer_tools/`，2026-10-08 迁来。2026-10 的 imgui 迁移（P8）把 `dearpygui` 移出 `requirements.txt` 后，直接依赖它的探针**不再能直接运行**（需临时 `pip install dearpygui`）；通用原生崩溃工具不依赖 DPG，仍可用。见文末 |

约定：归档项**完成后不删**（幂等 + 有 `.bak`，可对旧存档重放；探针是下次原生
崩溃的现场工具），但**不再演进**。需要长期维护的回归请写成 `tests/smoke_*.py` 或
`tests/check_*.py`。

**例外是数据迁移脚本**：一旦后续的破坏性更改让它的输出不再等于当前形状，它就从
「可重放」变成「会把旧目录改成半迁移状态」，此时由新的完整迁移脚本取代并删除旧的，
不要两份并存。

## 产物

各工具的落盘产物统一写 `scripts/_out/`（整目录不入库，见根 `.gitignore`）：

| 子目录 | 来源 |
|---|---|
| `_out/dpg_probe/` | `dpg_probe/` 各探针的 `_*.txt` / `*.dmp` / `_dpg_bindings.json`（共享常量 `OUT_DIR` / `out()` 在 `dpg_probe/_outdir.py`） |

`dungeon_autopilot.py` / `escape_sim.py` / `migrate_from_v1.py` / 两个探针
（`child_dpi_probe.py`、`platform_api_report.py`）都不落盘（迁移脚本直写 `data/`，
清单用 `--report` 显式指定路径）。

## 附录：dpg_probe/ 说明

DPG 2.3.1 的 Windows wheel 是 ANSI(MBCS) 构建，非 ASCII 标题建窗会**静默失败**，随后
首帧渲染必现访问违例。这批探针是当时追这一例留下的现场工具，**只存档不复用**——留着
是因为下次遇到原生崩溃还得靠它们。**脚本留在此目录，产物统一写 `_out/dpg_probe/`**
（共享常量在 `_outdir.py`），因此探针目录里只有代码。三层结构：

> 依赖说明（2026-10，imgui 迁移 P8）：`dearpygui` 已从 `requirements.txt` 移除。
> `_probe_dpg_min.py` / `_probe_fabric.py` / `_probe_bindings.py` / `_probe_pyd.py`
> 直接 import dearpygui，**不能直接跑了**（要跑先临时装回）；而
> `_probe_native.py` / `_probe_veh.py` / `_veh_filter.py` / `_probe_dbg.py` 是通用
> 原生崩溃工具链（ctypes + dbghelp + minidump），对 imgui 迁移后的崩溃同样可用。

- **抓现场（四条路，按需挑一条）**：`_probe_native.py`（纯 ctypes + dbghelp，进程内装
  vectored exception handler，打印「模块!符号+偏移」与栈扫描链，也是 `_probe_crash_run` /
  `_probe_trace` 的后端）、`_probe_veh.py`（VEH 宿主）、`_veh_filter.py`
  （`SetUnhandledExceptionFilter` + minidump，不影响 first-chance 分发）、
  `_probe_dbg.py`（进程外迷你调试器，不注入子进程）。
- **跑 + 出结论**：`_probe_run.py`（带超时跑命令，报告写 `_out/dpg_probe/_probe_last.txt`）→
  `_probe_report.py`（读同一份给紧凑结论）；`_probe_trace.py` 是带面包屑的启动器。
- **自检与单点复现**：`_probe_av.py`（故意触发 AV，验收处理器还活着）、
  `_probe_symtest.py`（验收 dbghelp 能命名地址）、`_probe_veh_selftest.py`、
  `_probe_dpg_min.py`（最小 DPG 渲染）、`_probe_fabric.py`（织物绘制复现）、
  `_probe_bindings.py` / `_probe_pyd.py`（导出表 / RVA，给纯地址命名）。

注意：这些探针依赖 Windows 专有 API（`ctypes.WinDLL`、dbghelp、minidump），**在
macOS / Linux 上跑不了**。但离线守卫只对源码做 AST 静态解析、**不执行**它们，所以放进
`scripts/` 后门禁照样过（`dearpygui` 在 `check_entrypoints.py::UNDECLARED_ALLOWED` 里
留了一处例外）。
