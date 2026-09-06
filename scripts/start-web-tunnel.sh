#!/usr/bin/env bash
# start-web-tunnel.sh — 一键启动 cloudflared 隧道，把 Web 端暴露到公网域名
#
# 两种模式：
#   quick  : 临时公共域名（重启即变），零配置，适合快速测试
#   named  : 固定域名（需 cloudflared/config.yaml + Cloudflare Zero Trust 绑定）
#
# 用法：
#   ./scripts/start-web-tunnel.sh quick          # 临时域名
#   ./scripts/start-web-tunnel.sh named          # 固定域名（读 cloudflared/config.yaml）
#
# 环境变量：
#   WEB_PORT   后端端口（默认 8903，镜像区；主区为 8902）
#   WEB_HOST   后端地址（默认 127.0.0.1）
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

TUNNEL_MODE="${1:-quick}"
LOG_DIR="$PROJECT_ROOT/data"
mkdir -p "$LOG_DIR"

# 只读取 tunnel 实际需要的两个 .env 字段，不 source/eval 整份文件。
# 密码哈希、token 等值可能含 `$`/shell 元字符；执行 .env 既脆弱也扩大秘密暴露面。
_read_env_value() {
  local key="$1"
  python3 - "$PROJECT_ROOT/.env" "$key" <<'PYENV'
from pathlib import Path
import sys
path, key = Path(sys.argv[1]), sys.argv[2]
if path.is_file():
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, value = line.split("=", 1)
        if k.strip() == key:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            print(value)
            break
PYENV
}
ENV_WEB_PORT="$(_read_env_value WEB_PORT)"
ENV_WEB_HOST="$(_read_env_value WEB_HOST)"
WEB_PORT="${WEB_PORT:-${ENV_WEB_PORT:-8903}}"
WEB_HOST="${WEB_HOST:-${ENV_WEB_HOST:-127.0.0.1}}"

# 校验 cloudflared
if ! command -v cloudflared >/dev/null 2>&1; then
  echo "❌ 未找到 cloudflared，请先安装：brew install cloudflared"
  exit 1
fi

# 校验后端可达（避免隧道通了但后端没起）
if ! curl -sf "http://$WEB_HOST:$WEB_PORT/auth/status" >/dev/null 2>&1; then
  echo "⚠️  后端 http://$WEB_HOST:$WEB_PORT/auth/status 不可达（继续建隧道，但请求会失败）"
  echo "   请先启动 web 服务: WEB_PORT=$WEB_PORT python -m llm_loop.web"
fi

case "$TUNNEL_MODE" in
  quick)
    echo "🚀 启动 quick tunnel（临时公共域名，重启即变）"
    echo "   后端: http://$WEB_HOST:$WEB_PORT"
    echo "   隧道日志: $LOG_DIR/cloudflared-quick.log"
    cloudflared tunnel --url "http://$WEB_HOST:$WEB_PORT" --no-autoupdate 2>&1 | tee "$LOG_DIR/cloudflared-quick.log"
    ;;
  named)
    LOCAL_CONFIG="$PROJECT_ROOT/cloudflared/config.local.yaml"
    TEMPLATE_CONFIG="$PROJECT_ROOT/cloudflared/config.yaml"
    CONFIG="$TEMPLATE_CONFIG"
    [[ -f "$LOCAL_CONFIG" ]] && CONFIG="$LOCAL_CONFIG"
    if [[ ! -f "$CONFIG" ]]; then
      echo "❌ 未找到配置文件: $CONFIG"
      echo "   请生成本机 cloudflared/config.local.yaml"
      exit 1
    fi
    if grep -q "REPLACE_WITH_TUNNEL_ID\|YOUR_DOMAIN" "$CONFIG"; then
      echo "❌ 当前仅有模板配置；请生成本机 cloudflared/config.local.yaml"
      exit 1
    fi
    echo "🚀 启动 named tunnel（固定域名，读 $CONFIG）"
    echo "   隧道日志: $LOG_DIR/cloudflared-named.log"
    cloudflared tunnel --config "$CONFIG" run 2>&1 | tee "$LOG_DIR/cloudflared-named.log"
    ;;
  *)
    echo "用法: $0 {quick|named}"
    echo "  quick  临时公共域名（零配置）"
    echo "  named  固定域名（需 cloudflared/config.yaml）"
    exit 1
    ;;
esac
