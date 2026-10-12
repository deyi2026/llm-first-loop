#!/bin/bash
# cloudflared-launch.sh — launchd 入口 (com.llmfirstloop.cloudflared)
# 动态解析本机物理网卡 IPv4 作为 --edge-bind-address：
#   背景1: 本机常有 Surge/VPN utun 虚接口，cloudflared 默认 bind 到 utun 后 7844 连
#          不上边缘(198.18.x 假IP污染)，需显式 bind 到物理网卡 IP。
#   背景2: 静态写死 IP 在换 Wi-Fi/网段后失效，进程"活着"但边缘全断(ha_connections=0)。
#   自愈: 运行中换网由 tunnel-watchdog.sh 检测 ha=0 后 kickstart 本服务 → 此处重新解析。
#   降级: 取不到任何合资格 IP 时不加 --edge-bind-address，按 cloudflared 默认行为跑。
# 注意: macOS 自带 bash 3.2，空数组 + set -u 需用 ${ARR[@]+"${ARR[@]}"} 惯用法。
set -u
CF=/opt/homebrew/bin/cloudflared
CONFIG="$(cd "$(dirname "$0")/.." && pwd)/cloudflared/config.local.yaml"
TAG="[cloudflared-launch]"

pick_ip() {
  local ifc ip
  for ifc in $(ifconfig -l); do
    case "$ifc" in
      lo*|utun*|awdl*|llw*|bridge*|veth*|docker*|anpi*|ap*|gif*|stf*|ipsec*) continue ;;
    esac
    ip=$(ipconfig getifaddr "$ifc" 2>/dev/null) || continue
    [ -n "$ip" ] || continue
    printf '%s' "$ip"
    return 0
  done
  return 1
}

BIND_ARGS=()
if IP=$(pick_ip); then
  echo "$(date '+%F %T') $TAG picked edge-bind-address $IP"
  BIND_ARGS=(--edge-bind-address "$IP")
else
  echo "$(date '+%F %T') $TAG no qualified physical iface IP, launching without bind"
fi

exec "$CF" tunnel \
  --no-autoupdate \
  --config "$CONFIG" \
  --protocol http2 \
  ${BIND_ARGS[@]+"${BIND_ARGS[@]}"} \
  --metrics 127.0.0.1:20243 \
  run
