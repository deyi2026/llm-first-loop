# CLI v2 execution

Goal: f3ca85bb-9b12-4c05-8bb0-9b17cdf8437c

Specification: LFL-CLI评估与需求实现计划-20261018.md, frozen design v2.
Frozen SHA256: `3bff19001452387db1d1378c1e0f36763c5cfbaad3fba0d3fca107b8bd4b4630`.
Initial base: `e3424f615b6312c2e6331faa762adeb423003bfa`.
Initial implementation branch: `feat/cli-ux-20261018`.
Current integration branch: `integrate/cli-ux-main-20261018`; starting main base: `302948e3c61499356feaa37ba173b9028f237dc2`.
While this branch remained isolated, local `main` advanced to `ab4672009ecb943086775698449ca13e2382fd46`
(`fix(review-admission): tighten manuscript gate 0.6->0.9 with bounded samples; degrade page cap to truncation`).
The current branch's merge-base with main is `59f51e3e58d802994cf07c998c6ec7c99355e3c4`, so it does not yet contain
that newer main commit; this is a separate integration step, not an implicit merge.

**Active integration candidate.** The initial CLI candidate is independently reviewed,
committed, and R9/install-validated. The current integration base commit
`9cd3674547451ecec4cabb6baf9533c124bc48e` passed its own R9 and fresh installed-wheel smoke;
the terminal compatibility follow-up was independently reviewed by GLM-5.3 (PASS, P0/P1/P2=0)
and committed as `47b757625766f88232e71ce04aaaee2b312bd0c6`, then passed original R9.
No work has merged into local main, been pushed, or been deployed. The user explicitly
authorized external GLM-5.3 review of the private candidate; that permission applies to
independent review of the current CLI candidate, not to main merge, push, or release.

## Candidate scope

The CLI is now a frontend adapter. Existing BackgroundRunner/EventBus own run lifecycle;
cancellation binds the exact session and generation. The terminal package owns text/JSON/
JSONL presentation, safe display, composer, explicit local commands and read-only queries.
No additional model policy, semantic success judge, scheduler or conversation store is added.

| Requirement | Candidate implementation / remaining acceptance |
| --- | --- |
| R01 | Authoritative incomplete/truncated/projection/cancel facts drive nonzero status; shell exit versus turn status documented |
| R02 | Effective interactive approval; non-TTY never consumes pipeline approval |
| R03 | Exact stdin/UTF-8 file, conflict checks, explicit startup model failure stops |
| R04 | Native `run_stream`/BackgroundRunner events; exact-generation cancellation; SIGINT one-shot=130 vs interactive round cancel=1 (including worker-error settlement); SIGTERM=143; startup handler is installed before worker start; real foreground `execute_command` SIGTERM and background-job BrokenPipe tests prove process/job termination and unknown-delivery messaging. Current R04 patch has 142 relevant tests passing and independent review PASS (P0/P1/P2=0); original full R9 passed on isolated commit `55f78344208d73f7ec91fdc02d33a7ee7a5044d6`. No real Provider canary was used. |
| R05 | text stdout versus stderr; one JSON object or sequenced JSONL; delivery unknown on broken pipe |
| R06 | Stateless new help/query namespaces; legacy command-specific pre-bootstrap parsing/help remains to be unified |
| R07 | Full IDs, search/show/export; native workspace mapping, owner/deletion validation, native event replay; no Engine/bootstrap |
| R08 | Safe configured-model catalog/identity; actual generation model from LoopResult; installed/source/service identity aggregation remains |
| R09 | prompt_toolkit composer, multiline, bracketed paste, in-memory per-session history/search, external editor; typing next draft during active run remains |
| R10 | Exact UTF-8 message file plus complete stored JSON/Markdown export; @ path completion does not silently read/upload |
| R11 | Usage and migration docs plus 61 existing install-workflow regressions; committed wheel/sdist and clean installed-candidate qualification passed for the pre-integration commit; requalify the integrated commit before release |
| R12 | Separate upgrade-execution G milestone; not claimed implemented by this frontend patch |
| R13 | Adaptive inline composer/status, themes, on-demand Markdown/code rendering; live Markdown block rendering remains |
| R14 | Native editing/history plus Ctrl+X application actions, contextual completion/approval, user binding validation/disable/reset; visible prefix timeout and full 29-action matrix remain |
| R15 | Slash-command and @ path completion, palette discovery, explicit selection; rich selectable palette/file ingestion remains |
| R16 | Transcript/details/stored diff/raw/render/copy/new-file export; advanced indexed navigation/horizontal diff viewer remains |
| R17 | Read-only native session/Goal/Task/child state; no implicit delegation; advanced sidebar optional F |
| R18 | Native approval callback marshalled to input owner, full safe arguments/default deny; expanded approval interruption PTY cases remain |
| R19 | Plain/dumb/non-TTY, safe control-character rendering and POSIX terminal restore; 3 real PTY layouts pass; remaining T01–T18 manual/SSH/tmux/IME/platform matrix remains |
| R20 | User-owned atomic display preferences, themes/width/keybindings separate from permissions; optional advanced status/notifications remain |

