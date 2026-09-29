---
method_id: stop-after-minimal-authoritative-claim-check-4d2607e920a6
name: stop-after-minimal-authoritative-claim-check
description: When a fetched article contains mutable external claims, first decide whether current-state verification is in scope. If yes, extract only the named object and claim, query the smallest authoritative view that directly answers it, compare, and stop. Do not expand to full history, adjacent metadata, or local environment unless the user explicitly asks. This prevents article-summary tasks from turning into broad package/registry audits.
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:b4651548-9342-4b65-bd99-85aba9b1f7a9:1:681112b673cb3041111b
evidence_refs: learning:learn:a5edd0ee1319
created_at: 2026-09-24T16:08:28.163640+00:00
updated_at: 2026-09-24T16:08:28.163640+00:00
---
## Trigger
User provides an article/content URL (or asks to read it), and the fetched content contains time-sensitive external claims whose current truth could be checked.

## Discriminator
The article names the exact external object and claim (e.g., package + channel/version), and a single authoritative view can answer it; the user did not ask for history, local state, or an upgrade decision.

## Short path
- Fetch/extract the article and classify the user goal as content-only vs current-state/action.
- If verification is in scope, list only the mutable claims that affect the requested answer.
- Query the smallest authoritative source/view that directly answers each claim (e.g., current channel tags, not full release history).
- Compare article-time claims with authoritative current values and label any drift.
- Stop after those claims are answered; offer deeper history/local checks only on request.

## Stop conditions
- Each in-scope mutable claim has a direct authoritative answer.
- The requested deliverable (summary/analysis) is complete.
- No explicit request exists for release history, local installed state, or upgrade execution.

## Verification
- Every current-state assertion is backed by the minimal authoritative query that produced it.
- The answer distinguishes article-time facts from current-time facts.
- No unrequested local environment or broad metadata queries were used.

## Counterexamples
- User explicitly asks whether the article is still true, what to install, or whether to upgrade.
- User asks for release timeline, publication dates, or why a channel changed.
- User asks what version is installed locally or asks to perform an upgrade.
- The article's claims are static or no authoritative source exists, so verification is impossible or irrelevant.
