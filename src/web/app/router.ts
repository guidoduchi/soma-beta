export type ClientRoute = Readonly<{path: string; surface: string; owner: string; recordId: string | null}>;
const routes = [
  ['/overview','overview','LLD-11'], ['/tickets','ticket_list','LLD-03/04'], ['/tickets/history','ticket_history','LLD-03/04'],
  ['/tickets/sr/{id}','sr_workbench','LLD-03'], ['/tickets/rfc/{id}','rfc_workbench','LLD-03'],
  ['/objectives','objectives','LLD-05'], ['/objectives/{id}','objective_detail','LLD-05'], ['/inventory','inventory','LLD-07'],
  ['/infrastructure','infrastructure','LLD-08'], ['/settings','settings','LLD-02/12'],
  ['/settings/communications','communication_settings','LLD-09'], ['/settings/appearance','appearance_settings','LLD-10'],
] as const;
export function resolveRoute(path: string): ClientRoute | null {
  if (path === '/') path = '/overview';
  if (path.startsWith('/api/v1') || /[?#\\\u0000]/u.test(path) || path.includes('//')) return null;
  for (const [pattern, surface, owner] of routes) {
    if (pattern === path) return {path, surface, owner, recordId: null};
    if (pattern.endsWith('/{id}') && path.startsWith(pattern.slice(0, -4))) {
      const encoded = path.slice(pattern.length - 4);
      let recordId: string;
      try { recordId = decodeURIComponent(encoded); } catch { continue; }
      if (/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u.test(recordId)) return {path, surface, owner, recordId};
    }
  }
  return null;
}
export function defaultOpen(recordType: string, id: string): ClientRoute | null {
  const base = ({SERVICE_REQUEST: '/tickets/sr/', RFC: '/tickets/rfc/', OBJECTIVE: '/objectives/'} as Record<string,string>)[recordType];
  return base ? resolveRoute(base + encodeURIComponent(id)) : null;
}
export type ReturnState = Readonly<{route: string; filterFingerprint: string; activeId: string | null; selectedId: string | null;
  memberIds: readonly string[]; scrollAnchor: string | null; focusToken: string | null; tab?: string; pane?: 'work' | 'communications';
  collectionQuery?:string;collectionOrder?:readonly string[];groupingQuery?:string|null}>;
/** Closed query intent for the implemented Objective collection, never a DTO. */
export function objectiveCollectionQuery(value:string|undefined):{asOf:number;cursor:unknown|null}|null {
  if(!value||!value.startsWith('/api/v1/objectives?')||new TextEncoder().encode(value).length>4096)return null;
  try {
    const url=new URL(value,'http://127.0.0.1');
    if(url.pathname!=='/api/v1/objectives'||url.hash||url.searchParams.get('limit')!=='200'
      ||Array.from(url.searchParams.keys()).some(key=>!['limit','as_of_utc','cursor'].includes(key))
      ||['limit','as_of_utc','cursor'].some(key=>url.searchParams.getAll(key).length>1))return null;
    const instant=url.searchParams.get('as_of_utc');
    if(!instant||!/^\d+$/u.test(instant))return null;
    const asOf=Number(instant);if(!Number.isSafeInteger(asOf)||asOf<0)return null;
    const raw=url.searchParams.get('cursor');return {asOf,cursor:raw===null?null:JSON.parse(raw)};
  }catch{return null;}
}

/** Bounded grouping query intent only; current owner facts are always fetched again. */
export function groupingCollectionQuery(value:string|undefined|null):{filters:{state:string;risk:string;origin:string};cursor:unknown|null}|null {
  if(!value||!value.startsWith('/api/v1/grouping/proposals?')||new TextEncoder().encode(value).length>4096)return null;
  try {
    const url=new URL(value,'http://127.0.0.1');
    const choices={state:['pending','accepted','rejected','superseded'],risk:['normal','high'],
      origin:['task_created','task_plan_changed','source_plan_adopted','manual_request','retry_created','objective_edit']};
    if(url.pathname!=='/api/v1/grouping/proposals'||url.hash||url.searchParams.get('limit')!=='200'
      ||Array.from(url.searchParams.keys()).some(key=>!['limit','state','risk','origin','cursor'].includes(key))
      ||['limit','state','risk','origin','cursor'].some(key=>url.searchParams.getAll(key).length>1))return null;
    const filters={state:'',risk:'',origin:''};
    for(const key of ['state','risk','origin'] as const) {
      const item=url.searchParams.get(key);
      if(item!==null&&!choices[key].includes(item))return null;
      filters[key]=item??'';
    }
    const raw=url.searchParams.get('cursor');const cursor=raw===null?null:JSON.parse(raw);
    if(cursor!==null) {
      if(typeof cursor!=='object'||Array.isArray(cursor)
        ||Object.keys(cursor).length!==6
        ||Object.keys(cursor).some(key=>!['version','query_id','sort_registry_id','last_key_tuple','filter_fingerprint','null_order'].includes(key))
        ||cursor.version!==1||cursor.query_id!=='GroupingProposalList'||cursor.sort_registry_id!=='GROUPING_PROPOSAL_CREATED_ID_ASC_V1'
        ||cursor.null_order!=='not_applicable'||typeof cursor.filter_fingerprint!=='string'||!/^[0-9a-f]{64}$/u.test(cursor.filter_fingerprint)
        ||!Array.isArray(cursor.last_key_tuple)||cursor.last_key_tuple.length!==2
        ||!Number.isSafeInteger(cursor.last_key_tuple[0])||cursor.last_key_tuple[0]<0
        ||typeof cursor.last_key_tuple[1]!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u.test(cursor.last_key_tuple[1]))return null;
    }
    return {filters,cursor};
  }catch{return null;}
}
export class NavigationHistory {
  private readonly entries = new Map<string, ReturnState>();
  remember(state: ReturnState): string {
    if (!resolveRoute(state.route) || state.memberIds.length > 200
      ||(state.groupingQuery!==undefined&&(state.route!=='/objectives'
        ||(state.groupingQuery!==null&&groupingCollectionQuery(state.groupingQuery)===null)))
      ||(state.collectionQuery!==undefined&&(state.route!=='/objectives'||objectiveCollectionQuery(state.collectionQuery)===null))
      ||(state.collectionOrder!==undefined&&(state.collectionOrder.length>200||new Set(state.collectionOrder).size!==state.collectionOrder.length
        ||state.collectionOrder.some(id=>typeof id!=='string'||id.length===0))))throw new Error('Invalid bounded return context');
    const token = crypto.randomUUID(); this.entries.set(token, Object.freeze({...state, memberIds: Object.freeze([...state.memberIds]),
      ...(state.collectionOrder===undefined?{}:{collectionOrder:Object.freeze([...state.collectionOrder])})}));
    while (this.entries.size > 50) { const oldest = this.entries.keys().next().value; if (oldest) this.entries.delete(oldest); }
    return token;
  }
  restore(token: string): ReturnState | null { return this.entries.get(token) ?? null; }
}

export type HistoryPort = Readonly<{replace: (state: unknown, path: string) => void; push: (state: unknown, path: string) => void; go: (delta: number) => void}>;
type Destination = Readonly<{path: string; index: number | null}>;
/** Session-only context; history entries contain no drafts, DTOs or credentials. */
export class RouteNavigation {
  private readonly session = crypto.randomUUID(); private index = 0; private path: string;
  private readonly contexts = new NavigationHistory(); private readonly tokens = new Map<number, string>();
  private pending: Destination | null = null; private restoring = false; private approved: Destination | null = null;
  constructor(start: string, private readonly port: HistoryPort, private readonly dirty: () => boolean,
    private readonly capture: () => ReturnState | null,
    private readonly changed: (path: string, restored: ReturnState | null) => void,
    private readonly ask: (path: string | null) => void) {
    this.path = start === '/' ? '/overview' : start; this.port.replace(this.state(), this.path);
  }
  private state() {return {soma_ui_navigation: {session: this.session, index: this.index}};}
  private save(): void {
    const value = this.capture(); if (!value || value.route !== this.path) return;
    this.tokens.set(this.index, this.contexts.remember(value));
    while (this.tokens.size > 50) {const oldest = this.tokens.keys().next().value; if (oldest !== undefined) this.tokens.delete(oldest);}
  }
  navigate(path: string): void {
    if (!resolveRoute(path) || path === this.path || this.restoring || this.pending) return;
    if (this.dirty()) {this.pending = {path, index: null}; this.ask(path); return;}
    this.push(path);
  }
  private push(path: string): void {
    this.save(); for (const index of this.tokens.keys()) if (index > this.index) this.tokens.delete(index);
    this.index++; this.path = path; this.port.push(this.state(), path); this.changed(path, null);
  }
  pop(path: string, raw: unknown): void {
    const envelope = raw as {soma_ui_navigation?: {session?: unknown; index?: unknown}} | null;
    const entry = envelope?.soma_ui_navigation;
    const target = entry?.session === this.session && Number.isSafeInteger(entry.index) && (entry.index as number) >= 0 ? entry.index as number : null;
    if (this.restoring) {
      if (target === this.index) {this.restoring = false; this.ask(this.pending?.path ?? null);}
      else if (target !== null) this.port.go(this.index - target);
      return;
    }
    if (this.approved && target === this.approved.index && path === this.approved.path) {
      this.approved = null; this.arrive(path, target); return;
    }
    if (path === this.path && target === this.index) return;
    if (this.dirty()) {
      this.pending = {path, index: target};
      if (target !== null && target !== this.index) {this.restoring = true; this.port.go(this.index - target);}
      else {this.port.push(this.state(), this.path); this.ask(path);}
      return;
    }
    this.arrive(path, target);
  }
  private arrive(path: string, target: number | null): void {
    this.save(); this.index = target ?? 0; this.path = path;
    if (target === null) this.port.replace(this.state(), path);
    const token = this.tokens.get(this.index); const restored = token ? this.contexts.restore(token) : null;
    this.changed(path, restored?.route === path ? restored : null);
  }
  confirm(): void {
    if (!this.pending || this.restoring) return;
    const destination = this.pending; this.pending = null; this.ask(null);
    if (destination.index === null) this.push(destination.path);
    else {this.save(); this.approved = destination; this.port.go(destination.index - this.index);}
  }
  cancel(): void {if (!this.restoring) {this.pending = null; this.ask(null);}}
}
