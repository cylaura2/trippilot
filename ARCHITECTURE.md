# How TripPilot is built

The app is a React browser interface connected to a Python service. Python reads a natural-language request, creates a validated itinerary, and runs a checkpointed checking workflow. Progress events stream back to React while work happens.

The reader/planner make structured model calls. LangGraph coordinates live tools and two bounded specialists: a PlaceResearcher that chooses typed tool actions from observations, and a LogisticsAnalyst that ranks Python-validated timing proposals. The supervisor and schedule arithmetic are ordinary Python.

## Building and checking

**Build my day plan**:

1. `Intent reader` calls the model to extract city, destination timezone, inclusive date range, intent, and any existing activities.
2. Missing destination/dates produce a question. User answers are appended to the original text for the next build.
3. Existing itineraries go directly to validation. A request for a new plan invokes the `Draft planner` in a second model call.
4. Python validates the result, rejects moved fixed bookings or overlapping generated visits, and returns an editable itinerary.

**Automatic check after build, Save & check, or Recheck day**:

1. The supervisor dispatches the logistics worker.
2. Logistics requests locations if they have not been researched.
3. The supervisor dispatches the place worker, which calls the live Geoapify adapter.
4. Ambiguous matches pause execution with LangGraph `interrupt()`.
5. After confirmation, logistics fetches selected travel routes and calculates schedule findings in Python.
6. The Logistics Analyst ranks checked timing alternatives when available; the supervisor finishes. SQLite checkpoints permit restoring a paused run.

## Python types: `trippilot/models.py`

| Type | Meaning |
| --- | --- |
| `Contract` | Shared Pydantic base. Rejects extra, unrecognized fields. |
| `Activity` | A stop: ID, short name, description, date, optional start/duration, fixed status, suggestion status. |
| `TripContext` | Destination, timezone, and start/end dates; fields may be unknown while clarifying. |
| `Trip` | A complete itinerary with context, activities, origin, original text, and notes. |
| `BuildRequest` | Natural-language text, reference date, and browser timezone. Rebuild accepts no previous-trip context. |
| `Usage` | Model identifier and aggregate call/input/output-token counts for one build. |
| `BuildResult` | A trip or a clarification question, plus extracted context and usage. |
| `ProgressEvent` | A role's ID, label, state, explanation, and kind: AI/workflow/tool/human. |
| `RunRequest` | A `Trip`, selected day, and optional previous run ID. |
| `ResumeRequest` | Activity IDs mapped to chosen candidate IDs, or `unresolved`. |
| `PlaceCandidate` | Validated provider ID, name, address, coordinates, and provider confidence. |
| `PlaceResolution` | Resolved/ambiguous/unresolved result with candidates, source, reason, proposed-option flag, and optional recommended candidate ID. |
| `TimingSuggestion` | A checked one-stop time edit with original/proposed times, day, message, and evidence. |
| `RouteEstimate` | Available/unavailable travel estimate, mode, boarding/pickup allowance, minutes, distance, source, and reason. |
| `Finding` | A transfer result: conflict, fits, or unknown; optional route/slack values and evidence. |

Methods:

- `Activity.valid_time(value)` normalizes a supplied local time to HH:MM and accepts unknown times as `None`.
- `Activity.instant(timezone_name)` converts a known local date/time into UTC for arithmetic. It rejects missing or ambiguous/nonexistent daylight-saving times.
- `Trip.valid_trip()` checks timezone, unique IDs, date-range ordering, activity inclusion in the range, and known local times. Missing boundaries can be derived from activities when restoring older drafts.
- `BuildRequest.valid_timezone(value)` validates the browser timezone used to interpret relative-date context.

## Model steps: `trippilot/planner.py`

The `Emit` alias describes a callback that accepts an event dictionary.

