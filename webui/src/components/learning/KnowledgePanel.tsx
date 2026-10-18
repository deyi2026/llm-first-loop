import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchExperienceCatalog,
  fetchKnowledgeScores,
  fetchMethodInventory,
  setExperienceLifecycle,
  setMethodTransition,
  type ExperienceCatalog,
  type ExperienceRecordInfo,
  type KnowledgeScoreLedgerEntry,
  type KnowledgeScoreSummary,
  type KnowledgeScoresResponse,
  type MethodCardInfo,
  type MethodInventory,
  type MethodTransition,
} from "../../core/api";

const EXPERIENCE_STATUS_LABELS: Record<string, string> = {
  active: "生效中",
  archived: "已归档",
  invalid: "已失效",
};

const METHOD_STATUS_LABELS: Record<string, string> = {
  candidate: "候选（可用）",
  qualified: "已验证",
  active: "常用",
  hold: "暂停",
  invalidated: "已失效",
  retired: "已退役",
  teacher: "teacher（教学参考）", // EVO-20261013-2: 补齐 store 合法状态，避免裸英文回退
};

const METHOD_TRANSITIONS: { value: MethodTransition; label: string }[] = [
  { value: "qualify", label: "转已验证" },
  { value: "activate", label: "标为常用" },
  { value: "hold", label: "暂停" },
  { value: "invalidate", label: "失效" },
  { value: "retire", label: "退役" },
  { value: "reopen", label: "重开为候选" },
];

type KnowledgeTab = "experiences" | "methods" | "scores";

/** 打分徽标短名：scorer_model 取首个 "-" 前段（如 27B-Instant-MLX-8bit → 27B）. */
function shortScorerName(model: string): string {
  return (model || "").split("-")[0] || model || "?";
}

function ScoreBadge({ summary }: { summary: KnowledgeScoreSummary }) {
  return (
    <span className="v2-knowledge-badge scored" data-testid="score-badge">
      {`${shortScorerName(summary.scorer_model)}·${summary.top_label} ${(summary.confidence ?? 0).toFixed(2)}`}
    </span>
  );
}

