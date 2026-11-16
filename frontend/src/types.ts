export interface Activity {
  id: string; name: string; description?: string; day: string; start: string | null;
  start_estimated?: boolean; duration_minutes: number | null; duration_estimated?: boolean; fixed: boolean; suggested?: boolean;
}
export interface TripContext {city: string | null; timezone: string | null; start_date: string | null; end_date: string | null}
export interface Trip {
  city: string; timezone: string; start_date?: string; end_date?: string; activities: Activity[];
  origin?: 'imported' | 'generated'; input_text?: string; notes?: string[];
}
export interface Usage {model: string; calls: number; input_tokens: number; output_tokens: number}
export interface BuildResult {trip: Trip | null; context: TripContext; clarification: string | null; usage: Usage; clarification_kind?: 'empty_itinerary' | null}
export interface Place {id: string; name: string; lat: number; lng: number; address?: string; confidence?: number; walk_anchor?: boolean}
export interface PlaceResult {status: string; place: Place | null; candidates: Place[]; source: string; reason?: string; proposed?: boolean; recommended_id?: string | null}
export interface Finding {source_id: string; destination_id: string; status: 'conflict' | 'fits' | 'unknown'; message: string; evidence: string; travel_minutes: number | null; travel_mode?: 'walk' | 'drive' | 'approximated_transit' | null; slack_minutes: number | null}
export interface TimingSuggestion {id: string; activity_id: string; day: string; current_start: string; proposed_start: string; message: string; evidence: string}
export interface Analysis {id: string; day?: string | null; trip: Trip; places: Record<string, PlaceResult>; findings: Finding[]; events: {worker: string; detail: string; stage?: string; status?: 'complete' | 'skipped'}[]; questions: {activity_id: string; name: string; candidates: Place[]; reason?: string; proposed?: boolean; recommended_id?: string | null}[]; status: string; data_source: string; suggestions?: TimingSuggestion[]; agent_usage?: Usage | null; agent_notes?: string[]}
export interface ProgressUpdate {
  type: 'progress'; stage: string; label: string; status: 'running' | 'complete' | 'waiting' | 'skipped' | 'error';
  detail: string; kind: 'ai' | 'workflow' | 'tool' | 'human'; activity_id?:string|null; destination_id?:string|null;
}
export interface Stage extends Omit<ProgressUpdate, 'type' | 'status'> {status: ProgressUpdate['status'] | 'queued'}
export type BackendEvent = ProgressUpdate | {type: 'context'; context: TripContext} | {type: 'run_created'; run_id: string} | {type: 'heartbeat'} | {type:'trip_update';trip:Trip} | {type:'place_update';activity_id:string;place:PlaceResult} | {type:'transfer_update';activity_id:string;finding:Finding};
export type StreamResult = BuildResult | {run: Analysis};

export async function api<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch('/api' + path, {signal});
  if (!response.ok) throw new Error('Could not restore the saved analysis.');
  return response.json();
}

export async function streamAPI(path: string, body: unknown, onEvent: (event: BackendEvent) => void): Promise<StreamResult> {
  const response = await fetch('/api' + path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : 'Check your trip details and try again.');
  }
  if (!response.body) throw new Error('Streaming is unavailable in this browser.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let result: StreamResult | undefined;
  const processLine = (line: string) => {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.type === 'error') throw new Error(event.message);
    if (event.type === 'result') result = event;
    else onEvent(event);
  };
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, {stream: true});
      let newline: number;
      while ((newline = buffer.indexOf('\n')) !== -1) {processLine(buffer.slice(0, newline)); buffer = buffer.slice(newline + 1);}
      if (done) break;
    }
    processLine(buffer);
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  } finally {reader.releaseLock();}
  if (!result) throw new Error('The connection ended before the workflow returned a result. Your current plan has been kept.');
  return result;
}

export function dateLabel(value: string, options: Intl.DateTimeFormatOptions = {month: 'short', day: 'numeric'}): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return 'Date needed';
  return new Intl.DateTimeFormat('en-US', {...options, timeZone: 'UTC'}).format(new Date(value + 'T12:00:00Z'));
}
export function rangeLabel(start?: string | null, end?: string | null): string {
  if (!start) return 'Dates to confirm';
  if (!end || start === end) return dateLabel(start, {month: 'short', day: 'numeric', year: 'numeric'});
  return `${dateLabel(start)} – ${dateLabel(end, {month: 'short', day: 'numeric', year: 'numeric'})}`;
}

export function tripDays(trip: Trip | null): string[] {
  if (!trip) return [];
  const activityDates = trip.activities.map(activity=>activity.day).sort();
  const start = trip.start_date ?? activityDates[0];
  const end = trip.end_date ?? activityDates[activityDates.length-1];
  const days: string[] = [];
  const current = new Date(start + 'T12:00:00Z');
  while (Number.isFinite(current.getTime()) && current.toISOString().slice(0,10) <= end) {
    days.push(current.toISOString().slice(0,10));
    current.setUTCDate(current.getUTCDate()+1);
  }
  return days;
}
