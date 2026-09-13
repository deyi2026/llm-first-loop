"""Provider-agnostic compact guidance for the Browser semantic-operation capability.

This is capability documentation, not a policy engine. The full Method remains
progressive-disclosure content in MethodStore.
"""

SEMANTIC_OPERATION_METHOD_REF = "method:method-semantic-operation"

SEMANTIC_OPERATION_METHOD_CARD = (
    "[Semantic Operation Method] "
    "Observe -> Ground -> Scope -> Act -> Receipt -> Verify; "
    f"method_ref={SEMANTIC_OPERATION_METHOD_REF}; "
    "object actions(click/fill/select/scroll)=object scope from observed SemanticObject; "
    "navigate=resource scope from observed page; receipt ok != task complete."
)
