# Learning cloud lane — 2026-10-13

## Incident and scope

The dedicated consumer was alive (PID 81810, release 138da6fb6) but its fresh admission heartbeat reported `foreground_busy`. The journal had 62 queued jobs, later 66, no in-flight job, 1,242 saved and 255 failed. The oldest queued job had waited over eight hours. Actual Web whole-run locks were held; their files were not merely stale tombstones.

The whole-run foreground barrier applies even while a task executes tools or waits. Continuous foreground use can therefore starve a remote Learning consumer. The configured Learning endpoint was `open.bigmodel.cn`. Restarting the same code would not remove this barrier. Historical failures are separate: 232 worker exceptions, 21 reflection-call failures and two candidate-save failures; this change does not bulk-replay them.

## Explicit independent cloud lane

Defaults remain unchanged. An operator can declare one additional Learning call on an exact cloud host:

```toml
[learning]
model = "glm/glm-5.3"
independent_cloud_hosts = "open.bigmodel.cn"
```

The equivalent governed environment key is `LEARNING_INDEPENDENT_CLOUD_HOSTS`. Comma-separated exact host names are supported. This is an explicit allowance for one Learning transport alongside foreground work, not a measurement or an assertion of unlimited provider capacity. The operator must use a cloud API account that permits that extra call; ordinary provider errors retain their existing handling.

Only the dedicated Learning runtime installs this probe. Task runtimes retain their standard probe. An explicit Learning model is required because a per-job fallback target is otherwise unknown at the global admission check. Both the current Reflection client and the actual MemoryExtractor client must match declared HTTPS hosts on port 443. Local/private IPs, localhost, common private DNS suffixes, empty clients, malformed URLs, credentials in URLs, other hosts/ports and client-resolution errors retain foreground yield. Host names are an operator declaration, not a DNS-derived proof of cloud placement. Client facts are checked on every admission/preemption probe. Grant mode pins the Reflection client, model reference and resource target at Learning startup; the probe observes that same instance. A pool registry refresh cannot substitute a new cloud client for an old in-flight local client. Reload Learning to apply Reflection routing changes in this mode; mutating the pinned transport to an ungranted/local endpoint immediately restores yield. With no grant, the existing dynamic pool route is unchanged.

The single consumer lock, Learning concurrency limit of one, straggler drain, quiet period, service restart barrier, durable journal and provider settlement stay in effect. The grant changes foreground yielding only. Emptying the field and reloading the Learning component restores whole-run yield. No extra automatic admission policy, content classifier, job deletion or queue-wide retry is added.

## Qualification and rollout

Regression tests hold a real exclusive whole-run flock while a cloud Reflection finishes; they also cover foreground arriving mid-call, a local extraction transport, endpoint changes, missing/invalid grants and a service restart barrier. Runtime TOML resolution is tested through Settings.

Run the independent code review before the full canonical gate. Keep production configuration unchanged until deployment is authorized. Publish a clean, qualified candidate through the managed service-control path; reload only Learning for this fix, after its current work has naturally drained. Preserve active Web/Feishu sessions. Verify actual worker identity and at least one durable `started -> saved/none` transition while a foreground lock remains held before claiming the live backlog recovered.

The queue counters above are incident snapshots, not a promise that the queue will become empty: foreground runtimes can continue appending new jobs.

## Resumed qualification on the latest main baseline

The original candidate's canonical gate stopped at Pyright: `_run_stream_inner`
exceeded the analyzer's control-flow complexity limit. The same diagnostic was
reproduced without the Learning patch on clean baselines `9164a1473` and
`102d03311`. No analyzer limit, static-debt ledger, architecture baseline, test
selection or production setting was changed.

On `102d03311`, the existing provider stream-consumption loop and synchronous
wait loop are extracted into immediately invoked nested functions. Their
nonlocal state and default-argument bindings retain cancellation, interjection,
disconnect, partial capture and timing behavior. Expanding the two extracted
loops produces the exact original complete-module AST. Provider dispatch and
settlement remain at their existing sites. This prerequisite enables the full
type analysis rather than hiding its diagnostic.

The resumed candidate passed 165 focused and adjacent tests, including both
Phase5/Phase6 interrupt paths, provider wire integrity, cache guard, task budget,
Learning admission and architecture guards. The full-tree Pyright ratchet
reports 21 historical diagnostics, zero new diagnostics and zero diagnostics in
modified files; Ruff reports no error in the modified engine. After these
checks, the candidate was advanced to `5c7f2acb9` to preserve the independently
committed stream-peek fail-open repair and its regression tests. The two loop
extractions expand to the exact complete-module AST of that new baseline too.
The 165-test and Pyright results above describe the preceding `102d03311`
candidate; the final canonical gate must requalify the new combined tree. The final
independent code-review receipt and canonical R9 commit gate must bind the
actual candidate before it can be published.

The next production action is an explicit Learning-only rollout: set the exact
host declaration above, publish the qualified immutable candidate through
managed service control, naturally drain current Learning work and reload only
Learning. Check current active sessions and pending service actions first.
Require matching runtime identity/model/host plus a durable Learning job
transition while a real foreground lock is held. Keep the default yielding
behavior available by clearing the host declaration and reloading Learning.
This qualification record does not authorize publishing, changing production
configuration or restarting services.
