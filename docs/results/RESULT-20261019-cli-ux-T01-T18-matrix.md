# LFL CLI T01-T18 acceptance matrix (isolated, not released)

Date: 2026-10-19. Scope: R14-R16/R18-R19 candidate based on isolated R13
commit 729b8a441c9596799803f37ac4590d91624bb5df. This is **not** a claim
of independent review, full R9, integration or installation acceptance.

macOS local POSIX PTY, fake Provider inputs and no external model call.
From this worktree the targeted command was:

    PYTHONPATH=src ../../.venv/bin/python -m pytest
      tests/unit/test_terminal_cli.py tests/unit/test_terminal_preinput.py
      tests/unit/test_terminal_pty.py tests/unit/test_terminal_markdown_stream.py
      tests/unit/test_terminal_keymap.py tests/unit/test_terminal_palette.py
      tests/unit/test_terminal_palette_pty.py tests/unit/test_terminal_record_browser.py
      tests/unit/test_terminal_approval_interrupt.py -q

All the test paths above were supplied in one command (line wraps are for display).
Actual final result: **197 passed / 0 failed**, 10.04 s. Evidence: task-owned ignored
file data/cli-r14-r19-extended-v3.log. Modified-source Ruff: PASS. A prior
157-case run had one SIGTERM/PTY timeout; isolated baseline reproduction of
that case passed, and the final combined 197-case run passed. The earlier
timeout is retained as evidence, not erased.

| ID | Qualification | Actual evidence / remaining boundary |
| --- | --- | --- |
| T01 | AUTOMATED_PASS | Real PTY 60x12, 100x24, 140x30 and SIGWINCH 80x24 to 120x40, 120x40 to 48x12, 48x12 to 80x24; composer/restoration |
| T02 | AUTOMATED_PASS | Real PTY 100 lines of bracketed paste with CJK, combining marks and blank lines; explicit submit preserves exact text |
| T03 | PARTIAL | Explicit multi-line mode and backslash/Enter plus dumb fallback verified; modified Shift+Enter/Meta translation varies by terminal |
| T04 | MANUAL_PENDING | CJK/emoji/combining paste covered; physical IME candidate-confirm interactions still require human input |
| T05 | AUTOMATED_PASS | Real PTY Tab completes /help without premature submit; palette Esc cancels and Tab/Enter selects /help, both preserve draft and terminal modes |
| T06 | AUTOMATED_PASS | Native BackgroundRunner exact-generation Ctrl+C and next-turn draft cancellation/settlement tests |
| T07 | PARTIAL | 29-action map, reserved keys, approval default-deny/close/late-yes tested; complete PTY focus-switch matrix still pending |
| T08 | PENDING | Browser anchors/paging are present, but streaming while viewing older records and new-item count not yet integrated in inline UI |
| T09 | PARTIAL | Stored exact diff, /raw, 10k-line paging; physical clipboard and horizontal diff viewer not fully qualified |
| T10 | AUTOMATED_PASS | NO_COLOR, exact raw/JSON, multiple themes and explicit text statuses in CLI/Markdown tests |
| T11 | AUTOMATED_PASS | Real dumb PTY multiline and linear plain rendering without cursor-control dependence |
| T12 | AUTOMATED_PASS | Real PTY SIGTERM, running-draft abort, termios restoration, failed external editor preserves draft |
| T13 | MANUAL_PENDING | Apple Terminal/iTerm2/VS Code, SSH/tmux and native Linux terminal actual builds not exercised by macOS PTY |
| T14 | PARTIAL | Browser cursor per session, session/workspace identity and preinput/run separation tested; live child events during browsing not |
| T15 | AUTOMATED_PASS | JSON/JSONL exact protocol, non-TTY fallback, BrokenPipe and unknown-settlement tests |
| T16 | AUTOMATED_PASS | Binding conflict/reserved keys/disable/reset and corrupt UI config fallback; no model-policy modification |
| T17 | NOT_APPLICABLE | Optional full-screen feature F not enabled; no full-screen success claim |
| T18 | PARTIAL | Existing 10,000 fake-event protocol test proves exact sequence, bounded 8 MiB peak, p95 under 200ms; real PTY high-volume redraw/keyboard responsiveness pending |

## Addendum: T08/T17 optional viewer and real terminal follow-up (isolated)

This addendum belongs to the distinct, **not yet reviewed or released**
`feat/cli-t08-terminal-closure-20261019` candidate, based on integrated
commit 59cc3b2230a10ceb54ad62bfd2852946e7bce427. The table above is
retained as the exact record of the previously reviewed R14-R19 commit.
Never reinterpret that older acceptance as a review or R9 permit for this new patch.

