# R9 static diagnostics ratchet — approved governance migration (2026-10-08)

## Scope and basis

R9's prior `scripts/ci_gate.sh` gates Ruff by the historical diff
`LFL_R9_BASE=eac9b2a..HEAD`, classifying every previously modified file as
R9-owned. By gen201, that set covers all existing 67 Ruff errors in 33 files.
The unconditional whole-source Pyright also reports 45 pre-existing errors
in 18 files, blocking the full suite before it can start. The prior gate
correctly fails closed; this change is an explicitly approved **policy
revision**, not a declaration that those errors have been fixed.

The immutable comparison authority is production release
`500ee8f3eff02b12eacf77dede706e5d57a8d9c5` (gen201). The source
snapshot was captured with the same local development interpreter,
Ruff 0.16.5 and Pyright 1.1.411. The frozen debt ledger is
`tests/guards/static_diagnostic_debt.json`, separately pinned by its
SHA256 in `scripts/check_static_diagnostics.py`. It records each original
diagnostic as `path + exact rule + exact message + SHA256(stripped source
line) + occurrence count`. No raw private paths or provider records are
included.

## Enforced contract

1. Ruff always scans `src tests scripts`; Pyright always scans the full
   configured project. Tool crashes, invalid output, changed versions,
   path escapes, missing files, and malformed/altered ledger all **fail closed**.
2. A diagnostic is historical only if its exact frozen fingerprint and
   occurrence count remain covered. **Any new diagnostic** (including a
   second instance of a pre-existing error in the same file) fails.
   Reductions are reported as resolved and never promoted into new debt.
3. Every Python file touched by the exact candidate commit (parent→HEAD),
   staged/unstaged edits, or an untracked `.py` file must have **zero**
   Ruff and Pyright errors, including frozen pre-existing errors. This
   prevents a touched file from indefinitely carrying old lint debt.
4. The ledger introduction must descend directly from the frozen origin.
   All later candidate commits must preserve ledger bytes and the pinned SHA;
   rebaselining needs an independently reviewed policy migration.
5. `scripts/ci_gate.sh` still executes env-pin verification, tier0, the
   unchanged xdist full pytest gate with serial red-case confirmation,
   and architecture guard. No test-skipping policy is introduced.
   Isolated Git checkouts also need two deterministic test prerequisites:
   private checkout-local `data/.ci-test-home` (the MCP sandbox HOME is
   under system-protected `/var`), and WebUI dist built from the exact
   candidate source with preinstalled local dependencies. Git intentionally
   excludes dist and node_modules; neither test fixture weakens safety
   or cookie checks, and neither touches production.
6. The two existing MethodStore `SIM102` Ruff findings are separately
   cleared in the MethodStore candidate rather than declared acceptable
   changed-file debt; its own changed Python paths have 0 Ruff/Pyright.

## Negative and positive evidence

The `tests/unit/test_static_diagnostic_gate.py` adversarial contract
checks duplicate same-rule new errors, changed-file historical errors,
source-line signature changes, path escapes, malformed/rewritten baseline,
new Python file discovery, Pyright warning exclusion, and preserved
resolved-debt reporting. The baseline and candidate full-tree JSON
fingerprint comparison showed Ruff 67→67 (new 0), Pyright 45→43
(new 0, resolved 2) before MethodStore cleaned its two pre-existing
Ruff findings. The full R9 wrapper remains the only qualification route;
an isolated governance candidate must pass that wrapper before integration.
The first R9 full run reached step [5/5] but failed 8 cases: on the
unchanged gen201 release the three safety cases reproduced with the sandbox
HOME; the five Web cases passed when built dist existed. A private HOME and
local source build made all eight pass together on the policy candidate.
The second full R9 run reached [5/5] and failed with no FAILED/ERROR
nodes, a CI infrastructure failure. The macOS host exposes 18 CPUs and
another independent pytest -n8 run was active: `-n auto` could
oversubscribe the same worker resources. CI now gives `-n auto` a
conservative default budget of four workers via xdist's supported
`PYTEST_XDIST_AUTO_NUM_WORKERS`; this **does not change test selection**.
Unknown failure shapes must still block the R9 wrapper.
The original error log was initially hidden because `set -euo pipefail`
aborted on a zero-hit `grep '^FAILED'`; CI now collects both FAILED
assertions and ERROR setup nodes before running the existing serial
reproduction. Retained full-suite output was 7720 passed / 116 skipped /
5 ERROR: all five were missing Playwright Chromium after private HOME
isolation. CI now points Playwright at the preinstalled OS-account browser
binary cache while keeping profiles and HOME isolated. The five targeted
cases then returned 5 skipped (no CDP endpoint in this sandbox), not
missing-binary errors; **this is not claimed as browser behavior PASS**.

## Boundaries

This governance change is independently committed, without MethodStore,
ArchiveStore, production publish/restart, or remote push. It does not
automatically promote the MethodStore candidate, claim production gen202,
or recategorize any runtime fact. The ledger is a *transparent historical
debt floor*, not an exemption for future lint/type failures. Prefer
shrinking it as underlying source issues are genuinely eliminated.
