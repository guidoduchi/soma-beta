from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4

from soma.communications.contracts.common import closed, integer

DECISIONS = frozenset({"KEEP_SEPARATE", "ATTACH_PROVIDER_IDENTITY", "CONSOLIDATE_LINKS_AND_ALIASES", "KEEP_RETAINED_CONTENT"})


@dataclass(frozen=True, slots=True)
class IdentityReviewRequest:
    source_scope_id: str
    source_scope_revision: int
    decision: str
    retained_communication_id: str
    retained_content_revision: int
    other_communication_id: str | None
    other_content_revision: int | None
    review_evidence_id: str | None

    def __post_init__(self):
        require_uuid4(self.source_scope_id)
        require_uuid4(self.retained_communication_id)
        integer(self.source_scope_revision, minimum=1)
        integer(self.retained_content_revision, minimum=1)
        if not isinstance(self.decision, str) or self.decision not in DECISIONS:
            raise ValidationError("Communication identity decision is invalid")
        if self.decision == "KEEP_RETAINED_CONTENT":
            require_uuid4(self.review_evidence_id)
            if self.other_communication_id is not None or self.other_content_revision is not None:
                raise ValidationError("Content acknowledgement has exactly one canonical candidate")
        else:
            require_uuid4(self.other_communication_id)
            integer(self.other_content_revision, minimum=1)
            if self.review_evidence_id is not None or self.other_communication_id == self.retained_communication_id:
                raise ValidationError("Pairwise identity review requires two distinct canonical candidates")

    @classmethod
    def from_value(cls, value):
        return cls(**closed(value, set(cls.__dataclass_fields__)))

    def to_value(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}
