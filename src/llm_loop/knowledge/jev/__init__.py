"""EVO-20261015 (P1a): Jev 参与经验/方法闭环的本地 fixture + shadow 层。

DESIGN-20261014-jev §11 P1a：官方 wire 契约、mock 传输（零真实外发）、
外发策略（预算/隐私）、shadow runner（只记录判断，不改检索输出）。
默认维持 OFF：本包不接入 live 检索路径、不新增启用真实外发的开关；
真实传输属 P1b（另授权）。本包不得 import 网络库（由 fixture 测试守卫）。
"""

from llm_loop.knowledge.jev.policy import (
    BudgetRefused,
    OutboundPolicy,
    PolicyGuard,
    ProjectionUnsafe,
    assert_projection_safe,
    build_projection,
    estimate_input_tokens,
)
from llm_loop.knowledge.jev.shadow import JevShadowRunner, ShadowOutcome
from llm_loop.knowledge.jev.transport import (
    JevTransport,
    JevTransportError,
    MockJevTransport,
)
from llm_loop.knowledge.jev.wire import (
    CONTRACT_ENDPOINT,
    CONTRACT_MODEL_ALIAS,
    WIRE_SCHEMA_VERSION,
    NormalizedAnswer,
    NormalizedResponse,
    QuestionSpec,
    UsageFacts,
    build_request,
    normalize_response,
    request_hashes,
)

__all__ = [
    "CONTRACT_ENDPOINT",
    "CONTRACT_MODEL_ALIAS",
    "WIRE_SCHEMA_VERSION",
    "BudgetRefused",
    "OutboundPolicy",
    "PolicyGuard",
    "ProjectionUnsafe",
    "assert_projection_safe",
    "build_projection",
    "estimate_input_tokens",
    "JevShadowRunner",
    "ShadowOutcome",
    "JevTransport",
    "JevTransportError",
    "MockJevTransport",
    "NormalizedAnswer",
    "NormalizedResponse",
    "QuestionSpec",
    "UsageFacts",
    "build_request",
    "normalize_response",
    "request_hashes",
]
