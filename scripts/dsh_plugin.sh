#!/usr/bin/env bash
# dsh_plugin.sh — DSH 插件命令面（对齐 dsh plugin add/remove/list 体验，EVO-20260819-f9e7ce23）
# add <pkg>   = npm install 到桥工程 + 写清单（data/dsh-bridge/plugins.json）
# remove <pkg> = npm uninstall + 清清单
# list        = 列出已桥接插件
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE_DIR="$ROOT/data/dsh-bridge"
MANIFEST="$BRIDGE_DIR/plugins.json"
PROFILES="$ROOT/data/dsh-home/profiles"

usage() { echo "用法: dsh_plugin.sh {add <pkg>|remove <pkg>|list}"; exit 1; }
cmd="${1:-list}"
case "$cmd" in
  add)
    pkg="${2:-}"; [ -n "$pkg" ] || usage
    echo ">> npm install $pkg → $PROFILES"
    (cd "$PROFILES" && npm install --no-audit --no-fund "$pkg")
    # 写清单（去重追加）
    python3 - "$MANIFEST" "$pkg" <<'PY'
import json, sys
manifest, pkg = sys.argv[1], sys.argv[2]
try:
    data = json.load(open(manifest))
except Exception:
    data = {"plugins": []}
if pkg not in data["plugins"]:
    data["plugins"].append(pkg)
json.dump(data, open(manifest, "w"), ensure_ascii=False, indent=2)
print("清单已更新:", data["plugins"])
PY
    ;;
  remove)
    pkg="${2:-}"; [ -n "$pkg" ] || usage
    echo ">> npm uninstall $pkg（若不在 DSH 依赖树中可忽略报错）"
    (cd "$PROFILES" && npm uninstall --no-audit --no-fund "$pkg" 2>/dev/null || true)
    python3 - "$MANIFEST" "$pkg" <<'PY'
import json, sys
manifest, pkg = sys.argv[1], sys.argv[2]
try:
    data = json.load(open(manifest))
except Exception:
    data = {"plugins": []}
data["plugins"] = [p for p in data["plugins"] if p != pkg]
json.dump(data, open(manifest, "w"), ensure_ascii=False, indent=2)
print("清单已更新:", data["plugins"])
PY
    ;;
  list)
    python3 - "$MANIFEST" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    data = {"plugins": []}
print("已桥接插件:", ", ".join(data["plugins"]) or "（空）")
PY
    ;;
  *) usage ;;
esac
