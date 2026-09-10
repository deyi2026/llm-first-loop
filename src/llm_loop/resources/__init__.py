"""Provider-agnostic resource governance.

RG-0 defines pure contracts; RG-1 adds the minimal lease/concurrency governor;
RG-2 adds qualified local-runtime provider-call coordination for Task/SubAgent.
RG-3A freezes cloud fact contracts. RG-3B captures typed transport facts in a
bounded process-local shadow recorder; admission/routing/fallback/enforcement
still do not consume those observations.
"""
