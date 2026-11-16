# TripPilot roadmap

## Implemented local prototype

- Natural-language extraction and optional itinerary drafting with Pydantic contracts.
- Multi-day timelines, stable map numbering, and in-place progress/events.
- Geoapify place/routing integration, bounded place research, and human clarification.
- LangGraph checkpoints and resume; supplied booking/time preservation.
- Deterministic schedule checks and user-applied timing alternatives.
- Editable missing-duration/start proposals based on preceding visits and available travel estimates.
- Openverse/Wikimedia photos and Google Maps directions links.
- SQLite trip library: save, reopen, rename, duplicate, delete/undo, version checks.
- Offline pytest regression suite, TypeScript/build checks, and GitHub Actions configuration.
- First-time setup, code/architecture guide, and portfolio/demo handoff documentation.

No sample itinerary is inserted into runtime state. Synthetic examples and deliberately conflicting cases belong in tests or a clearly described manual demonstration, never in a default user plan.

## Before promoting the repository

1. Finish the source/secret and first-install checks in [PORTFOLIO.md](docs/PORTFOLIO.md).
2. Capture the screenshots and short walkthrough in [DEMO.md](docs/DEMO.md).
3. Push to the chosen repository and observe GitHub Actions passing.
4. Verify the rendered README and setup on a fresh checkout.

## Next: model-quality evaluation

Create a labeled set of realistic requests, with development and held-out cases. Cover missing context, ambiguous places, changed venues, fixed bookings, timezone boundaries, unrealistic schedules, and provider failure. Compare the bounded specialist workflow with a single-agent baseline using the same model, tool access, expected outputs, and comparable budgets.

Report correctness, appropriate abstention, constraint preservation, conflict detection, clarification recovery, latency, and model/API usage. Keep deterministic regression test results separate from stochastic model-quality results. No comparative performance claim is established yet.

## Deferred product milestones

- Protected hosting and cross-device access: authentication, public request limits, durable storage, and a hosting budget.
- Reliable opening-hours checks with provenance and an explicit unknown state.
- Scheduled public transit and overnight/multi-timezone trips.
- Calendar export and optional home-screen/offline features.

Keep each milestone small, validate it end to end, and update README claims only after the feature or measurement exists.
