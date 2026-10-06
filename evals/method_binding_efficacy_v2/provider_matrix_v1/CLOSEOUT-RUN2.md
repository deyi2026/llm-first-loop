# Subject-Binding Efficacy v2 — Run2 Closeout

**Confirmatory verdict: `EFFICACY_NOT_QUALIFIED`**

Run2 completed all 84 frozen formal cells. The confirmatory efficacy gate did not pass for either model because both control and treatment were already perfect on the scored challenge sets: Strong B C0/C1 = 1.0000/1.0000, Weak B C0/C1 = 1.0000/1.0000; both models had positive_flips=0, negative_flips=0, net_flip=0. Reverse-risk C accuracy was also 1.0000 in both arms for both models, with zero new harm.

This is **no efficacy qualification**, not evidence of harm. All frozen reverse-risk, mechanical-safety, and cost guardrails passed. Strong token ratio was 1.0066; Weak token ratio was 1.0934 against the frozen <=1.10 gate. Weak treatment tool-call delta reached the allowed boundary (+2 total) but did not exceed it. The only technical retry in run2 was Weak C0 ordinal38 attempt1 after the outer command interrupted attempt0 before settlement; the attempt0 identity was preserved and never replayed.

Interpretation: this provider/task realization had no treatment opportunity because C0 already achieved 100% purpose-level applicability accuracy. Therefore subject-binding remains mechanically safe under this experiment but is not efficacy-qualified by this matrix. No Method lifecycle promotion, prompt/binding tuning, production config change, publish/restart, or push is authorized by this result.

Run1 is separately frozen as `EXECUTION_INVALID__OPERATOR_ENV_CONTAMINATION` and is not pooled with run2.
