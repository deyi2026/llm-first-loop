"""Provider-agnostic resource governance.

RG-0 defines pure contracts; RG-1 adds the minimal lease/concurrency governor;
RG-2 adds qualified local-runtime provider-call coordination for Task/SubAgent.
RG-3A freezes cloud fact contracts. RG-3B captures typed transport facts.
RG-3C adds durable logical-call/physical-attempt settlement and completeness-aware
accounting. RG-3D adds a rebuildable cross-session ledger projection plus explicit
scope/window/freshness/coverage shadow facts. RG-3E adds authority-safe product/account
binding and pure vendor normalizers; admission/routing/fallback/enforcement still do
not consume those facts.
"""
