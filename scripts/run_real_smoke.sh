#!/usr/bin/env bash
# 本地真实链路一键回归（R4/A3，2026-08-14）
#
# key 不上传策略下 CI nightly 跳过真实评测——本脚本在本地完成等价回归：
#   1. real_llm 冒烟（test_real_llm_smoke + test_real_llm_exec_smoke，需真实 key）
#   2. 评测集真实运行（6 场景 ×6 样本，报告落盘 docs/metrics/eval_<ts>/）
#   3. 失败即非零退出（可接 cron/手动）
#
# 用法:
#   bash scripts/run_real_smoke.sh            # 完整回归（key 从 .env 读取）
#   bash scripts/run_real_smoke.sh --quick    # 仅冒烟（跳过评测集，省配额）
#
# key 来源: DEEPSEEK_API_KEY env 优先 → 项目 .env；不上传任何仓库。

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

QUICK=0
if [[ "${1:-}" == "--quick" ]]; then
  QUICK=1
fi

# ── key 注入（env 优先 → .env 回退；不落盘不打印值）──
load_env_val() {
  local key="$1"
  local val=""
  if [[ -n "${!key:-}" ]]; then
    val="${!key}"
  elif [[ -f .env ]]; then
    val="$(grep -m1 "^${key}=" .env | cut -d= -f2- || true)"
  fi
  printf '%s' "$val"
}

export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-$(load_env_val DEEPSEEK_API_KEY)}"
export LLM_BASE_URL="${LLM_BASE_URL:-$(load_env_val LLM_BASE_URL)}"
export LLM_MODEL="${LLM_MODEL:-$(load_env_val LLM_MODEL)}"

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "❌ 未找到真实 LLM key（DEEPSEEK_API_KEY env 或 .env）；无法运行真实回归"
  exit 2
fi

echo "=== [1/3] real_llm 冒烟（$([ "$QUICK" = 1 ] && echo quick || echo full)）==="
if [[ "$QUICK" = 1 ]]; then
  .venv/bin/python -m pytest \
    tests/integration/test_real_llm_smoke.py::test_real_llm_smoke_self_evaluate_and_evolve \
    tests/integration/test_real_llm_exec_smoke.py::test_exec_aux_01_summarizer \
    -m real_llm -q
else
  .venv/bin/python -m pytest \
    tests/integration/test_real_llm_smoke.py tests/integration/test_real_llm_exec_smoke.py \
    -m real_llm -q
fi

# EVO-20260815-f22ab8dd: 真实 tool-call 往返门禁（v0.6.5 arguments 透传回归补洞）
# 协议矩阵: 默认 openai(deepseek); 其他协议经 SMOKE_WIRE_PROTOCOL=anthropic|google
#           + SMOKE_API_KEY/SMOKE_BASE_URL/SMOKE_MODEL 逐协议执行（无 key 自动 skip）
echo "=== [1.5/3] 真实 tool-call 往返（arguments str→dict 解析门禁）==="
.venv/bin/python -m pytest \
  tests/integration/test_real_llm_smoke.py::test_real_llm_tool_call_arguments_roundtrip \
  -m real_llm -q

if [[ "$QUICK" = 1 ]]; then
  echo "✅ quick 冒烟通过（完整回归请不带 --quick 运行）"
  exit 0
fi

echo "=== [2/3] 评测集真实运行 ==="
.venv/bin/python scripts/run_eval.py --output "docs/metrics/eval_$(date +%Y%m%d-%H%M%S)"

echo "✅ 本地真实回归全部通过（报告见 docs/metrics/eval_* 最新目录）"
