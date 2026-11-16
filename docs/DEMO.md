# Demonstrating TripPilot

The current [83-second walkthrough](media/walkthrough.mp4), [planner screenshot](images/planner.png), and [travel-check screenshot](images/itinerary-checks.png) are included and linked from the main README. The guidance below is for future recordings.

A short recording lets a reviewer see the workflow without creating API accounts. Use a synthetic itinerary with public place names and future dates. Nothing in this guide is preloaded into the app.

## Screenshots

Capture three views at a readable laptop size:

1. **Planner and map:** a completed itinerary with photos, labeled proposed values, a travel estimate, an Open directions link, and matching stop numbers.
2. **Human-in-the-loop step:** an actual ambiguous location and its candidate choices. Use a separate recording if your main request resolves automatically; do not fabricate a pause.
3. **My trips:** two saved versions showing an independent duplicate and the rename/delete controls. Clear unrelated personal plans from the frame without deleting anything you need.

Keep the full app context, including required map/photo attribution. Hide unrelated tabs, usernames, notifications, booking references, and credentials. Do not show `.env`, account billing pages, or a terminal command that prints keys.

Suggested repository paths:

```text
docs/images/planner.png
docs/images/itinerary-checks.png
docs/images/my-trips.png
```

Once the files exist, embed the strongest screenshot near the top of README:

```markdown
![TripPilot itinerary, travel checks, and synchronized map](docs/images/planner.png)
```

Use actual captures of the current app. Add the remaining screenshots farther down or link them from a short Demo section. Keep files reasonably small and verify they render on GitHub.

## A 60–90 second video

Record the app window with a screen recorder. A concise narration is useful; music is optional.

| Segment | Show | Explain |
| --- | --- | --- |
| 0–10 seconds | The natural-language input | “A plausible travel plan still needs real locations and feasible transfers.” |
| 10–30 seconds | Build and actual streamed progress | “Structured model output becomes validated itinerary state; tools provide place and route evidence.” |
| 30–45 seconds | A location choice, when genuinely ambiguous | “The workflow checkpoints and waits for a person instead of guessing the branch.” |
| 45–65 seconds | Edit a stop, Save & check, and map update | “The updated venue is resolved again, while unchanged confirmed places are reused.” |
| 65–80 seconds | Save, duplicate, and reopen | “Trip persistence restores the saved plan and checks without asking the model to regenerate them.” |
| Final seconds | Architecture/limitations in README | “Python owns validation and arithmetic. Authentication, deployment, and comparative model evaluations are future work.” |

If live calls take longer, speed up or trim idle waits and label that edit. Do not claim the video shows real-time latency after editing out waiting. Do not force a timing conflict into the normal demo; demonstrate an authentic user-supplied conflict separately if useful.

A reasonable main input:

> Barcelona on November 25, 2026. Visit Casa Batlló at 10:00 for 90 minutes, then have lunch at El Nacional at 12:30 for an hour. Use only these two stops.

A draft-generation alternative:

> Plan a relaxed day in Barcelona on November 25, 2026. I like architecture, neighborhood walks, and a long lunch. Suggest specific places and reasonable visit lengths.

Then change a meal venue to another real named restaurant and use Save & check. Location confidence and model output can vary between runs. Photos may be missing; explain that honestly rather than substituting a stock photo as though it shows that venue.

## Put the demo on GitHub

Keep screenshots in the repo. The current recording is included as a compact MP4 with a relative README link. For larger future recordings, use a GitHub issue/PR attachment, release asset, or a public video host, then link its actual URL. Keep large raw screen recordings outside normal Git history. A video is particularly valuable while there is no hosted app.

Before publication, play it from a signed-out browser and confirm that a reviewer can view it. Do not add a broken placeholder video URL to README.
