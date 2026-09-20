from __future__ import annotations

from soma.foundation.persistence.uow import UnitOfWork
from soma.product_line_sla.domain.policy import (
    SlaPolicyRevisionRecord,
    SlaPolicyTierRecord,
)


class SlaPolicyRepository:
    @staticmethod
    def get_revision(reader, policy_revision_id: str) -> SlaPolicyRevisionRecord | None:
        row = reader.execute(
            "SELECT policy_revision_id,contract_product_line_id,revision_ordinal,policy_name,template_source,"
            "created_at_utc,created_command_id FROM sla_policy_revisions WHERE policy_revision_id=?",
            (policy_revision_id,),
        ).fetchone()
        return None if row is None else SlaPolicyRevisionRecord(
            str(row[0]), str(row[1]), int(row[2]), str(row[3]), None if row[4] is None else str(row[4]), int(row[5]), str(row[6])
        )

    @staticmethod
    def next_ordinal(reader, contract_product_line_id: str) -> int:
        row = reader.execute(
            "SELECT COALESCE(MAX(revision_ordinal),0)+1 FROM sla_policy_revisions WHERE contract_product_line_id=?",
            (contract_product_line_id,),
        ).fetchone()
        return int(row[0])

    @staticmethod
    def insert_revision_with_tiers(
        uow: UnitOfWork,
        revision: SlaPolicyRevisionRecord,
        tiers: tuple[SlaPolicyTierRecord, ...],
    ) -> None:
        uow.connection.execute(
            "INSERT INTO sla_policy_revisions(policy_revision_id,contract_product_line_id,revision_ordinal,"
            "policy_name,template_source,created_at_utc,created_command_id) VALUES (?,?,?,?,?,?,?)",
            (
                revision.policy_revision_id,
                revision.contract_product_line_id,
                revision.revision_ordinal,
                revision.policy_name,
                revision.template_source,
                revision.created_at_utc,
                revision.created_command_id,
            ),
        )
        uow.connection.executemany(
            "INSERT INTO sla_policy_tiers(policy_tier_id,policy_revision_id,severity,tier_ordinal,"
            "required_percentage_millionths,maximum_duration_numerator_seconds,maximum_duration_denominator,"
            "derived_from_tier_id,derivation_num,derivation_den) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    tier.policy_tier_id,
                    tier.policy_revision_id,
                    tier.severity,
                    tier.tier_ordinal,
                    tier.required_percentage_millionths,
                    tier.maximum_duration_numerator_seconds,
                    tier.maximum_duration_denominator,
                    tier.derived_from_tier_id,
                    tier.derivation_num,
                    tier.derivation_den,
                )
                for tier in tiers
            ],
        )


__all__ = ["SlaPolicyRepository", "SlaPolicyRevisionRecord", "SlaPolicyTierRecord"]
