# Toolbox

> 一个本地优先的通用文件格式转换工具，支持 PDF ↔ Word ↔ Markdown ↔ HTML 等 15+ 种格式互转。

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## ✨ 项目简介

**Toolbox** 是一个聚合多种开源转换引擎的命令行 / HTTP 服务工具，目标是用**一行命令**完成绝大多数日常文档格式转换需求，例如：

- 把 PDF 转成可编辑的 Word / Markdown
- 把 Markdown 笔记一键生成 PDF / Word
- 把 PPT、Excel、ePub 统一转成 Markdown 用于 LLM 知识库
- 批量把 Word/PPT 文档转成 PDF 归档

它本身**不重复造轮子**，而是把社区里最好用的几个引擎（[MarkItDown](https://github.com/microsoft/markitdown)、[Pandoc](https://pandoc.org/)、[LibreOffice](https://www.libreoffice.org/)）封装在统一接口下，并通过**路由图**自动选择最优转换路径。

### 与同类工具的区别

| 能力 | Toolbox | 单一工具 (如 pandoc) |
|---|---|---|
| 多引擎自动路由 | ✅ BFS 找最短路径 | ❌ |
| 缺失依赖自动降级 | ✅ 运行时探测可用引擎 | ❌ |
| CLI + HTTP API 双形态 | ✅ 同一内核 | 通常仅 CLI |
| 多步转换链 | ✅ 例如 PDF→MD→DOCX 全自动 | ❌ 需手动拼 |

---

## 🏗️ 架构

```
   ┌────────────────┐      ┌──────────────────┐
   │  CLI (typer)   │      │  HTTP API (FastAPI) │
   └────────┬───────┘      └──────────┬───────┘
            └──────────┬──────────────┘
                       ▼
            ┌──────────────────────┐
            │  Router (BFS 路由图) │   ← 根据 (from, to) 找最短转换链
            └──────────┬───────────┘
                       ▼
   ┌────────────┬─────────────┬──────────────┐
   │ MarkItDown │   Pandoc    │  LibreOffice │
   │  (Python)  │ (subprocess)│ (subprocess) │
   └────────────┴─────────────┴──────────────┘
```

**核心设计：** 每个引擎自己声明能做哪些 `(源格式, 目标格式)` 边；启动时探测引擎是否可用，构建出有向图；调用时 BFS 找最短路径，自动多步串联。

---

## 📦 支持的转换

启动后用 `toolbox routes` 可查看当前环境下的全部可用边，下表是装齐三个引擎后的覆盖情况：

| 源格式 ↓ \ 目标 → | md | pdf | docx | html | epub |
|---|:---:|:---:|:---:|:---:|:---:|
| **pdf** | ✅ | — | ✅ (2-hop) | ✅ (2-hop) | ✅ (2-hop) |
| **docx** | ✅ | ✅ | — | ✅ | ✅ (2-hop) |
| **md** | — | ✅ | ✅ | ✅ | ✅ |
| **html** | ✅ | ✅ | ✅ | — | ✅ (2-hop) |
| **pptx / xlsx / odt / rtf / epub / txt / csv / json** | ✅ | ✅* | ✅ (2-hop) | ✅ (2-hop) | — |

> *部分组合需要装齐三个引擎；未装的引擎对应路径会自动隐藏。

---

## 🚀 快速开始

### 1. 安装 Python 依赖

需要 Python ≥ 3.11，推荐用 [uv](https://github.com/astral-sh/uv) 管理依赖：

```bash
git clone <repo>
cd toolbox
uv sync
```

> 仅此一步即可解锁 **任意格式 → Markdown**（由 MarkItDown 提供）。

### 2. 安装可选系统工具（按需）

根据你的需求安装下列工具，**Toolbox 会自动检测并启用对应路径**：

| 工具 | 解锁能力 | 安装命令（macOS） |
|---|---|---|
| `pandoc` | Markdown ↔ Word / HTML / EPUB / RTF / ODT | `brew install pandoc` |
| `xelatex` (LaTeX) | Markdown → PDF 直转 | `brew install --cask basictex` |
| `libreoffice` | Word / PPT / Excel → PDF | `brew install --cask libreoffice` |

Linux 用户对应包名：`apt install pandoc texlive-xetex libreoffice` 即可。

### 3. 验证安装

```bash
uv run toolbox engines    # 查看引擎可用性
uv run toolbox routes     # 查看可用的全部转换边
```

输出示例：

```
                                    Engines
┏━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Name        ┃ Available ┃ Edges                                    ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ markitdown  │ ✓         │ pdf→md, docx→md, pptx→md, xlsx→md ...   │
│ pandoc      │ ✓         │ md→docx, md→html, md→pdf, md→epub ...   │
│ libreoffice │ ✓         │ docx→pdf, doc→pdf, odt→pdf, pptx→pdf ...│
└─────────────┴───────────┴──────────────────────────────────────────┘
```

---

## 📖 使用方法

### CLI 命令行

```bash
# 基本用法：源文件 + -o 目标文件，格式从扩展名自动推断
uv run toolbox convert 论文.pdf      -o 论文.md
uv run toolbox convert 论文.pdf      -o 论文.docx        # 自动 2 跳：PDF→MD→DOCX
uv run toolbox convert 笔记.md       -o 笔记.pdf
uv run toolbox convert 报告.docx     -o 报告.pdf
uv run toolbox convert 演示.pptx     -o 演示.md
uv run toolbox convert 数据.xlsx     -o 数据.md

# 显式指定目标格式（适合输出文件名没有扩展名时）
uv run toolbox convert input.pdf -o output --to docx

# 查看完整子命令帮助
uv run toolbox --help
uv run toolbox convert --help
```

#### CLI 子命令清单

| 命令 | 用途 |
|---|---|
| `toolbox convert <in> -o <out>` | 转换单个文件 |
| `toolbox engines` | 列出所有引擎及可用性 |
| `toolbox routes` | 列出当前可用的所有转换边 |
| `toolbox serve` | 启动 HTTP API 服务 |

### HTTP API 服务

```bash
uv run toolbox serve --host 0.0.0.0 --port 8000
```

启动后可用接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET`  | `/health`  | 健康检查 |
| `GET`  | `/engines` | 列出引擎及可用性（JSON） |
| `GET`  | `/routes`  | 列出全部可用转换边（JSON） |
| `POST` | `/convert?to=<fmt>` | 上传文件并转换，返回转换后文件 |

调用示例：

```bash
# PDF 转 Markdown
curl -F "file=@input.pdf" "http://127.0.0.1:8000/convert?to=md" -o output.md

# Word 转 PDF
curl -F "file=@报告.docx" "http://127.0.0.1:8000/convert?to=pdf" -o 报告.pdf

# 查看可用引擎
curl http://127.0.0.1:8000/engines | jq
```

Swagger 文档：启动服务后访问 <http://127.0.0.1:8000/docs>。

---

## 🛠️ 项目结构

```
toolbox/
├── pyproject.toml          # 项目配置 + 依赖（uv 管理）
├── README.md
└── src/toolbox/
    ├── cli.py              # Typer CLI 入口
    ├── api.py              # FastAPI HTTP 入口
    ├── router.py           # BFS 路由图：根据 (from→to) 找最短链
    ├── core/
    │   ├── detect.py       # 扩展名 → 格式类型
    │   ├── pipeline.py     # 串联多个引擎执行多步转换
    │   └── errors.py       # 业务异常类型
    └── engines/
        ├── base.py         # 引擎抽象基类
        ├── markitdown.py   # MarkItDown 适配器（任意 → MD）
        ├── pandoc.py       # Pandoc 适配器（MD ↔ DOCX/HTML/...）
        └── libreoffice.py  # LibreOffice 适配器（Office → PDF）
```

### 添加一个新引擎

1. 在 `engines/` 下新建文件，继承 `Engine` 基类
2. 实现 `available` 属性（探测依赖是否就位）、`edges()` 方法（声明能做哪些转换）、`convert()` 方法
3. 在 `router.py` 的 `ENGINES` 列表里注册

无需改动路由逻辑，新引擎的边会自动被纳入 BFS 图。

---

## 📋 引擎说明

| 引擎 | 协议 | 用途 | 安装方式 |
|---|---|---|---|
| **MarkItDown** | MIT | 把 30+ 种格式统一转 Markdown，速度快 | `uv sync` 自动装 |
| **Pandoc** | GPL-2.0+ | Markdown 与各种文档格式之间互转，最稳的中转节点 | 系统包管理器 |
| **LibreOffice** | MPL-2.0 | Office 文档高保真转 PDF（业界事实标准） | 系统包管理器 |

> Pandoc / LibreOffice 通过子进程方式调用，不与本项目源码静态链接，使用上不传染 License。

---

## 🗺️ 路线图

| 阶段 | 状态 | 内容 |
|---|---|---|
| **M1** | ✅ 已完成 | Python 核心 — CLI + HTTP API，3 引擎，BFS 路由 |
| **M2** | 🚧 进行中 | Next.js 拖拽前端，批量队列，实时进度 |
| **M3** | 📅 规划中 | Tauri 桌面壳，离线优先，文件夹自动监听 |
| **M4** | 💭 构想中 | LLM 排版修正，配方系统（一键复用上次配置），模板化输出 |

---

## 🤝 贡献

欢迎 Issue / PR。提交前请确保：

```bash
uv run pytest                          # 测试通过
uv run toolbox engines                 # 至少 markitdown 可用
uv run toolbox convert tests/sample.md -o /tmp/t.pdf   # 烟测通过
```

---

## 📄 License

本项目采用 **MIT License**。

底层依赖的引擎各自的 License：
- MarkItDown — MIT
- Pandoc — GPL-2.0+（子进程调用）
- LibreOffice — MPL-2.0（子进程调用）
