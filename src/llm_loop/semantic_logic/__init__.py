"""Shadow-only typed semantic representation for SMC qualification.

P1-A intentionally has no production consumers.  Existing Browser/SMX/FileService
paths remain authoritative while frozen canonical outputs are projected into this IR.
"""

from llm_loop.semantic_logic.ir import (
    ContainerShape,
    FactContext,
    FactGraph,
    FactProvenance,
    SemanticFact,
    project_document,
)

__all__ = [
    "ContainerShape",
    "FactContext",
    "FactGraph",
    "FactProvenance",
    "SemanticFact",
    "project_document",
]
