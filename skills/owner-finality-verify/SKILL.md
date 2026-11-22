---
name: owner-finality-verify
description: Read-only completed Goal finality and evidence integrity checklist for trusted Host.
---

# Completed Goal finality (Host-only)

This Skill is an integrity-checked knowledge source, not a permission grant.
It must not be treated as evidence of task acceptance or an instruction to
call the Provider. The Host must read its actual durable stores.

## Mandatory steps

1. Match exact Goal and Owner session.
2. Require terminal Tasks and durable EvidenceRefs.
3. Verify every EvidenceRef in current OwnerScope.
4. Rehydrate RULE-AI-01 and manifest-verified Skill.
5. Return HOLD on any gap; never issue a Host grant.

A positive read-only receipt is NO_WRITE_VERIFIED, not Goal completion,
deployment authorization, or proof that the underlying work was correct.
If the Goal is active, missing, corrupt, or the owner/evidence/knowledge
cannot be verified, return HOLD and do not skip a legitimate new task.
