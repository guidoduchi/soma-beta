from __future__ import annotations

OBJECTIVE_REVIEW_REASONS = frozenset(
    {"due_unreviewed", "lost_last_executable", "mixed_outcomes", "corrected_after_review"}
)
SOURCE_TERMINAL_REVIEW_STATES = frozenset(
    {"pending", "retain_local_work", "terminate_local_work", "superseded"}
)

__all__ = ["OBJECTIVE_REVIEW_REASONS", "SOURCE_TERMINAL_REVIEW_STATES"]
