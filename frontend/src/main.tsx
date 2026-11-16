import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowRight, CalendarDays, CircleHelp, Compass, MapPin, Navigation, RotateCcw, Sparkles, TriangleAlert } from 'lucide-react';
import { api, streamAPI, rangeLabel, dateLabel, tripDays, type Finding, type PlaceResult, type Analysis, type BackendEvent, type BuildResult, type Stage, type TimingSuggestion, type Trip, type TripContext } from './types';
import { TripLibrary, NameDialog, libraryAPI, type SavedTrip } from './TripLibrary';
import { directionsURL } from './directions';
import { ItineraryInput } from './ItineraryInput';
import { DayPlan } from './DayPlan';
import { ActionProgress } from './ActionProgress';
import { ReviewResults, StopReview } from './ReviewResults';
import { TripMap } from './TripMap';
import { useDestinationPhoto } from './DestinationBackground';
import './style.css';

const EMPTY_CONTEXT: TripContext = {city:null,timezone:null,start_date:null,end_date:null};
type Action = 'build' | 'fill' | 'check' | 'resume' | 'apply';
const BUILD_STAGES: Stage[] = [
  {stage:'reader',label:'Intent reader',kind:'ai',status:'queued',detail:'Read the destination, date range, and request.'},
  {stage:'validation',label:'Plan validation',kind:'workflow',status:'queued',detail:'Validate the dates and protect fixed bookings.'},
];
const CHECK_STAGES: Stage[] = [
  {stage:'supervisor',label:'Supervisor',kind:'workflow',status:'queued',detail:'Coordinate the work and follow-up requests.'},
  {stage:'logistics',label:'Logistics analyst',kind:'workflow',status:'queued',detail:'Check transfers against the schedule.'},
  {stage:'places',label:'Place researcher',kind:'tool',status:'queued',detail:'Search real locations with Geoapify.'},
  {stage:'place_agent',label:'Place Researcher agent',kind:'ai',status:'queued',detail:'Refine uncertain searches and find nearby options when needed.'},
  {stage:'logistics_agent',label:'Logistics Analyst agent',kind:'ai',status:'queued',detail:'Rank checked timing adjustments when needed.'},
];
function localDate(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
}
function normalizeTrip(value: Trip): Trip {
  const dates = value.activities.map(activity=>activity.day).sort();
  return {...value,start_date:value.start_date ?? dates[0],end_date:value.end_date ?? dates[dates.length-1]};
}
function contextOf(trip: Trip): TripContext {
  return {city:trip.city,timezone:trip.timezone,start_date:trip.start_date ?? null,end_date:trip.end_date ?? null};
}