This table distinguishes working candidate code from final acceptance. It is not a claim
that all 20 requirements or phases A–E are complete.

## Evidence

- Original A contract tests on baseline: **21 failed, 2 passed**.
- Current CLI/terminal/native-runner/storage/PTY/architecture targeted suite:
  **158 passed, 3 pre-existing warnings**.
- Existing installation/doctor/upgrade-preflight/committed-distribution-builder regressions:
  **61 passed**.
- Changed Python Ruff: **PASS**. Scoped Pyright: **0 errors, 0 warnings**.
- `git diff --check`: **PASS**. `uv lock --check --offline`: command succeeded.
- PTY layouts: 60×12, 100×24, 140×30. Verified Unicode/combining emoji, exact multiline
  bracketed paste without implicit submit, explicit send, ordinary cooked input/echo
  handoff, then all original termios attributes (no masked flags). Darwin PENDIN is
  transient until the handoff read; the test exercises that read explicitly.
- The local editable installation is built from this candidate's locked dependencies;
  it is not a committed wheel/sdist or a production installation qualification.

Logs under ignored task-owned `data/cli-ux-*.log` preserve actual commands/results.
The original full R9 subsequently **ran to completion and passed** on commit
`f348dd6e18d8a28c1f8d9794f0eacac52854f348`: 9,520 passed / 142 skipped /
0 failed, with Ruff, Pyright, environment, Tier-0 and final guards green.
Log SHA256: `84782bf87a089bc460173408e1e07a906c754fb44261e8a78ca45586e66baae1`.
The frozen clean commit produced a wheel and sdist offline, and the wheel passed fresh-venv
offline installed smoke: 345 resource hashes, Web health/UI 200, correct workspace,
0 real Provider calls and no source-checkout path. The wheel was **not** signed or
published. These facts qualify the pre-integration CLI tree, not this new combined tree.

### Current R04 follow-up acceptance (isolated integration branch)

- RED confirmed the default noninteractive `run_turn()` SIGINT path returned 1 instead of
  the specified 130. The fix records SIGINT separately from SIGTERM; interactive Ctrl-C
  returns the cancelled-round status so the shell can continue, while SIGTERM returns 143
  and exits the interactive shell.
- Signal handlers now install before `BackgroundRunner.start()` so a worker cannot launch a
  real tool process before the CLI has claimed signal handling.
- Real signal matrix + interactive-shell propagation + real foreground process termination
  + real background-job BrokenPipe settlement are covered with FakeLLM and real local
  subprocesses (no external Provider requests). The full R04-related suite is
  **142 passed / 1 warning / 0 failed**; Ruff PASS; scoped Pyright 0 errors/0 warnings;
  `uv lock --check --offline` PASS.
- Modified code paths: `src/llm_loop/terminal/execution.py`,
  `src/llm_loop/terminal/shell.py`, and `tests/unit/test_terminal_cli.py`.
- The current R04 delta received a fresh, completed, isolated GLM-5.3 review:
  `subagent_cd13a2cc94f2`, result `result-d5f9af8fc0b043f3a1fef89ce8f49a32`, PASS,
  P0/P1/P2=0, reviewed patch SHA
  `fdc62f74480bbd558d31560d3f82141ffc2c54446fc2a457c4eabf9e58481765`.
