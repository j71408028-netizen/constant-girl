# macOS 支持说明

## 1. 支持范围

| 环境 | 状态 | 说明 |
|---|---|---|
| macOS 12+ · Apple Silicon（M1 及更新） | ✅ 支持 | 发行包为 `ConstantGirl.app` |
| macOS · Intel | ❌ 不支持 | 副本窗口渲染依赖 `imgui-bundle==1.92.900`，该版本只发布 macOS **arm64** wheel，Intel 无从安装 |

这里的限制来自第三方依赖，不是本项目可为 Intel 单独打补丁绕过的；在 Intel Mac 上
`pip install -r requirements.txt` 就会失败。

## 2. 安装与运行

从 [Releases](https://github.com/j71408028-netizen/constant-girl/releases) 下载 macOS 压缩包并解压：

- 直接双击 `ConstantGirl.app`。首次打开需**右键 →「打开」**（未签名/未公证的应用会被
  Gatekeeper 拦下，这是预期行为）。
- 包内同层还有 `.command` 维护入口；若 `.app` 不可用，它会退到裸目录可执行文件。

用户数据写在 `~/Library/Application Support/constant-girl/data`，首启从包内资源拷出可写副本。

## 3. 字体与显示

中文字体走系统自带字体（苹方 / 冬青黑体 / 宋体），由 `fonts` 的平台分支解析；
找不到时退回默认字体，不会导致启动失败。副本窗口使用原生窗口服务，**不需要 X11/Xvfb**。

## 4. 验证现状

[`macos.yml`](../../../.github/workflows/macos.yml) 在 `macos-latest`（当前为 arm64）runner 上分两档验证：

- **每 PR / 推 main**：整份依赖安装、导入自检、全部离线守卫、默认方案校验、小游戏无头模拟；
- **每晚 + 手动**：原生窗口下的副本窗口自动驾驶、`smoke_mini`、`smoke_switch`，以及用官方
  `build/macos/build_macos.sh` 打包后核对 `.app` 结构（含随包原生库清单）并上传产物。

这些是**自动化证据**，不等于所有平台验收完成。以下项目 CI 无法覆盖，仍需真实用户环境补全：

- 下载后带 `com.apple.quarantine` 隔离属性时的「首次打开」体验与公证提示；
- 真实音频外放听感、字体渲染与动画的人眼观感；
- 真实旧版本数据目录的升级路径。

## 5. 已知限制

- **Intel Mac 不可用**（见 §1）。
- **未签名 / 未公证**：首次打开需要右键绕过 Gatekeeper。
- 打包产物为 `.app`，暂无 `.dmg` 安装器与桌面集成。
