"""Communications reads its own evidence through LLD-03's published capture view."""
from __future__ import annotations

from soma.tickets.queries.communication_cascade import RFC_TERMINAL_CASCADE_RFC_MEMBERS_V1 as MEMBERS


def members(reader, proposal):
    return reader.connection.execute(
        f"SELECT rfc_id,captured_rfc_revision,captured_role FROM {MEMBERS} "
        "WHERE proposal_id=? AND proposal_revision=? ORDER BY rfc_id",
        (proposal.proposal_id, proposal.proposal_revision),
    )


def scoped_links(reader, proposal, *, after="", limit=None, state="ACTIVE", command_id=None):
    condition = "l.target_type='RFC' AND l.state=? AND l.communication_link_id>?"
    parameters = [proposal.proposal_id, proposal.proposal_revision, state, after]
    if command_id is not None:
        condition += " AND EXISTS(SELECT 1 FROM communication_link_events e WHERE e.communication_link_id=l.communication_link_id AND e.command_id=? AND e.event_kind='CLOSED' AND e.new_revision=l.revision)"
        parameters.append(command_id)
    sql = f"SELECT l.* FROM {MEMBERS} m JOIN communication_links l ON l.target_id=m.rfc_id "
    sql += "WHERE m.proposal_id=? AND m.proposal_revision=? AND " + condition + " ORDER BY l.communication_link_id"
    if limit is not None:
        sql += " LIMIT ?"
        parameters.append(limit)
    cursor = reader.connection.execute(sql, parameters)
    names = tuple(column[0] for column in cursor.description)
    return (dict(zip(names, row)) for row in cursor)


def affected_messages(reader, proposal, *, after="", limit=None):
    """Deduplicate scope siblings in SQL; compute dependency counts for its page."""
    parameters = [proposal.proposal_id, proposal.proposal_revision, after]
    page = f"SELECT l.communication_id FROM {MEMBERS} m JOIN communication_links l ON l.target_id=m.rfc_id "
    page += "WHERE m.proposal_id=? AND m.proposal_revision=? AND l.target_type='RFC' AND l.state='ACTIVE' "
    page += "AND l.communication_id>? GROUP BY l.communication_id ORDER BY l.communication_id"
    if limit is not None:
        page += " LIMIT ?"
        parameters.append(limit)
    # Pending proposals normally have their PROPOSAL hold. Count only a missing
    # hold separately, so a damaged/incomplete fixture still fails closed rather
    # than predicting deletion of a pending proposal's source evidence.
    sql = "WITH affected AS MATERIALIZED (" + page + ") SELECT c.communication_id,c.content_revision,c.content_state,r.state,r.revision,"
    sql += "(SELECT count(*) FROM communication_links a WHERE a.communication_id=c.communication_id AND a.state='ACTIVE'),"
    sql += "(SELECT count(*) FROM communication_protection_holds h WHERE h.communication_id=c.communication_id AND h.state='ACTIVE')+"
    sql += "(SELECT count(*) FROM communication_proposals p WHERE p.communication_id=c.communication_id AND p.state IN ('PENDING','DEFERRED') "
    sql += "AND NOT EXISTS(SELECT 1 FROM communication_protection_holds h WHERE h.communication_id=p.communication_id AND h.hold_kind='PROPOSAL' AND h.owner_ref=p.communication_proposal_id AND h.state='ACTIVE')),"
    sql += f"(SELECT count(*) FROM communication_links a JOIN {MEMBERS} m ON m.rfc_id=a.target_id "
    sql += "WHERE a.communication_id=c.communication_id AND a.target_type='RFC' AND a.state='ACTIVE' AND m.proposal_id=? AND m.proposal_revision=?) "
    sql += "FROM affected x JOIN communications c USING(communication_id) LEFT JOIN communication_retention r USING(communication_id) ORDER BY c.communication_id"
    parameters.extend((proposal.proposal_id, proposal.proposal_revision))
    return reader.connection.execute(sql, parameters)
