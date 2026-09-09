"""Runtime SSOT 层（RUNTIME-SOT-WIRE 专项）。

R1: identity.py — Workspace Identity Guard
R2: resolver.py — Runtime Resolver（统一配置语义）
R3: manifest.py — Runtime Manifest
"""

from .identity import IdentityReport, RuntimeIdentityError, check_identity, compute_identity

__all__ = ["IdentityReport", "RuntimeIdentityError", "check_identity", "compute_identity"]
