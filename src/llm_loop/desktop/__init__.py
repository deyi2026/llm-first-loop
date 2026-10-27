"""M3 desktop read-only perception package (DESIGN-20261027 §5.3/§7.2, D2).

Import safety contract: importing ``llm_loop.desktop`` (or any submodule) NEVER
loads macOS frameworks — every ``ctypes.CDLL`` happens lazily inside functions
of the ``macos_*`` modules, so the package imports cleanly on any platform and
in CI without a GUI.  The tool layer lives in
``llm_loop.tools.builtin.desktop_perceive`` and owns validation, privacy
gating, receipts, and audit.
"""

from llm_loop.desktop.models import (
    AX_NODE_LIMIT_DEFAULT,
    DEFAULT_AX_DEPTH,
    MAX_AX_DEPTH,
    DesktopErrorCode,
)

__all__ = [
    "AX_NODE_LIMIT_DEFAULT",
    "DEFAULT_AX_DEPTH",
    "DesktopErrorCode",
    "MAX_AX_DEPTH",
]

