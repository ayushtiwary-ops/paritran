"""REST routers for SPEC 9.1 (Milestone 4).

Deliberately absent (deferred, SPEC 18): ``/api/demo/*`` (Milestone 9)
and ``/api/security/posture`` (Milestone 7).
"""

from paritran.api.routers import (  # noqa: F401
    audit,
    cases,
    decisions,
    evaluation,
    intake,
    networks,
    runs,
)

ALL_ROUTERS = (
    intake.router,
    runs.router,
    networks.router,
    cases.router,
    decisions.router,
    audit.router,
    evaluation.router,
)
