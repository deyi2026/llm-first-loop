---
method_id: verify-active-pointer-before-deleting-old-version-0b130c190942
name: verify-active-pointer-before-deleting-old-version
description: Before deleting an old installed binary or version, first identify the active executable pointer and current version, then search relevant configs and scripts for references to the target. Delete only after confirming the target is inactive and unreferenced, record a fingerprint or size, and verify that the active command still works. Also remove temporary probe artifacts created while evaluating alternatives.
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:f7469d7b-59d1-494b-955f-c9153320141e:253:52297c17aa4d4d1cb5ee
evidence_refs: learning:learn:c06a46874c25
created_at: 2026-09-20T18:02:06.013348+00:00
updated_at: 2026-09-20T18:02:06.013348+00:00
---
## Trigger
User asks to clean up or delete an old installed version or binary, and the deletion is irreversible.

## Discriminator
The active symlink or current version and any config or script references to the target are observable before deletion.

## Short path
- List installed candidates and identify the active symlink or current version.
- Confirm the target is not the active pointer.
- Search relevant configs and scripts for references to the target.
- Record the target fingerprint or size, then delete only the target.
- Verify the active command and version still work, and clean temporary probe artifacts.

## Stop conditions
- The target is removed, the active pointer is unchanged, the active command works, and no remaining references to the target exist.

## Verification
- The active symlink or current version still points to the intended version.
- The command runs and reports the expected version.
- Disk usage decreased by approximately the target size.
- Reference search returns no external references, or only self-references inside the target binary.

## Counterexamples
- The target is the active version or is referenced by configs or scripts.
- The user explicitly authorizes deleting the active version.
- The artifact is disposable temporary data with no installed-pointer semantics.
