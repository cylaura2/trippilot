import {useEffect,useState} from 'react';
import {ArrowRight,Copy,FolderHeart,MapPin,Pencil,Plus,Trash2,X} from 'lucide-react';
import {rangeLabel,type Trip,type PlaceResult} from './types';

export interface SavedTrip {
  id:string;title:string;city:string;start_date:string;end_date:string;stop_count:number;
  version:number;updated_at:string;trip:Trip;prompt:string;run_id:string|null;places:Record<string,PlaceResult>;
}
export async function libraryAPI<T>(path='',method='GET',body?:unknown):Promise<T>{
  const response=await fetch('/api/trips'+path,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok){const value=await response.json().catch(()=>({}));throw new Error(typeof value.detail==='string'?value.detail:'Could not update your saved trips. Please try again.');}
  return response.json();
}

export function TripLibrary({onOpen,onNew,onChanged}:{onOpen:(trip:SavedTrip)=>Promise<void>;onNew:()=>void;onChanged:(trip:SavedTrip,deleted?:boolean)=>void}){
  const [trips,setTrips]=useState<SavedTrip[]>([]);
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [renaming,setRenaming]=useState<SavedTrip|null>(null);
  const [title,setTitle]=useState('');
  const [deleted,setDeleted]=useState<SavedTrip|null>(null);
  async function refresh(){setTrips(await libraryAPI<SavedTrip[]>());}
  useEffect(()=>{let active=true;libraryAPI<SavedTrip[]>().then(value=>{if(active)setTrips(value);}).catch(error=>{if(active)setError(error.message);}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[]);
  async function act(work:()=>Promise<void>){if(busy)return;setBusy(true);setError('');try{await work();}catch(error){setError((error as Error).message);}finally{setBusy(false);}}
  return <section className="trip-library" aria-label="My trips">
    <div className="library-heading"><div><span className="eyebrow">KEEP THE GOOD PLANS</span><h1>My trips</h1><p>Your saved itineraries, ready when you are.</p></div><button className="primary" disabled={busy} onClick={onNew}><Plus size={17}/>New trip</button></div>
    {error&&<p role="alert" className="error-banner">{error}</p>}
    {deleted&&<div className="library-notice" role="status"><span>“{deleted.title}” moved to trash.</span><button disabled={busy} className="text-button" onClick={()=>act(async()=>{await libraryAPI(`/${deleted.id}/restore`,'POST');setDeleted(null);await refresh();})}>Undo</button></div>}
    {loading?<p role="status">Loading your trips…</p>:trips.length===0?<div className="library-empty"><FolderHeart size={36}/><h2>A place for your next adventure.</h2><p>Build a plan, then choose “Save trip” to keep it here.</p></div>:<div className="library-grid">{trips.map(trip=><article className="saved-trip-card" key={trip.id}>
      <span className="library-city"><MapPin size={15}/>{trip.city}</span><h2>{trip.title}</h2><p>{rangeLabel(trip.start_date,trip.end_date)}</p><small>{trip.stop_count} {trip.stop_count===1?'stop':'stops'} · Saved {new Intl.DateTimeFormat('en-US',{month:'short',day:'numeric'}).format(new Date(trip.updated_at))}</small>
      <div className="library-card-actions"><button className="primary" disabled={busy} onClick={()=>act(async()=>onOpen(await libraryAPI<SavedTrip>(`/${trip.id}`)))}>Open trip<ArrowRight size={15}/></button><div>
      <button className="icon-button" aria-label={`Rename ${trip.title}`} disabled={busy} onClick={()=>{setRenaming(trip);setTitle(trip.title);}}><Pencil size={16}/></button>
      <button className="icon-button" aria-label={`Duplicate ${trip.title}`} disabled={busy} onClick={()=>act(async()=>{await libraryAPI(`/${trip.id}/duplicate`,'POST');await refresh();})}><Copy size={16}/></button>
      <button className="icon-button" aria-label={`Delete ${trip.title}`} disabled={busy} onClick={()=>act(async()=>{await libraryAPI(`/${trip.id}`,'DELETE');onChanged(trip,true);setDeleted(trip);await refresh();})}><Trash2 size={16}/></button></div></div>
    </article>)}</div>}
    <p className="library-storage-note">Saved on this TripPilot server. Hosting and cross-device access are not enabled yet.</p>
    {renaming&&<NameDialog label="Rename trip" initial={title} busy={busy} error={error} onCancel={()=>setRenaming(null)} onSubmit={value=>act(async()=>{const renamed=await libraryAPI<SavedTrip>(`/${renaming.id}`,'PATCH',{title:value,version:renaming.version});onChanged(renamed);await refresh();setRenaming(null);})}/>}
  </section>;
}

export function NameDialog({label,initial,busy,error,onCancel,onSubmit}:{label:string;initial:string;busy:boolean;error:string;onCancel:()=>void;onSubmit:(title:string)=>void}){
  const [title,setTitle]=useState(initial);
  return <div className="dialog-backdrop"><section className="trip-dialog" role="dialog" aria-modal="true" aria-labelledby="trip-dialog-title" onKeyDown={event=>{if(event.key==='Escape'&&!busy)onCancel();}}><div className="dialog-heading"><h2 id="trip-dialog-title">{label}</h2><button className="icon-button" aria-label="Close dialog" disabled={busy} onClick={onCancel}><X size={19}/></button></div><form onSubmit={event=>{event.preventDefault();if(title.trim())onSubmit(title.trim());}}><label>Trip name<input autoFocus required maxLength={100} value={title} onChange={event=>setTitle(event.target.value)} placeholder="A weekend in Barcelona"/></label>{error&&<p role="alert" className="editor-error">{error}</p>}<div className="editor-actions"><button type="button" className="text-button" disabled={busy} onClick={onCancel}>Cancel</button><button className="primary" disabled={busy||!title.trim()}>{busy?'Saving…':'Save'}</button></div></form></section></div>;
}
