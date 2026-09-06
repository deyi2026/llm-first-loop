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
WEB_PORT="${WEB_PORT:-8903}"
WEB_HOST="${WEB_HOST:-127.0.0.1}"
LOG_DIR="$PROJECT_ROOT/data"
mkdir -p "$LOG_DIR"

# 加载 .env（与 web 服务同约定，保证 WEB_PORT 等一致）
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

# 校验 cloudflared
if ! command -v cloudflared >/dev/null 2>&1; then
  echo "❌ 未找到 cloudflared，请先安装：brew install cloudflared"
  exit 1
fi

# 校验后端可达（避免隧道通了但后端没起）
if ! curl -sf "http://$WEB_HOST:$WEB_PORT/health" >/dev/null 2>&1; then
  echo "⚠️  后端 http://$WEB_HOST:$WEB_PORT/health 不可达（继续建隧道，但写请求会失败）"
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
    CONFIG="$PROJECT_ROOT/cloudflared/config.yaml"
    if [[ ! -f "$CONFIG" ]]; then
      echo "❌ 未找到配置文件: $CONFIG"
      echo "   请先运行: ./scripts/gen-cloudflared-config.sh <tunnel-id> <your-domain>"
      exit 1
    fi
    if grep -q "REPLACE_WITH_TUNNEL_ID\|YOUR_DOMAIN" "$CONFIG"; then
      echo "❌ 配置文件尚未填写：tunnel ID 和 hostname 仍是占位符"
      echo "   请先运行: ./scripts/gen-cloudflared-config.sh <tunnel-id> <your-domain>"
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
