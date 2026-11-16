import type { ReactNode } from 'react';
import { CornerDownLeft, LoaderCircle, Sparkles } from 'lucide-react';

interface Props {text: string; onText: (text: string) => void; busy: boolean; working?: boolean; aiAvailable: boolean|null; hasPlan: boolean; feedback?: ReactNode; onSubmit: () => void}

export function ItineraryInput({text, onText, busy, working, aiAvailable, hasPlan, feedback, onSubmit}: Props) {
  return <fieldset className="composer" disabled={busy}>
    <div className="composer-label"><Sparkles size={16}/><span>Tell me your itinerary, or where you’re going.</span></div>
    <textarea id="itinerary-prompt" aria-label="Tell me your itinerary or where you’re going" value={text} onChange={event => onText(event.target.value)} maxLength={10000} rows={4}
      placeholder="Tell me your destination, dates, interests, and any bookings—or paste your itinerary."
      onKeyDown={event => {if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && text.trim() && aiAvailable) onSubmit();}}/>
    <div className="composer-bottom"><div><span className="shortcut"><CornerDownLeft size={11}/> ⌘ / Ctrl + Enter</span><button type="button" className="primary build-button" onClick={onSubmit} disabled={!aiAvailable || !text.trim()}>{working ? <LoaderCircle className="spin" size={16}/> : <Sparkles size={16}/>} {working ? 'Working on your trip' : hasPlan ? 'Rebuild my day plan' : 'Build my day plan'}</button></div></div>
    {feedback}
    {aiAvailable === false && <p className="composer-help">Connect OPENAI_API_KEY in your local .env file to build a plan.</p>}
    {hasPlan && <p className="composer-help">Rebuilding uses only the text above and replaces your previous plan and edits.</p>}
  </fieldset>;
}
