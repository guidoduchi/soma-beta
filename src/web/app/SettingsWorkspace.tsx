import {createContext,useContext,useEffect,useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {filterFingerprint} from '../data/query-controller';
import type {ReturnState} from './router';
import {settingsIntent,settingsQuery,type SettingsIntent,type SettingsOpened,type SettingsSlot} from './settings-intent';
const empty:SettingsIntent={queries:{},opened:{customers:null,contacts:null,dispatch:null,source:null},accountHistory:false};
type Context=Readonly<{intent:SettingsIntent;query:(slot:SettingsSlot,path:string)=>void;open:(slot:keyof SettingsOpened,id:string|null)=>void;history:(value:boolean)=>void}>;
const SettingsContext=createContext<Context|null>(null);
export function useSettingsNavigation():Context {const value=useContext(SettingsContext);if(!value)throw new Error('Settings navigation is not composed');return value;}
export function useSettingsQuery(slot:SettingsSlot,initial:string):[string,(value:string)=>void] {
  const context=useSettingsNavigation();const saved=context.intent.queries[slot];
  const path=saved&&saved.split('?')[0]===initial.split('?')[0]?saved:initial;
  return [path,value=>context.query(slot,value)];
}
export function SettingsWorkspace({path,restored=null,onReturnState,children}:{path:string;restored?:ReturnState|null;
  onReturnState?:(capture:()=>ReturnState|null)=>void;children:ReactNode}) {
  const restoredIntent=restored?.route===path?settingsIntent(restored.settings,path):null;
  const [intent,setIntent]=useState<SettingsIntent>(()=>restoredIntent??empty);
  const [notice,setNotice]=useState<string|null>(restored&&!restoredIntent?'The previous Settings context is unavailable; current first pages are shown.':null);
  const root=useRef<HTMLDivElement>(null);const focus=useRef<string|null>(restoredIntent?restored?.focusToken??null:null);
  const fingerprint=useRef<{intent:SettingsIntent;value:string}|null>(null);
  useEffect(()=>{let active=true;void filterFingerprint({settings:JSON.stringify(intent)}).then(value=>{if(active)fingerprint.current={intent,value};});return()=>{active=false;};},[intent]);
  useEffect(()=>{onReturnState?.(()=>{
    if(fingerprint.current?.intent!==intent)return null;
    const panes=Array.from(root.current?.querySelectorAll<HTMLElement>('[data-return-scroll]')??[]).slice(0,12)
      .map(node=>[node.dataset.returnScroll,node.scrollTop,node.scrollLeft]);
    return {route:path,filterFingerprint:fingerprint.current.value,activeId:null,selectedId:null,memberIds:[],settings:intent,focusToken:focus.current,
      scrollAnchor:JSON.stringify({main:document.getElementById('main-content')?.scrollTop??0,panes})};
  });},[intent,path,onReturnState]);
  useLayoutEffect(()=>{
    const node=root.current;if(!node||!restoredIntent||!restored)return;
    let positions:{main:number;panes:[string,number,number][]}|null=null;
    try {if(restored.scrollAnchor&&restored.scrollAnchor.length<=2048){const value=JSON.parse(restored.scrollAnchor);
      const coordinate=(n:unknown)=>typeof n==='number'&&Number.isFinite(n)&&n>=0;
      if(value&&Object.keys(value).length===2&&coordinate(value.main)&&Array.isArray(value.panes)&&value.panes.length<=12
        &&value.panes.every((p:unknown)=>Array.isArray(p)&&p.length===3&&typeof p[0]==='string'&&p[0].length<=64&&coordinate(p[1])&&coordinate(p[2])))positions=value;
    }}catch{/* Invalid scroll intent leaves current positions. */}
    let observer:MutationObserver|null=null;let explained=false;const stop=()=>{observer?.disconnect();observer=null;};
    const apply=()=>{
      if(Array.from(node.querySelectorAll('[role="status"]')).some(element=>element.textContent?.startsWith('Loading accepted')))return;
      if(restored.focusToken){const control=Array.from(node.querySelectorAll<HTMLElement>('[data-focus-token]')).find(element=>element.dataset.focusToken===restored.focusToken
        &&element.getClientRects().length>0&&!element.matches(':disabled'));
        (control??document.getElementById('main-content'))?.focus({preventScroll:true});
        if(!control&&!explained){explained=true;setNotice('The previous Settings control is unavailable; focus returned to Settings.');return;}
      }
      if(positions){const main=document.getElementById('main-content');if(main)main.scrollTop=positions.main;
        for(const [token,top,left] of positions.panes){const pane=Array.from(node.querySelectorAll<HTMLElement>('[data-return-scroll]')).find(element=>element.dataset.returnScroll===token);
          if(pane){pane.scrollTop=top;pane.scrollLeft=left;}}
      }stop();
    };
    observer=new MutationObserver(apply);observer.observe(node,{childList:true,subtree:true,characterData:true});apply();
    for(const event of ['pointerdown','keydown','wheel','touchstart'])node.addEventListener(event,stop,{capture:true,once:true});
    return()=>{stop();for(const event of ['pointerdown','keydown','wheel','touchstart'])node.removeEventListener(event,stop,true);};
  },[]);
  const context:Context={intent,query:(slot,query)=>{if(!settingsQuery(query,slot,intent.opened))throw new Error('Invalid Settings query intent');setIntent(value=>({...value,queries:{...value.queries,[slot]:query}}));},
    open:(slot,id)=>setIntent(value=>{const queries={...value.queries};if(slot==='customers'){delete queries.accountHistory;}if(slot==='contacts'){delete queries.channels;}
      const next={...value,queries,opened:{...value.opened,[slot]:id},...(slot==='customers'?{accountHistory:false}:{})};if(!settingsIntent(next,path))throw new Error('Invalid Settings open intent');return next;}),
    history:accountHistory=>setIntent(value=>({...value,accountHistory}))};
  return <SettingsContext.Provider value={context}><div ref={root} onFocusCapture={event=>{const control=event.target.closest<HTMLElement>('[data-focus-token]');if(control)focus.current=control.dataset.focusToken??null;}}>
    {notice&&<p role="status">{notice}</p>}{children}</div></SettingsContext.Provider>;
}
