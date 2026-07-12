"""REST routers for SPEC 9.1 (Milestones 4 and 7).

Deliberately absent (deferred, SPEC 18): ``/api/demo/*`` (Milestone 9).
"""

from paritran.api.routers import (  # noqa: F401
    audit,
    cases,
    decisions,
    evaluation,
    intake,
    networks,
    runs,
    security,
)

ALL_ROUTERS = (
    intake.router,
    runs.router,
    networks.router,
    cases.router,
    decisions.router,
    audit.router,
    evaluation.router,
    security.router,
)
