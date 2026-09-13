"""Provider-agnostic compact guidance for the Browser semantic-operation capability.

This is capability documentation, not a policy engine. The full Method remains
progressive-disclosure content in MethodStore.
"""

SEMANTIC_OPERATION_METHOD_REF = "method:method-semantic-operation"

SEMANTIC_OPERATION_METHOD_CARD = (
    "[Semantic Operation Method] "
    "Observe -> Ground -> Execute -> Receipt -> Re-observe/Verify; "
    f"method_ref={SEMANTIC_OPERATION_METHOD_REF}; "
    "use browser_semantic_execute with an exact observed GroundingRef; "
    "object actions use SemanticObject.grounding_ref, navigate uses the snapshot result resource_ref; "
    "receipt ok != task complete."
)
