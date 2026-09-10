"""Provider-agnostic resource governance.

RG-0 defines pure contracts; RG-1 adds the minimal lease/concurrency governor;
RG-2 adds qualified local-runtime provider-call coordination for Task/SubAgent.
RG-3A freezes cloud fact contracts. RG-3B captures typed transport facts.
RG-3C adds durable logical-call/physical-attempt settlement and completeness-aware
accounting; admission/routing/fallback/enforcement still do not consume shadow facts.
"""
