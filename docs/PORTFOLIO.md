# Publishing TripPilot as a portfolio project

## Position it accurately

A suitable repository description:

> Human-in-the-loop itinerary copilot with LangGraph orchestration, structured LLM outputs, live routing, deterministic validation, and a React/FastAPI interface.

Suggested GitHub topics:

```text
applied-ai  llm  ai-agents  langgraph  structured-outputs
human-in-the-loop  tool-calling  workflow-orchestration
fastapi  python  react  typescript  sqlite  api-integration
```

These terms are supported by the implementation. Do not label the project RAG, fine-tuning, enterprise-ready, production-deployed, or benchmarked unless those capabilities are subsequently built and measured.

For forward-deployed engineering (FDE) interviews, explain the delivery decisions rather than just listing libraries:

- **Problem discovery and workflow scoping:** the app handles destination/date extraction, place ambiguity, schedule feasibility, and user correction as separate problems.
- **Full-stack implementation:** React/TypeScript UI, Python APIs, typed contracts, streamed events, external integrations, and persistent state.
- **Reliable integration:** allowlisted tool actions, provider-backed candidates, timeouts, bounded calls, conservative abstention, and checkpointed human decisions.
- **Product iteration:** edits trigger rechecks in place; uncertainty is actionable; maps and stop numbers stay synchronized; unsupported facts remain unknown.
- **Technical handoff:** reproducible setup, documented data flow, regression tests, CI, and an honest roadmap.

The project demonstrates these practices in a personal prototype. It is not evidence of an enterprise customer deployment, production adoption, or measured customer impact.

## First push

The current project already has a local `.git` directory. Start by reviewing files, not reinitializing it.

1. On GitHub, create an **empty** repository, such as `trippilot`. Do not initialize it with another README, license, or `.gitignore` if you intend to push this local repository directly. Public visibility makes it reviewable by recruiters; choose visibility deliberately.
2. In a terminal at the project root, inspect what Git sees:

```sh
git status --short
git status --short --ignored
git check-ignore .env .data/checkpoints.sqlite .data/workspace.sqlite
```

The last command should print all three paths. `.env`, `.data`, virtual environments, dependency folders, and generated frontend output must stay excluded. Ignore rules do not remove a file already committed earlier; inspect `git ls-files` and history if you have previously committed this project.

3. Run verification:

```sh
uv run pytest -q
pnpm --dir frontend build
```

4. Review and stage the intended source/docs:

```sh
git add .
git diff --cached --stat
git diff --cached --name-only
```

Review staged text changes locally before committing. Check specifically for credentials, copied personal itineraries, screenshots with booking details, database files, recordings, and local absolute paths. Do not paste the staged diff publicly if you spot a secret.

5. Commit and connect the repository:

```sh
git commit -m "Build TripPilot itinerary copilot"
git branch -M main
git remote add origin YOUR_REPOSITORY_URL
git push -u origin main
```

Replace `YOUR_REPOSITORY_URL` with the HTTPS or SSH URL GitHub provides. If `origin` already exists, inspect `git remote -v` first rather than blindly adding or changing it. Use GitHub's normal authentication flow; never put an access token in a remote URL or source file.

6. Open the repository's **Actions** tab. Observe the Checks workflow passing on Ubuntu. Local checks passing is useful evidence, but it does not mean GitHub CI has run yet.
7. Read the rendered README on GitHub, open the setup/architecture links, and clone the repository into a different folder to run the first-time setup. Ask another person to follow the instructions if possible.
8. Add a concise description, topics, screenshots, and a video link. Pin the repository on your profile when the presentation is ready.

A source repository can be public while the app remains local; you do not need to pay for hosting to publish this portfolio version. Do not add a live-app URL until a protected deployment actually exists.

## Screenshots and video

The repository includes **two screenshots and an 83-second walkthrough**, linked near the top of README. An additional My trips screenshot would be useful but is optional. A video reduces the setup burden for a reviewer; screenshots make the README understandable at a glance. See [DEMO.md](DEMO.md) for the storyboard, capture checklist, and safe example inputs.

## A grounded resume bullet

> Built TripPilot, a full-stack itinerary copilot using FastAPI, React/TypeScript, LangGraph, and structured OpenAI outputs; integrated place/routing APIs with checkpointed human confirmation, deterministic schedule validation, and a persistent trip library, backed by 168 offline regression tests and a GitHub Actions check workflow.

Update the test count when it changes. Only say “passing GitHub CI” after observing the remote workflow. Be ready to explain the functions and tradeoffs yourself, including what assistance you used when building it. Do not invent percentages, model accuracy, token savings, latency reductions, or user adoption.

## What would strengthen it further

The highest-value next evidence is a labeled evaluation set and a comparable single-agent baseline. Measure correct extraction, booking preservation, place resolution/appropriate abstention, conflict precision/recall, recovery after clarification, latency, and usage-based cost. Record model/version, tool responses or fixtures, sample counts, and the date of each run. Report failures and inconclusive outcomes.

A protected hosted demo is another milestone, requiring authentication, public request limits, durable persistence, and a hosting budget. Those are deferred by choice and should stay labeled as future work.
