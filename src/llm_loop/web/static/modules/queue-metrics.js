// 可观测性 M1c-rev（2026-10-14 立项 GOAL-20261014-dddae6e0）：插话指标面板。
// 消费 GET /api/v1/chat/queue/metrics/global（M1b 全局六桶三口径聚合，只读、零写副作用），
// 渲染六桶卡片 + 结构零徽标（structural_zero/zero_reason，M1c §9 口径）。
// 渲染规则对齐后端注释（human_turn_queue.py STRUCTURAL_ZERO_BUCKETS）：
// - structural_zero 且 n=0 → 「结构零」徽标 + 成因文案（部署拓扑使然，非采样不足）；
// - structural_zero 但 n>0 → 照常显示统计，附注「拓扑或已变化」（该属性是拓扑
//   推断而非物理定律，后端 M1c 修订注释明示 n>0 时标注自然不出现）；
// - 非 structural_zero 且 n<5 → insufficient_sample 灰标（诚实口径，不冒充达标）；
// - n=0 → p50/p95 显示 —（后端 null 不造数，前端同口径）。

"use strict";

const QM_BUCKET_LABELS = {
  interruptible: "可打断窗口",
  natural_boundary: "自然边界",
  llm_stream: "流内保守等待",
  llm_stream_interrupt: "流内打断收割",
  sync_window_poll: "同步窗口轮询",
  idle: "空闲期",
};

let _qmTimer = null;

function _qmFmtMs(v) {
  return v === null || v === undefined ? "\u2014" : `${v} ms`;
}

async function loadQueueMetrics() {
  const body = document.getElementById("queue-metrics-body");
  if (!body) return;
  let d = null;
  try {
    const r = await api("/api/v1/chat/queue/metrics/global");
    if (r.status === 200 && r.data && r.data.ok) d = r.data;
  } catch {
    /* fail-open：面板置为不可用，不影响主链路 */
  }
  if (!d) {
    body.textContent = "指标暂不可用";
    return;
  }
  body.innerHTML = "";
  // 窗口口径标注（M1b B5 消费端防误读：视图=最近 N 条终态滚动窗口，非全历史）
  body.appendChild(el("div", "qm-window",
    `窗口：最近 ${d.window_terminal_cap} 条终态 · 覆盖 ${d.sessions_in_window} 会话 · 合计 ${d.n} 条`));
  const buckets = d.buckets || {};
  for (const [key, meta] of Object.entries(buckets)) {
    const card = el("div", "qm-bucket");
    const head = el("div", "qm-bucket-head");
    head.appendChild(el("span", "qm-bucket-name", QM_BUCKET_LABELS[key] || key));
    const zero = meta.structural_zero === true;
    const empty = (meta.n || 0) === 0;
    if (zero && empty) {
      head.appendChild(el("span", "qm-badge qm-badge-zero", "结构零"));
    } else if (meta.insufficient_sample) {
      head.appendChild(el("span", "qm-badge qm-badge-insuff", "样本不足"));
    }
    head.appendChild(el("span", "qm-bucket-n", `n=${meta.n}`));
    card.appendChild(head);
    card.appendChild(el("div", "qm-bucket-stats",
      `p50 ${_qmFmtMs(meta.p50_t_effect_ms)} · p95 ${_qmFmtMs(meta.p95_t_effect_ms)}`));
    if (zero && empty && meta.zero_reason) {
      card.appendChild(el("div", "qm-reason", `结构性零：${meta.zero_reason}`));
    } else if (zero && !empty) {
      card.appendChild(el("div", "qm-reason qm-reason-warn",
        "结构零口径桶出现样本：部署拓扑或已变化（该口径为拓扑推断，非物理定律）"));
    }
    body.appendChild(card);
  }
}

function initQueueMetrics() {
  const panel = document.getElementById("queue-metrics");
  if (!panel) return;
  // 展开时拉取 + 展开期间低频轮询（60s）；收起即停（无谓轮询不占后端）。
  // 独立于 init() 主链路自初始化：面板失败不阻塞会话加载。
  panel.addEventListener("toggle", () => {
    if (panel.open) {
      loadQueueMetrics();
      if (!_qmTimer) _qmTimer = setInterval(loadQueueMetrics, 60000);
    } else if (_qmTimer) {
      clearInterval(_qmTimer);
      _qmTimer = null;
    }
  });
}

initQueueMetrics();