| ID | New candidate evidence | Qualification / remaining blocker |
| --- | --- | --- |
| T03 | Actual macOS PTY: Alt+Enter inserts a newline in single-line mode; explicit multi-line sends only via Ctrl+X s; Unicode and combining characters round-trip | Improved automated fallback; Shift+Enter hardware translations still vary |
| T04 | Actual PTY CJK/emoji/combining marks and explicit send tests pass | Physical OS Pinyin/Japanese IME candidate selection remains MANUAL_PENDING |
| T07 | Existing 29-action keymap, new real PTY full-screen focus/close/return to cooked mode | Partial; terminal-specific focus and shortcut combinations need physical terminal run |
| T08 | Real POSIX PTY opens a read-only viewer while 10,000 simulated stream deltas occur and a newly saved message arrives; reports +1 saved separately from +10,000 streamed, retains old message cursor, exits preserving draft | Automated fake-provider/real-PTY integration PASS; no external Provider call |
| T09 | Real PTY full-screen diff viewer: keypresses l/h move horizontal column window 1→101→1; raw stored diff remains unchanged | Horizontal viewing PASS; physical system clipboard remains untested to avoid modifying user clipboard |
| T13 | Real isolated localhost OpenSSH server/SSH -tt on macOS, earlier tmux 3.7b installed-Wheel input roundtrip, **Ubuntu 26.04 LTS ARM64 guest** fresh virtualenv installation with 345/345 resource integrity and native PTY Unicode submit; macOS-to-Ubuntu authenticated SSH -tt gave real Linux /dev/pts | Native Linux+SSH verified on prior integrated 59cc3b2 Wheel; new T08/T17 Wheel must be retested; macOS GUI/IME still separate |
| T14 | Session-scoped cursor remains while fake streamed events and a new persisted assistant message appear; no model re-submission | Partial; real child Agent event stream during viewing remains unverified |
| T17 | Explicit /fullscreen or /browse full enters PromptToolkit alternate-screen viewer and exits via q/Esc; PTY tests show recovered original draft and cooked termios; plain mode remains text only | Opt-in full-screen AUTOMATED_PASS, not on by default |
| T18 | 10,000-event JSONL original benchmark retained; fake stream causes one redraw request when 10,000 updates arrive at the same monotonic tick; real PTY remains interactive while it receives the 10,000-event status | Improved macOS real-PTY endurance; real slow remote terminal latency p95 still to qualify |

Local availability: Docker CLI was present but its daemon initially unreachable
at the Unix socket. OrbStack's CLI existed inside its application bundle rather
than PATH; a real Ubuntu 26.04 LTS ARM64 instance became available. Because the
Ubuntu guest lacked ensurepip, a SHA-observed official PyPA pip.pyz bootstrap
was used exclusively inside a temporary `venv --without-pip`, without apt or
root package modifications. The prior integrated Wheel 0.6.32 installed,
`pip check` passed, `lfl --version` and `lfl check-install` passed (345 files),
and a real Linux PTY accepted/sent Unicode. A real SSH connection from macOS
via OrbStack into Ubuntu produced Linux `/dev/pts`; another isolated macOS
OpenSSH server test used ephemeral keys and loopback only. The guest test
removed temporary virtualenv and files; no model Provider was contacted.
The exact new T08/T17 Wheel still needs its own Linux retest after full R9.
Human-triggered IME acceptance requires physically selecting a suggestion in
the target terminal and verifying that neither Enter nor candidate confirmation
accidentally submits a model turn; the fallback /input multiline + Ctrl+X s
provides explicit separation when modifier-key reporting is ambiguous.

### 2026-10-19 T04 Mac Terminal incident — incomplete modifier sequence

The real user entered Chinese text 你好 using the Mac IME. The first diagnostic
timed out after 75 seconds without a send; in the second attempt the editor
showed an extra literal s before the Chinese text instead of submitting.
This proves that the multi-key send was not recognized in that interaction,
but cannot identify which layer (IME, Terminal, prompt_toolkit or prefix
interval) intercepted the leader. No model/provider call occurred.
T04 remains MANUAL_PENDING.

The separate isolated fix/cli-ime-explicit-send-20261019 candidate provides
an independent text-only way to finish multiline entry: put /send alone on
the last line and press Enter. The sentinel and its separating newline are
removed from the submitted message; Enter on other lines remains a newline.
Real PTY regression verifies this fallback and retains Ctrl+X s. It is
NOT evidence that physical macOS Chinese IME candidate selection has passed.

AUTOMATED_PASS means the stated executable assertions actually ran on this Mac.
PARTIAL means only part of the criterion is covered; MANUAL_PENDING means the
target terminal was not available; PENDING is a functional gap;
NOT_APPLICABLE means a not-yet-enabled optional feature.

Next: address reachable gaps without a new rendering framework, obtain a fresh
independent GLM-5.3 Reviewer for the exact final candidate (PASS, P0/P1=0),
then original full R9 and isolated commit. Linux/SSH/tmux/IME qualifications
require their actual target terminal. A macOS PTY is not interchangeable.
