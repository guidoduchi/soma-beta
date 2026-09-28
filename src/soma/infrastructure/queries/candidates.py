from soma.foundation.errors import SomaError
from soma.infrastructure.domain.relationships import normalize_ip
from soma.infrastructure.domain.sites import match_key
from soma.infrastructure.repositories.core import count, get, rows
from .core import cursor_key, make_cursor, page

QUERY_NAMES = frozenset({"NetworkElementCandidateQuery", "IpCandidateQuery", "SiteArchiveBlockerQuery"})


def site_blockers(service, reader, p):
    get(reader, "sites", p["site_id"])
    query = "SiteArchiveBlockerQuery"
    last = cursor_key(query, p, 3)
    limit = p.get("limit", 100)
    items, total, indeterminate = [], 0, len(service.site_dependencies) != 3
    physical = ("SELECT 0 provider_order,'room' blocker_kind,room_id blocker_id,'ACTIVE_ROOM' reason_code FROM rooms WHERE site_id=? AND lifecycle_state='active' "
                "UNION ALL SELECT 0,'network_element',network_element_id,'ACTIVE_NETWORK_ELEMENT' FROM network_elements WHERE site_id=? AND lifecycle_state='active' "
                "UNION ALL SELECT 0,'cloud_deployment',cloud_deployment_id,'ACTIVE_CLOUD_DEPLOYMENT' FROM cloud_deployments WHERE site_id=? AND lifecycle_state='active' "
                "UNION ALL SELECT 0,'rack',rack_id,'ACTIVE_RACK' FROM racks r JOIN rooms m USING(room_id) WHERE m.site_id=? AND r.lifecycle_state='active'")
    total += count(reader, "SELECT count(*) FROM (" + physical + ")", (p["site_id"],) * 4)
    physical_p = {**p, "limit": limit}
    physical_rows, physical_next = page(reader, query, physical_p, physical, (p["site_id"],) * 4,
                                         ["provider_order", "blocker_kind", "blocker_id"])
    items.extend(physical_rows)
    has_more = physical_next is not None
    for order, provider in enumerate(service.site_dependencies, 1):
        try:
            total += provider.count_blockers(reader, p["site_id"])
            if last and order < last[0]:
                continue
            if has_more or len(items) > limit:
                continue
            provider_cursor = last[2] if last and order == last[0] else None
            while len(items) <= limit:
                page_result = provider.list_blockers(
                    reader, p["site_id"], provider_cursor, min(200, limit + 1 - len(items)))
                blockers = page_result["blockers"]
                for identity in blockers:
                    items.append(dict(provider_order=order,
                                      blocker_kind=("ticket", "task", "inventory")[order - 1],
                                      blocker_id=identity, reason_code="OPERATIONAL_DEPENDENCY"))
                next_provider_cursor = page_result.get("continuation")
                if next_provider_cursor is None:
                    break
                if not blockers or next_provider_cursor == provider_cursor:
                    raise ValueError("Site dependency provider did not advance its cursor")
                provider_cursor = next_provider_cursor
                if len(items) > limit:
                    break
        except Exception:
            indeterminate = True
    continuation = make_cursor(query, p, [items[limit - 1][key] for key in ("provider_order", "blocker_kind", "blocker_id")]) if len(items) > limit or has_more else None
    return dict(items=items[:limit], next_cursor=continuation, exact_count=total, indeterminate=indeterminate)


def execute(service, reader, query, p):
    if query == "SiteArchiveBlockerQuery":
        return site_blockers(service, reader, p)
    if query == "IpCandidateQuery":
        canonical = normalize_ip(p["canonical_address"]).canonical_text
        sql = ("SELECT i.network_element_ip_id,i.network_element_id,n.site_id,i.is_primary FROM network_element_ip_current i "
               "JOIN network_elements n USING(network_element_id) WHERE i.canonical_address=? AND i.active=1")
        result, continuation = page(reader, query, p, sql, [canonical], ["network_element_id", "network_element_ip_id"])
        for row in result:
            row["is_primary"] = bool(row["is_primary"])
        return dict(items=result, next_cursor=continuation, exact_count=count(reader, "SELECT count(*) FROM (" + sql + ")", (canonical,)))
    evidence, values = [], []
    if p.get("name"):
        evidence.append("SELECT network_element_id,'NAME_EXACT' code FROM network_elements WHERE name_match_key=?")
        values.append(match_key(p["name"]))
    if p.get("serial"):
        evidence.append("SELECT network_element_id,'SERIAL_EXACT' code FROM network_elements WHERE serial_match_key=?")
        values.append(match_key(p["serial"]))
    if p.get("canonical_ip"):
        evidence.append("SELECT network_element_id,'IP_EXACT' code FROM network_element_ip_current WHERE canonical_address=? AND active=1")
        values.append(normalize_ip(p["canonical_ip"]).canonical_text)
    if p.get("site_id"):
        evidence.append("SELECT network_element_id,'SITE_EXACT' code FROM network_elements WHERE site_id=?")
        values.append(p["site_id"])
    if p.get("model_id"):
        evidence.append("SELECT network_element_id,'MODEL_EXACT' code FROM network_element_model_current WHERE network_element_model_id=?")
        values.append(p["model_id"])
    if not evidence:
        cursor_key(query, p, 2)
        return dict(candidates=[], next_cursor=None, candidate_count=0)
    sql = ("SELECT n.network_element_id,count(DISTINCT e.code) evidence_rank,group_concat(DISTINCT e.code) codes,"
           "n.site_id,n.lifecycle_state lifecycle FROM (" + " UNION ALL ".join(evidence) +
           ") e JOIN network_elements n USING(network_element_id) GROUP BY n.network_element_id")
    result, continuation = page(reader, query, p, sql, values, ["evidence_rank", "network_element_id"], ["DESC", "ASC"])
    for row in result:
        row["evidence_codes"] = sorted(row.pop("codes").split(","))
    return dict(candidates=result, next_cursor=continuation, candidate_count=count(reader, "SELECT count(*) FROM (" + sql + ")", values))