| Type/function | Responsibility |
| --- | --- |
| `ExtractedActivity` | Structured model output for an activity, including verbatim booking and duration evidence quotes. |
| `ParsedRequest` | Reader response: intent, context, existing activities, and possible question. |
| `DraftStop` | A proposed stop with a required, format-constrained time and positive duration. |
| `DraftDay` | One dated day with a schema-enforced 3–5 stops. |
| `DraftPlan` | Planner response: a list of day objects, flattened into application activities after parsing. |
| `progress(...)` | Validates and emits a `ProgressEvent`. It does not call a model. |
| `call_model(schema, instructions, text, usage)` | Makes one bounded structured-output API call and updates token/call counters. |
| `read_request(request, usage, emit)` | Emits reader status, calls the reader prompt, and returns `ParsedRequest`. |
| `resolve_context(parsed)` | Produces `TripContext`, anchors known-city timezones, and asks a question when required details are missing/invalid. |
| `supported_duration(item, text)` | Keeps a positive imported duration only when a verbatim source quote contains explicit duration units or a clock-time range; zero/unsupported estimates become unknown. |
| `to_activity(item, index, context, text, suggested)` | Converts model output into an application `Activity`, assigns an ID, applies single-day fallback dates, checks booking/duration evidence, and rejects dates outside the trip range. It does not rewrite a model-returned year. |
| `draft_days(context, days, anchors, text, usage, emit)` | Runs one planner call for exactly the requested dates, creates unique suggestion IDs, and validates the result. |
| `fill_empty_days(trip, text, emit, usage)` | Determines dates without activities, drafts only those dates, and appends suggestions while preserving every existing stop. |
| `validate_draft(activities, context, anchors, expected_dates)` | Enforces per-day stop counts, known timings, within-day bounds, no visit overlap, and preservation of fixed anchors. |
| `build_itinerary(request, emit)` | Coordinates reading, clarification, optional drafting, final validation, and the `BuildResult`. |

`READER_PROMPT` and `PLANNER_PROMPT` are separate constants because preserving an existing itinerary and inventing a draft need different instructions. There is no template parsing branch.

## Checking workflow: `trippilot/workflow.py`

`State` is a `TypedDict`: a description of graph fields for developers/type tools. It is not a Pydantic runtime validator. Graph state includes trip data, place results, findings, events, requests, and control flags.

- `event(state, worker, detail)` appends a concise execution outcome to the stored event history.
- `supervisor(state)` chooses logistics, place research, or completion from the current flags and requests.
- `analysis_trip(state)` creates the selected-day working view while keeping the full itinerary in checkpoint state.
- `logistics(state, tools, emit)` requests missing place work on its first pass; afterward it fetches eligible travel routes, stores them separately, and calls `check_schedule()`. Route lookup is independent of schedule completeness.
- `research(state, tools, emit)` runs initial lookups, invokes `PlaceResearcher.refine()` on uncertain stops, then checkpoints candidates, agent actions/notes, and model usage.
- `advice(state, emit)` invokes `LogisticsAnalyst.suggest()` after feasibility checks, stores timing alternatives and usage, and marks advice complete.
- `needs_clarification(state)` selects human confirmation when any match is ambiguous.
- `clarify(state, emit)` emits a waiting event, pauses with `interrupt()`, validates resumed choices, and returns selected locations.
- `build_graph(checkpointer, emit, tools)` accepts an optional test tool adapter, otherwise uses `GeoapifyClient`, creates the LangGraph nodes and edges, then compiles with checkpoint storage.
- Its inner `observed(...)` function wraps a worker so actual node start/end events reach the UI. Inner `run(state)` executes that wrapped worker. The clarification node emits its own pause/resume events.

Graph nodes coordinate the work; specialist behavior lives in `PlaceResearcher` and `LogisticsAnalyst` classes in `trippilot/agents.py`. State updates and conditional edges implement supervision.

## Tools and arithmetic

In `tests/fixture_tools.py` (offline tests only; not imported by production workflow/checker):

- `normalize(value)` normalizes whitespace/case/accents for sample lookup.
- `lookup_place(name, city)` returns a resolved candidate, ambiguous candidates, or unresolved status from fixtures.
- `route_minutes(origin, destination)` returns a sample walking time or `None`.

In `trippilot/geoapify.py`:

