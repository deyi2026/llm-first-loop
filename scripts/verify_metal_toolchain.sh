#!/bin/bash
# Metal Toolchain 安装后验证脚本: 确认 llama.cpp Metal 后端恢复
set -e
MODEL=/Users/yyj/.lmstudio/.internal/bundled-models/nomic-ai/nomic-embed-text-v1.5-GGUF/nomic-embed-text-v1.5.Q4_K_M.gguf
BIN=~/.lmstudio/extensions/backends/llama.cpp-mac-arm64-apple-metal-advsimd-2.28.2/llama-server
echo "== 1. 离线 Metal 编译器 =="
printf '#include <metal_stdlib>\nusing namespace metal;\nkernel void t(device float* o [[buffer(0)]], uint i [[thread_position_in_grid]]) { o[i] = 1.0; }\n' > /tmp/mt.metal
if xcrun -sdk macosx metal -c /tmp/mt.metal -o /tmp/mt.air 2>/tmp/mt.err; then
  echo "OK: xcrun metal 可编译"
else
  echo "FAIL: $(cat /tmp/mt.err)"
fi
echo "== 2. llama-server Metal 初始化 =="
LOG=/tmp/mt_verify.log
("$BIN" --model "$MODEL" --port 59888 --n-gpu-layers 999 > "$LOG" 2>&1 & echo $! > /tmp/mt_verify.pid)
sleep 8
kill "$(cat /tmp/mt_verify.pid)" 2>/dev/null || true
if grep -q "error compiling source" "$LOG"; then
  echo "FAIL: Metal 仍初始化失败（CPU 模式）"
else
  echo "OK: 无 Metal 编译错误"
fi
grep -iE "metal|offload|buffer size|VRAM" "$LOG" | head -5 || true
rm -f /tmp/mt.metal /tmp/mt.air /tmp/mt.err /tmp/mt_verify.log /tmp/mt_verify.pid
