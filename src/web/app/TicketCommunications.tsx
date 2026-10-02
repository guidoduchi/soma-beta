import {useState} from 'react';
import {CommunicationPanel, type PanelQuery} from '../components/CommunicationPanel';
import {OwnerProjection} from '../components/OwnerProjection';
import {ownerQuery} from '../data/http';

/** Accepted LLD-09 panel HTTP binding; summary and message paging stay owner-atomic. */
const query:PanelQuery=(type,id,cursor,limit,signal)=>ownerQuery(
  `/api/v1/communications/entities/${encodeURIComponent(type)}/${encodeURIComponent(id)}/panel?limit=${limit}`
    +(cursor===null?'':'&cursor='+encodeURIComponent(JSON.stringify(cursor))),signal);
type Message=Readonly<{communication_id:string;subject:string|null;body:string|null;body_kind:string;content_state:'RETAINED'|'PURGED'}>;
export function TicketCommunications({targetType,targetId}:{targetType:'SERVICE_REQUEST'|'RFC';targetId:string}) {
  const [message,setMessage]=useState<string|null>(null);
  return <><CommunicationPanel targetType={targetType} targetId={targetId} query={query} openMessage={setMessage}/>
    {message&&<section aria-label="Canonical message detail"><button type="button" onClick={()=>setMessage(null)}>Close message</button>
      <OwnerProjection<Message> path={'/api/v1/communications/messages/'+encodeURIComponent(message)} render={value=>{
        if(value.communication_id!==message||!['RETAINED','PURGED'].includes(value.content_state)
          ||(value.subject!==null&&typeof value.subject!=='string')||(value.body!==null&&typeof value.body!=='string')
          ||(value.content_state==='PURGED'&&(value.body!==null||value.subject!==null)))throw new Error('Invalid canonical message detail');
        return <><h3>{value.subject??'Content unavailable'}</h3><p>Communication identity: {value.communication_id}. Content state: {value.content_state}.</p>
          {value.body===null?<p>No retained body is available.</p>:<p style={{whiteSpace:'pre-wrap'}}>{value.body}</p>}</>;
      }}/></section>}
  </>;
}
