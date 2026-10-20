#!/usr/bin/env bash
# D7-3: 下载本地两段式语义检索模型（Xenova/bge-small-zh-v1.5 int8 量化版）.
#
# 用法: bash scripts/download_semantic_model.sh [目标目录]
#   目标目录缺省 ~/.cache/lfl/models/bge-small-zh-v1.5（LocalOnnxEmbedder 默认
#   探测路径；亦可用 env LFL_SEMANTIC_MODEL_DIR 指定任意目录）。
# 行为:
#   - 逐文件 sha256 锁定校验（指纹来自统筹者实测）；
#   - 已存在且校验通过 → 跳过下载；存在但损坏/指纹不符 → 重新下载覆盖；
#   - 任一文件下载/校验失败 → 非零退出（调用方可 fail-open 回退词法检索）；
#   - 修订（批次2 D7 后审）: EXIT trap 清理残留 .tmp.* 孤儿文件（中断/被杀
#     不留半成品），下载前另做一次陈旧 tmp 预清理。
set -euo pipefail

BASE_URL="https://huggingface.co/Xenova/bge-small-zh-v1.5/resolve/main"
# 实测路径: 量化 ONNX 在 onnx/ 子目录（根路径 404），tokenizer.json 在根目录
MODEL_URL="$BASE_URL/onnx/model_quantized.onnx"
MODEL_FILE="model_quantized.onnx"
MODEL_SHA256="15b717c382bcb518ba457b93ea6850ede7f4f1cd8937454aa06972366cd19bcc"
TOKENIZER_URL="$BASE_URL/tokenizer.json"
TOKENIZER_FILE="tokenizer.json"
TOKENIZER_SHA256="48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26"
TARGET_DIR="${1:-$HOME/.cache/lfl/models/bge-small-zh-v1.5}"

# 孤儿临时文件清理: tmp_file 为全局变量（fetch 内赋值），EXIT trap 兜底删除
# 当前在途 tmp；正常路径（校验通过 mv 后）置空避免误删。
tmp_file=""
cleanup_tmp() {
  if [ -n "${tmp_file:-}" ]; then
    rm -f "$tmp_file"
  fi
}
trap cleanup_tmp EXIT

# 预清理: 上次中断遗留的陈旧半成品（glob 无匹配时 rm -f 静默通过）
rm -f "$TARGET_DIR"/*.tmp.* 2>/dev/null || true

sha256_of() {  # <file> → sha256 hex
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    sha256sum "$1" | awk '{print $1}'
  fi
}

fetch() {  # <remote_url> <filename> <expected_sha256>
  local url="$1" file="$TARGET_DIR/$2" expected="$3" actual
  # 注意: tmp_file 故意不进 local——EXIT trap 需读到全局在途路径兜底清理
  if [ -f "$file" ]; then
    actual="$(sha256_of "$file" || true)"
    if [ "$actual" = "$expected" ]; then
      echo "[skip] $2 已存在且 sha256 校验通过: $file"
      return 0
    fi
    echo "[redo] $2 指纹不符（损坏/版本漂移），重新下载"
  fi
  mkdir -p "$TARGET_DIR"
  tmp_file="$file.tmp.$$"
  echo "[get ] $url -> $file"
  # -C - 断点续传 + --retry-all-errors（curl 18 部分传输不在默认 transient 列表）
  if ! curl -fL --retry 5 --retry-all-errors --retry-delay 2 -C - \
      --connect-timeout 15 -o "$tmp_file" "$url"; then
    echo "[error] 下载失败: $url" >&2
    rm -f "$tmp_file"
    exit 1
  fi
  actual="$(sha256_of "$tmp_file")"
  if [ "$actual" != "$expected" ]; then
    echo "[error] $2 sha256 校验失败: 期望 $expected 实得 $actual" >&2
    rm -f "$tmp_file"
    exit 1
  fi
  mv "$tmp_file" "$file"
  tmp_file=""  # 已就位，EXIT trap 无需再清理
  echo "[ok  ] $2 ($actual)"
}

fetch "$MODEL_URL" "$MODEL_FILE" "$MODEL_SHA256"
fetch "$TOKENIZER_URL" "$TOKENIZER_FILE" "$TOKENIZER_SHA256"
echo "done: 模型就绪 @ $TARGET_DIR"
