import { StopEditor } from './StopEditor';
import { PlacePhoto } from './PlacePhoto';
import { useState, type ReactNode } from 'react';
import { CheckCircle2, Clock3, Info, LockKeyhole, MapPin, Pencil, Plus, Sparkles } from 'lucide-react';
import { dateLabel, rangeLabel, tripDays, type PlaceResult, type Trip } from './types';

interface Props {trip: Trip|null;onChange:(trip:Trip)=>void;onSave:(trip:Trip,stopId:string)=>void;onFillDays:()=>void;busy:string;selectedDay:string;onDay:(day:string)=>void;selectedStop:string|null;onShowMap:(id:string)=>void;places:Record<string,PlaceResult>;checkFeedback?:ReactNode;fillFeedback?:ReactNode;renderCheck?:(id:string,onEdit:()=>void)=>ReactNode;checkSummary?:string}

export function DayPlan({trip,onChange,onSave,onFillDays,busy,selectedDay:selected,onDay:setSelected,selectedStop,onShowMap,places,checkFeedback,fillFeedback,renderCheck,checkSummary}:Props){
  const [editing,setEditing]=useState<string|null>(null);
  const days=tripDays(trip);
  if(!trip)return <div className="empty-plan"><span className="empty-icon"><CompassMark/></span><div><h2>Good days start with a few words.</h2><p>Your itinerary will appear here, ready to make your own.</p></div></div>;
  const visible=trip.activities.filter(activity=>activity.day===(selected||days[0]));
  const emptyDays=days.filter(day=>!trip.activities.some(activity=>activity.day===day));
  return <fieldset className="plan-canvas">
    <div className="plan-meta"><span>{rangeLabel(trip.start_date,trip.end_date)}</span><span className="pill">{trip.origin==='generated'?'AI DRAFT':'YOUR ITINERARY'}</span></div>
    {days.length>1&&<div className="day-selector" role="group" aria-label="Choose itinerary day">{days.map((day,index)=><button key={day} type="button" disabled={!!busy} aria-pressed={day===(selected||days[0])} onClick={()=>setSelected(day)}><span>DAY {index+1}</span>{dateLabel(day,{weekday:'short',month:'short',day:'numeric'})}{emptyDays.includes(day)&&<small>Not planned yet</small>}</button>)}</div>}
    {emptyDays.length>0&&<div className="empty-days-banner"><div><strong>{emptyDays.length} {emptyDays.length===1?'day is':'days are'} waiting for a plan</strong><p>Keep your existing stops and let AI draft only the empty days.</p></div><button type="button" className="primary" disabled={!!busy} onClick={onFillDays}><Sparkles size={14}/>Plan empty days</button></div>}
    {fillFeedback}
    {visible.some(activity=>!activity.start||activity.duration_minutes==null)&&<p className="plan-note"><Info size={13}/>Missing times and visit lengths will be proposed after locations and travel times are checked.</p>}
    {(trip.notes??[]).filter(note=>!note.startsWith('Unspecified durations stayed blank')&&!note.startsWith('Missing start times stayed blank')).map((note,index)=><p className="plan-note" key={index}><Info size={13}/>{note}</p>)}
    <div className="plan-check-toolbar">
      <div><span className="eyebrow">YOUR DAY, IN DETAIL</span><p>{checkSummary||'Check locations and travel times right here.'}</p></div>

    </div>
    {checkFeedback}
    <div className="timeline">
      {visible.length===0&&<div className="unplanned-day"><CompassMark/><h3>Not planned yet</h3><p>No activities have been added for {dateLabel(selected||days[0],{weekday:'long',month:'long',day:'numeric'})}. Add a stop below or plan the empty days.</p></div>}
      {visible.map(activity=>{
        const number=trip.activities.findIndex(item=>item.id===activity.id)+1;
        const resolved=places[activity.id]?.place;
        return <article id={`stop-${activity.id}`} tabIndex={-1} className={`timeline-stop ${editing===activity.id?'editing':''} ${selectedStop===activity.id?'selected-stop':''}`} key={activity.id}>
          <div className="stop-time"><strong>{activity.start??'— —'}</strong>{activity.start_estimated&&<small className="duration-estimate-label">proposed start</small>}{activity.duration_minutes?<small>{activity.duration_minutes} min{activity.duration_estimated&&<span className="duration-estimate-label">proposed</span>}</small>:<button type="button" className="missing-duration-button" disabled={!!busy} onClick={()=>setEditing(activity.id)}>Add visit length</button>}</div>
          <div className="stop-node"><button type="button" className="stop-number" aria-label={`Stop ${number}: ${activity.name}${resolved?', show on map':', location not confirmed'}`} disabled={!resolved} onClick={()=>onShowMap(activity.id)}>{number}</button></div>
          <div className="stop-content"><PlacePhoto name={activity.name} city={trip.city} place={resolved}/><div className="stop-heading"><h3>{activity.name}</h3><button type="button" className="icon-button" aria-label={`Edit ${activity.name}`} disabled={!!busy} onClick={()=>setEditing(editing===activity.id?null:activity.id)}><Pencil size={13}/></button></div>
            {activity.description&&<p className="stop-description">{activity.description}</p>}
            {resolved&&<small className="location-confirmed"><CheckCircle2 size={12}/>{resolved.walk_anchor?'Walk starting point confirmed':'Location confirmed'}</small>}
            {resolved&&<button type="button" className="stop-location" onClick={()=>onShowMap(activity.id)}><MapPin size={12}/>{resolved.name}<span>View on map</span></button>}
            <div className="stop-tags">{activity.fixed&&<span className="fixed-tag"><LockKeyhole size={10}/>Fixed booking</span>}{activity.suggested&&<span>Suggested stop</span>}{!activity.start&&<span className="missing-time"><Clock3 size={10}/>Time after travel check</span>}</div>
            {renderCheck?.(activity.id,()=>setEditing(activity.id))}
            {editing===activity.id&&<StopEditor key={activity.id} activity={activity} busy={!!busy} canRemove={trip.activities.length>1}
              onCancel={()=>setEditing(null)} onRemove={()=>{onChange({...trip,activities:trip.activities.filter(item=>item.id!==activity.id)});setEditing(null);}}
              onSave={updated=>{
                const activities=trip.activities.map(item=>item.id===activity.id?updated:item);
                const dates=activities.map(item=>item.day).sort();
                const next={...trip,activities,start_date:trip.start_date&&trip.start_date<dates[0]?trip.start_date:dates[0],end_date:trip.end_date&&trip.end_date>dates[dates.length-1]?trip.end_date:dates[dates.length-1]};
                setEditing(null);onSave(next,activity.id);
              }}/>}
          </div>
        </article>;
      })}
    </div>
    <button type="button" className="text-button add-activity" disabled={!!busy||trip.activities.length>=120} onClick={()=>{
      const id=crypto.randomUUID();onChange({...trip,activities:[...trip.activities,{id,name:'New activity',day:selected||days[0],start:null,duration_minutes:null,fixed:false}]});setEditing(id);
    }}><Plus size={14}/>Add a stop</button>
  </fieldset>;
}
function CompassMark(){return <svg width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden="true"><circle cx="13" cy="13" r="10" stroke="currentColor"/><path d="m17 9-2.5 5.5L9 17l2.5-5.5L17 9Z" stroke="currentColor"/></svg>;}
