# Clash Verge IP Checker Auto

[English](README.md) | [简体中文](README.zh-CN.md)

用于 Clash Verge Rev 的本地节点检测与整理工具。项目可读取本机订阅配置，检测节点出口 IP 质量，筛选结果并导出新的 checked YAML。

> 仅在本机或可信局域网中使用，请勿部署到公网。

## 功能预览

![节点检测与导出界面](docs/assets/screenshots/overview.png)

![检测前的网络影响确认](docs/assets/screenshots/network-impact-confirmation.png)

截图使用演示订阅、演示节点和文档保留 IP。

## 核心功能

- 自动发现 Clash Verge Rev 数据目录、订阅和 External Controller 配置。
- 支持 Remote 与 Local 主订阅，其他配置片段单独显示。
- 使用 IPPure 快速检测出口 IP，也可启用浏览器检测获取更多信息。
- 复用 14 天内同一出口 IP 的成功结果，并按出口 IP 去重。
- 默认选择风险分数不高于 30% 的已完成节点。
- 导出新的 `*_checked.yaml`，并提供 Clash Verge 导入入口。

## 安全提示

- 检测前会验证 External Controller，并提示宿主机网络可能受到的影响。
- 检测期间会临时切换 Clash 模式和代理节点，后台下载、同步、SSH、浏览器及 API 任务可能换 IP 或短暂中断。
- 正常完成、停止或异常时，工具会恢复原节点和原模式。
- 检测非当前订阅时，可临时加载配置；结束后恢复 Clash Verge 运行时配置。
- 导出不会覆盖原订阅或编辑 `profiles.yaml`，也不会自动启用新订阅。

## 运行要求

- Python 3.10 或更高版本。
- 已安装并启动 Clash Verge Rev。
- Clash Verge Rev 已启用 External Controller。
- 订阅由本地 YAML 文件支撑，类型为 Remote 或 Local 主订阅。

Controller 建议绑定到本机地址，例如 `127.0.0.1:9097`。如果配置了 secret，请保留在本机；工具可以自动读取，但不会在页面上显示。

## 快速开始

### macOS

```bash
./run_mac.command
```

### Windows

```bat
run_windows.bat
```

启动器会创建或修复项目内的 `.venv`，并按需安装依赖。Web UI 默认使用端口 8080；端口被占用时，会从 `18080-18120` 选择并复用可用端口。请打开终端输出的实际地址。

### 手动启动

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python web.py
```

浏览器检测模式还需要安装 Chromium：

```bash
.venv/bin/python -m playwright install chromium
```

可通过 `CLASH_CHECKER_PORT` 指定固定端口，通过 `CLASH_VERGE_HOME` 指定 Clash Verge Rev 数据目录。显式端口被占用时，启动会安全失败。

## 使用流程

1. 启动 Clash Verge Rev，并确认 External Controller 可用。
2. 启动本工具，选择 Remote 或 Local 主订阅。
3. 保持代理组为 `auto`，或填写实际 selector 名称。
4. 点击 `切换并检测`，阅读网络影响提示后确认或取消。
5. 检查节点结果和默认选择。
6. 点击 `导出选中`。
7. 首次导出时选择导入 Clash Verge；后续导出刷新已有 checked 订阅即可。
8. 在 Clash Verge 中检查并手动启用导入的订阅。

`刷新并切换检测` 会读取 Remote 订阅的最新内容，但不会写回原始订阅文件。高级设置可以忽略 14 天 IP 缓存并重新检测。

## 局域网访问

macOS：

```bash
./run_lan_mac.command
```

Windows：

```bat
run_lan_windows.bat
```

LAN 模式只适合可信网络。页面控制的是运行服务那台电脑上的 Clash Verge，而不是浏览器所在设备的 Clash Verge。服务没有登录层，不应暴露到公网。

如需固定 LAN 地址，请同时设置 `CLASH_CHECKER_PORT` 和 `CLASH_CHECKER_PUBLIC_BASE_URL`，并确保两个端口一致。

## 本地数据与隐私

| 路径 | 内容 | Git 状态 |
| --- | --- | --- |
| `exports/` | 导出的 checked YAML | 忽略 |
| `data/results.sqlite3` | 本机订阅与节点检测结果 | 忽略 |
| `sync/ip_reputation_cache.json` | 出口 IP 信誉缓存 | 忽略 |
| `sync/ip_reputation_cache.example.json` | 空缓存模板 | 提交 |
| `.runtime/` | 端口、日志和临时配置 | 忽略 |

不要提交真实订阅 YAML、`profiles.yaml`、导出文件、API secret、服务商 URL、token 或包含真实订阅信息的截图。

如果真实 IP 缓存曾进入 Git 提交，仅添加 `.gitignore` 不会删除旧历史；公开仓库前仍需清理相关历史或创建经过审计的新公开历史。

## 故障排查

### 找不到订阅

确认 Clash Verge Rev 已至少启动过一次。自定义数据目录可在页面填写，或通过 `CLASH_VERGE_HOME` 指定。

### 无法连接 External Controller

确认 Clash Verge Rev 正在运行、External Controller 已启用，并检查 Controller 地址和 secret。

### 无法自动识别代理组

填写能够切换到待测节点的 selector 名称，例如 `GLOBAL`、`Proxy` 或配置中使用的代理组名。

### 导入后未生效

导入只会创建 checked 订阅。请回到 Clash Verge 手动检查、刷新并启用该订阅。

## 许可证与归属

项目采用 [GPL-3.0](LICENSE) 许可证，基于 [tombcato/clash-ip-checker](https://github.com/tombcato/clash-ip-checker) 修改。这不是上游官方版本，归属信息见 [NOTICE](NOTICE)。
