"""RG-3E vendor-specific resource fact normalizers.

Adapters translate explicit provider facts into vendor-neutral RG contracts. They do
not perform network I/O and are not consulted by ResourceGovernor in RG-3E.
"""

from llm_loop.resources.vendor_adapters.deepseek import DeepSeekResourceAdapter
from llm_loop.resources.vendor_adapters.glm import GlmResourceAdapter
from llm_loop.resources.vendor_adapters.minimax import MiniMaxResourceAdapter

__all__ = ("DeepSeekResourceAdapter", "GlmResourceAdapter", "MiniMaxResourceAdapter")
