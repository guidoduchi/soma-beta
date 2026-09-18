from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.persistence.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class ProductLineRecord:
    product_line_id: str
    name: str
    lifecycle_state: str
    revision: int
    created_at_utc: int
    created_command_id: str
    last_command_id: str


@dataclass(frozen=True, slots=True)
class ContractRecord:
    contract_id: str
    customer_org_id: str
    name: str
    contract_reference: str
    lifecycle_state: str
    revision: int
    created_at_utc: int
    created_command_id: str
    last_command_id: str


@dataclass(frozen=True, slots=True)
class ContractProductLineRecord:
    contract_product_line_id: str
    contract_id: str
    product_line_id: str
    lifecycle_state: str
    current_policy_revision_id: str | None
    revision: int
    created_at_utc: int
    created_command_id: str
    last_command_id: str


class ProductLineRepository:
    @staticmethod
    def get(reader, product_line_id: str) -> ProductLineRecord | None:
        row = reader.execute(
            "SELECT product_line_id,name,lifecycle_state,revision,created_at_utc,created_command_id,last_command_id "
            "FROM product_lines WHERE product_line_id=?",
            (product_line_id,),
        ).fetchone()
        return None if row is None else ProductLineRecord(
            str(row[0]), str(row[1]), str(row[2]), int(row[3]), int(row[4]), str(row[5]), str(row[6])
        )

    @staticmethod
    def insert(uow: UnitOfWork, record: ProductLineRecord) -> None:
        uow.connection.execute(
            "INSERT INTO product_lines(product_line_id,name,lifecycle_state,revision,created_at_utc,"
            "created_command_id,last_command_id) VALUES (?,?,?,?,?,?,?)",
            (
                record.product_line_id,
                record.name,
                record.lifecycle_state,
                record.revision,
                record.created_at_utc,
                record.created_command_id,
                record.last_command_id,
            ),
        )


class ContractRepository:
    @staticmethod
    def get(reader, contract_id: str) -> ContractRecord | None:
        row = reader.execute(
            "SELECT contract_id,customer_org_id,name,contract_reference,lifecycle_state,revision,created_at_utc,"
            "created_command_id,last_command_id FROM contracts WHERE contract_id=?",
            (contract_id,),
        ).fetchone()
        return None if row is None else ContractRecord(
            str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]), int(row[5]), int(row[6]), str(row[7]), str(row[8])
        )

    @staticmethod
    def insert(uow: UnitOfWork, record: ContractRecord) -> None:
        uow.connection.execute(
            "INSERT INTO contracts(contract_id,customer_org_id,name,contract_reference,lifecycle_state,revision,"
            "created_at_utc,created_command_id,last_command_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                record.contract_id,
                record.customer_org_id,
                record.name,
                record.contract_reference,
                record.lifecycle_state,
                record.revision,
                record.created_at_utc,
                record.created_command_id,
                record.last_command_id,
            ),
        )


class ContractProductLineRepository:
    @staticmethod
    def get(reader, contract_product_line_id: str) -> ContractProductLineRecord | None:
        row = reader.execute(
            "SELECT contract_product_line_id,contract_id,product_line_id,lifecycle_state,current_policy_revision_id,"
            "revision,created_at_utc,created_command_id,last_command_id FROM contract_product_lines "
            "WHERE contract_product_line_id=?",
            (contract_product_line_id,),
        ).fetchone()
        return None if row is None else ContractProductLineRecord(
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            None if row[4] is None else str(row[4]),
            int(row[5]),
            int(row[6]),
            str(row[7]),
            str(row[8]),
        )

    @staticmethod
    def insert(uow: UnitOfWork, record: ContractProductLineRecord) -> None:
        uow.connection.execute(
            "INSERT INTO contract_product_lines(contract_product_line_id,contract_id,product_line_id,lifecycle_state,"
            "current_policy_revision_id,revision,created_at_utc,created_command_id,last_command_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                record.contract_product_line_id,
                record.contract_id,
                record.product_line_id,
                record.lifecycle_state,
                record.current_policy_revision_id,
                record.revision,
                record.created_at_utc,
                record.created_command_id,
                record.last_command_id,
            ),
        )


__all__ = [
    "ContractProductLineRecord",
    "ContractProductLineRepository",
    "ContractRecord",
    "ContractRepository",
    "ProductLineRecord",
    "ProductLineRepository",
]