- `GeoapifyError` holds a safe public error without provider URLs, response bodies, or credentials.
- `normalize(value)` normalizes accents/case/punctuation for conservative named-match checks.
- `distance_km(a, b)` checks that candidates lie within the destination search area.
- `GeoapifyClient.__init__(api_key)` reads the backend key, optionally accepting an explicit key for testing.
- `_request(endpoint, **params)` sends an HTTPS request with a 12-second timeout and no retries; shares a four-per-second limiter and 512-entry, one-hour memory cache across local runs. Cache keys contain a credential hash, not a raw key. Cached response copies prevent caller mutation.
- `search_place(name, city)` locates the destination city, searches within 50 km, rejects city centroids and street substitutions for venues/addresses; explicitly named street walks may offer a name-matched `walk_anchor` candidate that always needs human confirmation, validates candidates, and automatically resolves only a single high-confidence named match. Other usable matches need human confirmation.
- `get_route(origin, destination)` prefers short walks and compares approximate transit and driving for longer walks; `_route` fetches one validated mode. Selected non-walking routes add five minutes for boarding/pickup. Missing routes remain unavailable.

In `trippilot/checker.py`, `activity_pairs(trip)` groups and orders stops within each date, preserving source order on days with missing times. Overnight transfers are excluded. `check_schedule(trip, places, routes)` performs duration + travel arithmetic using separately supplied route results. It detects direct overlaps without locations and explicitly reports missing inputs/routes. It has no network calls and no fixture fallback.

In `trippilot/agents.py`:

- `PlaceAction` is the strict next-action contract: search, nearby, or finish; nullable arguments must be supplied explicitly. No arbitrary tool names/URLs/coordinates.
- `NearbyAction` narrows generic coffee/meal requests to nearby search or finish, preventing irrelevant name-search loops.
- `RankedRepairs` contains only IDs of checked timing options.
- `progress(...)` emits real specialist activity with AI/tool distinctions.
- `generic_category(name)` recognizes common generic coffee/meal breaks without treating named venues like “Lunch at Sol” as category requests.
- `category_matches(candidate, category)` checks provider categories against the allowed category hierarchy.
- `PlaceResearcher.__init__(tools, emit, usage)` initializes per-research budgets, public notes, and action records.
- `PlaceResearcher.refine(trip, places)` observes uncertain results, asks for a typed action, validates its arguments against confirmed same-day anchors/candidates, enforces food-category matching and explicit nearby-anchor/radius constraints, runs an allowed tool, and observes again. At most two turns per stop, six model attempts, and six follow-up searches. Validated nearby defaults for flexible meals and exact high-confidence named matches can resolve automatically; other named candidates pause for confirmation. Model failures preserve existing evidence and stop further reasoning attempts in that research phase.
- `LogisticsAnalyst.__init__(emit, usage)` receives the stream and usage accumulator.
- `LogisticsAnalyst.suggest(...)` asks Python for checked repair options, makes at most one model call to rank their IDs, rejects unknown IDs, and falls back to checked options with a note on model failure.

The agent loop uses structured next-action output via the existing Responses API parser, followed by an explicit Python dispatcher; it does not use the Agents SDK or native function-call output. The feedback loop still lets the model choose the next permitted tool from actual observations. Supervisor/arithmetic decisions are deterministic.

In `trippilot/repairs.py`:

- `apply_timing(trip, suggestion)` validates the stop ID, date, original start, and flexible status before returning a copied, validated itinerary.
- `timing_options(...)` derives small shifts from measured negative slack, preserves date/order/fixed bookings, and rechecks every same-day pair. A change cannot break a previously fitting pair or conceal a known conflict as unknown. Up to eight independent alternatives are generated; this is not global optimization.

`GeoapifyClient.search_nearby(category, anchor)` uses the v2 Places API with four allowed categories, a 1 km radius, and five results maximum. Its results are suggestions. Flexible generic meals can adopt a validated nearby venue by default, while fixed generic bookings still need confirmation. Existing geocoding/routing use v1.


## Streaming: `trippilot/streaming.py`

- `public_error(error)` converts failures into safe messages without exposing provider error bodies or credentials. Validation messages distinguish duration, start-time, date, and text-field failures rather than labeling every failure as a bad date.
- `stream_job(job)` starts one worker thread and yields newline-delimited JSON events as work progresses.
- Its inner `emit(event)` places an event into a bounded queue, while checking for client disconnect.
- Inner `work()` executes the job, sends a final result or error, and closes the stream with a private sentinel.

Heartbeats keep long model requests connected. There are no fake sleeps, simulated worker events, or made-up token percentages.

