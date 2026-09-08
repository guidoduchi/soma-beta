from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.persistence.uow import UnitOfWork


_OWNER_SPECS = {
    "service_request": ("service_requests", "service_request_id", "sr_working_notes", "service_request_id"),
    "rfc": ("rfcs", "rfc_id", "rfc_working_notes", "rfc_id"),
}


@dataclass(frozen=True, slots=True)
class WorkingNoteRecord:
    working_note_id: str
    owner_type: str
    owner_id: str
    created_by_local_user_profile_id: str
    body_text: str
    revision: int
    created_at_utc: int
    updated_at_utc: int
    created_command_id: str


class WorkingNoteRepository:
    @staticmethod
    def _spec(owner_type: str) -> tuple[str, str, str, str]:
        try:
            return _OWNER_SPECS[owner_type]
        except KeyError as exc:
            raise ValidationError("owner_type must be service_request or rfc") from exc

    def require_owner(self, connection, owner_type: str, owner_id: str) -> None:
        owner_table, owner_id_column, _, _ = self._spec(owner_type)
        row = connection.execute(
            f"SELECT 1 FROM {owner_table} WHERE {owner_id_column}=?",
            (owner_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "Working Note owner ticket does not exist")

    def get(self, connection, owner_type: str, owner_id: str, working_note_id: str) -> WorkingNoteRecord | None:
        _, _, note_table, note_owner_column = self._spec(owner_type)
        row = connection.execute(
            f"SELECT working_note_id,{note_owner_column},created_by_local_user_profile_id,body_text,revision,"
            f"created_at_utc,updated_at_utc,created_command_id FROM {note_table} "
            f"WHERE working_note_id=? AND {note_owner_column}=?",
            (working_note_id, owner_id),
        ).fetchone()
        if row is None:
            return None
        return WorkingNoteRecord(
            working_note_id=str(row[0]),
            owner_type=owner_type,
            owner_id=str(row[1]),
            created_by_local_user_profile_id=str(row[2]),
            body_text=str(row[3]),
            revision=int(row[4]),
            created_at_utc=int(row[5]),
            updated_at_utc=int(row[6]),
            created_command_id=str(row[7]),
        )

    def insert(self, uow: UnitOfWork, note: WorkingNoteRecord) -> None:
        _, _, note_table, note_owner_column = self._spec(note.owner_type)
        uow.connection.execute(
            f"INSERT INTO {note_table}(working_note_id,{note_owner_column},created_by_local_user_profile_id,"
            "body_text,revision,created_at_utc,updated_at_utc,created_command_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                note.working_note_id,
                note.owner_id,
                note.created_by_local_user_profile_id,
                note.body_text,
                note.revision,
                note.created_at_utc,
                note.updated_at_utc,
                note.created_command_id,
            ),
        )

    def update(
        self,
        uow: UnitOfWork,
        *,
        owner_type: str,
        owner_id: str,
        working_note_id: str,
        base_revision: int,
        body_text: str,
        updated_at_utc: int,
    ) -> None:
        _, _, note_table, note_owner_column = self._spec(owner_type)
        cursor = uow.connection.execute(
            f"UPDATE {note_table} SET body_text=?,revision=revision+1,updated_at_utc=? "
            f"WHERE working_note_id=? AND {note_owner_column}=? AND revision=?",
            (body_text, updated_at_utc, working_note_id, owner_id, base_revision),
        )
        if cursor.rowcount != 1:
            raise SomaError("STALE_REVISION", "Working Note revision changed")

    def remove_with_prior_capture(
        self,
        uow: UnitOfWork,
        *,
        owner_type: str,
        owner_id: str,
        working_note_id: str,
        base_revision: int,
    ) -> WorkingNoteRecord:
        prior = self.get(uow.connection, owner_type, owner_id, working_note_id)
        if prior is None:
            raise SomaError("WORKING_NOTE_NOT_FOUND", "Working Note does not exist under this ticket")
        if prior.revision != base_revision:
            raise SomaError("STALE_REVISION", "Working Note revision changed")
        _, _, note_table, note_owner_column = self._spec(owner_type)
        cursor = uow.connection.execute(
            f"DELETE FROM {note_table} WHERE working_note_id=? AND {note_owner_column}=? AND revision=?",
            (working_note_id, owner_id, base_revision),
        )
        if cursor.rowcount != 1:
            raise SomaError("STALE_REVISION", "Working Note revision changed")
        return prior
