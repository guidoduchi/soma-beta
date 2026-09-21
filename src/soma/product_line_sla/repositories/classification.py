from __future__ import annotations

from soma.foundation.persistence.uow import UnitOfWork
from soma.product_line_sla.domain.classification import (
    ClassificationMappingRecord,
    SrClassificationCurrentRecord,
)


class ClassificationMappingRepository:
    @staticmethod
    def insert(uow: UnitOfWork, record: ClassificationMappingRecord) -> None:
        uow.connection.execute(
            "INSERT INTO sla_classification_mappings(mapping_id,mapping_key_type,normalized_key,customer_org_id,"
            "contract_product_line_id,active,revision,created_at_utc,opened_command_id,closed_command_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                record.mapping_id,
                record.mapping_key_type,
                record.normalized_key,
                record.customer_org_id,
                record.contract_product_line_id,
                1 if record.active else 0,
                record.revision,
                record.created_at_utc,
                record.opened_command_id,
                record.closed_command_id,
            ),
        )

    @staticmethod
    def get(reader, mapping_id: str) -> ClassificationMappingRecord | None:
        row = reader.execute(
            "SELECT mapping_id,mapping_key_type,normalized_key,customer_org_id,contract_product_line_id,"
            "active,revision,created_at_utc,opened_command_id,closed_command_id "
            "FROM sla_classification_mappings WHERE mapping_id=?",
            (mapping_id,),
        ).fetchone()
        return None if row is None else ClassificationMappingRecord(
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            bool(int(row[5])),
            int(row[6]),
            int(row[7]),
            str(row[8]),
            None if row[9] is None else str(row[9]),
        )

    @staticmethod
    def match(reader, normalized_key: str, customer_org_id: str):
        return reader.execute(
            "SELECT mapping_id,contract_product_line_id,revision FROM sla_classification_mappings "
            "WHERE mapping_key_type='customer_account_code' AND normalized_key=? AND customer_org_id=? "
            "AND active=1 ORDER BY mapping_id",
            (normalized_key, customer_org_id),
        ).fetchall()


class SrClassificationRepository:
    @staticmethod
    def current(reader, service_request_id: str) -> SrClassificationCurrentRecord | None:
        row = reader.execute(
            "SELECT service_request_id,contract_product_line_id,classification_event_id,revision,last_command_id "
            "FROM sr_classification_current WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone()
        return None if row is None else SrClassificationCurrentRecord(
            str(row[0]), str(row[1]), str(row[2]), int(row[3]), str(row[4])
        )

    @staticmethod
    def append_event(
        uow: UnitOfWork,
        *,
        classification_event_id: str,
        service_request_id: str,
        event_kind: str,
        prior_contract_product_line_id: str | None,
        new_contract_product_line_id: str | None,
        origin: str,
        mapping_id: str | None,
        reason_code: str | None,
        recorded_at_utc: int,
        command_id: str,
    ) -> None:
        uow.connection.execute(
            "INSERT INTO sr_classification_events(classification_event_id,service_request_id,event_kind,"
            "prior_contract_product_line_id,new_contract_product_line_id,origin,mapping_id,reason_code,"
            "recorded_at_utc,command_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                classification_event_id,
                service_request_id,
                event_kind,
                prior_contract_product_line_id,
                new_contract_product_line_id,
                origin,
                mapping_id,
                reason_code,
                recorded_at_utc,
                command_id,
            ),
        )

    @staticmethod
    def set_current(
        uow: UnitOfWork,
        *,
        service_request_id: str,
        contract_product_line_id: str,
        classification_event_id: str,
        revision: int,
        command_id: str,
    ) -> None:
        uow.connection.execute(
            "INSERT INTO sr_classification_current(service_request_id,contract_product_line_id,"
            "classification_event_id,revision,last_command_id) VALUES (?,?,?,?,?) "
            "ON CONFLICT(service_request_id) DO UPDATE SET "
            "contract_product_line_id=excluded.contract_product_line_id,"
            "classification_event_id=excluded.classification_event_id,"
            "revision=excluded.revision,last_command_id=excluded.last_command_id",
            (
                service_request_id,
                contract_product_line_id,
                classification_event_id,
                revision,
                command_id,
            ),
        )

    @staticmethod
    def clear_current(uow: UnitOfWork, service_request_id: str) -> None:
        uow.connection.execute(
            "DELETE FROM sr_classification_current WHERE service_request_id=?",
            (service_request_id,),
        )


__all__ = [
    "ClassificationMappingRecord",
    "ClassificationMappingRepository",
    "SrClassificationCurrentRecord",
    "SrClassificationRepository",
]
