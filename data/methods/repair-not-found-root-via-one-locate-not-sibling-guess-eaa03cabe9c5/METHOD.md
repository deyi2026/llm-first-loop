---
method_id: repair-not-found-root-via-one-locate-not-sibling-guess-eaa03cabe9c5
name: repair-not-found-root-via-one-locate-not-sibling-guess
description: Deterministic 'path not found' on a direct read is a locator fact: the path root/prefix is wrong, not the file missing. Keep guessing sibling filenames under the same root and every new path string looks 'new' to dedup while resolving the same unknown. One locate action (search/list on the distinctive basename) recovers the true prefix and usually reveals siblings in the same hits. Not repo-api-discovery (signature/callsite verification): the trigger here is the not-found receipt itself.
status: candidate
source_model: chatgpt-web/web-gpt
source_episode_refs: episode:9ceab5d6-9c2f-4cf4-a73d-9ed7ecee9969:52:4c60f8da7d3b15032d31
evidence_refs: learning:learn:aa3209778505
created_at: 2026-10-01T22:42:56.795896+08:00
updated_at: 2026-10-01T22:42:56.795896+08:00
---
## Trigger
A direct read against a guessed path returns a deterministic '路径不存在/file not found' receipt (not transient timeout/permission), and the next planned action is to try other filenames under the same root prefix.

## Discriminator
The failure class is deterministic not-found, and (after the second receipt) multiple sibling reads share the same missing root prefix — so the unresolved unknown is the root/prefix, not which leaf file. The receipts themselves already recommend search/list location. Sibling retries are string-new but semantically duplicates of the same failed unknown.

## Short path
- On the first not-found receipt, reclassify the unknown from 'file content' to 'correct path/root'; stop planning further reads under that prefix.
- Run one locate action: search_files/list keyed on the most distinctive name fragment (e.g., basename 'provider_settlement'); this resolves the true prefix.
- Read the located path verbatim; the same search hits typically expose sibling targets (e.g., provider_calls.py, factory.py) with zero extra guessing.
- Stop locating once the target content is in hand and continue the actual task.

## Stop conditions
- Located real path obtained and a read against it succeeds — discovery is over, proceed to analysis.
- Locate returns no match — treat the file as genuinely absent, report the gap or ask the user; do not resume guessed-path enumeration.

## Verification
- The subsequent read uses the search-hit path string exactly and returns success.
- No further read attempts are made under the failed root prefix after the first not-found receipt.
- Sibling file paths needed later come from locate hits, not from new guesses.

## Counterexamples
- Not-found is the expected result (verifying a file was deleted or never created): absence is the answer, do not 'repair' the path.
- Failure is transient (timeout, 5xx, lock) or permission-denied: retry/backoff or permission escalation applies, not path repair.
- Basename is too generic for search (e.g., 'models.py' in a huge repo): list a known-good parent directory or ask the user instead.
- Root was actually correct and only the leaf name was misspelled: one corrected read suffices — but only while no correct sibling under that root has also failed; once two different leaves under one root both return not-found, the root is the suspect.