## HTTP service: `trippilot/api.py`

- `graph_session(emit)` opens the checkpoint database and yields a compiled graph; closes storage afterward.
- `config(run_id)` validates the ID and creates LangGraph thread settings with an execution limit.
- `present(graph, run_id)` reads a saved snapshot, derives pending questions/status, and creates the browser-facing analysis object.
- `response_for(job)` wraps `stream_job` in an NDJSON `StreamingResponse`.
- `get_config()` reports model/key availability without returning a key.
- `health()` reports server health.
- `fill_days(request)` serves `POST /api/build/fill-days/stream` for a single-call empty-day draft.
- `build_plan(request)` serves `POST /api/build/stream` and runs the prompt pipeline.
- `start_analysis(trip, places, day)` streams a new analysis, optionally retaining confirmed place choices for a time-only adjustment.
- `apply_suggestion(run_id, suggestion_id)` validates a saved timing suggestion server-side and starts a fresh analysis without changing the original.
- `start_run(request)` serves `POST /api/runs/stream`; its inner `run(emit)` creates a run ID, invokes the graph, and returns analysis.
- `get_run(run_id)` serves `GET /api/runs/{id}` for restoration.
- `resume_run(run_id, request)` checks submitted choices; its inner `resume(emit)` continues the checkpointed graph through `Command(resume=...)`.

Built frontend files are served from `frontend/dist` after the API routes are registered.

## React types and network helpers: `frontend/src/types.ts`

TypeScript interfaces describe browser data; they do not replace Python runtime validation.

- `Activity`, `Trip`, `TripContext`, `Usage`, `BuildResult`, and `ProgressUpdate` mirror backend contracts.
- `Place` describes a location; `PlaceResult` adds resolution status/candidates/source.
- `Finding` and `Analysis` describe check results and saved graph runs.
- `Stage` describes a visible role, including a queued state used before it starts.
- `BackendEvent` is a union of progress, extracted context, run-ID, and heartbeat events.
- `StreamResult` is a union of a build result and a completed/paused analysis result.
- `api(path, signal)` restores/configures through ordinary GET requests.
- `streamAPI(path, body, onEvent)` POSTs an action, decodes NDJSON across arbitrary network chunks, dispatches progress, and returns the final result. Its inner `processLine` handles one JSON line.
- `dateLabel(value, options)` formats a calendar date without accidentally shifting its timezone.
- `tripDays(trip)` enumerates the inclusive date range using UTC calendar arithmetic.
- `rangeLabel(start, end)` formats an inclusive one-day or multi-day range.

## React components and local state

`frontend/src/main.tsx`:

- `localDate()` gets the browser-local reference date for interpreting expressions such as tomorrow.
- `normalizeTrip(value)` fills missing range metadata in older saved drafts.
- `contextOf(trip)` derives display context from an itinerary.
- `App()` connects the prompt, trip state, streaming activity, photo, map, day plan, and results.
- `restoreTrip(value, restoreText)` restores a trip/context and optionally its source text. It preserves separately saved text when restoring an older analysis.
- `clearAnalysis()` discards stale findings after edits or a successful rebuild.
- `changeTrip(value)` applies edits and invalidates old analysis.
- `onEvent(event)` updates extracted context, stored run ID, and compact inline role statuses from real events.
- `perform(label, initial, operation)` sets the running state, handles failures, and finishes an action.
- `fillDays()` submits the current saved trip to the empty-day planner and replaces the displayed draft only after success.
- `buildPlan(input)` submits natural language and applies either the resulting trip or a clarification question.
- `checkPlan()` submits the full itinerary plus selected day to the graph.
- `selectStop(id)` selects the stop’s day, highlights it, and focuses its timeline entry.
- `showOnMap(id)` selects a resolved stop and scrolls its marker into view.
- `applySuggestion(suggestion)` calls the saved-suggestion endpoint and replaces the displayed trip only when the new analysis succeeds.
- `resumePlan()` resumes that graph with the user's location choices.
- `clearPlan()` clears the browser draft and analysis references.
- `reply()` appends clarification details to the source prompt and rebuilds.
- `example()` fills an ordinary natural-language example; it does not parse or bypass the model.

Other components:

