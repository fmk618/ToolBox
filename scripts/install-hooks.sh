#!/usr/bin/env bash
# 把 scripts/commit-msg 安装到根仓库与 web/ 子模块的 .git/hooks/ 下。
#
# 用法：bash scripts/install-hooks.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK_SRC="$REPO_ROOT/scripts/commit-msg"

if [[ ! -f "$HOOK_SRC" ]]; then
  echo "✗ 未找到 $HOOK_SRC" >&2
  exit 1
fi

install_hook() {
  local label="$1"
  local hooks_dir="$2"

  if [[ ! -d "$hooks_dir" ]]; then
    echo "·  跳过 $label：$hooks_dir 不存在"
    return
  fi

  cp "$HOOK_SRC" "$hooks_dir/commit-msg"
  chmod +x "$hooks_dir/commit-msg"
  echo "✓  已安装到 $label ($hooks_dir/commit-msg)"
}

# 根仓库
install_hook "根仓库" "$REPO_ROOT/.git/hooks"

# web/ 子模块。子模块的 .git 可能是文件（gitdir 指针），用 rev-parse 解析。
WEB_DIR="$REPO_ROOT/web"
if [[ -e "$WEB_DIR/.git" ]]; then
  WEB_GITDIR="$(git -C "$WEB_DIR" rev-parse --git-dir 2>/dev/null || true)"
  if [[ -n "$WEB_GITDIR" ]]; then
    # rev-parse 可能返回相对路径
    case "$WEB_GITDIR" in
      /*) ;;
      *) WEB_GITDIR="$WEB_DIR/$WEB_GITDIR" ;;
    esac
    install_hook "web 子模块" "$WEB_GITDIR/hooks"
  fi
fi

echo
echo "完成。下次 git commit 将校验信息格式（详见 docs/COMMIT_CONVENTION.md）"
