---
method_id: treat-parse-errors-as-query-dialect-declaration-7d2608f1f873
name: treat-parse-errors-as-query-dialect-declaration
description: When a query/search tool fails with a parse-class error (PatternError, 'unterminated subpattern', JSONDecodeError-style), the error text itself declares which language the query parameter is compiled in and names the offending metacharacter position. Treat one such error as a dialect declaration for the whole episode: sanitize the pending query and all later queries to that tool (escape or strip metacharacters, keep distinctive literal tokens), instead of retrying tweaked variants that repeat the same parse failure.
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:a8ca7a5d-9f35-462e-b02e-e13f15ff0023:283:3da08849bc55a45b4b7a
evidence_refs: learning:learn:b0f63faa3978
created_at: 2026-09-20T12:28:40.365567+00:00
updated_at: 2026-09-20T12:28:40.365567+00:00
---
## Trigger
A tool call whose query string contains metacharacters returns a parse/compile-class error, and an earlier same-class error in the episode has already named the parse type (e.g., 'PatternError: missing ), unterminated subpattern at position N').

## Discriminator
The first error message is a compiler-style diagnostic: 'PatternError ... unterminated subpattern' is a regex-compile failure, which at that moment proves the content-search parameter is regex-parsed and that '(' in the literal query was read as a group opener — cause and fix were determined before the next call, with no further probing needed.

## Short path
- On the first parse-class error, read the error as a dialect spec: parse class + character position identifies the exact metacharacter in my query that caused it.
- Sanitize the pending query once: escape or drop metacharacters while preserving distinctive tokens ('compressed=' not '(compressed=').
- Apply the same sanitization rule to every subsequent query to that tool in the episode; never re-learn the dialect via a second identical failure.
- If a later query genuinely needs regex features, write it deliberately and validate it (balanced groups, escaped literals) before sending.

## Stop conditions
- Sanitized query returns hits / a normal result.
- One properly sanitized retry still fails with the same error class → dialect hypothesis falsified; switch cause (glob/literal/size limits) instead of more parameter mutation.

## Verification
- Zero repeated same-class parse errors for the remainder of the episode.
- Hit lists confirm the preserved tokens matched the intended symbols.
- Any intentionally-regex query is validated (balanced/escaped) before being sent.

## Counterexamples
- Transient or empty-result errors (timeout, zero hits) declare nothing about the query dialect; do not sanitize on their basis.
- Queries that genuinely need regex semantics (alternation, boundaries) must be escaped/validated, not stripped — stripping silently changes search intent.
- Tools documented as literal or glob matchers: a parse error there means something else; re-read the tool contract rather than assuming regex.
- After one correctly sanitized retry the identical error class recurs → the metacharacter hypothesis is wrong; stop applying this method.
