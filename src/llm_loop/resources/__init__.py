"""Provider-agnostic resource governance.

RG-0 defines pure contracts; RG-1 adds the minimal lease/concurrency governor;
RG-2 adds qualified local-runtime provider-call coordination for Task/SubAgent
while keeping cloud rate/cost/trust/cancel policy intentionally unwired. RG-3A
extends only the pure cloud fact vocabulary (product/usage/error/quota/pricing
and independent resource dimensions); it still adds no cloud enforcement.
"""
