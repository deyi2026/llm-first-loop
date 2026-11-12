# LFL 0.6.47 deployed production and future managed release closure

Date: 2026-11-12 (Asia/Shanghai). Target: Deepin Deepin target host (redacted), managed Web / Feishu / Learning.

## Verified production state, distinct from GitHub Release

- Current deployment: 0.6.47, generation 11, wheel SHA256
  1c784b47d238d9ab1a503c65d7355cc8f3826cc919e69cfd78bd267a11a73b84.
- Controlled restart action svc-d10874f6affb421a816eb600228ffe27 completed
  succeeded/confirmed_ok. All three service desired/live/stable identities
  converge to generation 11 and wheel SHA; restart_required=false.
- The previous 0.6.46 release is retained for rollback.
- WeCom was not part of restart target all and has a separate runtime-manifest gap.
- Knowledge health remains quarantined/writes_enabled=false. Release identity PASS
  is not a claim that knowledge-writing health is restored.

The installed wheel originates from candidate source commit
d297df4153e5ba864ba8d20dbe93ea5dea2e6c13, which at the time was
two TEST-ONLY commits ahead of main 0c9281eea1d54a81e72fe3e2adf67ba0a630617e.
An independent reviewer PASS and original full R9 subprocess exit 0 were
recorded for that exact candidate. An outer R9 wrapper incorrectly wrote its
OWN receipt exit code 70 after the child ci_gate returned 0 and printed PASS;
never substitute the wrapper's bookkeeping value for the actual gate result.

GitHub tag + artifact set + release formalization is NOT equivalent to the
already completed Deepin deployment.

## Required steps for the next wheel upgrade

1. Freeze the exact candidate source and preserve independent review (P0=0,
   P1=0) plus original full R9 exit 0. Protect other contributors' dirty main.
2. For GitHub source release, a tag must point at the exact independently
   qualified commit. Draft release remains draft until required macOS signed
   assets and Linux artifacts match the manifest, then finalize via existing
   release_finalize.py gate. No retrospective rewriting of the installed wheel.
3. Before Deepin cutover freeze immutable EXPECTED version, wheel SHA, prior
   desired generation, and exact host. Independently obtain backups, data
   compatibility proof, rollback readiness and workload idle evidence.
4. Operator safely stops the three services, then stages the wheel via official
   install_linux.sh --candidate WHEEL --expected-sha256 SHA --no-start.
5. Use scripts/finish_managed_release.py. By default it reports PLAN_ONLY
   and does not publish/restart. Only after explicit --execute does it use
   existing service_control publish-wheel CAS followed by managed restart all.
   It waits for a durable succeeded/confirmed_ok action, then automatically
   calls scripts/verify_managed_release.py. It never force-stops, force-restarts,
   silently retries a publish, or attempts an automatic rollback.
6. Verification checks independently frozen target version/gen/SHA against
   fresh Web API Date, authoritative on-disk desired, installed wheel manifest,
   active pointer, Web build SHA, systemd PIDs and three durable succeeded
   receipts. Any mismatch returns nonzero and preserves a unique, create-only
   JSON receipt, not a misleading success.
7. Historical messages describing desired=0.6.37 were STALE and cannot
   serve as source truth. Re-read current live status at each run.

Example: read-only plan, with NEW release identities substituted:

    python3 scripts/finish_managed_release.py --version TARGET_VERSION \
      --sha TARGET_WHEEL_SHA --prior-generation OLD_DESIRED_GENERATION \
      --expected-host HOSTNAME --install-root "$HOME/.local/share/lfl"

After operator-controlled staging, backup and idle check, append --execute.

## Deliberate scope limitation

This is a LOCAL operator-triggered managed-release orchestration, not a GitHub
job that automatically logs into the private Deepin host. GitHub Release
packages both tools for future use; it does not remotely restart production.
The scripts are new source artifacts requiring their own review/R9/CI before
integration. Running production 0.6.47 does not require a new restart.