function ExperienceCard({
  record,
  onAction,
  busy,
  score,
}: {
  record: ExperienceRecordInfo;
  onAction: (id: string, action: "archive" | "invalidate" | "restore") => void;
  busy: boolean;
  score?: KnowledgeScoreSummary;
}) {
  const id = record.experience_ref || record.experience_id || "";
  return (
    <article className="v2-knowledge-card" data-testid="experience-card">
      <header>
        <strong>{record.summary}</strong>
        <span className={`v2-knowledge-badge ${record.status}`}>
          {EXPERIENCE_STATUS_LABELS[record.status] ?? record.status}
        </span>
        {score ? <ScoreBadge summary={score} /> : null}
      </header>
      <p className="v2-knowledge-desc">{record.scenario}</p>
      <div className="v2-knowledge-meta">
        {record.record_kind ? <span>{record.record_kind === "lesson" ? "lesson" : "experience"}</span> : null}
        {record.verification_state ? <span>{record.verification_state}</span> : null}
        {record.use_count != null ? (
          <span data-testid="experience-use-count">使用 {record.use_count} 次</span>
        ) : null}
        {record.last_used_at ? (
          <span data-testid="experience-last-used">最近使用 {record.last_used_at.slice(0, 10)}</span>
        ) : null}
        {record.updated_at ? <span>{record.updated_at.slice(0, 10)}</span> : null}
      </div>
      {(record.tags ?? []).length > 0 ? (
        <div className="v2-knowledge-tags">
          {(record.tags ?? []).slice(0, 6).map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
      ) : null}
      <footer className="v2-knowledge-actions">
        <code title={id}>{id.slice(-24)}</code>
        {record.status === "active" ? (
          <>
            <button disabled={busy} onClick={() => onAction(id, "archive")}>归档</button>
            <button disabled={busy} className="danger" onClick={() => onAction(id, "invalidate")}>失效</button>
          </>
        ) : (
          <button disabled={busy} onClick={() => onAction(id, "restore")}>恢复生效</button>
        )}
      </footer>
    </article>
  );
}

function MethodCard({
  card,
  onTransition,
  busy,
  score,
}: {
  card: MethodCardInfo;
  onTransition: (id: string, transition: MethodTransition) => void;
  busy: boolean;
  score?: KnowledgeScoreSummary;
}) {
  const id = card.key || card.id || ""; // card() 投影：key=method:<id>（打分索引/流转端点同一 ref 形态）
  const [pending, setPending] = useState<MethodTransition | "">("");
  return (
    <article className="v2-knowledge-card" data-testid="method-card">
      <header>
        <strong>{card.summary || card.id}</strong>
        <span className={`v2-knowledge-badge ${card.status}`}>
          {METHOD_STATUS_LABELS[card.status] ?? card.status}
        </span>
        {score ? <ScoreBadge summary={score} /> : null}
      </header>
      <p className="v2-knowledge-desc">{card.description}</p>
      <div className="v2-knowledge-meta">
        {card.source_model ? <span>{card.source_model}</span> : null}
        {card.ts ? <span>{card.ts.slice(0, 10)}</span> : null}
        {card.last_signal_age_days != null ? <span>最近信号 {card.last_signal_age_days}d 前</span> : null}
      </div>
      <footer className="v2-knowledge-actions">
        <code title={id}>{id.slice(-28)}</code>
        <select aria-label="更改方法状态" value={pending} onChange={(e) => setPending(e.target.value as MethodTransition | "")}>
          <option value="">更改状态</option>
          {METHOD_TRANSITIONS.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        <button
          disabled={busy || !pending}
          onClick={() => {
            if (pending) onTransition(id, pending);
            setPending("");
          }}
        >
          应用
        </button>
      </footer>
    </article>
  );
}

/** 打分明细页签的单条 ledger 行（ts 倒序由调用方保证）。 */
function ScoreRow({ entry }: { entry: KnowledgeScoreLedgerEntry }) {
  const ref = entry.ref || "";
  return (
    <article className="v2-knowledge-card" data-testid="score-entry">
      <header>
        <code title={ref} data-testid="score-entry-ref">
          {ref.slice(-40)}
        </code>
        <span className="v2-knowledge-badge scored">{entry.kind || "—"}</span>
      </header>
      <div className="v2-knowledge-meta">
        <span>{entry.top_label || "（无打分结果）"}</span>
        {entry.top_label ? <span>置信 {(entry.confidence ?? 0).toFixed(2)}</span> : null}
        <span>期望 {(entry.expected ?? 0).toFixed(2)}</span>
        <span>证据充分 {(entry.p_evidence_sufficient ?? 0).toFixed(2)}</span>
        <span>{entry.adopted ? "✓采纳" : "✗未采纳"}</span>
        {entry.decision_reported ? <span>{entry.decision_reported}</span> : null}
        {entry.ts ? <span>{entry.ts.slice(0, 10)}</span> : null}
        {entry.scorer_model ? <span>{shortScorerName(entry.scorer_model)}</span> : null}
      </div>
      {entry.error ? (
        <p className="v2-knowledge-error" data-testid="score-entry-error">
          {entry.error}
        </p>
      ) : null}
    </article>
  );
}

export function KnowledgePanel() {
  const [tab, setTab] = useState<KnowledgeTab>("experiences");
  const [experiences, setExperiences] = useState<ExperienceCatalog | null>(null);
  const [methods, setMethods] = useState<MethodInventory | null>(null);
  const [expStatus, setExpStatus] = useState("");
  const [methodStatus, setMethodStatus] = useState("");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [expError, setExpError] = useState("");
  const [mthError, setMthError] = useState("");
  // 阶段2: 知识打分只读索引（徽标 + 打分明细页签）
  const [scoreData, setScoreData] = useState<KnowledgeScoresResponse | null>(null);
  const [scoresLoading, setScoresLoading] = useState(true);
  const scoreWarned = useRef(false);

  const refresh = useCallback(async () => {
    // EVO-20261013-2: 读取失败与空库分开呈现（fetch 失败抛错），错误不再伪装成"无匹配"
    const [expRes, mthRes] = await Promise.allSettled([
      fetchExperienceCatalog(query, expStatus, 150),
      fetchMethodInventory(query, methodStatus, 150),
    ]);
    if (expRes.status === "fulfilled") {
      setExperiences(expRes.value);
      setExpError("");
    } else {
      setExperiences(null);
      setExpError(expRes.reason instanceof Error ? expRes.reason.message : String(expRes.reason));
    }
    if (mthRes.status === "fulfilled") {
      setMethods(mthRes.value);
      setMthError("");
    } else {
      setMethods(null);
      setMthError(mthRes.reason instanceof Error ? mthRes.reason.message : String(mthRes.reason));
    }
    setLoading(false);
    // 阶段2: 打分索引独立拉取（不进 allSettled，失败静默降级——不显示徽标、
    // 不阻塞经验/方法列表，仅 console.warn 一次避免 30s 轮询刷屏）
    setScoresLoading(true);
    fetchKnowledgeScores()
      .then((res) => {
        setScoreData(res);
      })
      .catch((err: unknown) => {
        setScoreData(null);
        if (!scoreWarned.current) {
          scoreWarned.current = true;
          console.warn("knowledge scores unavailable:", err);
        }
      })
      .finally(() => setScoresLoading(false));
  }, [query, expStatus, methodStatus]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const timer = window.setInterval(() => void refresh(), 30000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const doExperienceAction = async (id: string, action: "archive" | "invalidate" | "restore") => {
    if (!window.confirm(`确认对经验 ${id.slice(-20)} 执行 ${action}？`)) return;
    setBusy(true);
    setMessage(null);
    const result = await setExperienceLifecycle(id, action);
    setBusy(false);
    if (result.ok) {
      setMessage({ kind: "ok", text: `已${action === "archive" ? "归档" : action === "invalidate" ? "失效" : "恢复"} → ${result.status}` });
    } else {
      setMessage({ kind: "err", text: result.detail || result.error || "操作失败" });
    }
    void refresh();
  };

  const doMethodTransition = async (id: string, transition: MethodTransition) => {
    if (!window.confirm(`确认对方法 ${id.slice(-24)} 执行 ${transition}？（受门禁校验，非法流转会被拒绝）`)) return;
    setBusy(true);
    setMessage(null);
    const result = await setMethodTransition(id, transition);
    setBusy(false);
    if (result.ok) {
      setMessage({ kind: "ok", text: `流转成功 → ${result.status}` });
    } else {
      setMessage({ kind: "err", text: result.detail || result.error || "流转被拒绝" });
    }
    void refresh();
  };

  const statusChips = (counts: Record<string, number>, current: string, onSelect: (s: string) => void) => {
    const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    return (
      <div className="v2-knowledge-chips">
        <button className={!current ? "on" : ""} onClick={() => onSelect("")}>
          全部 {entries.reduce((sum, [, n]) => sum + n, 0)}
        </button>
        {entries.map(([status, n]) => (
          <button key={status} className={current === status ? "on" : ""} onClick={() => onSelect(status)}>
            {(tab === "experiences" ? EXPERIENCE_STATUS_LABELS[status] : METHOD_STATUS_LABELS[status]) ?? status} {n}
          </button>
        ))}
      </div>
    );
  };

  return (
    <section className="v2-knowledge-panel" data-testid="knowledge-panel">
      <header className="v2-knowledge-header">
        <div>
          <h2>📚 知识管理</h2>
          <p>经验与方法按任务检索使用，状态和验证信息供参考。</p>
        </div>
        <nav className="v2-knowledge-tabs">
          <button className={tab === "experiences" ? "on" : ""} onClick={() => setTab("experiences")}>
            经验 {experiences ? `(${Object.values(experiences.counts).reduce((a, b) => a + b, 0)})` : ""}
          </button>
          <button className={tab === "methods" ? "on" : ""} onClick={() => setTab("methods")}>
            方法 {methods ? `(${Object.values(methods.counts).reduce((a, b) => a + b, 0)})` : ""}
          </button>
          <button className={tab === "scores" ? "on" : ""} onClick={() => setTab("scores")}>
            打分明细 {scoreData ? `(${scoreData.count})` : ""}
          </button>
        </nav>
      </header>
      <div className="v2-knowledge-toolbar">
        <input
          type="search"
          placeholder={
            tab === "experiences"
              ? "按标题/场景/标签搜索…"
              : tab === "methods"
                ? "按 id/名称/描述搜索…"
                : "打分明细只读，按时间倒序展示全部落账行…"
          }
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button onClick={() => void refresh()} disabled={busy}>刷新</button>
      </div>
      {message ? <div className={`v2-knowledge-message ${message.kind}`}>{message.text}</div> : null}
      {tab === "experiences" ? (
        <>
          {experiences ? statusChips(experiences.counts, expStatus, setExpStatus) : null}
          <div className="v2-knowledge-list">
            {loading ? (
              <div className="v2-knowledge-empty">读取经验库…</div>
            ) : expError ? (
              <div className="v2-knowledge-empty" data-testid="exp-load-error">
                经验库读取失败（{expError}）— 服务异常或未就绪，非空库；30s 后自动重试
              </div>
            ) : (experiences?.records.length ?? 0) === 0 ? (
              <div className="v2-knowledge-empty">无匹配经验</div>
            ) : (
              experiences?.records.map((record) => (
                <ExperienceCard
                  key={record.experience_ref || record.experience_id || record.summary}
                  record={record}
                  score={scoreData?.scores[record.experience_ref || record.experience_id || ""]}
                  onAction={(id, action) => void doExperienceAction(id, action)}
                  busy={busy}
                />
              ))
            )}
          </div>
        </>
      ) : tab === "methods" ? (
        <>
          <p className="v2-knowledge-desc">
            候选方法可直接检索、按任务使用，无需先改为“常用”或完成验证；适用性由模型判断。已退役方法不参与常规检索。
          </p>
          {methods ? statusChips(methods.counts, methodStatus, setMethodStatus) : null}
          <div className="v2-knowledge-list">
            {loading ? (
              <div className="v2-knowledge-empty">读取方法库…</div>
            ) : mthError ? (
              <div className="v2-knowledge-empty" data-testid="mth-load-error">
                方法库读取失败（{mthError}）— 服务异常或未就绪，非空库；30s 后自动重试
              </div>
            ) : (methods?.records.length ?? 0) === 0 ? (
              <div className="v2-knowledge-empty">无匹配方法</div>
            ) : (
              methods?.records.map((card) => (
                <MethodCard
                  key={card.id}
                  card={card}
                  score={scoreData?.scores[card.key || ""]}
                  onTransition={(id, t) => void doMethodTransition(id, t)}
                  busy={busy}
                />
              ))
            )}
          </div>
        </>
      ) : (
        <>
          <div
            data-testid="score-runner-status"
            style={{ display: "flex", flexWrap: "wrap", gap: 12, fontSize: 12, opacity: 0.8, margin: "4px 0 8px" }}
          >
            <span title="按 use slot 统计，包含等待重试的 error 行">
              待补分 {scoreData?.pending ?? "未知"} 条
            </span>
            {scoreData?.runner?.last_success_at ? (
              <span>最近自动打分 {scoreData.runner.last_success_at.slice(0, 16).replace("T", " ")}</span>
            ) : (
              <span>自动打分器尚未运行</span>
            )}
            {scoreData?.runner?.consecutive_failures ? (
              <span
                style={{ color: "#b45309" }}
                title={scoreData.runner.last_error || "打分服务不可用或超时"}
              >
                连续失败 {scoreData.runner.consecutive_failures} 次
                {scoreData.runner.next_retry_at
                  ? `，下次重试 ${scoreData.runner.next_retry_at.slice(0, 16).replace("T", " ")}`
                  : ""}
              </span>
            ) : null}
          </div>
          <div className="v2-knowledge-list">
            {scoresLoading ? (
              <div className="v2-knowledge-empty">读取打分明细…</div>
            ) : (scoreData?.ledger.length ?? 0) === 0 ? (
              <div className="v2-knowledge-empty" data-testid="scores-empty">
                暂无打分记录
              </div>
            ) : (
              [...(scoreData?.ledger ?? [])]
                .sort((a, b) => (b.ts || "").localeCompare(a.ts || ""))
                .map((entry) => (
                  <ScoreRow key={`${entry.ledger_seq}-${entry.ref}-${entry.ts}`} entry={entry} />
                ))
            )}
          </div>
        </>
      )}
    </section>
  );
}
