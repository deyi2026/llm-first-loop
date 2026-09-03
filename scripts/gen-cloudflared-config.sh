#!/usr/bin/env bash
# gen-cloudflared-config.sh — 生成 cloudflared named tunnel 配置
#
# 用法：
#   ./scripts/gen-cloudflared-config.sh <TUNNEL_ID> <YOUR_DOMAIN> [WEB_PORT]
#
# 示例：
#   ./scripts/gen-cloudflared-config.sh abc123def456  ui.example.com 8903
#
# 生成 cloudflared/config.yaml（填入 tunnel ID + hostname + 端口），
# 随后把 credentials file 命名为 cloudflared/tunnel.json 即可：
#   ./scripts/start-web-tunnel.sh named
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TUNNEL_ID="${1:-}"
DOMAIN="${2:-}"
WEB_PORT="${3:-8903}"

if [[ -z "$TUNNEL_ID" || -z "$DOMAIN" ]]; then
  echo "用法: $0 <TUNNEL_ID> <YOUR_DOMAIN> [WEB_PORT]"
  echo "  TUNNEL_ID  从 Cloudflare Zero Trust 获取的 Tunnel ID（32 位 hex）"
  echo "  YOUR_DOMAIN  要绑定的公网域名（如 ui.example.com）"
  echo "  WEB_PORT   后端端口（默认 8903）"
  exit 1
fi

CONFIG="$PROJECT_ROOT/cloudflared/config.yaml"
cat > "$CONFIG" << YAML_EOF
# cloudflared Named Tunnel 配置（固定域名访问）
# 由 ./scripts/gen-cloudflared-config.sh 自动生成 — $(date '+%Y-%m-%d %H:%M:%S')
#
# Tunnel ID: $TUNNEL_ID
# 绑定域名: $DOMAIN
# 后端端口: $WEB_PORT
#
# 【后续操作】
#   1. 把 credentials file 下载到本目录并命名为 tunnel.json:
#      $PROJECT_ROOT/cloudflared/tunnel.json
#   2. 启动隧道:
#      ./scripts/start-web-tunnel.sh named
#
tunnel: $TUNNEL_ID
credentials-file: ./tunnel.json

ingress:
  - hostname: $DOMAIN
    service: http://127.0.0.1:$WEB_PORT

  - service: http_status:404
YAML_EOF

echo "✅ 已生成配置: $CONFIG"
echo "   Tunnel ID: $TUNNEL_ID"
echo "   绑定域名:  $DOMAIN"
echo "   后端端口:  $WEB_PORT"
echo ""
echo "下一步："
echo "  1. 把 credentials file 放到: $PROJECT_ROOT/cloudflared/tunnel.json"
echo "  2. 启动: ./scripts/start-web-tunnel.sh named"
