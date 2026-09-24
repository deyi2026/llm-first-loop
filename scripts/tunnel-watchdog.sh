#!/usr/bin/env bash
# tunnel-watchdog.sh — cloudflared 边缘连接自愈
# 机制：Surge 假IP期会把 daemon 内存边缘地址池污染成 198.18.x，DNS 恢复后进程
# 仍无限重拨假 IP（ha_connections=0 死锁），唯一恢复手段是重启进程重新解析。
# 本脚本每 2 分钟被 launchd 调起，连续 2 次发现 ha_connections=0 即 kickstart。
set -u
METRICS="http://127.0.0.1:20243/metrics"
STATE="/tmp/llmfirstloop-tunnel-watchdog.miss"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/data/tunnel-watchdog.log"
LABEL="gui/$(id -u)/com.llmfirstloop.cloudflared"

# Prometheus exposition also contains HELP/TYPE metadata lines with the metric
# name. Match the sample row exactly; otherwise `ha` becomes a multi-line value
# such as "HELP\nTYPE\n4", which makes the numeric test fail and can trigger a
# restart loop even while the tunnel is healthy.
ha=$(curl -s --max-time 5 "$METRICS" 2>/dev/null | awk '$1 == "cloudflared_tunnel_ha_connections" { print int($2); exit }')
if [ "${ha:-0}" -ge 1 ]; then
  [ -f "$STATE" ] && rm -f "$STATE"
  exit 0
fi
miss=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
echo "$(date '+%F %T') miss=$miss ha=${ha:-unreachable}" >> "$LOG"
if [ "$miss" -ge 2 ]; then
  echo "$(date '+%F %T') ha_connections=0 x2, restarting $LABEL" >> "$LOG"
  launchctl kickstart -k "$LABEL"
  rm -f "$STATE"
fi
echo "$miss" > "$STATE"
