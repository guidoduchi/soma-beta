from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.persistence.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    command_id: str
    command_type: str
    request_hash: str
    target_type: str
    target_id: str | None
    committed_at_utc: int
    result_type: str | None
    result_id: str | None


@dataclass(frozen=True, slots=True)
class CommittedCommandResult:
    command_id: str
    response_schema: str
    response_version: int
    response_json: str
    response_sha256: str


class CommandReceiptStore:
    def get(self, uow: UnitOfWork, command_id: str) -> CommandReceipt | None:
        row = uow.connection.execute(
            "SELECT command_id, command_type, request_hash, target_type, target_id, "
            "committed_at_utc, result_type, result_id "
            "FROM command_receipts WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        if row is None:
            return None
        return CommandReceipt(
            command_id=str(row[0]),
            command_type=str(row[1]),
            request_hash=str(row[2]),
            target_type=str(row[3]),
            target_id=None if row[4] is None else str(row[4]),
            committed_at_utc=int(row[5]),
            result_type=None if row[6] is None else str(row[6]),
            result_id=None if row[7] is None else str(row[7]),
        )

    def get_exact_result(
        self,
        uow: UnitOfWork,
        command_id: str,
    ) -> CommittedCommandResult | None:
        row = uow.connection.execute(
            "SELECT command_id, response_schema, response_version, response_json, response_sha256 "
            "FROM command_receipt_results WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        if row is None:
            return None
        return CommittedCommandResult(
            command_id=str(row[0]),
            response_schema=str(row[1]),
            response_version=int(row[2]),
            response_json=str(row[3]),
            response_sha256=str(row[4]),
        )

    def insert(self, uow: UnitOfWork, receipt: CommandReceipt) -> None:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id, command_type, request_hash, target_type, target_id, "
            "committed_at_utc, result_type, result_id"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                receipt.command_id,
                receipt.command_type,
                receipt.request_hash,
                receipt.target_type,
                receipt.target_id,
                receipt.committed_at_utc,
                receipt.result_type,
                receipt.result_id,
            ),
        )

    def insert_exact_result(
        self,
        uow: UnitOfWork,
        result: CommittedCommandResult,
    ) -> None:
        uow.connection.execute(
            "INSERT INTO command_receipt_results("
            "command_id, response_schema, response_version, response_json, response_sha256"
            ") VALUES (?, ?, ?, ?, ?)",
            (
                result.command_id,
                result.response_schema,
                result.response_version,
                result.response_json,
                result.response_sha256,
            ),
        )
