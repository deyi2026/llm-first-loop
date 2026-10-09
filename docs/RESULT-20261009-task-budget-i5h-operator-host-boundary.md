# I5-H — operator OS/ACL, exact-once receipt and human approval handoff

**Base:** I5-G `0e33414400a526b7c007c04695ce62a3ec287d69`.
**Branch:** `feat/task-budget-i5h-operator-deployment-20261009`.
**Intent:** implementation and offline qualification of strict *deployment
primitives*, **not a live production rollout** or GLM billing certification.

## Release boundary

I5-G established `tb3`, independently verified `op1` signatures, Web-side
single-physical-attempt dispatch and an operator-only Unix-socket signer.
But it did **not** prove actual separate OS users/ACLs, a reviewed human
event, crash-safe signer one-shot recovery, or proper service lifecycle.
It had only per-request T1 append audit, which could issue multiple signed
tokens for one event before the Web's durable CAS blocked a second Run.

I5-H addresses those gaps at the control plane without changing ordinary
Web behavior or enabling `tb3` in the runtime factory:

1. **One event, at most one signer-issued token.** Prior to exposing `tb3`,
   the issuer creates `issued-<SHA(session,NUL,event)>.json` using O_EXCL,
   file fsync, directory fsync, then appends and fsyncs the T1 JSONL audit.
   Duplicate event, process restart, concurrent issuer threads and partial
   or uncertain writes fail closed; a visible partial marker is **never**
   deleted/replaced/retried automatically. This is a conservative allocation:
   a crash before response can permanently deny an unused event, rather than
   accidentally authorize a second Provider request. T2+T1 registry remains
   `partial` until crash/power-loss/ACL multi-principal qualification.
2. **Actual signed event source is readonly.** Before any signer approval,
   under the issuer's *real* effective UID, the event directory and exact
   single-file session event must be owned by the configured Web UID; the
   issuer must be able to `open(O_RDONLY|O_NOFOLLOW)` but must NOT be allowed
   to write either EventStore directory or event file. Existing EventStore
   rotation into multi-segment format remains unqualified and is denied.
   The OS-level grant is a dedicated read-only ACL, **not chmod 0644**.
3. **Three OS identities** are necessary: Web, human reviewer and budget
   issuer are distinct non-root UIDs. An authenticated OS terminal reviewer
   must independently inspect the actual persisted event and type the exact
   `APPROVE <event-id> <digest-prefix>` challenge. The operator signs
   using a private Ed25519 key owned only by that review account, after
   an exact second EventStore reread. The op1 proof is **not printed**,
   pasted into chat or taken from user/model/tool metadata.
4. **Bounded protected handoff.** The independently operator-owned mailbox
   has mode `2750` (setgid, Web-group read+traverse, no group/world write).
   The reviewer creates an O_EXCL approval file, fsyncs before chmod 0640
   and fsyncs again; the Web side can only read it through its trusted
   control-plane callback. Same-event reapproval is denied even after an
   uncertain write. The callback checks signed op1 event/session/scope,
   bounded waiting (<=45s), cancellation before RPC, then sends the proof
   only to the OS-UID-authenticated local issuer. A forged, revoked, stale,
   changed or missing proof does NOT authorize a positive grant.
5. **Daemon startup preflight** now requires a Web GID and operator-owned,
   group-traversable setgid socket directory; checks actual event directory
   readonly access; rejects root or same UID, wrong group, missing key,
   weak key/trust file permissions and oversized Unix socket paths. After
   binding, verifies socket owner/GID/mode exactly `0660`. It never silently
   removes a pre-existing socket, installs launchd jobs or changes a UID,
   ACL, key or production config as a side effect.

## Deployment prerequisites (operator-run, not performed by this patch)

Record an **authoritative currentness receipt** before privileged mutation:

| Variable | Authoritative host evidence required |
| --- | --- |
| `WEB_UID` / `WEB_GID` | Effective UID/GID of the actual managed Web process, not shell login/user declaration |
| `HUMAN_UID` | Distinct non-root user with authenticated interactive terminal, operator approval private Ed25519 key owned 0600 |
| `ISSUER_UID` | Third non-root signer service account with its own distinct budget-signing Ed25519 key owned 0600 |
| `EVENT_DIR` | Web-owned EventStore dir and per-session file with issuer-only **read** ACL; issuer cannot append/mutate |
| `SOCKET_DIR` | Issuer-owned group `WEB_GID`, mode `2750`, absolute short socket path |
| `OP_MAILBOX` | Human-owned group `WEB_GID`, mode `2750`, Web can read 0640 approval files, not write |
| `ISSUER_AUDIT` | Issuer-owned locked directory 0700; once-marker and approvals.jsonl readable to independent auditor via trusted channel |
| `OPERATOR_TRUST` | Issuer-owned 0600 pinned **public** key role/revocation mapping, refreshed per approval |
| `BUDGET_KEY` | Issuer-owned 0600 **private** signing key, never mounted in Web or exposed to any model/tool |

