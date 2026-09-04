# Clash Verge IP Checker Auto

[English](README.md) | [简体中文](README.zh-CN.md)

一个给 Clash Verge Rev 用的本地节点整理工具。它会读取本机配置，检测节点出口 IP 质量，导出新的 checked YAML，再通过导入链接把结果加回 Clash Verge。

这是基于 [tombcato/clash-ip-checker](https://github.com/tombcato/clash-ip-checker) 做的个人改造版。这个版本主要解决我在 Clash Verge Rev 里日常使用不顺手的问题：自动读取本机配置、导出前筛掉高风险节点，并把最终启用动作留给用户确认。

只建议在自己的电脑或可信局域网使用，不要部署到公网。

## 功能预览

以下截图只使用演示订阅、演示节点和文档保留 IP，不包含真实订阅、节点、密钥或网络信息。

![脱敏后的节点检测与导出界面](docs/assets/screenshots/overview.png)

检测开始前会展示宿主机网络影响，并允许取消操作：

![检测前的宿主机网络影响确认](docs/assets/screenshots/network-impact-confirmation.png)

## 与原项目的主要差异

- 直接读取 Clash Verge Rev 本机配置，不需要把订阅 YAML 复制到页面里。
- 自动查找 Clash Verge Rev 数据目录、`profiles.yaml`、订阅 YAML、External Controller 地址和本机已有 secret。
- 默认只展示可检测的 Remote / Local 主订阅；Merge、script、rules 等配置片段单独折叠。
- IPPure 快速检测没有沿用原项目检测端，也没有启用 Ping0/Fallback。
- 导出新的 checked YAML，不覆盖原订阅、不写回 `profiles.yaml`、不自动替换或启用当前订阅。
- 手机订阅 URL/二维码只在 LAN 启动模式下生成；它只是导入导出 YAML 的入口，不负责启动服务。
- LAN 模式只给可信设备下载本机导出的 YAML，不带登录层，也不适合公网。
- 节点观测写入 SQLite `data/results.sqlite3`；成功的 IP 风险结果另存到可同步的 `sync/ip_reputation_cache.json`，相同出口 IP 在 14 天内可复用。
- 默认只勾选已完成检测且风险分数不高于 30% 的节点；Pending、失败、未知和高风险节点默认不选。
- 按出口 IP 去重，并保留导出文件列表，减少重复节点和手动筛选。

## 功能

- 读取 Clash Verge Rev 的 `profiles.yaml` 和 `profiles/` 下的 YAML 文件。
- 检测节点时通过 Clash External Controller 临时切换模式和节点。
- 默认使用 IPPure 快速检测节点出口 IP 质量。
- 可选浏览器检测模式，速度较慢，但信息更完整。
- 在本地 `exports/` 下导出新的 `*_checked.yaml`。
- 生成 `clash://install-config` 导入链接；LAN 启动模式下还会生成用于录入已导出 YAML 的手机订阅 URL/二维码。

## 安全边界

- 不覆盖现有 Clash Verge 配置文件。
- 不直接编辑 `profiles.yaml`。
- 不调用 Clash Verge 内部 Tauri IPC。
- 不自动替换或激活当前订阅。
- 导入后的 checked 订阅需要用户在 Clash Verge 内手动检查并启用。
- 检测前会验证 External Controller，并通过二次确认明确提示宿主机网络可能受到的影响。
- 检测过程中会通过 Clash External Controller 临时切换 Clash 模式和当前节点；正常完成、停止或异常时，都会先恢复原节点和原模式，再释放任务锁。
- 检测非当前订阅并开启临时加载时，会临时 reload Clash core 配置，结束后按“运行时配置 → 原节点 → 原模式”的顺序恢复。

最后一步需要回到 Clash Verge 里手动确认。启用或替换订阅会改变真实流量路由，这里不自动替用户做决定。

## 运行要求

- Python 3.10+。
- 已安装 Clash Verge Rev。
- 检测时 Clash Verge Rev 需要处于运行状态。
- Clash Verge Rev 需要启用 External Controller。
- 被选订阅必须是本地 YAML 文件支撑的 Remote 或 Local 主订阅。

## 准备 Clash Verge Rev

1. 打开 Clash Verge Rev。
2. 进入设置页面。
3. 找到 Clash/Mihomo 内核设置区域。
4. 如果你的版本提供 External Controller 或 HTTP controller 开关，请启用它。
5. 尽量保持 controller 绑定到本机地址，例如 `127.0.0.1:9097`。
6. 如果 controller 设置了 secret，请只保存在本机。不要把 secret 粘贴到 GitHub issue、聊天、截图或公开日志里。

不同 Clash Verge Rev 版本的 UI 文案可能不同。如果本机 `config.yaml` 已经存在 `external-controller`，本工具会自动读取该值。

API secret 输入框只是备用入口。如果本机 Clash Verge 配置里已有 secret，后端会直接读取，但不会显示在页面上。

## 快速开始

### macOS

```bash
./run_mac.command
```

脚本要求 Python 3.10+。仅当 `.venv` 新建、损坏或 `requirements.txt`
发生变化时才准备依赖；随后启动本地 Web UI。8080 仍是默认端口；如果
被其他程序占用，启动器会从 `18080-18120` 选择第一个空闲端口，写入
Git 忽略的本机运行状态，并在以后优先复用。终端会显示并打开实际地址，例如：

```text
http://127.0.0.1:8080
```

### Windows

```bat
run_windows.bat
```

Windows 启动器使用相同的环境、动态端口与依赖指纹检查，随后启动本地 Web UI，
并打开实际选择的地址，例如：

```text
http://127.0.0.1:8080
```

### 手动启动

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python web.py
```

手动入口同样使用已持久化的端口选择。请打开进程输出的实际地址，例如：

```text
http://127.0.0.1:8080
```

如果你要使用浏览器检测模式，需要安装 Playwright Chromium 运行时：

```bash
.venv/bin/python -m playwright install chromium
```

快速检测模式不需要启动 Playwright Chromium。

本地项目中心直接使用仓库自有的生命周期入口：

```bash
./scripts/project_center_service status
./scripts/project_center_service start
./scripts/project_center_service restart
./scripts/project_center_service stop
```

`status` 不会安装依赖。生命周期入口只有在端口、工作目录、命令标记和应用响应均确认属于本仓库服务后，才会停止监听进程。

如需强制使用指定端口，可设置 `CLASH_CHECKER_PORT`。显式端口被占用时不会
静默切换，启动会安全失败；只有未设置该变量时才会自动选择备用端口。

## 基本流程

1. 启动 Clash Verge Rev。
2. 确认 External Controller 已启用。
3. 启动本工具。
4. 选择一个支持的 Remote 或 Local 主订阅。
5. `代理组` 先保持 `auto`。
6. 点击 `切换并检测`，阅读网络影响说明；只有确认宿主机其他任务可以承受 IP 变化时才继续。
7. 如果自动识别代理组失败，手动输入真实 Clash 代理组名，例如 `GLOBAL`、`Proxy`、`PROXY`，或你的配置里使用的 selector 名称。
8. 检查节点列表和自动选中的节点。
9. 点击 `导出选中`。
10. 首次导出时，在弹窗里选择“首次导入到 Clash Verge”。
11. 后续重复导出会覆盖同一个 checked YAML；如果 Clash Verge 已有对应订阅，页面不会再次发起新建导入，请在 Clash Verge 刷新已有 checked 订阅。
12. 首次导入后，打开 Clash Verge，手动检查并选择或启用 checked 订阅。

手机订阅 URL/二维码只在 LAN 启动模式下生成。普通本机启动时，页面不会给出手机可用的二维码；移动端只是导入这台电脑导出的 YAML，不能启动本工具。

对 Remote 订阅，`刷新原订阅并检测` 会把最新远程 YAML 下载到内存中，检测后导出 checked YAML。它不会写回原始订阅文件。

两种检测操作都会先通过 HTTPS 确认节点当前出口 IP，再复用 14 天内该 IP 的成功风险结果。需要强制刷新 IPPure 风险结果时，可在“高级”中勾选“忽略 14 天 IP 缓存，重新查询风险”；同一任务内相同出口 IP 仍只查询一次。

## 局域网访问

LAN 模式只适合同一可信网络里的设备访问这台电脑上的 checker UI，或下载这台电脑生成的 YAML。

macOS:

```bash
./run_lan_mac.command
```

Windows:

```bat
run_lan_windows.bat
```

LAN 模式会把 Web 服务绑定到 `0.0.0.0`，并尝试检测当前局域网 IP，例如：

```text
http://192.168.1.23:8080
```

如果自动检测到的地址不对，可以启动前手动设置：

```bash
CLASH_CHECKER_PUBLIC_BASE_URL=http://192.168.1.23:8080 ./run_lan_mac.command
```

手动设置 `CLASH_CHECKER_PUBLIC_BASE_URL` 时，其中的端口必须与服务实际端口一致；
如需固定 LAN 地址，请同时设置两个环境变量。

重要 LAN 边界：

- LAN 页面操作的是这台电脑上运行的服务。
- 工具读取的是这台电脑上的 Clash Verge 文件，控制的也是这台电脑上的 Clash External Controller。
- 别人不能通过你的 LAN 页面读取或控制他们自己电脑上的 Clash Verge。
- 如果别人要处理自己电脑上的 Clash Verge，需要在自己的机器上本地运行本工具。
- 不要把这个服务暴露到公网。本工具没有登录层。
- 如果 macOS 或 Windows 防火墙提示 Python 网络访问，只应在可信 LAN 下允许。

## 本地数据与隐私

本工具会读取本机 Clash Verge profile 元数据和 profile YAML 内容。生成的数据默认只保留在本机：

- 导出的 YAML 写入 `exports/`。
- 本机订阅与节点观测保存在 `data/results.sqlite3`。
- 成功的 IP 风险结果保存在本机 `sync/ip_reputation_cache.json`；该文件包含出口 IP 和检测时间，已被 Git 忽略。公开仓库只提交空模板 `sync/ip_reputation_cache.example.json`。
- 临时运行文件可能写入 `.runtime/`。

本仓库已忽略这些路径：

```gitignore
exports/
data/
.runtime/
.venv/
sync/ip_reputation_cache.json
```

发布或推送 fork 前，建议运行：

```bash
git status --short --ignored
git ls-files exports data .runtime sync/ip_reputation_cache.json
git log --all -- sync/ip_reputation_cache.json
```

公开前的预期结果：导出的 YAML、本地 SQLite 数据库、临时运行文件和真实 IP 缓存都不应出现在 `git ls-files` 中；`git log` 也不应再显示真实 IP 缓存的旧提交。只清空当前文件或修改 `.gitignore` 不会清除历史，必须另外清理相关 Git 历史，或从经过审计的干净历史创建公开仓库。

不要提交：

- Clash Verge 的 `profiles.yaml`。
- 来自真实服务商的订阅 YAML。
- 导出的 checked YAML。
- `data/results.sqlite3`。
- API secret、服务商 URL、token，或暴露订阅名称/订阅 URL 的截图。

本机 IP 缓存不包含订阅名称、节点名称、节点配置或密钥，但出口 IP 和检测时间仍属于不应公开的本机网络数据。若缓存 JSON 无法解析，程序会保留原文件、不覆盖它，并继续把节点结果写入本机 SQLite。

## 许可证与归属

本仓库沿用 GPL-3.0，详见 [LICENSE](LICENSE)。

代码基于 [tombcato/clash-ip-checker](https://github.com/tombcato/clash-ip-checker) 做个人改造。原作者和贡献者保留原始贡献版权；本仓库新增改动由本仓库维护。

这不是上游官方版本。归属信息见 [NOTICE](NOTICE)。

## UI 说明

- 订阅列表默认只显示可选择的 Remote 和 Local 主订阅。
- Merge、script、rules 等不完整配置片段会显示在折叠区域，因为它们不是完整节点订阅。
- 快速检测模式通过 HTTPS 获取 IPv4 出口，并优先使用 Clash mixed-port 的 SOCKS5 IPv4 通道调用 IPPure；返回地址必须与前置 IPv4 一致。
- 如果 IPPure 仍返回 IPv6 或缺少风险分数，页面会明确显示“IPv6无评分”或“出口不一致”，且不会把该节点自动选为低风险节点。
- 页面会优先显示当前节点上次确认 IP 所对应的 14 天内最近成功结果，而不是只读取订阅最近一次检测日。
- 关闭快速检测后会使用浏览器检测，速度更慢，但能收集更完整的信息。
- 导出选择默认包含风险分数已完成且不高于 30% 的节点。
- Pending、失败、未知和风险大于 30% 的节点不会默认选中。
- 可见节点列表会按具体出口 IP 去重。空 IP、pending、unknown 和 N/A 不参与去重。

## 故障排查

### 找不到订阅

- 确认已安装 Clash Verge Rev。
- 确认 Clash Verge Rev 至少打开过一次。
- 如果你的数据目录是自定义路径，请在 UI 中填写，或设置 `CLASH_VERGE_HOME`。

### 无法连接 Clash External Controller

- 启动 Clash Verge Rev。
- 在 Clash Verge Rev 设置中启用 External Controller 或 HTTP controller。
- 确认本工具显示的 controller 地址与你的 Clash 配置一致。
- 如果配置了 secret，让工具从本机读取，或在 API secret 输入框中填写。

### 自动识别代理组失败

手动输入 selector/proxy group 名称。这个组必须是 Clash 能切换到每个节点的代理组。

### 导入后的订阅没有生效

这是预期行为。导入只会创建新的 checked 订阅，Clash Verge 不一定会自动选中它。请打开 Clash Verge，检查后手动选择或启用该 checked 订阅。

### 重复导出后是否需要再次导入

不需要。项目会覆盖稳定的 `*_checked.yaml` 文件，并检测 Clash Verge 中是否已有指向该文件的订阅。已有订阅时，请在 Clash Verge 中刷新它；重复执行“安装配置”会新增订阅而不是覆盖旧订阅。如果已经产生多个重复项，请在 Clash Verge 中手动保留一个并删除其余项。