function App() {
  const operationLock=useRef(false);
  const [view,setView]=useState<'planner'|'library'>('planner');
  const [savedTrip,setSavedTrip]=useState<{id:string;title:string;version:number}|null>(null);
  const [savedFingerprint,setSavedFingerprint]=useState('');
  const [saving,setSaving]=useState(false);
  const [saveDialog,setSaveDialog]=useState(false);
  const [saveError,setSaveError]=useState('');
  const [libraryNotice,setLibraryNotice]=useState('');
  const [text,setText] = useState('');
  const [trip,setTrip] = useState<Trip|null>(null);
  const [context,setContext] = useState<TripContext>(EMPTY_CONTEXT);
  const [run,setRun] = useState<Analysis|null>(null);
  const [livePlaces,setLivePlaces]=useState<Record<string,PlaceResult>>({});
  const [liveFindings,setLiveFindings]=useState<Record<string,Finding>>({});
  const [stopStages,setStopStages]=useState<Record<string,Stage>>({});
  const [choices,setChoices] = useState<Record<string,string>>({});
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [previousRunId,setPreviousRunId]=useState<string|null>(null);
  const [clarificationKind,setClarificationKind]=useState<string|null>(null);
  const [question,setQuestion] = useState<string|null>(null);
  const [answer,setAnswer] = useState('');
  const [stages,setStages] = useState<Stage[]>([]);
  const [action,setAction] = useState<Action|null>(null);
  const [selectedDay,setSelectedDay] = useState('');
  const [applyingActivity,setApplyingActivity]=useState<string|null>(null);
  const [selectedStop,setSelectedStop] = useState<string|null>(null);
  const [phase,setPhase] = useState('');
  const [aiAvailable,setAiAvailable] = useState<boolean|null>(null);

  function restoreTrip(value: Trip, restoreText=true) {
    const restored = normalizeTrip(value);
    setTrip(restored); setContext(contextOf(restored));
    if (restoreText && restored.input_text) setText(restored.input_text);
  }
  useEffect(()=>{
    const controller = new AbortController();
    api<{ai_available:boolean}>('/config',controller.signal).then(value=>{setAiAvailable(value.ai_available);}).catch(error=>{if(error.name!=='AbortError')setError('The Python backend is unavailable. Start it and refresh.');});
    try{const saved=JSON.parse(localStorage.getItem('trippilot-saved-trip')??'null');if(saved?.id){setSavedTrip(saved);setSavedFingerprint(saved.fingerprint??'');}}catch{}
    const draft = localStorage.getItem('trippilot-draft');
    const savedPrompt=localStorage.getItem('trippilot-prompt');
    if(savedPrompt!==null)setText(savedPrompt);
    if(draft)try{const value=JSON.parse(draft);if(Array.isArray(value.activities)&&value.activities.length){restoreTrip(value,false);if(savedPrompt===null&&value.input_text)setText(value.input_text);}}catch{localStorage.removeItem('trippilot-draft');}
    setPreviousRunId(localStorage.getItem('trippilot-location-run'));
    const saved = localStorage.getItem('trippilot-run');
    if(saved)api<Analysis>(`/runs/${saved}`,controller.signal).then(value=>{
      rememberRun(value);restoreTrip(value.trip,false);if(value.day)setSelectedDay(value.day);
      setPhase('Last schedule check');setAction('check');
      setStages(CHECK_STAGES.flatMap(stage=>{const saved=value.events.find(event=>event.stage===stage.stage);if(saved)return [{...stage,status:saved.status??'complete',detail:saved.detail}];if(stage.stage.endsWith('_agent'))return [];return value.events.some(event=>!event.stage&&event.worker.toLowerCase().startsWith(stage.label.toLowerCase().split(' ')[0]))?[{...stage,status:'complete' as const}]:[];}));
      try{const savedChoices=JSON.parse(localStorage.getItem('trippilot-location-choices')??'null');if(savedChoices?.runId===value.id)setChoices(savedChoices.choices??{});}catch{}
      if(value.status==='needs_confirmation')setStages(previous=>[...previous,{stage:'confirmation',label:'Your confirmation',kind:'human',status:'waiting',detail:'A location needs your choice.'}]);
    }).catch(()=>{});
    return ()=>controller.abort();
  },[]);
  useEffect(()=>{if(trip)localStorage.setItem('trippilot-draft',JSON.stringify(trip));},[trip]);
  useEffect(()=>{localStorage.setItem('trippilot-prompt',text);},[text]);

  useEffect(()=>{if(run?.status==='needs_confirmation')localStorage.setItem('trippilot-location-choices',JSON.stringify({runId:run.id,choices}));},[run?.id,run?.status,choices]);
  function rememberRun(value:Analysis){setRun(value);setLivePlaces({});setLiveFindings({});setStopStages({});setPreviousRunId(value.id);localStorage.setItem('trippilot-location-run',value.id);}
  function clearAnalysis(){setRun(null);setLivePlaces({});setLiveFindings({});setStopStages({});setChoices({});localStorage.removeItem('trippilot-run');}
  function changeTrip(value:Trip){const changed=normalizeTrip(value);const retained=Object.fromEntries(changed.activities.flatMap(activity=>{const before=trip?.activities.find(item=>item.id===activity.id);const place=places[activity.id];return trip?.city===changed.city&&before&&place?.status==='resolved'&&before.name===activity.name&&before.description===activity.description&&before.day===activity.day?[[activity.id,place]]:[];}));setTrip(changed);setContext(contextOf(changed));clearAnalysis();setLivePlaces(retained);setAction(null);setStages([]);setError('');setSelectedStop(null);}
  function onEvent(event:BackendEvent){
    if(event.type==='context'){setContext(event.context);return;}
    if(event.type==='run_created'){localStorage.setItem('trippilot-run',event.run_id);return;}
    if(event.type==='trip_update'){restoreTrip(event.trip,false);return;}
    if(event.type==='place_update'){
      setLivePlaces(previous=>({...previous,[event.activity_id]:event.place}));
      setStopStages(previous=>({...previous,[event.activity_id]:{stage:'places',label:'Place researcher',kind:'tool',status:'complete',detail:event.place.status==='resolved'?'Location matched.':'Location search finished.'}}));return;
    }
    if(event.type==='transfer_update'){
      setLiveFindings(previous=>({...previous,[event.activity_id]:event.finding}));
      setStopStages(previous=>({...previous,[event.activity_id]:{stage:'logistics',label:'Travel check',kind:'tool',status:'complete',detail:event.finding.message}}));return;
    }
    if(event.type!=='progress')return;
    if(event.activity_id)setStopStages(previous=>({...previous,[event.activity_id!]:{...event}}));
    setStages(previous=>{
      const found=previous.some(stage=>stage.stage===event.stage);
      if(found)return previous.map(stage=>stage.stage===event.stage?{...event}:stage);
      const next=[...previous];
      const validation=next.findIndex(stage=>stage.stage==='validation');
      if(event.stage==='planner'&&validation>=0)next.splice(validation,0,{...event});else next.push({...event});
      return next;
    });
  }
  async function perform(action:Action,label:string,initial:Stage[],operation:()=>Promise<void>){
    if(operationLock.current)return;
    operationLock.current=true;
    if(action==='build'||action==='fill')setLivePlaces({});
    setLiveFindings({});setStopStages({});
    setAction(action);setBusy(true);setError('');setPhase(label);setStages(initial.map(stage=>({...stage})));
    try{await operation();}catch(error){
      const message=error instanceof Error?error.message:'This step could not finish.';
      setError(message);setStages(previous=>{
        const active=previous.findIndex(stage=>stage.status==='running');
        const failed=active>=0?active:Math.max(0,previous.findIndex(stage=>stage.status==='queued'));
        return previous.map((stage,index)=>index===failed?{...stage,status:'error',detail:message}:stage.status==='queued'?{...stage,status:'skipped'}:stage);
      });
    }finally{operationLock.current=false;setBusy(false);}
  }
  async function buildPlan(input=text){
    setQuestion(null);setClarificationKind(null);setAnswer('');
    let ready:Trip|null=null;
    await perform('build','Building your trip',BUILD_STAGES,async()=>{
      const result=await streamAPI('/build/stream',{text:input,reference_date:localDate(),client_timezone:Intl.DateTimeFormat().resolvedOptions().timeZone},onEvent) as BuildResult;
      setContext(result.context);setClarificationKind(result.clarification_kind??null);
      if(result.clarification){setQuestion(result.clarification);setStages(previous=>previous.map(stage=>stage.status==='queued'?{...stage,status:'skipped'}:stage));return;}
      if(result.trip){ready=result.trip;restoreTrip(result.trip,false);clearAnalysis();}
    });
    if(ready){setPreviousRunId(null);localStorage.removeItem('trippilot-location-run');localStorage.removeItem('trippilot-location-choices');const firstDay=tripDays(ready)[0];setSelectedDay(firstDay);await checkPlan(ready,firstDay,null,null);}
  }
  async function fillDays(){if(!trip)return;const target=tripDays(trip).find(day=>!trip.activities.some(activity=>activity.day===day))??day;let ready:Trip|null=null;setQuestion(null);await perform('fill','Planning the empty days',[
    {stage:'planner',label:'Draft planner',kind:'ai',status:'queued',detail:'Draft only dates without activities.'},
    ...BUILD_STAGES.filter(stage=>stage.stage==='validation'),
  ],async()=>{
    const result=await streamAPI('/build/fill-days/stream',{trip},onEvent) as BuildResult;

    if(result.clarification){setQuestion(result.clarification);return;}
    if(result.trip){ready=result.trip;restoreTrip(result.trip,false);clearAnalysis();}
  });if(ready){setSelectedDay(target);await checkPlan(ready,target);}}
  async function checkPlan(nextTrip=trip,checkDay=day,focusId:string|null=null,previousId:string|null=previousRunId){if(!nextTrip||operationLock.current)return;setChoices({});setSelectedStop(focusId);await perform('check','Checking your itinerary',CHECK_STAGES,async()=>{
    const result=await streamAPI('/runs/stream',{trip:nextTrip,day:checkDay,previous_run_id:previousId},onEvent);
    if('run'in result){rememberRun(result.run);restoreTrip(result.run.trip,false);setChoices({});localStorage.setItem('trippilot-run',result.run.id);}
  });}
  async function applySuggestion(suggestion:TimingSuggestion){if(!run)return;setApplyingActivity(suggestion.activity_id);await perform('apply','Updating the time and rechecking',CHECK_STAGES.filter(stage=>!['places','place_agent'].includes(stage.stage)),async()=>{
    const result=await streamAPI(`/runs/${run.id}/suggestions/${suggestion.id}/apply/stream`,{},onEvent);
    if('run'in result){rememberRun(result.run);restoreTrip(result.run.trip,false);setChoices({});localStorage.setItem('trippilot-run',result.run.id);}
  });}
  async function resumePlan(nextChoices=choices){if(!run||operationLock.current||!run.questions.every(question=>!!nextChoices[question.activity_id]))return;await perform('resume','Checking routes and timing',[
    {stage:'confirmation',label:'Your confirmation',kind:'human',status:'queued',detail:'Apply your location choice.'},
    ...CHECK_STAGES.filter(stage=>!['places','place_agent'].includes(stage.stage)),
  ],async()=>{const result=await streamAPI(`/runs/${run.id}/resume/stream`,{choices:nextChoices},onEvent);if('run'in result){rememberRun(result.run);restoreTrip(result.run.trip,false);setChoices({});}});}
  function chooseLocation(id:string,choice:string){
    if(operationLock.current||!run)return;
    const next={...choices,[id]:choice};
    setChoices(next);setSelectedStop(id);
    if(run.status==='needs_confirmation'&&run.questions.every(question=>!!next[question.activity_id]))void resumePlan(next);
  }
  async function saveStop(value:Trip,stopId:string){
    if(operationLock.current)return;
    const activity=value.activities.find(item=>item.id===stopId);
    if(!activity)return;
    changeTrip(value);setSelectedDay(activity.day);setSelectedStop(stopId);
    await checkPlan(value,activity.day,stopId);
  }
  function clearPlan(){setSavedTrip(null);setSavedFingerprint('');localStorage.removeItem('trippilot-saved-trip');setTrip(null);setContext(EMPTY_CONTEXT);clearAnalysis();setStages([]);setAction(null);setSelectedStop(null);setPhase('');setQuestion(null);localStorage.removeItem('trippilot-draft');}
  const fingerprint=JSON.stringify({trip,prompt:text});
  const unsaved=!!trip&&fingerprint!==savedFingerprint;
  function trackSaved(value:SavedTrip,signature:string){
    const meta={id:value.id,title:value.title,version:value.version};
    setSavedTrip(meta);setSavedFingerprint(signature);
    localStorage.setItem('trippilot-saved-trip',JSON.stringify({...meta,fingerprint:signature}));
  }
  async function saveCurrent(title:string){
    if(!trip||saving)return;setSaving(true);setSaveError('');
    try{
      const body={title,trip,prompt:text,places,run_id:run&&JSON.stringify(run.trip)===JSON.stringify(trip)?run.id:null};
      const value=await libraryAPI<SavedTrip>(savedTrip?`/${savedTrip.id}`:'',savedTrip?'PUT':'POST',savedTrip?{...body,version:savedTrip.version}:body);
      trackSaved(value,fingerprint);setSaveDialog(false);setLibraryNotice('Trip saved to My trips.');
    }catch(error){setSaveError((error as Error).message);}finally{setSaving(false);}
  }
  async function openSaved(value:SavedTrip){
    if(unsaved&&!window.confirm('Open this trip and replace your unsaved draft? Choose Cancel to save the draft first.'))return;
    setBusy(true);clearAnalysis();setPreviousRunId(null);localStorage.removeItem('trippilot-location-run');localStorage.removeItem('trippilot-location-choices');
    restoreTrip(value.trip,false);setText(value.prompt);setSelectedDay(tripDays(value.trip)[0]);setSelectedStop(null);setStages([]);setAction(null);setError('');setQuestion(null);setLivePlaces(value.places??{});
    trackSaved(value,JSON.stringify({trip:normalizeTrip(value.trip),prompt:value.prompt}));
    if(value.run_id){
      try{const checked=await api<Analysis>(`/runs/${value.run_id}`);rememberRun(checked);if(checked.day)setSelectedDay(checked.day);setAction('check');localStorage.setItem('trippilot-run',checked.id);}
      catch{setLibraryNotice('Trip opened. Recheck the day to refresh its saved checks.');}
    }
    setView('planner');setBusy(false);
  }
  function newTrip(){
    if(unsaved&&!window.confirm('Start a new trip and replace your unsaved draft? Choose Cancel to save the draft first.'))return;
    clearPlan();setText('');setPreviousRunId(null);localStorage.removeItem('trippilot-location-run');localStorage.removeItem('trippilot-location-choices');setLibraryNotice('');setView('planner');
  }
  function reply(value=answer){const combined=text+'\nAdditional details: '+value;setText(combined);buildPlan(combined);}

  const days=useMemo(()=>tripDays(trip),[trip]);
  const day=days.includes(selectedDay)?selectedDay:days[0]??'';
  const numbers=useMemo(()=>Object.fromEntries((trip?.activities??[]).map((activity,index)=>[activity.id,index+1])),[trip]);
  const dayActivities=useMemo(()=>trip?.activities.filter(activity=>activity.day===day)??[],[trip,day]);
  const places={...run?.places,...livePlaces};
  function selectStop(id:string){const activity=trip?.activities.find(a=>a.id===id);if(!activity)return;setSelectedDay(activity.day);setSelectedStop(id);requestAnimationFrame(()=>{const target=document.getElementById('stop-'+id);target?.focus({preventScroll:true});target?.scrollIntoView({behavior:'smooth',block:'nearest'});});}
  function showOnMap(id:string){setSelectedStop(id);document.getElementById('trip-map-panel')?.scrollIntoView({behavior:'smooth',block:'nearest'});}
  const progress=<ActionProgress stages={stages} busy={busy} label={phase} error={error}/>;
  const clarification=question&&<div className="question-card" role="status"><CircleHelp size={20}/><div><h3>One quick detail</h3><p>{question}</p>{clarificationKind==='empty_itinerary'&&<button type="button" className="primary draft-instead" disabled={busy} onClick={()=>reply('Please draft a new itinerary for this destination and date range, preserving any reservations mentioned above.')}>Plan this trip <Sparkles size={14}/></button>}<div className="answer-row"><input aria-label="Your clarification" placeholder="Add the missing detail…" value={answer} disabled={busy} onChange={event=>setAnswer(event.target.value)} onKeyDown={event=>{if(event.key==='Enter'&&answer.trim()&&!busy)reply();}}/><button type="button" className="primary" disabled={busy||!answer.trim()} onClick={()=>reply()}>Continue <ArrowRight size={14}/></button></div></div></div>;
  const buildFeedback=<>{action==='build'&&progress}{action==='build'&&clarification}{!action&&error&&<p role="alert" className="error-banner">{error}</p>}</>;
  const wholeTripCheck=!!run&&!run.day&&new Set(run.trip.activities.map(activity=>activity.day)).size>1;
  const checking=!!action&&['check','resume','apply'].includes(action);
  const checkBusy=busy&&checking;
  const currentRun=run&&(!run.day||run.day===day)&&!wholeTripCheck?run:null;
  const activeStage=[...stages].reverse().find(stage=>stage.status==='running'&&stage.stage!=='supervisor');
  const pending=currentRun?.questions.filter(question=>!choices[question.activity_id]).length??0;
  const checkSummary=checkBusy?(activeStage?.label??'Checking your day'):
    currentRun?.status==='needs_confirmation'?(pending?`Choose locations in ${pending} ${pending===1?'stop':'stops'} below.`:'Starting route checks…'):
    currentRun?.status==='complete'?`${currentRun.findings.filter(f=>f.status==='conflict').length} timing ${currentRun.findings.filter(f=>f.status==='conflict').length===1?'conflict':'conflicts'} · ${currentRun.findings.filter(f=>f.status==='unknown').length} transfers need details`:
    'Check locations and travel times right here.';
  const checkFeedback=<>{checking&&error&&<div role="alert" className="error-banner">{error}<button type="button" className="text-button" onClick={()=>currentRun?.status==='needs_confirmation'?resumePlan():checkPlan()}>Retry check</button></div>}{currentRun&&!busy&&<ReviewResults run={currentRun} onRecheck={()=>checkPlan()}/>}</>;
  function renderCheck(id:string,onEdit:()=>void){
    if(!trip)return null;
    const activity=trip.activities.find(item=>item.id===id)!;
    const question=!(checkBusy&&action==='check')?currentRun?.questions.find(item=>item.activity_id===id):undefined;
    const finding=liveFindings[id]??(!checkBusy?currentRun?.findings.find(item=>item.source_id===id):undefined);
    const stage=(checkBusy&&action==='apply'&&applyingActivity===id?{stage:'apply',label:'Logistics analyst',kind:'workflow' as const,status:'running' as const,detail:'Applying the chosen time and rechecking this stop.'}:stopStages[id])??(checkBusy?{stage:'waiting',label:'Waiting',kind:'workflow' as const,status:'queued' as const,detail:'This stop will update as checks finish.'}:undefined);
    const result=places[id];
    return <StopReview name={activity.name} question={question} choice={choices[id]} onChoice={choice=>chooseLocation(id,choice)}
      finding={finding} directionsUrl={finding?directionsURL(places[id],places[finding.destination_id],finding.travel_mode):null} destination={trip.activities.find(item=>item.id===finding?.destination_id)?.name}
      suggestions={checkBusy?[]:currentRun?.suggestions?.filter(item=>item.activity_id===id)??[]}
      onApply={applySuggestion} busy={checkBusy} stage={stage} unresolved={!busy&&result?.status==='unresolved'?result.reason:undefined}
      onEdit={onEdit}/>;
  }
  const background=useDestinationPhoto(context.city);


  return <div className="app-shell">
    <div className={`destination-backdrop ${background?'has-photo':''}`} style={background?{backgroundImage:`url(${background.url})`}:undefined}/><div className="backdrop-wash"/>
    <header className="topbar"><a className="brand" href="/" aria-label="TripPilot home"><span className="brand-icon"><Navigation size={20}/></span>trip<span>pilot</span></a><div className="header-center"><Compass size={13}/><span>YOUR PLANS. A LITTLE MORE POSSIBILITY.</span></div><nav className="workspace-nav" aria-label="Workspace"><button type="button" aria-current={view==='planner'?'page':undefined} disabled={busy||saving} onClick={()=>setView('planner')}>Planner</button><button type="button" aria-current={view==='library'?'page':undefined} disabled={busy||saving} onClick={()=>setView('library')}>My trips</button></nav></header>
    <main>
      {view==='library'?<TripLibrary onOpen={openSaved} onNew={newTrip} onChanged={(value,deleted)=>{if(savedTrip?.id!==value.id)return;if(deleted){setSavedTrip(null);setSavedFingerprint('');localStorage.removeItem('trippilot-saved-trip');}else trackSaved(value,savedFingerprint);}}/>:<>
      <div className="workspace-save-bar"><span>{savedTrip?<><strong>{savedTrip.title}</strong><small>{unsaved?'Unsaved changes':'Saved to My trips'}</small></>:trip?'Keep this itinerary in My trips.':'Plan something worth keeping.'}</span><div><button className="text-button" disabled={busy||saving} onClick={newTrip}>New trip</button>{trip&&<button className="primary" disabled={busy||saving||(!unsaved&&!!savedTrip)} onClick={()=>{setSaveError('');if(savedTrip)void saveCurrent(savedTrip.title);else setSaveDialog(true);}}>{saving?'Saving…':savedTrip?'Save changes':'Save trip'}</button>}</div></div>
      {libraryNotice&&<p className="library-notice" role="status">{libraryNotice}<button className="text-button" onClick={()=>setLibraryNotice('')}>Dismiss</button></p>}
      {saveError&&!saveDialog&&<p role="alert" className="error-banner">{saveError}</p>}
      <div className="workspace">
        <section className="main-column">
          <ItineraryInput text={text} onText={setText} busy={busy} working={busy&&action==='build'} aiAvailable={aiAvailable} hasPlan={!!trip} feedback={buildFeedback} onSubmit={()=>buildPlan()}/>
          {(context.city||context.start_date)&&<div className="trip-context" aria-label="Extracted trip details"><span className="context-label">TRIP DETAILS</span>{context.city&&<span><MapPin size={14}/>{context.city}</span>}<span><CalendarDays size={14}/>{rangeLabel(context.start_date,context.end_date)}</span>{context.timezone&&<small>{context.timezone}</small>}</div>}
          <section className="day-plan-section" id="day-plan" aria-label="Your day plan" aria-live="polite"><div className="section-heading"><div><span className="eyebrow">A DAY THAT FEELS LIKE YOU</span><h1>{trip?`${trip.city}, at your pace.`:'Your day plan'}</h1></div>{trip&&<button className="text-button" disabled={busy} onClick={clearPlan}><RotateCcw size={13}/>Clear</button>}</div>
            <DayPlan trip={trip} onChange={changeTrip} onSave={saveStop} onFillDays={fillDays} selectedDay={day} onDay={value=>{setSelectedDay(value);setSelectedStop(null);clearAnalysis();if(trip)void checkPlan(trip,value);}} selectedStop={selectedStop} onShowMap={showOnMap} places={places} renderCheck={renderCheck} checkSummary={checkSummary} checkFeedback={checkFeedback} fillFeedback={action==='fill'?<>{progress}{clarification}</>:null} busy={busy?'Working':''}/>
          </section>
        </section>
        <aside className="side-column">
          <div className="map-panel" id="trip-map-panel"><div className="map-title"><span><MapPin size={15}/>Your stops on the map</span>{day&&<small>{dateLabel(day)}</small>}</div>
            {dayActivities.some(activity=>places[activity.id]?.place)?<TripMap activities={dayActivities} places={places} numbers={numbers} selectedId={selectedStop} onSelect={selectStop}/>:<div className="map-placeholder"><Compass size={24}/><p>{trip?'Confirm & check to locate your stops. The numbers will match your itinerary.':'Build a day plan to see your stops here.'}</p></div>}
            {dayActivities.length>0&&<div className="map-legend" aria-label="Map stop legend">{dayActivities.map(activity=><button type="button" className={selectedStop===activity.id?'selected':''} key={activity.id} onClick={()=>selectStop(activity.id)}><span className="legend-number">{numbers[activity.id]}</span><span><strong>{activity.name}</strong><small>{activity.start??'Time needed'} · {places[activity.id]?.place?.name??'Location not confirmed'}</small></span><ArrowRight size={13}/></button>)}</div>}
            <p className="map-disclaimer">Numbers match the stops in your itinerary. Place and route data: <a href="https://www.geoapify.com/" target="_blank" rel="noreferrer">Geoapify</a> / © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>. Travel times are estimates.</p>
          </div>

        </aside>
      </div>
      </>}
      {saveDialog&&trip&&<NameDialog label="Save trip" initial={`${trip.city} · ${rangeLabel(trip.start_date,trip.end_date)}`} busy={saving} error={saveError} onCancel={()=>setSaveDialog(false)} onSubmit={saveCurrent}/>}
      <footer><span><Sparkles size={12}/>Leave room for the unexpected.</span>{background?.attribution_required&&<details className="background-credit"><summary aria-label="Background photo attribution">ⓘ</summary><div><a href={background.source_url} target="_blank" rel="noreferrer">{background.title}</a><span>{background.author}</span><a href={background.license_url} target="_blank" rel="noreferrer">{background.license}</a><small>Cropped as background</small></div></details>}</footer>
    </main>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
