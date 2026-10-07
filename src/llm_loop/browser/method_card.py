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
    "receipt ok != task complete; "
    "rejection != not-ready: a FAILURE compile rejection means your own action did not dispatch — "
    "fix the ref and re-dispatch that same action, never answer a rejection with a wait tool; "
    "self-caused predicates are not waitable: if a wait returns unsatisfied on a state only your "
    "own pending action can change (e.g. url still about:blank after a rejected navigate), "
    "re-dispatch that action instead of waiting longer; "
    "gate predicates on objects, not on scope: target button enabled / status text Ready -> "
    "browser_wait_object_state / browser_wait_object_text, not scope ready/url; "
    "diff-first consumption: after an executed mutation, consume the returned diff "
    "(inline summary or hydrate of changed grounding refs) before re-snapshotting; "
    "an empty diff is evidence only for a 'nothing should change' expectation — any "
    "expected visual/interactive effect still requires re-observe (fresh snapshot or "
    "vision evidence), because attribute-level diff can miss rendered change; "
    "value_text '<redacted:sensitive>' is a policy exclusion sentinel: treat the field "
    "as redacted, never match or assert its concrete value."
)
