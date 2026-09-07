"""Web compatibility facade for durable attachment storage.

The storage/recovery implementation is runtime-neutral and lives in
``llm_loop.memory.attachments``.  Web routes keep importing this module so the public
internal import path remains stable without making the factory depend on ``llm_loop.web``.
"""

from llm_loop.memory.attachments import (
    ATTACHMENT_EXCERPT_CHARS,
    ATTACHMENT_SCHEME,
    AttachmentError,
    AttachmentRecord,
    AttachmentStore,
    workspace_scope,
)

__all__ = [
    "ATTACHMENT_EXCERPT_CHARS",
    "ATTACHMENT_SCHEME",
    "AttachmentError",
    "AttachmentRecord",
    "AttachmentStore",
    "workspace_scope",
]
