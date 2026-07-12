"""REST routers for SPEC 9.1 (Milestones 4, 7, and 9).

Milestone 9 adds ``/api/demo/*`` and the demo beat stream (SPEC 14).
"""

from paritran.api.routers import (  # noqa: F401
    audit,
    cases,
    decisions,
    demo,
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
    demo.router,
)
