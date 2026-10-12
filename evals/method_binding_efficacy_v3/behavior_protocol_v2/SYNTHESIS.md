# Subject-Binding v3 Natural Closeout Development Result

**Verdict: PASS**

- record_use success: 44/44 = 1.0000
- successful experience artifact: 44/44 = 1.0000
- Weak C0 negative-decision accuracy: 16/22 = 0.7273
- malformed/missing decision: 0/44 = 0.0000
- all latest mechanically healthy: True
- exactly-one save_experience tool-call rows: 29/44; duplicate-call rows: 15/44 (diagnostic; frozen gate is successful artifact write)

## Family selection
- same_evidence_different_claim: Weak negative accuracy=0.6000, viable=True
- same_infra_different_decision: Weak negative accuracy=1.0000, viable=False
- same_object_different_action: Weak negative accuracy=0.6667, viable=True
- same_workflow_different_phase: Weak negative accuracy=0.6000, viable=True

Development instances are permanently non-confirmatory. Only the viable abstract families may seed fresh holdout construction. C1 was never used on development cases.
