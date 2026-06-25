# Tauri 桌面客户端

## 概述

M5 里程碑为 Toolbox 提供 Tauri v2 桌面壳，通过 Webview 将 Next.js 前端打包为原生桌面应用（macOS / Windows / Linux）。

## 前置依赖

| 工具 | 说明 | 安装 |
|---|---|---|
| Rust（rustup） | Tauri 编译依赖 | https://rustup.rs |
| Tauri CLI v2 | 构建/打包工具 | `cargo install tauri-cli --version "^2"` |
| Node.js 20+ | 前端构建 | https://nodejs.org |

## 开发模式

```bash
# 在 repo 根目录
cargo tauri dev
```

Tauri 会自动执行 `cd web && npm run dev`，然后在 Webview 中加载 `http://localhost:3000`。

## 生产构建

```bash
cargo tauri build
```

等效流程：
1. 执行 `cd web && TAURI=1 next build` → 静态导出到 `web/out/`
2. Tauri 打包 Webview + 静态资源 → 平台原生安装包（`.dmg` / `.exe` / `.AppImage`）

输出目录：`src-tauri/target/release/bundle/`

## 图标生成

Tauri 需要多尺寸图标。从一张 1024×1024 PNG 一键生成：

```bash
cargo tauri icon path/to/icon-1024.png
```

生成结果会覆盖 `src-tauri/icons/` 下的所有占位文件。

## 后端配置

桌面版默认**不**自动启动 Python 后端。有两种方式使用文件转换功能：

**方式 1 — 手动启动**：
```bash
uv run toolbox serve --host 127.0.0.1 --port 8000
```
然后在应用内「系统设置」中确认 API 地址为 `http://127.0.0.1:8000`。

**方式 2 — Sidecar（计划中）**：
将 Python 后端打包为 Tauri Sidecar 二进制，随桌面应用自动启动。参见 Issue #TODO。

## 静态导出说明

`TAURI=1 next build` 会将所有工具页面预渲染为静态 HTML（`web/out/tools/<slug>/index.html`）。所有 31 个工具均为纯客户端组件（`ssr: false`），静态导出安全无副作用。

API 调用（文件转换）在离线或无后端时会显示友好错误，不影响其余 30 个纯前端工具。