- `ItineraryInput(props)` is the single prompt composer with submit/example/keyboard controls.
- `DayPlan(props)` renders every date in the trip range, including explicit empty-day states and a Plan empty days button. `StopEditor` stages changes; committing preserves the range or expands it when needed. `CompassMark()` draws its small empty-state icon.
- `ActionProgress(props)` renders compact live status, colored agent-step indicators, and optional step details directly under the triggering button.
- `StopReview(props)` renders per-stop loading, location radio cards, a collapsible chosen location, transfer findings, and checked timing suggestions within the itinerary row. `ReviewResults(props)` holds only optional agent notes and the JSON download action. Unknown schedule feasibility remains explicit.
- `TripMap(props)` initializes Leaflet, updates selected-day numbered markers with named popups, synchronizes selection with itinerary stop IDs, and cleans up map/resize resources.
- `destinationPhoto(city)` selects a correctly credited local destination image or returns no match. Unsupported cities get a neutral gradient.

The `Props` interfaces local to components specify the state and callbacks each receives from `App`; they are component contracts, not agent state.

## What is next

Evaluate the bounded specialist agents against a single-agent baseline. Keep deterministic arithmetic and checkpointed confirmation. Compare the resulting system against a single-agent baseline before claiming multi-agent improvements.


### Optional place photos and confirmation reuse

`photos.PhotoRequest` accepts only bounded place names, city, and coordinates. `photo_for` maintains a bounded TTL cache and turns provider failures into optional unavailable results. `find_photo` finds a same-name Wikipedia article within 750 m, then retrieves Commons image metadata. Only HTTPS Wikimedia image hosts and Commons source pages are accepted. Author HTML is stripped; credits and license links accompany each image. `request_json` uses fixed provider hosts, an eight-second timeout and shared rate limit. `/api/places/photo` serves metadata; `PlacePhoto` loads it asynchronously beside each timeline stop. No model or paid key is used.

`RunRequest.previous_run_id` allows server-side reuse of resolved places only when city, activity ID, name, description, and day still match. Cached resolved generic stops bypass initial category filtering; newly suggested generic stops still require confirmation. Browser choices are saved by run ID and collapse after selection. Empty imports return an explicit drafting clarification instead of failing trip validation.


Route lookup depends only on resolved endpoints. `logistics` fetches travel estimates independently of schedule completeness; `check_schedule` retains travel minutes and provider evidence for incomplete or overlapping schedules, but computes slack only when the required schedule inputs are known.


### In-place streaming and Openverse fallback

Progress events optionally carry `activity_id` and `destination_id`. `research` emits `place_update` events after grounded lookup and refinement. `logistics` emits `transfer_update` findings as routes return. The final run remains the authoritative checkpoint; streamed results are provisional UI updates. `App` overlays live places and findings on the displayed run, while `stopStages` drives the affected row's spinner and agent label. Rechecks retain existing rows/photos while working, and applying a saved repair replaces the same activity's time. No stream step automatically scrolls to a lower results section.

`request_openverse` anonymously searches the fixed Openverse images endpoint with bounded query length and page size. `openverse_photo` requires a place-name phrase in the title, city evidence in title/tags, a supported reusable license, author, and public HTTPS image/source/license links. The fallback runs after Wikipedia misses or fails; provider errors stay optional and short-cached. Credits identify Openverse as the search provider. Search requests contain names and city only, not dates, bookings, or the complete itinerary.


`materialize_suggestions(trip, places)` replaces resolved, flexible generic meal/coffee placeholders with the selected venue name and removes Restaurant TBD text. It preserves activity IDs, dates, times, durations, named stops, and fixed bookings. The graph checkpoints the updated full trip and emits `trip_update` so the existing browser row updates. `present` also normalizes older saved checks for display. Raw route provenance remains in exported data; `StopReview` displays only concise travel summaries.


### Automatic continuation and staged edits

`chooseLocation` passes the newly constructed choices map to `resumePlan` immediately after the last pending choice. `perform` owns a ref-based synchronous lock so rapid clicks cannot start duplicate jobs; it releases the lock on success or error without automatic retries. `StopEditor` stages an activity copy and validates its form before `Save & check`. `saveStop` commits once and passes the updated trip and day explicitly to `checkPlan`, avoiding stale React state. Changed names/descriptions/dates invalidate cached places; unchanged stops retain matches and photos. The edited stop stays selected as its marker updates.

