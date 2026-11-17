# Independent Host snapshot issuer — one-time macOS bootstrap

Status: **code candidate only; production Host eligibility remains HOLD until privileged installation and a real signed-run acceptance test**. This procedure is separate from GitHub PR CI and from LFL Web/model tools.

## Trust boundary

- Dedicated macOS account: `_lfl_dual_witness` (UID 462), distinct from LFL Web UID 501. The signer has **no daemon, Web endpoint, model tool or writable repository entrypoint**. Only an operator with macOS administrator privileges can invoke it under the witness account.
- Root-owned, immutable installed code: `/Library/Application Support/LFL-HostIssuer/bin/issuer.py` (0555). The installer must compare its SHA-256 to the **reviewed source on protected `main`** both before and after copying. Never execute a mutable worktree script as root.
- Witness-owned private key: `/Library/Application Support/LFL-HostIssuer/private/host-ed25519.pem` (0600), inside a witness-owned 0700 directory. The key is generated **after** privilege separation and is never placed in Git, CI, LFL Web configuration, or model-visible receipts.
- Root-owned public trust anchor: `/Library/Application Support/LFL-HostIssuer/trust/host-ed25519.pub.pem` (0644). The Host verifier receives this **public** PEM via `LFL_PREMERGE_HOST_SNAPSHOT_PUBKEY`.
- Witness-owned signed-receipt directory: `/Library/Application Support/LFL-HostIssuer/receipts` (0750, group `staff`); published envelopes are 0640. LFL can read the public signed envelope but cannot read the signing key or invoke the signer under UID 462.

## Privileged install (operator action; never run automatically by LFL)

1. Verify GitHub `main` protection: strict required checks, PR required, admin enforcement, no force push/deletion. Confirm the policy `docs/governance/required-ci-checks.json` is present on protected `main` and all five checks match the API.
2. From the reviewed **exact protected-main** SHA, calculate the SHA-256 of `scripts/premerge_host_snapshot_issuer.py`. Use a root-owned installation procedure to create the directories above, copy the source to a root-owned 0555 `issuer.py`, and verify the installed SHA-256 equals the reviewed value. Refuse any mismatch; never source or execute an unverified shell script with elevated privileges.
3. As root, create the witness-owned 0700 `private` directory and witness-owned group-`staff` 0750 `receipts` directory. As `_lfl_dual_witness`, invoke the root-owned script with `--mode keygen` using `/Library/Application Support/LFL-DualAgent/python/bin/python3.13 -I -S`. Key generation is create-only (`O_EXCL`); do not overwrite an existing key.
4. As root, copy only the generated public PEM into the root-owned trust directory; record key ID, installed code SHA, directory ownership/modes and timestamp. Verify UID 501 cannot read the private key. **Do not** put the private PEM into any LFL environment variable.
5. Run the signed-envelope synthetic compatibility test against `scripts/premerge_host.py::_verified_snapshot`, then verify the unprivileged CLI refuses `--mode keygen` and `--mode issue`. Verify missing/stale local evidence, mismatched SHA, incorrect Queue slot, red CI and tampered receipt all fail closed.

## Real issue flow (requires a fresh eligible Lane/Queue)

The operator prepares **issuer-owned 0600** JSON receipts for independent Reviewer PASS (`candidate_sha`, `reviewer_model=glm/glm-5.3-flash`, `reviewer_session_id`, `terminal`, `verdict`, `p0`, `p1`), original full R9 (`candidate_sha`, `full`, `exit_code`, `log_path`, `log_sha256`) and integration (`main_sha`, `candidate_sha`, `contracts_verified`, `merge_tree_clean`). The operator must inspect the original evidence; LFL-generated claims alone are **not** trusted receipts.

The signer independently checks live GitHub PR/main/run identity and success; the local LFL board and authoritative Lane/Queue ledgers; `lane.status=merging`, `queue.status=merging`, a single exclusive slot, exact CAS versions and last successful preflight on current main; the reviewed receipts, R9 log hash, clean integration worktree and main ancestry. It re-reads remote and local state immediately before signing, then atomically publishes an Ed25519 envelope with a fresh `checked_at`. No arbitrary payload signing is exposed.

`premerge_host.py --mode host` verifies the public signature and independently rechecks GitHub protection, protected-main policy, 12 trusted gate blobs, exact CI origins, tested PR merge identity and artifact. **This is a read-side eligibility check, not an atomic remote-main CAS or deployment authorization.** The managed merge executor must revalidate the Queue slot/version and remote main before writing.

## Queue contract dependency (separate PR #53)

Real `MergeQueueStore.run_preflight` transitions to `ready_for_confirm` **and releases the slot**. `request_merge` transitions to `merging` **and reacquires the slot**. The Host verifier must require `queue.status=merging && slot_held=true`; the previous `ready_for_confirm && slot_held=true` was an impossible state. The separate protected PR #53 owns the Queue/Host predicate correction and its tests. This issuer-only change relies on that reviewed base; it does not modify `scripts/premerge_host.py` or its tests.

## Recovery and rollback

Until installation and a real positive end-to-end Host eligibility test, keep **Host production eligibility HOLD**; GitHub branch protection and required CI checks remain active. On a signer failure, preserve audit and refuse signing; do not fall back to a same-UID private key, unsigned snapshot, or administrator bypass. Roll back code via a protected PR and stop issuing new envelopes; rotate/revoke a compromised key through a separate explicit operator procedure, never by silently deleting the old key.