- Original full R9 passed on commit `55f78344208d73f7ec91fdc02d33a7ee7a5044d6`:
  `scripts/r9_commit.sh` returned EXIT=0, the `ci_gate` full chain returned EXIT=0, the
  five-rule `r9_commit_check` passed before and after commit, the fixture manifest passed,
  and final security scans passed. The wrapper's temporary detailed pytest log was not
  retained, so no new full-suite pass/skip count is claimed here.
- The first exact incremental review returned PASS/P0=P1=P2=0 and five P3 suggestions.
  The follow-up closes the directly actionable ones: interactive Ctrl-C now has an explicit
  prompt-resumption test; SIGTERM during `runner.start()` or a worker `error` preserves
  exit 143/unknown settlement; the BrokenPipe test uses a fresh monkeypatched JobRegistry
  instance rather than leaking singleton configuration. Those changes were rerun, reviewed,
  and passed as the exact R04 delta recorded above.
- The second exact incremental review also returned PASS/P0=P1=P2=0 and recommended explicit
  POSIX skips for real process/signal tests, a deterministic startup-handler probe, and
  fixing SIGINT cancellation if the worker emits `error` rather than `done`. Those refinements
  are now included and covered by the 142-test final run.
- SIGINT intentionally waits for the core's terminal fact without a separate timeout so an
  interactive prompt cannot overlap a still-running generation; repeated Ctrl-C reports that
  settlement is still pending. SIGTERM is the bounded hard-cleanup path (five seconds), after
  which exit 143 is reported with settlement explicitly unknown.

## Independent review record

The original 27-file candidate received a genuine, completed, isolated GLM-5.3 full review:
`subagent_325b99246b98`, result `result-3991bf7cf667433291c546a97f190307`, source SHA
`c7c248bd9d63513fd6c197f05d8e723f10809d923575845642c3812003652b98`, PASS, P0/P1=0,
P2=2. It identified the installed legacy query root and failed startup model leaving a new
empty session. Both were fixed with RED→GREEN tests. The exact three-file delta received
isolated reviewer `subagent_cf1871aaf86b`, result `result-5cf82d76e0a84b65b0fcd1ee4bcc9539`,
PASS, P0/P1=0, P2=1 (only the pathological empty-string session ID boundary).

The original full R9 then exposed two additional genuine regressions: a legacy approval test
did not model TTY, and five direct process-environment reads violated the architecture
ratchet. Both were fixed without loosening the ratchet. The exact four-file delta received
isolated reviewer `subagent_d2bd11393b92`, result `result-df6f912e9989468fb56fdf12e8c01213`,
PASS, P0/P1/P2=0. The final staged/source SHA was
`a32a3adfa488d5ed3e2d21c91e4bd0cf22abbfe96e49e3f1aefb0c2264ea683e`.

That exact source tree was committed as `f348dd6e18d8a28c1f8d9794f0eacac52854f348` and
passed original R9 (9,520 passed / 142 skipped / 0 failed). A clean offline wheel build and
fresh-venv installed smoke also passed. This evidence applies to that source commit, not the
new combined tree based on `59f51e3e`; the integration delta below needs its own review and R9.

## Next work

1. Reconcile this isolated branch with latest local main `ab4672009` in a new isolated
   integration candidate. Its current base is `59f51e3e`; do not merge automatically or
   treat the R04 R9 result as validation of the newer main commit.
2. Continue mandatory gaps in R06/R08/R09/R13/R14/R16/R18/R19 and the T01-T18 terminal
   compatibility matrix, keeping each implemented/verified/pending state evidence-backed.
3. Rebuild wheel/sdist from the latest accepted integration commit and rerun fresh-venv
   installed CLI smoke; do not infer installation qualification from the older commit.
4. Coordinate the separate G upgrade-transaction milestone without duplicating the already
   completed first-use simplification; unsigned `.pkg` is not eligible for public release.
5. Obtain specific authorization before any actual local `main` merge; no push/deploy/restart
   is authorized. Mark Goal complete only after mandatory scope and integration are truly met;
   optional F/G milestones and unverified platforms must not be implied complete.