`specific_place_name` narrowly recognizes a neighborhood walk followed by an explicitly named landmark. Lookup uses that landmark instead of the combined string. Import/draft normalization retains the walk in its description and preserves fixed booking names. Older combined-name location matches are not reused, preventing a stale hotel/apartment match from standing in for a cathedral. Named meal stops adopt the resolved provider spelling after checks.


### Visit-length proposals and dynamic destination backgrounds

`durations.proposed_minutes` provides a category-based fallback, prioritizing the activity name over its description. `with_proposed_durations` fills only missing lengths and sets `duration_estimated=True`; explicit visit lengths and booking times are untouched. The reader has a separate `proposed_duration_minutes` output so guesses cannot masquerade as supplied facts. The API upgrades older saved plans on read and recomputes their findings when missing durations or old buffer arithmetic would make saved results stale. Travel-buffer configuration, state, request fields, UI, and arithmetic have been removed.

`destination_photo(city)` searches Openverse on demand, preferring CC0/public-domain results and matching city evidence in image metadata. `useDestinationPhoto` starts with no image, fetches when extracted city changes, and switches the CSS background only after the remote image loads. Unmatched/failed searches retain the generic gradient. No images are bundled or downloaded to the repository. Required attribution remains behind an info icon, while optional credits and model-usage labels are absent from product UI.


### Fresh rebuilds and estimated visit-length checks

`BuildRequest` has no previous-trip field. `read_request` forwards only the current request text; previous itinerary context is rejected by the schema. `buildPlan` clears saved location-choice references after a successful rebuild and calls `checkPlan` with an explicit null previous-run ID. The runtime example button and its sample itinerary were deleted; synthetic data lives only in the tests package.

Logistics preserves supplied schedule values: it fetches travel estimates, checks the proposed stays and start times, and streams findings into the existing rows. It does not shorten visits or move starts to make a plan pass. Timing suggestions require user acceptance, and transport arrival/departure anchors are excluded from automatic timing suggestions.

`with_proposed_starts` fills missing start times from the previous stop’s duration and available route minutes. It marks `start_estimated`, defaults the first unspecified start per day to 09:00, preserves explicit anchors, and recomputes inferred starts on recheck. Missing routes and transfers crossing midnight remain unresolved rather than inventing travel times or dates. Inferred sequences keep source order; complete explicitly timed sequences sort by start. `trip_update` streams these proposals into the timeline. Editing a start clears its estimated flag. Photo requests accept optional coordinates so Openverse can search the name/city immediately; Wikimedia geosearch begins once coordinates are known.

Generic meal/coffee routing is determined by the activity name. A named venue must not be reclassified or require a nearby anchor merely because its description contains an old generic meal/nearby description. Explicit nearby constraints in descriptions remain active for genuinely generic titles. Renaming a stop in the editor clears its old location-specific description.


### Trip library

`trippilot/library.py` owns SQLite CRUD in a separate workspace database. `TripSave` validates itinerary and place snapshots; each record stores a title, JSON payload (trip, source prompt, confirmed places, run ID), timestamps, version, and a soft-delete flag. List responses contain only card summaries. Updates and renames acquire an immediate transaction and compare versions to reject stale writes. Duplicate creates a new record with an independent payload; analysis IDs reference immutable checkpoints. Deletion hides a record; restore reverses that flag. Every connection is committed/rolled back and closed per operation.

`TripLibrary.tsx` renders the library, rename/save dialogs, and delete/undo feedback. `App` tracks the active saved record and its saved-content fingerprint separately from the working draft. Opening restores the snapshot and fetches its checkpoint without starting agents. Save is explicit; existing local draft recovery remains. Deleting the currently open saved record detaches its identity so the working draft can be saved again. Hosting and authentication are not enabled in this local-only release.

Photo responses may include a validated `full_url`. Clicking a thumbnail mounts a native modal dialog through a React portal, with Escape/backdrop/close controls, thumbnail fallback, an original-source link, and required credits. Wikimedia originals must use its upload host; Openverse originals must pass the public HTTPS URL check.
