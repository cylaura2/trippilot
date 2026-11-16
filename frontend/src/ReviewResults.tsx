import { useState } from 'react';
import { ArrowRight, ArrowUpRight, CheckCircle2, CircleHelp, Download, LoaderCircle, MapPin, Sparkles, TriangleAlert } from 'lucide-react';
import type { Analysis, Finding, Stage, TimingSuggestion } from './types';

type Question = Analysis['questions'][number];
interface StopProps {
  name:string;question?:Question;choice?:string;onChoice:(value:string)=>void;
  finding?:Finding;destination?:string;directionsUrl?:string|null;suggestions:TimingSuggestion[];
  onApply:(suggestion:TimingSuggestion)=>void;busy:boolean;stage?:Stage;
  unresolved?:string;onEdit:()=>void;
}

export function StopReview({name,question,choice,onChoice,finding,destination,directionsUrl,suggestions,onApply,busy,stage,unresolved,onEdit}:StopProps){
  const [expanded,setExpanded]=useState(false);
  const active=busy&&stage?.status==='running';
  const chosen=question?.candidates.find(candidate=>candidate.id===choice);
  return <div className="stop-review">
    {busy&&stage?.status==='queued'&&<p className="stop-queued" role="status"><i/>Waiting for this stop’s check</p>}
    {active&&<div className="stop-work" role="status"><LoaderCircle size={15} className="spin"/><span><strong>{stage.label}</strong>{stage.detail}</span><i/></div>}
    {question&&<div className="stop-question">
      {choice&&!expanded?<button type="button" className="chosen-location-summary" aria-label={`Change location for ${name}`} disabled={busy} onClick={()=>setExpanded(true)}><CheckCircle2 size={16}/><span><strong>{choice==='unresolved'?'Left unresolved':chosen?.name}</strong><small>Selected · Change location</small></span></button>:<>
        <h4><MapPin size={15}/>{question.candidates.some(candidate=>candidate.walk_anchor)?'Choose a starting point for this walk':question.proposed?'Choose a place for this stop':'Which location did you mean?'}</h4>
        {question.candidates.some(candidate=>candidate.walk_anchor)&&<p className="editor-help">The pin marks one starting point, not the whole walk. For a precise meeting point, edit this stop to use a landmark or street address.</p>}
        <div role="radiogroup" aria-label={`Location for ${name}`}>
          {question.candidates.map(candidate=><label className="location-choice" key={candidate.id}><input type="radio" name={`place-${question.activity_id}`} disabled={busy} checked={choice===candidate.id} onChange={()=>{onChoice(candidate.id);setExpanded(false);}}/><span><strong>{candidate.name}{candidate.walk_anchor&&<small className="recommended-place">Walk starting point</small>}{candidate.id===question.recommended_id&&<small className="recommended-place">Suggested match</small>}</strong><small>{candidate.address??'Address unavailable'}</small></span></label>)}
          <label className="location-choice leave-unresolved"><input type="radio" name={`place-${question.activity_id}`} disabled={busy} checked={choice==='unresolved'} onChange={()=>{onChoice('unresolved');setExpanded(false);}}/><span><strong>Leave unresolved</strong><small>You can update this stop later.</small></span></label>
        </div>
      </>}
    </div>}
    {unresolved&&!question&&!active&&<p className="stop-unresolved"><CircleHelp size={15}/><span>{unresolved} <button type="button" className="text-button" disabled={busy} onClick={onEdit}>Edit this stop</button></span></p>}
    {finding&&!active&&<div className={`transfer-inline ${finding.status}`} aria-label={`Transfer from ${name}`}>
      {finding.status==='fits'?<CheckCircle2 size={16}/>:finding.status==='conflict'?<TriangleAlert size={16}/>:<CircleHelp size={16}/>}
      <div><strong>Next: {destination}</strong><p>{finding.message}</p>
        {directionsUrl&&<a className="directions-link" href={directionsUrl} target="_blank" rel="noopener noreferrer" aria-label={`Open directions from ${name} to ${destination} in Google Maps`}>Open directions<ArrowUpRight size={14}/><span>Google Maps</span></a>}
        {finding.status==='unknown'&&<button type="button" className="text-button" disabled={busy} onClick={onEdit}>Edit time or visit length</button>}
      </div>
    </div>}
    {suggestions.map(suggestion=><div className="stop-suggestion" key={suggestion.id}><Sparkles size={16}/><div><strong>{suggestion.message}</strong><button type="button" className="primary" disabled={busy} onClick={()=>onApply(suggestion)}>Apply &amp; recheck <ArrowRight size={14}/></button></div></div>)}
  </div>;
}

export function ReviewResults({run,onRecheck}:{run:Analysis;onRecheck:()=>void}){
  function download(){const url=URL.createObjectURL(new Blob([JSON.stringify(run,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='trippilot-analysis.json';a.click();URL.revokeObjectURL(url);}
  return <div className="check-notes">
    {!!run.agent_notes?.length&&<details><summary>Additional check notes</summary>{run.agent_notes.map((note,index)=><p key={index}>{note}</p>)}</details>}
    {run.status==='complete'&&<button type="button" className="text-button" onClick={onRecheck}>Recheck day</button>}
    <button type="button" className="text-button" onClick={download}><Download size={14}/>Download check results</button>
  </div>;
}
