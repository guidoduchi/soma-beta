"""Application-only bindings to installed owner APIs; no copied owner SQL."""
from dataclasses import dataclass, asdict
import re

from soma.foundation.errors import SomaError, ValidationError
from soma.infrastructure.api.routes_infrastructure import InfrastructureRouteAdapter
from soma.infrastructure.queries.core import InfrastructureQueries
from soma.infrastructure.services.core import InfrastructureService
from soma.objectives_tasks.api.routes_objectives_tasks import ObjectiveTaskRouteAdapter, task_collection_handlers
from soma.objectives_tasks.queries.objectives import ObjectiveQueryService
from soma.objectives_tasks.queries.tasks import TaskQueryService
from soma.reference.api.routes_reference import ReferenceRouteAdapter, REFERENCE_ROUTE_SPECS
from soma.reference.queries.references import ReferenceQueries
from soma.reference.application.profile_service import LocalUserProfileService
from soma.ui.composition import build_ui_runtime


@dataclass(frozen=True)
class OwnerResponse:
    status: int
    body: object


def query_object(request):
    if len(request.url.query.encode("utf-8")) > 4096:
        raise ValidationError("query exceeds its byte bound")
    result = {}
    for key, value in request.query_params.multi_items():
        if key in result:
            raise ValidationError("query repeats a field")
        if value in {"true", "false"}:
            value = value == "true"
        elif re.fullmatch(r"-?(0|[1-9][0-9]*)", value):
            value = int(value)
        elif value.startswith(("{", "[")):
            from soma.foundation.strict_json import loads_strict_bytes
            value = loads_strict_bytes(value.encode("utf-8"), max_bytes=4096)
        result[key] = value
    return result


class UncomposedRevisionReader:
    def current_revision_token(self, *_args):
        # Current accepted UI registry has no production working-copy entries.
        # Never derive owner revision authority from private domain tables.
        raise SomaError("SECURITY_NOT_READY", "working-copy owner revision provider is not composed")


