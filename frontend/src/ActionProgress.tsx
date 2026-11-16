import { CheckCircle2, CircleHelp, LoaderCircle, TriangleAlert } from 'lucide-react';
import type { Stage } from './types';

export function ActionProgress({stages,busy,label,error}: {stages:Stage[];busy:boolean;label:string;error?:string}) {
  if (!stages.length && !error) return null;
  const names:Record<string,string>={reader:'Read request',planner:'Draft plan',validation:'Validation',places:'Place search',place_agent:'Place agent',logistics:'Travel check',logistics_agent:'Timing agent',confirmation:'Your choices'};
  const waiting=stages.some(stage=>stage.status==='waiting');
  const failed=!!error||stages.some(stage=>stage.status==='error');
  const active=[...stages].reverse().find(stage=>stage.status==='running');
  const detail=error || (waiting?stages.find(stage=>stage.status==='waiting')?.detail:busy?active?.detail||'Getting started…':[...stages].reverse().find(stage=>stage.status==='complete'&&stage.stage!=='supervisor')?.detail||'Finished.');
  return <div className={`action-progress ${failed?'failed':waiting?'waiting':busy?'working':'finished'}`} role="status" aria-live="polite">
    <div className="action-progress-title">{failed?<TriangleAlert size={16}/>:waiting?<CircleHelp size={16}/>:busy?<LoaderCircle size={16} className="spin"/>:<CheckCircle2 size={16}/>}<strong>{failed?'Needs attention':waiting?'Your choice is needed':busy?label:'Done'}</strong></div>
    <p>{detail}</p>
    {!failed&&<div className="action-steps" aria-label="Agent progress">{stages.filter(stage=>stage.stage!=='supervisor').map(stage=><span key={stage.stage} className={stage.status} title={stage.detail}><i/>{names[stage.stage]??stage.label}<b/></span>)}</div>}
    <details className="action-details"><summary>Step details</summary><ol>{stages.map(stage=><li key={stage.stage}><strong>{stage.label}</strong><span>{stage.status==='queued'?'Not started':stage.status}</span><p>{stage.detail}</p></li>)}</ol></details>
  </div>;
}
