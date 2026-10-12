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
from llm_loop.semantic_logic.serialization import (
    CANONICAL_JSON_PROFILE,
    CANONICAL_N3_PROFILE,
    OPAQUE_IDENTITY_POLICY,
    canonical_json_bytes,
    canonical_n3_bytes,
    load_canonical_json,
    load_canonical_n3,
)

__all__ = [
    "ContainerShape",
    "FactContext",
    "FactGraph",
    "FactProvenance",
    "CANONICAL_JSON_PROFILE",
    "CANONICAL_N3_PROFILE",
    "OPAQUE_IDENTITY_POLICY",
    "SemanticFact",
    "canonical_json_bytes",
    "canonical_n3_bytes",
    "load_canonical_json",
    "load_canonical_n3",
    "project_document",
]
