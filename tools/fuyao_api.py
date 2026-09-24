#!/usr/bin/env python3
"""同花顺金融数据服务（fuyao.aicubes.cn）REST 客户端（LFL 接入层）。

契约来源: github.com/HiThink-Tech/Financial-API docs/api（2026-09-20 核对）
- Base URL: https://fuyao.aicubes.cn ；公开数据端点均为 GET
- 认证: HTTP Header  X-api-key: <key>
- 成功: HTTP 200 且 code == 0（业务错误 HTTP 恒 200，经 code 表达）
- 信封: {code, message, request_id, data}
- 限流 4001 / 服务端 5xxx / 网络错误自动退避重试（≤3 次）；1xxx/2xxx/3xxx 不重试

配置: 工作区 .env 中  FUYAO_API_KEY=<你的key>（勿提交 git，勿在对话外明文扩散）

端点别名:
  trading-days  GET /api/a-share/calendar/trading-days   近一年交易日，无参数
  historical    GET /api/a-share/prices/historical       历史K线
                thscode=600519.SH  interval=1d 必传（实测缺省报 code=1001，当前仅支持日线）
                start/end=毫秒时间戳（可直接给 yyyyMMdd，自动换算 Asia/Shanghai）
                adjust=none|forward|backward（默认 forward）窗口≤10年
  snapshot      GET /api/a-share/prices/snapshot         最新行情快照
  search        GET /api/meta/tickers/search             标的检索消歧 (q, limit)
  valuations    GET /api/a-share/valuations/snapshot     估值快照
  也支持完整路径（自动补 /api/ 前缀），如 a-share/financials/indicators

CLI:
  python3 tools/fuyao_api.py trading-days
  python3 tools/fuyao_api.py historical thscode=600519.SH start=20260914 end=20260920
  python3 tools/fuyao_api.py search q=600519 limit=1
  大结果落盘: 追加 out=路径.json（终端只回执文件路径+条数，契约要求大结果不进对话）
Python:
  from tools.fuyao_api import api
  api("historical", {"thscode": "600519.SH", "start": "20260901", "end": "20260920"})

响应: 成功 -> {"ok": true, "data": ...}；失败 -> {"ok": false, "code", "error", ...}
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE_URL = os.environ.get("FUYAO_BASE_URL", "https://fuyao.aicubes.cn")
_WORKSPACE = Path(__file__).resolve().parent.parent
_CST = timezone(timedelta(hours=8))  # 契约: 日期按 Asia/Shanghai 解释

ALIASES = {
    "trading-days": "/api/a-share/calendar/trading-days",
    "historical": "/api/a-share/prices/historical",
    "snapshot": "/api/a-share/prices/snapshot",
    "valuations": "/api/a-share/valuations/snapshot",
    "search": "/api/meta/tickers/search",
}

_HINTS = {
    1001: "缺少必填参数——补齐后重试",
    1002: "参数格式无效——核对代码/枚举/日期格式",
    1003: "参数超范围——缩小分页或时间窗口（历史K线≤10年）",
    1004: "参数冲突——按端点互斥规则重组参数",
    2001: "未认证——检查 X-api-key 是否携带且格式正确",
    2003: "Key 无效或无该接口权限——控制台核对授权或重签",
    3001: "标的不存在——先用 search 端点消歧 thscode",
    3002: "数据尚未就绪——保留 request_id 稍后再查，勿补零",
    3004: "该资产类型不支持此能力——换适用端点",
    4001: "触发限流——已指数退避重试",
    5001: "服务端异常——已退避重试",
    5002: "上游异常——已退避重试",
    5003: "上游异常——已退避重试",
}
_RETRYABLE = {4001, 5001, 5002, 5003}
_DATE_RE = re.compile(r"\d{8}")
_MS_RE = re.compile(r"\d{13}")


def load_env(path=None):
    """把 .env 中缺失变量补入 os.environ；进程已有变量优先，不覆盖。"""
    p = Path(path) if path else _WORKSPACE / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _to_ms(v):
    """yyyyMMdd → Asia/Shanghai 当日 00:00 毫秒时间戳；13 位毫秒戳原样；其余透传。"""
    s = str(v).strip()
    if _MS_RE.fullmatch(s):
        return int(s)
    if _DATE_RE.fullmatch(s):
        return int(datetime.strptime(s, "%Y%m%d").replace(tzinfo=_CST).timestamp() * 1000)
    return v


def _resolve(endpoint):
    ep = str(endpoint).strip().strip("/")
    if ep in ALIASES:
        return ALIASES[ep]
    if "/" in ep:
        return f"/api/{ep}" if not ep.startswith("api/") else f"/{ep}"
    raise ValueError(
        f"未知端点: {endpoint}。可用别名: {', '.join(sorted(ALIASES))} "
        f"或完整路径（如 a-share/financials/indicators）"
    )


def api(endpoint, params=None, api_key=None, timeout=30, retries=3):
    """调用 GET <BASE_URL><path>，统一处理 ApiResponse 信封与有界退避重试。"""
    load_env()
    key = (api_key or os.environ.get("FUYAO_API_KEY", "")).strip()
    if not key:
        return {"ok": False, "code": None,
                "error": "FUYAO_API_KEY 未配置：请在工作区 .env 填入后重试"}
    try:
        path = _resolve(endpoint)
    except ValueError as e:
        return {"ok": False, "code": None, "error": str(e)}
    params = {k: (_to_ms(v) if k in ("start", "end", "date") else v)
              for k, v in (params or {}).items()}
    url = f"{BASE_URL}{path}"
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers={"X-api-key": key}, timeout=timeout)
        except requests.RequestException as e:
            last = {"ok": False, "code": None, "error": f"网络错误: {e!r}"}
        else:
            if r.status_code != 200:
                last = {"ok": False, "code": None,
                        "error": f"HTTP {r.status_code}: {r.text[:200]}"}
            else:
                try:
                    env = r.json()
                except ValueError:
                    return {"ok": False, "code": None, "error": f"非 JSON 响应: {r.text[:300]}"}
                code = env.get("code")
                if code == 0:
                    return {"ok": True, "data": env.get("data")}
                last = {"ok": False, "code": code,
                        "error": _HINTS.get(code, env.get("message", "未知业务错误")),
                        "message": env.get("message"), "request_id": env.get("request_id")}
                if code not in _RETRYABLE:
                    return last  # 1xxx/2xxx/3xxx 调用方可修复，重试无意义
        if attempt < retries:
            time.sleep(2 ** attempt)  # 1s/2s/4s 指数退避
    return last


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    params = {}
    for kv in argv[1:]:
        if "=" not in kv:
            print(f"忽略非法参数(需 k=v): {kv}", file=sys.stderr)
            continue
        k, _, v = kv.partition("=")
        params[k] = v
    out_path = params.pop("out", None)
    out = api(argv[0], params)
    if out_path and out.get("ok"):
        p = Path(out_path).expanduser()
        p.write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
        data = out.get("data") or {}
        n = len(data.get("item", [])) if isinstance(data, dict) else None
        print(json.dumps({"ok": True, "file": str(p),
                          "bytes": p.stat().st_size, "items": n}, ensure_ascii=False))
        return 0
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str)[:8000])
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
