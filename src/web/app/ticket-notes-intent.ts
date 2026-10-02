export const noteIdentity=(value:unknown):value is string=>typeof value==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u.test(value);
export function ticketNotesQuery(path:string,route:string):{cursor:unknown|null}|null {
  const target=/^\/tickets\/(sr|rfc)\/([^/]+)$/u.exec(route);
  if(!target||!noteIdentity(target[2])||typeof path!=='string'||new TextEncoder().encode(path).length>4096||/[#\\\u0000]/u.test(path)||path.includes('//'))return null;
  try {
    const url=new URL(path,'http://127.0.0.1');
    if(!path.startsWith('/api/v1/')||url.pathname!==`/api/v1/tickets/${target[1]==='sr'?'service_request':'rfc'}/${target[2]}/notes`
      ||url.searchParams.get('limit')!=='10'||Array.from(url.searchParams.keys()).some(key=>!['limit','cursor'].includes(key))
      ||['limit','cursor'].some(key=>url.searchParams.getAll(key).length>1))return null;
    const raw=url.searchParams.get('cursor');const cursor=raw===null?null:JSON.parse(raw);
    if(cursor!==null&&(typeof cursor!=='object'||Array.isArray(cursor)||Object.keys(cursor).length!==6
      ||Object.keys(cursor).some(key=>!['version','query_id','sort_registry_id','last_key_tuple','filter_fingerprint','null_order'].includes(key))
      ||cursor.version!==1||cursor.query_id!=='ListWorkingNotes'||cursor.sort_registry_id!=='WORKING_NOTE_CREATED_ID_ASC_V1'||cursor.null_order!=='not_applicable'
      ||typeof cursor.filter_fingerprint!=='string'||!/^[0-9a-f]{64}$/u.test(cursor.filter_fingerprint)
      ||!Array.isArray(cursor.last_key_tuple)||cursor.last_key_tuple.length!==2||!Number.isSafeInteger(cursor.last_key_tuple[0])||cursor.last_key_tuple[0]<0||!noteIdentity(cursor.last_key_tuple[1])))return null;
    return {cursor};
  }catch{return null;}
}
export function nextTicketNotesQuery(path:string,route:string,cursor:unknown|null,ownerFingerprint:string):string {
  if(cursor!==null&&(!cursor||typeof cursor!=='object'||(cursor as {filter_fingerprint?:unknown}).filter_fingerprint!==ownerFingerprint))throw new Error('Foreign Working Note continuation');
  const url=new URL(path,'http://127.0.0.1');if(cursor===null)url.searchParams.delete('cursor');else url.searchParams.set('cursor',JSON.stringify(cursor));
  const next=url.pathname+'?'+url.searchParams.toString();if(!ticketNotesQuery(next,route))throw new Error('Invalid Working Note continuation');return next;
}
