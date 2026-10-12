"""SMC Browser domain primitives.

Phase 1 intentionally starts with read-only perception.  Mutation dispatch remains
outside this package until a later qualification phase.
"""

from llm_loop.browser.perception import (
    BrowserPerceptionAdapter,
    BrowserPerceptionStore,
    PlaywrightPageCaptureBackend,
)

__all__ = [
    "BrowserPerceptionAdapter",
    "BrowserPerceptionStore",
    "PlaywrightPageCaptureBackend",
]
