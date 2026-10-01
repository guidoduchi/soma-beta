"""LLD-03 owns the bounded join surface for immutable RFC capture membership."""

RFC_TERMINAL_CASCADE_RFC_MEMBERS_V1 = "rfc_terminal_cascade_rfc_members_v1"

RFC_TERMINAL_CASCADE_RFC_MEMBERS_V1_DDL = """
CREATE VIEW rfc_terminal_cascade_rfc_members_v1 AS
SELECT p.rfc_terminal_cascade_proposal_id AS proposal_id,p.revision AS proposal_revision,
       m.rfc_id,m.captured_rfc_revision,m.captured_role
FROM rfc_terminal_cascade_proposals p
JOIN rfc_terminal_cascade_rfc_members m
  ON m.rfc_terminal_cascade_proposal_id=p.rfc_terminal_cascade_proposal_id;
"""
