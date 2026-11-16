import { useState, type FormEvent } from 'react';
import { CheckCircle2, Trash2 } from 'lucide-react';
import type { Activity } from './types';

export function StopEditor({activity,busy,onSave,onCancel,onRemove,canRemove}:{activity:Activity;busy:boolean;onSave:(value:Activity)=>void;onCancel:()=>void;onRemove:()=>void;canRemove:boolean}){
  const [draft,setDraft]=useState({...activity});
  const [error,setError]=useState('');
  function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    const date=new Date(draft.day+'T12:00:00Z');
    if(!draft.name.trim()||!Number.isFinite(date.getTime())||date.toISOString().slice(0,10)!==draft.day){setError('Add a place name and a valid date.');return;}
    const name=draft.name.trim();
    const changed=name!==activity.name;
    // A replacement venue must not inherit the old venue's location-specific description.
    const description=changed?'':draft.description;
    onSave({...draft,name,description,suggested:changed?false:activity.suggested});
  }
  return <form className="stop-editor" aria-label={`Edit stop ${activity.name}`} onSubmit={submit}>
    <fieldset disabled={busy}>
      <label>Name<textarea aria-label={`Activity ${activity.id} name`} rows={2} value={draft.name} required maxLength={200} onChange={event=>setDraft({...draft,name:event.target.value})}/></label>
      <div className="activity-meta">
        <label>Date<input type="date" required value={draft.day} onChange={event=>setDraft({...draft,day:event.target.value})}/></label>
        <label>Start<input type="time" value={draft.start??''} onChange={event=>setDraft({...draft,start:event.target.value||null,start_estimated:false})}/></label>
        <label>Visit length (min)<input type="number" min="1" max="1440" step="1" value={draft.duration_minutes??''} onChange={event=>setDraft({...draft,duration_minutes:event.target.value?Number(event.target.value):null,duration_estimated:false})}/></label>
      </div>
      {draft.duration_minutes==null&&<div className="visit-length-help"><p>Leave this blank for a proposed visit length, or choose one below.</p><div>{[30,60,90].map(minutes=><button type="button" key={minutes} onClick={()=>setDraft({...draft,duration_minutes:minutes,duration_estimated:false})}>Use {minutes} min</button>)}</div></div>}
      {draft.start_estimated&&<p className="editor-help">This start is proposed from the previous visit and travel time. Edit it to set your own time.</p>}
      {draft.duration_estimated&&<p className="editor-help">This visit length is proposed. Adjust it to suit your plans.</p>}
      <div className="edit-bottom"><label className="fixed-toggle"><input type="checkbox" checked={draft.fixed} onChange={event=>setDraft({...draft,fixed:event.target.checked})}/>Fixed reservation</label><button type="button" className="text-button danger" disabled={!canRemove} onClick={onRemove}><Trash2 size={12}/>Remove</button></div>
      {error&&<p role="alert" className="editor-error">{error}</p>}
      <div className="editor-actions"><button type="button" className="text-button" onClick={onCancel}>Cancel</button><button type="submit" className="primary"><CheckCircle2 size={15}/>Save &amp; check</button></div>
      <small className="editor-help">Saving finds the updated location, refreshes the map, and checks travel times.</small>
    </fieldset>
  </form>;
}
