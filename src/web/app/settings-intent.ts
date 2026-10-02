export const settingsSlots=['customers','contacts','dispatch','channels','accountHistory','products','contracts','cpls','mappings','sources','jobs','housekeeping'] as const;
export type SettingsSlot=typeof settingsSlots[number];
export type SettingsOpened=Readonly<{customers:string|null;contacts:string|null;dispatch:string|null;source:string|null}>;
export type SettingsIntent=Readonly<{queries:Partial<Record<SettingsSlot,string>>;opened:SettingsOpened;accountHistory:boolean}>;
export const settingsIdentity=(value:unknown):value is string=>typeof value==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u.test(value);
const uuid=settingsIdentity;
const integer=(value:unknown)=>Number.isSafeInteger(value)&&Number(value)>=0;
type Definition=Readonly<{path:string;limit:number;query:string;sort:string;nullOrder:string;keys:readonly ('text'|'uuid'|'integer'|'nullableInteger')[]}>;
const definitions:Partial<Record<SettingsSlot,Definition>>={
  customers:{path:'/api/v1/reference/customer-organizations',limit:200,query:'ListActiveReferences',sort:'CUSTOMER_REFERENCE_NAME_ID_ASC_V1',nullOrder:'not_applicable',keys:['text','uuid']},
  contacts:{path:'/api/v1/reference/contacts',limit:200,query:'ListActiveReferences',sort:'CONTACT_REFERENCE_NAME_ID_ASC_V1',nullOrder:'not_applicable',keys:['text','uuid']},
  dispatch:{path:'/api/v1/reference/dispatch-locations',limit:200,query:'ListActiveReferences',sort:'DISPATCH_REFERENCE_NAME_ID_ASC_V1',nullOrder:'not_applicable',keys:['text','uuid']},
  products:{path:'/api/v1/product-lines',limit:200,query:'ListProductLines',sort:'PRODUCT_LINE_PRESENTATION_ASC_V1',nullOrder:'none',keys:['text','uuid']},
  contracts:{path:'/api/v1/contracts',limit:200,query:'ListContracts',sort:'CONTRACT_CANONICAL_ASC_V1',nullOrder:'none',keys:['uuid','text','uuid']},
  cpls:{path:'/api/v1/contract-product-lines',limit:200,query:'ListContractProductLines',sort:'CPL_CANONICAL_ASC_V1',nullOrder:'none',keys:['uuid','uuid','uuid']},
  mappings:{path:'/api/v1/sla/classification-mappings',limit:200,query:'ListClassificationMappings',sort:'SLA_CLASSIFICATION_MAPPING_ASC_V1',nullOrder:'none',keys:['uuid','text','text','uuid']},
  sources:{path:'/api/v1/communications/source-scopes',limit:8,query:'ListCommunicationSourceScopes',sort:'ListCommunicationSourceScopes_ORDER_V1',nullOrder:'none',keys:['text','uuid']},
  jobs:{path:'/api/v1/communications/jobs',limit:100,query:'ListCommunicationJobs',sort:'ListCommunicationJobs_ORDER_V1',nullOrder:'none',keys:['integer','uuid']},
  housekeeping:{path:'/api/v1/communications/housekeeping',limit:100,query:'ListCommunicationHousekeeping',sort:'ListCommunicationHousekeeping_ORDER_V1',nullOrder:'due null last',keys:['integer','nullableInteger','uuid']},
};
/** Closed, bounded owner query intent; it contains no projection or edit payload. */
export function settingsQuery(path:string,slot:SettingsSlot,opened?:SettingsOpened):{cursor:unknown|null}|null {
  if(typeof path!=='string'||new TextEncoder().encode(path).length>4096||!path.startsWith('/api/v1/')||/[#\\\u0000]/u.test(path)||path.includes('//'))return null;
  let def=definitions[slot];
  if(slot==='channels') {
    const id=opened?.contacts??/^\/api\/v1\/reference\/contacts\/([^/]+)\/channels\?/u.exec(path)?.[1];if(!uuid(id))return null;
    def={path:`/api/v1/reference/contacts/${id}/channels`,limit:200,query:'GetContactChannels',sort:'CONTACT_CHANNEL_KIND_CREATED_ID_ASC_V1',nullOrder:'not_applicable',keys:['text','integer','uuid']};
  }else if(slot==='accountHistory') {
    const id=opened?.customers??/^\/api\/v1\/reference\/customer-organizations\/([^/]+)\/customer-account-code\/history\?/u.exec(path)?.[1];if(!uuid(id))return null;
    def={path:`/api/v1/reference/customer-organizations/${id}/customer-account-code/history`,limit:200,query:'GetCustomerAccountCodeHistory',sort:'ACCOUNT_CODE_HISTORY_CREATED_ID_ASC_V1',nullOrder:'not_applicable',keys:['integer','uuid']};
  }
  if(!def)return null;
  try {
    const url=new URL(path,'http://127.0.0.1');const allowed=slot==='channels'?['limit','cursor','include_archived']:['limit','cursor'];
    if(url.pathname!==def.path||url.searchParams.get('limit')!==String(def.limit)
      ||Array.from(url.searchParams.keys()).some(key=>!allowed.includes(key))||allowed.some(key=>url.searchParams.getAll(key).length>1)
      ||(slot==='channels'&&!['true','false'].includes(url.searchParams.get('include_archived')??'')))return null;
    const raw=url.searchParams.get('cursor');const cursor=raw===null?null:JSON.parse(raw);
    if(cursor!==null) {
      if(typeof cursor!=='object'||Array.isArray(cursor)||Object.keys(cursor).length!==6
        ||Object.keys(cursor).some(key=>!['version','query_id','sort_registry_id','last_key_tuple','filter_fingerprint','null_order'].includes(key))
        ||cursor.version!==1||cursor.query_id!==def.query||cursor.sort_registry_id!==def.sort||cursor.null_order!==def.nullOrder
        ||typeof cursor.filter_fingerprint!=='string'||!/^[0-9a-f]{64}$/u.test(cursor.filter_fingerprint)
        ||!Array.isArray(cursor.last_key_tuple)||cursor.last_key_tuple.length!==def.keys.length)return null;
      if(def.keys.some((type,index)=>{const value=cursor.last_key_tuple[index];return type==='uuid'?!uuid(value):type==='integer'?!integer(value):
        type==='nullableInteger'?(value!==null&&!integer(value)):typeof value!=='string'||value.length>2048||value.includes('\u0000');}))return null;
      if(slot==='housekeeping'&&cursor.last_key_tuple[0]>1)return null;
    }
    return {cursor};
  }catch{return null;}
}
export function settingsIntent(value:SettingsIntent|undefined,route:string):SettingsIntent|null {
  if(!value||Object.keys(value).length!==3||!value.queries||typeof value.queries!=='object'||Array.isArray(value.queries)
    ||!value.opened||Object.keys(value.opened).length!==4||Object.keys(value.opened).some(key=>!['customers','contacts','dispatch','source'].includes(key))
    ||Object.values(value.opened).some(id=>id!==null&&!uuid(id))||typeof value.accountHistory!=='boolean')return null;
  const slots:readonly SettingsSlot[]=route==='/settings'?settingsSlots.slice(0,9):route==='/settings/communications'?settingsSlots.slice(9):[];
  if(!['/settings','/settings/communications','/settings/appearance'].includes(route)
    ||Object.keys(value.queries).some(key=>!slots.includes(key as SettingsSlot)||!settingsQuery(value.queries[key as SettingsSlot]!,key as SettingsSlot,value.opened)))return null;
  if(route!=='/settings'&&(value.opened.customers!==null||value.opened.contacts!==null||value.opened.dispatch!==null||value.accountHistory))return null;
  if(route!=='/settings/communications'&&value.opened.source!==null)return null;
  if(value.accountHistory&&value.opened.customers===null)return null;
  if(value.queries.channels!==undefined&&value.opened.contacts===null)return null;
  if(value.queries.accountHistory!==undefined&&value.opened.customers===null)return null;
  return value;
}
export function nextSettingsQuery(path:string,slot:SettingsSlot,cursor:unknown|null):string {
  const url=new URL(path,'http://127.0.0.1');if(cursor===null)url.searchParams.delete('cursor');else url.searchParams.set('cursor',JSON.stringify(cursor));
  const next=url.pathname+'?'+url.searchParams.toString();if(!settingsQuery(next,slot))throw new Error('Invalid owner Settings continuation');return next;
}
