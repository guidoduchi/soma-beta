from .core import page

QUERY_NAMES = frozenset({"InfrastructureExplorerQuery"})

_SQL = """
SELECT 'site' kind,s.site_id id,s.name label,NULL parent_context_id,s.lifecycle_state lifecycle,
       s.customer_org_id,s.site_id,0 kind_order FROM sites s
UNION ALL SELECT 'room',m.room_id,m.name,m.site_id,m.lifecycle_state,s.customer_org_id,s.site_id,1
       FROM rooms m JOIN sites s USING(site_id)
UNION ALL SELECT 'rack',r.rack_id,r.name,r.room_id,r.lifecycle_state,s.customer_org_id,s.site_id,2
       FROM racks r JOIN rooms m USING(room_id) JOIN sites s USING(site_id)
UNION ALL SELECT 'cloud_deployment',c.cloud_deployment_id,c.name,c.site_id,c.lifecycle_state,s.customer_org_id,s.site_id,3
       FROM cloud_deployments c JOIN sites s USING(site_id)
UNION ALL SELECT 'network_element',n.network_element_id,n.operational_name,p.rack_id,n.lifecycle_state,s.customer_org_id,s.site_id,4
       FROM network_elements n JOIN sites s USING(site_id) JOIN network_element_placement_current p USING(network_element_id)
UNION ALL SELECT 'containment',n.network_element_id,n.operational_name,c.parent_network_element_id,n.lifecycle_state,s.customer_org_id,s.site_id,5
       FROM network_element_containment_current c JOIN network_elements n ON n.network_element_id=c.child_network_element_id JOIN sites s ON s.site_id=n.site_id
"""


def execute(service, reader, query, p):
    where, values = [], []
    for key, column in (("customer_org_id", "customer_org_id"), ("site_id", "site_id"), ("node_kind", "kind"), ("lifecycle", "lifecycle")):
        if p.get(key) is not None:
            where.append(column + "=?")
            values.append(p[key])
    sql = "SELECT * FROM (" + _SQL + ")" + (" WHERE " + " AND ".join(where) if where else "")
    result, continuation = page(reader, query, p, sql, values, ["customer_org_id", "site_id", "kind_order", "id"])
    nodes = [{key: row[key] for key in ("kind", "id", "label", "parent_context_id", "lifecycle")} | {"warning_codes": []} for row in result]
    return dict(nodes=nodes, next_cursor=continuation)