### Actual per-role ACL acceptance — hard stop on any missing fact

The provisioning operator must run a separate, independently authenticated
command under each real UID, not monkeypatch `geteuid` or claim that the
configuration's UID strings establish isolation:

```text
web:     can read OP_MAILBOX/approved-*.json and connect to issuer.sock;
         cannot create/replace mailbox approval; cannot open human or issuer private keys;
         cannot mutate issuer audit receipts;
human:   can read EVENT_DIR exact event but cannot append or alter it;
         can create one mailbox approval under owned dir;
         cannot read issuer budget private key or rewrite audit;
issuer:  can read EVENT_DIR exact event but cannot write it;
         can read public operator trust, issuer budget private key;
         can create audit marker/append evidence;
         cannot read the human's private approval key;
all:     a wrongly owned, symlink, group-writable or mixed-identity target denies.
```

**Real deployment blocker:** previous Web EventStore strict append requires
Web ownership and a private event file. Until read-only ACLs are proven on
the actual macOS host for both the issuer and reviewer, the I5-H path
correctly refuses signing. Running all three modules under the same login
UID and monkeypatching the permission checks is strictly a unit test.

### Explicit human step (separate terminal, operator UID only)

Run `python -m llm_loop.resources.task_budget_operator_mailbox` with explicit
`--event-store`, `--workspace`, `--session`, `--event`, `--web-uid`,
`--issuer-uid`, `--web-group-gid`, `--mailbox`, `--operator-key`, `--key-id`,
`--operator-id`; never put private keys, passwords or tokens on CLI args.
The terminal prints only a bounded JSON-escaped preview, event ID/seq,
full digest and fixed one-attempt capability statement. The human must
inspect the authoritative event source and type the exact approval phrase.
No auto-yes mode, non-TTY stdin approval or fallback to Web login is allowed.
Current TTY/OS-login proof is **not MFA/hardware human presence**; stronger
identity/UX evidence is required before fully unattended rollout.

### Issuer lifecycle and safe rollback

Run `python -m llm_loop.resources.task_budget_operator_service` only under
the dedicated issuer UID with `--socket`, `--web-uid`, `--web-gid`,
`--event-store`, `--workspace`, `--budget-key`, `--budget-key-id`,
`--operator-trust`, `--audit-dir`. Never enable `launchctl submit` or
KeepAlive loops to hide startup failures: an unexpected existing socket is
a **hard stop**. A privileged operator must first prove the old process
is dead, inspect the exact inode/owner and archive its lifecycle receipt
before removing a stale socket. The daemon does not self-delete an existing
socket, and a pending audit marker is never deleted on rollback.

All runtime enablement still requires a separately reviewed trusted
`SignedWebEventPlan(allow_one_physical_attempt=True)` and cancellation-aware
mailbox bridge; **no normal Web factory, config, model, or tool auto-binds it**.
The I5-D exclusive Provider worker still needs OS hard memory/CPU/spawn
quotas, owner-kill orphan tests, actual GLM model registry/egress evidence,
provider-side usage/cost receipts and live stop/billing reconciliation before
claiming positive-cap production qualification.

## Evidence / release decision

Unit tests intentionally distinguish simulated cross-UID IPC/ACL success
from actual same-UID rejection. Relevant tests: `test_task_budget_operator_
mailbox.py`, `test_task_budget_operator_recovery.py`, prior I5-G issuer tests
and all I5-A..G adjacent suites. Official frozen SHA R9 and whole-tree
security scan govern artifact acceptance, **not** live qualification.

**Decision at I5-H code stage:** if all offline gates pass, preserve
`I5H_OFFLINE_MECHANISM_PASS`; retain `PRODUCTION_ON_HOLD` until real three-UID
ACL, authenticated human UX, supervised daemon and process-hardening tests
pass. No direct Web restart, main merge, remote push, secrets/OS-user
provisioning, provider call or normal TaskBudget ON is authorized here.
