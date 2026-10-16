"""独立打分器接入（知识闭环: 经验/方法卡实际帮助程度的独立评价）.

对「知识卡在某任务中的实际帮助程度」做独立（非模型自评）打分：
- client: StartLux-Decision /v1/systemone 协议 HTTP 客户端（严格校验）
- state_builder: 知识卡 + 使用回执 → 中文三段式 state
- ledger: 打分明细账本 data/knowledge_scores/ledger.jsonl（原子追加 + 行级完整性）
- card_writeback: 打分结果写回（sidecar，不触碰卡片文件——version 调查结论）
- pending: --all-pending 的 slot 级待打分扫描

全部为新增旁路链路：不修改 settlement/store/use_ledger 主链路，不 import 其私有函数。
"""

from llm_loop.knowledge_score.card_writeback import write_sidecard
from llm_loop.knowledge_score.client import (
    LEVELS,
    ScorerError,
    ScoreResult,
    ScorerResponseError,
    ScorerTransportError,
    build_request_body,
    parse_response,
    score_state,
)
from llm_loop.knowledge_score.ledger import (
    SCHEMA_KNOWLEDGE_SCORE,
    KnowledgeScoreLedger,
)
from llm_loop.knowledge_score.state_builder import (
    CardInfo,
    CardParseError,
    build_state,
    find_card,
)

__all__ = [
    "CardInfo",
    "CardParseError",
    "LEVELS",
    "SCHEMA_KNOWLEDGE_SCORE",
    "KnowledgeScoreLedger",
    "ScoreResult",
    "ScorerError",
    "ScorerResponseError",
    "ScorerTransportError",
    "build_request_body",
    "build_state",
    "find_card",
    "parse_response",
    "score_state",
    "write_sidecard",
]
