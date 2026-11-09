#!/usr/bin/env bash
# 安装仓库自带的 git 钩子（.githooks/）：设置 core.hooksPath=.githooks。
#
# 为什么需要这一步：`core.hooksPath` 是**本地**配置，git 不会随 clone 传播。新
# clone 里 .githooks/ 目录在、文件在，但钩子**不生效**——闸看着存在，实际不跑。
# 本脚本就是那一步显式动作，替代原先指向不存在文件的悬空指引。
#
# 用法:
#   bash scripts/install_security_hooks.sh            # 幂等：已安装则零变更返回
#   bash scripts/install_security_hooks.sh --force    # 覆盖已指向别处的 core.hooksPath
#
# 边界:
#   - 只写仓库本地配置（git config --local），不碰 global/system；
#   - 不复制、不链接任何文件到 .git/hooks；
#   - 钩子缺执行位则拒装（装了也是静默跳过，与 tests/unit/test_githooks_exec_bit.py 同口径）。
#
# 兼容性：所有紧邻非 ASCII 字符的展开一律写成 ${VAR}——bash 3.2（macOS 系统自带）
# 会把多字节字节并进变量名，`$VAR（` 会被解析成变量 `VAR（` 而报 unbound variable。
#
# 设计变更（2026-11-10）：原裁量「不改 core.hooksPath」的依据是镜像区 .git 由外部
# 会话共享；镜像区取消后该前提消失，钩子化改由本脚本承担（见 scripts/r9_commit.sh 头注）。
set -euo pipefail

HOOKSPATH=".githooks"
FORCE=0
if [ "${1:-}" = "--force" ]; then
  FORCE=1
elif [ -n "${1:-}" ]; then
  echo "❌ 未知参数: ${1}（仅支持 --force）" >&2
  exit 1
fi

if ! ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
  echo "❌ 不在 git 工作树内：git rev-parse --show-toplevel 失败" >&2
  exit 1
fi
cd "${ROOT}"

if [ ! -d "${HOOKSPATH}" ]; then
  echo "❌ 钩子目录缺失: ${ROOT}/${HOOKSPATH} —— 无可安装内容" >&2
  exit 1
fi

HOOK_NAMES=""
missing_exec=0
for hook in "${HOOKSPATH}"/*; do
  [ -f "${hook}" ] || continue
  HOOK_NAMES="${HOOK_NAMES} $(basename "${hook}")"
  if [ ! -x "${hook}" ]; then
    echo "❌ 钩子缺执行位: ${hook#"${ROOT}"/}（git 会静默跳过它；chmod +x 后重试）" >&2
    missing_exec=1
  fi
done
[ "${missing_exec}" -eq 0 ] || exit 1
if [ -z "${HOOK_NAMES}" ]; then
  echo "❌ ${HOOKSPATH} 下没有任何钩子文件 —— 装上了也没有闸可生效" >&2
  exit 1
fi

current=$(git config --local --get core.hooksPath || true)
if [ "${current}" = "${HOOKSPATH}" ]; then
  echo "✅ 已安装：core.hooksPath=${HOOKSPATH}（无需变更）"
  echo "   钩子:${HOOK_NAMES}"
  exit 0
fi
if [ -n "${current}" ] && [ "${FORCE}" -eq 0 ]; then
  echo "❌ core.hooksPath 已指向 '${current}'，与本仓库钩子目录冲突" >&2
  echo "   确认改用 ${HOOKSPATH} 请加 --force；否则先人工核对现状" >&2
  exit 1
fi

git config --local core.hooksPath "${HOOKSPATH}"

# 写入成功≠生效：以回读值为准（fail-closed）
after=$(git config --local --get core.hooksPath || true)
if [ "${after}" != "${HOOKSPATH}" ]; then
  echo "❌ 回读不一致：期望 '${HOOKSPATH}'，实际 '${after}'" >&2
  exit 1
fi

echo "✅ 已安装：core.hooksPath=${HOOKSPATH}"
echo "   钩子:${HOOK_NAMES}"
echo "   自检: GIT_TRACE=1 git hook run pre-commit"
