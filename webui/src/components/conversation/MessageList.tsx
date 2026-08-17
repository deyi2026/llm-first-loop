// Web V2：消息列表（滚动跟随/回到底部/加载更早；流式期间自动跟随）

import { useEffect, useMemo, useRef, useState } from "react";
import { MessageItem, extractProducedPaths } from "./MessageItem";
import { loadEarlierHistory, useConversation } from "../../core/conversation";
import { sessionStore } from "../../core/stores";
import { EVT_SEARCH_FOCUS } from "../../core/shortcuts";
import { zh } from "../../i18n/zh";

export function MessageList() {
  const conv = useConversation();
  const [atBottom, setAtBottom] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  // 对齐 DSH：会话内搜索（轻量——过滤当前加载消息 + 高亮 + 定位）
  const [searchQ, setSearchQ] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  // 会话级出产物集合（对齐 DSH turn 级 deliverables）：跨消息累积 edit_file 路径，
  // 供最终回答正文中的路径引用可点击打开（编辑与引用通常在不同消息）
  const producedPaths = useMemo(() => {
    const out: string[] = [];
    for (const m of conv.messages) {
      for (const p of extractProducedPaths(m.toolCalls)) {
        if (!out.includes(p)) out.push(p);
      }
    }
    return new Set(out);
  }, [conv.messages]);

  const updateBottom = () => {
    const el = scrollRef.current;
    if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 120);
  };

  // 消息变化（含流式增量）→ 底部态跟随滚动
  useEffect(() => {
    const el = scrollRef.current;
    if (el && atBottom) {
      el.scrollTop = el.scrollHeight;
    }
  }, [conv.messages, atBottom]);

  // 对齐 DSH：⌘K / Ctrl+K 聚焦搜索框（全局事件）
  useEffect(() => {
    const onFocus = () => {
      setSearchOpen(true);
      requestAnimationFrame(() => searchRef.current?.focus());
    };
    window.addEventListener(EVT_SEARCH_FOCUS, onFocus);
    return () => window.removeEventListener(EVT_SEARCH_FOCUS, onFocus);
  }, []);

  // 轻量过滤：匹配当前加载消息（content 含关键字）
  const searchResults = useMemo(() => {
    const q = searchQ.trim().toLowerCase();
    if (!q) return [];
    const out: number[] = [];
    conv.messages.forEach((m, i) => {
      const c = (m.content ?? "").toLowerCase();
      const tc = (m.toolCalls ?? [])
        .map((t: { name?: string; args?: string }) => `${t.name ?? ""} ${t.args ?? ""}`)
        .join(" ")
        .toLowerCase();
      if (c.includes(q) || tc.includes(q)) out.push(i);
    });
    return out;
  }, [searchQ, conv.messages]);

  // 定位到匹配消息（滚动 + 高亮闪烁）
  const locate = (idx: number) => {
    const el = scrollRef.current;
    if (!el) return;
    const target = el.querySelector(`[data-msg-idx="${idx}"]`);
    if (target) {
      target.scrollIntoView({ block: "center", behavior: "smooth" });
      target.classList.add("v2-search-flash");
      window.setTimeout(() => target.classList.remove("v2-search-flash"), 1500);
    }
  };

  if (conv.messages.length === 0) {
    return (
      <div className="v2-conversation-empty" data-testid="empty-state">
        <h2>{zh.emptyHeroTitle}</h2>
        <p>{zh.emptyHeroSub}</p>
      </div>
    );
  }

  return (
    <div
      className="v2-message-list"
      ref={scrollRef}
      onScroll={updateBottom}
      data-testid="message-list"
    >
      {conv.hasMoreHistory && (
        <button
          type="button"
          className="v2-load-earlier"
          onClick={() => {
            const sid = sessionStore.getState().currentSessionId;
            if (sid) void loadEarlierHistory(sid);
          }}
        >
          ↑ {zh.loadEarlier}
        </button>
      )}
      {searchOpen && (
        <div className="v2-search-bar" data-testid="session-search">
          <input
            ref={searchRef}
            className="v2-search-input"
            placeholder={zh.searchInSession}
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setSearchOpen(false);
                setSearchQ("");
              } else if (e.key === "Enter" && searchResults.length > 0) {
                locate(searchResults[0]);
              }
            }}
          />
          <span className="v2-search-count">
            {searchQ.trim()
              ? `${searchResults.length} ${zh.searchMatches}`
              : ""}
          </span>
          {searchQ.trim() && searchResults.length === 0 && (
            <span className="v2-search-none">{zh.searchNoMatch}</span>
          )}
        </div>
      )}
      {conv.messages.map((m, i) => (
        <MessageItem
          key={i}
          msg={m}
          index={i}
          sessionId={sessionStore.getState().currentSessionId ?? undefined}
          producedPaths={producedPaths}
        />
      ))}
      {!atBottom && (
        <button
          type="button"
          className="v2-scroll-bottom"
          onClick={() => {
            const el = scrollRef.current;
            if (el) el.scrollTop = el.scrollHeight;
          }}
        >
          ↓ {zh.backToBottom}
        </button>
      )}
    </div>
  );
}
