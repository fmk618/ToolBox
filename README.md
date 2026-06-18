# Toolbox · 工具百宝箱

> 一个本地优先的开发者工具集合 ——「工具百宝箱」。
> 19+ 个常用小工具开箱即用，仅文件格式转换工具走 Python 后端。

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## ✨ 项目简介

仓库包含两部分：

| 部分                  | 路径                                                           | 角色                                                                                     |
| --------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| **Python 后端**       | `src/toolbox/`                                                 | 文件格式转换工具的运行时（CLI + HTTP API + 5 个转换引擎）                                  |
| **Next.js Web 前端**  | [`web/`](https://github.com/fmk618/ToolBox-web)（子模块）       | 浏览器端「工具百宝箱」UI，shadcn/ui 视觉、⌘K 命令面板、本地运行 18+ 工具 + 调用后端转换 1 个 |

后端架构上**不重复造轮子**：把社区里最好用的几个引擎（MarkItDown、Docling、Pandoc、LibreOffice、Vision-LLM）封装在统一接口下，用**路由图 BFS**自动选择最优转换路径。

---

## 🛠️ 工具清单（19 个）

| 分类     | 工具                                                              | 依赖    |
| -------- | ----------------------------------------------------------------- | ------- |
| 文件转换 | 文件格式转换                                                       | 后端    |
| 编解码   | Base64 · URL · HTML 实体                                          | 纯前端  |
| 加密哈希 | Hash（SHA-1/256/384/512）· 密码生成 · JWT 解码                     | 纯前端  |
| 文本工具 | JSON 格式化 · YAML⇄JSON · Markdown 预览 · Diff 对比 · 正则测试     | 纯前端  |
| 开发辅助 | UUID v4 · 二维码生成                                              | 纯前端  |
| 时间日期 | 时间戳 · 时区换算 · Cron 表达式                                    | 纯前端  |
| 颜色数据 | Hex⇄RGB⇄HSL · WCAG 颜色对比度                                     | 纯前端  |
| 系统设置 | 系统设置（后端地址 / Vision-LLM 配置 / 本地数据）                   | 纯前端  |

---

## 🏗️ 后端架构

```
   ┌────────────────┐      ┌──────────────────────┐
   │  CLI (typer)   │      │  HTTP API (FastAPI)  │
   └────────┬───────┘      └──────────┬───────────┘
            └──────────┬──────────────┘
                       ▼
       ┌──────────────────────────────────┐
       │  core/engines_graph.py (BFS 路由) │ ← 根据 (from, to) 找最短转换链
       └──────────────┬───────────────────┘
                      ▼
   ┌─────────────┬──────────┬────────────┬────────┬──────────────┐
   │  Vision-LLM │  Docling │ MarkItDown │ Pandoc │ LibreOffice  │
   │   (云端)    │  (本地)  │  (Python)  │ (子进程)│   (子进程)   │
   └─────────────┴──────────┴────────────┴────────┴──────────────┘
```

每个引擎自己声明能做哪些 `(源格式, 目标格式)` 边；启动时探测可用性，构建有向图；调用时 BFS 找最短路径，自动多步串联。

---

## 🚀 快速开始

### 1. 克隆（含子模块）

```bash
git clone --recurse-submodules https://github.com/fmk618/ToolBox.git
cd ToolBox
```

如果已经 clone 没拿子模块：`git submodule update --init`。

### 2. 安装 Python 后端

需要 Python ≥ 3.11，推荐 [uv](https://github.com/astral-sh/uv)：

```bash
uv sync
```

此步即可解锁**任意格式 → Markdown**（由 MarkItDown 提供）。

### 3. 安装可选系统工具（按需）

| 工具          | 解锁能力                                | 安装命令（macOS）                  |
| ------------- | --------------------------------------- | ---------------------------------- |
| `pandoc`      | Markdown ↔ Word / HTML / EPUB / RTF     | `brew install pandoc`              |
| `xelatex`     | Markdown → PDF 直转                     | `brew install --cask basictex`     |
| `libreoffice` | Word / PPT / Excel → PDF                | `brew install --cask libreoffice`  |

Linux：`apt install pandoc texlive-xetex libreoffice`。

Vision-LLM 引擎（PDF → Markdown 质量最高）在前端「系统设置」里配置 OpenAI / DeepSeek / 智谱等 API Key 即可启用。

### 4. 启动前后端

```bash
# 终端 1 — 后端
uv run toolbox serve            # → http://127.0.0.1:8000

# 终端 2 — Web 前端
cd web
npm install
npm run dev                     # → http://localhost:3000
```

浏览器打开 <http://localhost:3000> 即可看到工具百宝箱。

---

## 📖 使用方法

### CLI

```bash
uv run toolbox convert 论文.pdf -o 论文.md
uv run toolbox convert 论文.pdf -o 论文.docx     # 2 跳：PDF → MD → DOCX
uv run toolbox convert 笔记.md  -o 笔记.pdf
uv run toolbox engines                            # 列出所有引擎与可用性
uv run toolbox routes                             # 列出当前可用的全部转换边
uv run toolbox serve --host 0.0.0.0 --port 8000  # 启动 HTTP API
```

### HTTP API

URL 命名空间按工具 slug 隔离：

| 方法     | 路径                                  | 用途                                          |
| -------- | ------------------------------------- | --------------------------------------------- |
| `GET`    | `/health`                             | 健康检查                                       |
| `GET`    | `/tools/file-convert/engines`         | 列出引擎与可用性（JSON）                       |
| `GET`    | `/tools/file-convert/routes`          | 列出当前可用的全部转换边（JSON）                |
| `POST`   | `/tools/file-convert/convert?to=<fmt>` | 上传文件并转换，返回转换后文件                  |
| `GET`    | `/providers`                          | 列出支持的 Vision-LLM Provider                  |
| `GET/POST/DELETE` | `/settings/llm`              | Vision-LLM Provider / Model / API Key 配置      |
| `POST`   | `/settings/llm/test`                  | 测试当前 LLM 凭据是否能跑通                     |

```bash
# 命令行调用示例
curl -F "file=@input.pdf" "http://127.0.0.1:8000/tools/file-convert/convert?to=md" -o output.md
curl http://127.0.0.1:8000/tools/file-convert/engines | jq
```

Swagger 文档：<http://127.0.0.1:8000/docs>。

---

## 📁 项目结构

```
toolbox/
├── pyproject.toml
├── README.md
├── docs/COMMIT_CONVENTION.md         # 中文提交规范
├── scripts/                           # commit-msg 钩子 + install-hooks 脚本
├── web/                               # Web 前端子模块（fmk618/ToolBox-web）
└── src/toolbox/
    ├── cli.py                         # Typer CLI 入口
    ├── api.py                         # FastAPI HTTP 入口（薄）
    ├── core/
    │   ├── engines_graph.py           # BFS 路由图
    │   ├── pipeline.py                # 多步转换串联
    │   ├── detect.py                  # 扩展名 → 格式类型
    │   ├── errors.py                  # 业务异常
    │   ├── llm_settings.py            # LLM 配置持久化
    │   ├── providers.py               # LLM Provider 目录
    │   └── settings_api.py            # /settings/llm + /providers Router
    ├── tools/
    │   └── file_convert/
    │       ├── __init__.py
    │       └── router.py              # /tools/file-convert/* Router
    └── engines/
        ├── base.py                    # 引擎抽象基类
        ├── markitdown.py              # MarkItDown 适配器（任意 → MD）
        ├── docling.py                 # Docling 适配器（本地 PDF → MD，高质量）
        ├── pandoc.py                  # Pandoc 适配器（MD ↔ DOCX/HTML/...）
        ├── libreoffice.py             # LibreOffice 适配器（Office → PDF）
        └── vision_llm.py              # Vision-LLM 适配器（云端 PDF → MD/HTML）
```

### 添加新引擎

1. 在 `engines/` 下继承 `Engine` 基类，实现 `available` / `edges()` / `convert()`
2. 在 `core/engines_graph.py` 的 `ENGINES` 列表注册（顺序即优先级）
3. 不需要改路由逻辑，新边会自动进入 BFS 图

### 添加新后端工具

1. 新建 `src/toolbox/tools/<slug>/`，加 `__init__.py` 与 `router.py`（APIRouter）
2. 在 `api.py` 加一行 `api.include_router(<your_router>, prefix="/tools/<slug>")`
3. 前端在 `web/src/tools/<slug>/` 加 `meta.ts` + `ui.tsx`，slug 跨语言一一对齐

### 添加新前端工具

不需要后端改动。详见 [web/README.md](https://github.com/fmk618/ToolBox-web#%EF%B8%8F-工具开发约定)。

---

## 📋 引擎说明

| 引擎             | 协议      | 用途                                      | 安装方式                  |
| ---------------- | --------- | ----------------------------------------- | ------------------------- |
| **Vision-LLM**   | —         | 云端视觉大模型 PDF→Markdown，质量最高     | 在前端设置页填 API Key    |
| **Docling**      | MIT       | 本地 ML 模型 PDF→Markdown，无需联网       | `uv sync` 自动装          |
| **MarkItDown**   | MIT       | 30+ 种格式统一转 Markdown，最快           | `uv sync` 自动装          |
| **Pandoc**       | GPL-2.0+  | Markdown 与各种格式互转，最稳的中转节点    | 系统包管理器              |
| **LibreOffice**  | MPL-2.0   | Office 文档高保真转 PDF（事实标准）        | 系统包管理器              |

> Pandoc / LibreOffice 通过子进程调用，不与本项目源码静态链接，使用上不传染 License。

---

## 🌳 分支与发布

| 仓库                     | 默认 / 工作分支 | 发布约束                                          |
| ------------------------ | --------------- | ------------------------------------------------- |
| `fmk618/ToolBox` (本仓库) | `beta`          | 严格 PR 工作流，所有改动经 PR 合入 `beta`         |
| `fmk618/ToolBox-web`     | `main`          | 直接 push（无 PR 规则）                            |

提交信息遵循 [docs/COMMIT_CONVENTION.md](docs/COMMIT_CONVENTION.md)。
本地可一键安装 commit-msg 钩子：

```bash
bash scripts/install-hooks.sh
```

---

## 🗺️ 路线图

| 阶段 | 状态     | 内容                                                                                |
| ---- | -------- | ----------------------------------------------------------------------------------- |
| M1   | ✅       | Python 后端 — CLI + HTTP API，5 引擎，BFS 路由                                       |
| M2   | ✅       | Next.js 工具百宝箱前端，shadcn 视觉，⌘K 命令面板，19 个工具                          |
| M3   | 📅       | 更多工具（JSON 可视化 / 图片压缩 / SVG 优化 / Carbon 代码截图 / Mock 数据 / ...）     |
| M4   | 💭       | 工具收藏 / 最近使用、跨设备配置同步、PWA 离线模式                                     |
| M5   | 💭       | Tauri 桌面壳，文件夹自动监听、批量转换                                                |

---

## 🤝 贡献

欢迎 Issue / PR。提交前：

```bash
uv run pytest                                          # 测试通过
uv run toolbox engines                                 # 至少 markitdown 可用
uv run toolbox convert tests/sample.md -o /tmp/t.pdf   # 烟测通过
```

---

## 📄 License

本项目采用 **MIT License**。

底层依赖的引擎各自的 License：
- MarkItDown — MIT
- Docling — MIT
- Pandoc — GPL-2.0+（子进程调用）
- LibreOffice — MPL-2.0（子进程调用）
