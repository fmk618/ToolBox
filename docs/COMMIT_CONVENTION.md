# 提交规范 (Commit Convention)

本仓库遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/) 风格，所有提交信息使用 **中文** 编写。本文档同时适用于 `fmk618/ToolBox`（根仓库）与 `fmk618/ToolBox-web`（前端子模块）。

## 一、核心提交规范

每次提交的信息应当遵循以下格式：

```
<type>(<scope>): <subject>

<body>

<footer>
```

- **`type`**：必填，提交类型，见下文表格。
- **`scope`**：可选，影响范围（模块/目录/包名），加圆括号。
- **`subject`**：必填，简短描述，中文，不超过 50 字，**句末不加句号**。
- **`body`**：可选，详细描述（动机、背景、对比），中文，每行不超过 72 字。
- **`footer`**：可选，破坏性变更声明、关联 issue、Co-Authored-By 等。

### 1.1 `type` 类型

| Type       | 含义                                                         |
| ---------- | ------------------------------------------------------------ |
| `feat`     | 新增功能 (Feature)                                            |
| `fix`      | 修复 Bug                                                      |
| `docs`     | 仅仅修改了文档 (Documentation)                                |
| `style`    | 代码格式调整（不影响逻辑，如空格、缩进等）                    |
| `refactor` | 代码重构（既不是新增功能，也不是修改 Bug 的代码变动）          |
| `perf`     | 优化相关（提升性能、体验）                                    |
| `test`     | 增加或修改测试用例                                            |
| `chore`    | 构建过程或辅助工具的变动（如更新依赖包）                      |
| `build`    | 影响构建系统或外部依赖（如 npm、uv、Docker、Makefile）        |
| `ci`       | CI 配置文件与脚本的变动（GitHub Actions、workflow）           |
| `revert`   | 回滚之前的提交                                                |

### 1.2 `scope` 范围（本项目约定）

- 前端 (`fmk618/ToolBox-web`)：
  - `web`：泛指前端
  - `shell`：应用骨架（sidebar/topbar/layout）
  - `tool/<slug>`：特定工具（如 `tool/base64`、`tool/file-convert`）
  - `api`：前端到后端的 client 层 (`src/lib/api.ts`)
- 后端 (`fmk618/ToolBox`)：
  - `toolbox`：泛指后端包
  - `core`：核心层（`src/toolbox/core/`）
  - `tools/<slug>`：后端工具模块（如 `tools/file_convert`）
  - `engines`：转换引擎层
  - `cli`：命令行入口

`scope` 不强制必填，但**多模块仓库强烈建议**填写。

### 1.3 示例

```
feat(tool/jwt): 新增 JWT 解码工具

支持 HS256/RS256 校验，载荷字段以表格形式展示。
底层使用 Web Crypto SubtleCrypto，无外网请求。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

```
fix(api): 修复 file-convert 大文件超时

将 fetch 替换为 XHR 并启用 upload.onprogress，
避免 Next.js 16 默认 30s 超时截断。

Closes #42
```

```
refactor(toolbox): 后端拆分为 thin app + tools/file_convert + core/settings_api
```

```
docs: 补充提交规范说明
```

## 二、破坏性变更 (BREAKING CHANGE)

- 在 `<type>` 后追加 `!`：`feat(api)!: 删除旧版 /convert 接口`
- 或在 `<footer>` 中独占一行：

```
feat(api): 移除根级 /convert 端点

BREAKING CHANGE: /convert 已迁至 /tools/file-convert/convert，
旧 URL 不再保留兼容层。
```

## 三、分支与发布

- `main` 是工作分支：所有功能与修复直接合入 `main`（受 PR 保护规则保护，需经 PR 合并）。
- `beta` 是发布分支：由 `main` → PR → `beta` 发布。**不要直接 push `beta`**。

## 四、本地校验

仓库提供 `scripts/commit-msg`（commit-msg 钩子），会在每次 `git commit` 时校验信息格式。

启用方法（一次性）：

```bash
bash scripts/install-hooks.sh
```

该脚本会同时为根仓库和 `web/` 子模块安装钩子。

不符合规范时，钩子会拒绝提交并打印示例。如需临时绕过（**不推荐**），可加 `--no-verify`，但请同步告知团队。

## 五、生成提交（可选辅助）

未使用 commitizen 等交互式工具时，建议手动按如下顺序构造：

1. 主类型：是新增（feat）、修复（fix）、还是重构（refactor）？
2. 范围：动了哪个 scope？跨多个则省略 scope。
3. 主题：用一句中文回答「做了什么」，动词开头。
4. 主体：解释「为什么这么做」「带来什么影响」，可省略。
5. 页脚：列 BREAKING CHANGE / Closes / Co-Authored-By。