class DomainRoutes:
    def __init__(self, factory, security):
        self.factory, self.security = factory, security
        self.ui = build_ui_runtime(factory, revision_reader=UncomposedRevisionReader(), session_security=security)
        queries = InfrastructureQueries(InfrastructureService(factory))
        from soma.infrastructure.queries import candidates, details, explorer, history, workbooks
        names = set().union(*(owner.QUERY_NAMES for owner in (candidates, details, explorer, history, workbooks)))
        self.infrastructure = InfrastructureRouteAdapter({name: self._infrastructure_query(queries, name) for name in names})
        references = ReferenceQueries(factory)
        handlers = {}
        for spec in REFERENCE_ROUTE_SPECS:
            match = re.fullmatch(r"(ListActiveReferences|GetReferenceById)\(([^)]+)\)", spec.handler)
            if match:
                handlers[spec.handler] = self._reference_query(references, *match.groups())
        from soma.reference.queries.history import ReferenceHistoryQueries
        reference_history = ReferenceHistoryQueries(factory)
        handlers.update({
            "GetCustomerAccountCodeHistory": lambda route, values: asdict(reference_history.get_customer_account_code_history(customer_org_id=route.path_parameters["customer_org_id"], **values)),
            "GetContactChannels": lambda route, values: asdict(reference_history.get_contact_channels(contact_id=route.path_parameters["contact_id"], **values)),
            "GetContactAffiliationHistory": lambda route, values: asdict(reference_history.get_contact_affiliation_history(contact_id=route.path_parameters["contact_id"], **values)),
        })
        from soma.reference.domain.settings import SettingDefinitionRegistry
        from soma.reference.application.settings_service import SettingService
        from soma.objectives_tasks.settings import build_objective_timezone_setting_registry
        from soma.communications.settings import build_communications_setting_registry
        from soma.infrastructure.settings import build_import_directory_setting_registry
        from soma.ui.settings import build_ui_setting_registry
        registry = SettingDefinitionRegistry()
        for owner, definitions in (("LLD-05", build_objective_timezone_setting_registry()),
            ("LLD-08", build_import_directory_setting_registry(str(security.root / "data"))),
            ("LLD-09", build_communications_setting_registry()), ("LLD-10", build_ui_setting_registry())):
            for definition in definitions.all_for_owner(owner):
                registry.register(definition)
        settings = SettingService(factory, registry)
        def get_setting(route, values):
            if values:
                raise ValidationError("setting query has no fields")
            result = asdict(settings.get(route.path_parameters["setting_key"]))
            result.pop("replayed")
            result.pop("no_change")
            return result
        handlers["GetSetting"] = get_setting
        self.reference = ReferenceRouteAdapter(handlers)
        from soma.inventory.queries.stock_needs import InventoryNeedsQueryService
        from soma.inventory.queries.attention_history import InventoryAttentionHistoryQuery
        from soma.inventory.queries.requests_rma import InventoryRequestsRmaQueryService
        from soma.inventory.api.routes_inventory import build_route_adapter
        stock = InventoryNeedsQueryService(factory)
        attention = InventoryAttentionHistoryQuery(factory)
        requests = InventoryRequestsRmaQueryService(factory)
        self.inventory = build_route_adapter({
            "StockEligibilityQuery": lambda route, values: asdict(stock.stock_eligibility(**values)),
            "InventoryAttentionQuery": lambda route, values: attention.attention(**values),
            "SpareRequestListQuery": lambda route, values: requests.list_requests(**values),
        })
        from soma.product_line_sla.queries.catalog import ProductLineSlaCatalogQueryService
        from soma.product_line_sla.queries.classification import ProductLineSlaClassificationQueryService
        from soma.product_line_sla.api.routes_product_line_sla import ProductLineSlaRouteAdapter
        catalog = ProductLineSlaCatalogQueryService(factory)
        classification = ProductLineSlaClassificationQueryService(factory)
        self.sla = ProductLineSlaRouteAdapter({
            "ListProductLines": lambda route, values: asdict(catalog.list_product_lines(**values)),
            "ListContracts": lambda route, values: asdict(catalog.list_contracts(**values)),
            "ListContractProductLines": lambda route, values: asdict(catalog.list_contract_product_lines(**values)),
            "ListClassificationMappings": lambda route, values: asdict(classification.list_mappings(**values)),
        })
        self.profiles = LocalUserProfileService(factory)
        self.tasks, self.objectives = TaskQueryService(factory), ObjectiveQueryService(factory)
        task_handlers = dict(task_collection_handlers(self.tasks))
        task_handlers["TaskList"] = lambda route, values: self.tasks.list_tasks(**values)
        task_handlers["TaskWorkbench"] = lambda route, values: self.tasks.workbench(route.path_parameters["task_id"]) if not values else self._bad_query()
        task_handlers["ObjectiveList"] = lambda route, values: self.objectives.list_objectives(**values)
        task_handlers["ObjectiveWorkbench"] = lambda route, values: self.objectives.workbench(objective_id=route.path_parameters["objective_id"], **values)
        self.objective_routes = ObjectiveTaskRouteAdapter(task_handlers)
        from soma.communications.adapters.pff_reader import PffReaderAdapter
        from soma.communications.composition import build_communications_runtime
        self.communications = build_communications_runtime(factory, PffReaderAdapter())

    @staticmethod
    def _bad_query():
        raise ValidationError("query fields are invalid")

    @staticmethod
    def _infrastructure_query(queries, name):
        return lambda route, values: queries.execute(name, dict(values))

    @staticmethod
    def _reference_query(queries, operation, kind):
        def invoke(route, values):
            if operation == "ListActiveReferences":
                return asdict(queries.list_active_references(reference_type=kind, **values))
            identity = next(iter(route.path_parameters.values()))
            return asdict(queries.get_reference_by_id(reference_type=kind, reference_id=identity, **values))
        return invoke

    def dispatch(self, request, body):
        path, method = request.url.path, request.method
        values = query_object(request) if method == "GET" else body
        if method == "GET" and body:
            raise ValidationError("GET query must not carry a body")
        if path == "/api/v1/reference/local-user-profile" and method == "GET":
            if values:
                raise ValidationError("profile query has no fields")
            return OwnerResponse(200, self.profiles.get_singleton())
        if path.startswith("/api/v1/ui/"):
            return self.ui.routes.dispatch(method, path, request=request, decoded=values)
        context = self.security.validate_request(request, mutation=method != "GET")
        communications = self.communications.routes(actor_kind="local_user", actor_id=context.actor_id)
        for adapter in (self.infrastructure, self.reference, self.inventory, self.sla, self.objective_routes, communications):
            try:
                result = adapter.dispatch(method, path, values)
            except TypeError:
                raise ValidationError("query fields are invalid") from None
            if result is not None:
                return result
        return None
