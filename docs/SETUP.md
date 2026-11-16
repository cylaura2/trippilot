# First-time setup

This walkthrough starts from a fresh checkout. You do not need React experience to run the built app: one Python process serves both the frontend and the backend.

## 1. Install the prerequisites

- [Git](https://git-scm.com/downloads), to clone the repository.
- [uv](https://docs.astral.sh/uv/getting-started/installation/), to install the locked Python environment. Python 3.13 can be downloaded automatically by uv.
- [Node.js 24](https://nodejs.org/en/download), to build the React app.
- pnpm 11.25.0. After installing Node, run:

```sh
npm install --global pnpm@11.25.0
```

Check that your terminal can find the tools:

```sh
git --version
uv --version
node --version
pnpm --version
```

Use Node 24 and pnpm 11.25.0 for the documented setup. Reopen the terminal if a newly installed command is not found. You do not need Docker, PostgreSQL, Openverse registration, or a Google Maps API key.

## 2. Get the code

On the GitHub repository page, choose **Code**, then copy its HTTPS clone URL. Replace the uppercase placeholders below with your actual URL and the directory Git creates:

```sh
git clone YOUR_REPOSITORY_URL
cd YOUR_REPOSITORY_DIRECTORY
```

Run the following commands from this project root, where `pyproject.toml` and `.env.example` are located.

## 3. Create your local environment file

macOS/Linux:

```sh
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Open `.env` in a text editor. It is a hidden file on some systems; an editor's file explorer can show it. Add your own keys:

```dotenv
OPENAI_API_KEY=your_own_openai_key
OPENAI_MODEL=gpt-5.4-mini
GEOAPIFY_API_KEY=your_own_geoapify_key
```

- OpenAI: create a key in your [API project](https://platform.openai.com/api-keys), enable billing if needed, and set provider-side usage controls. A ChatGPT subscription is separate from API billing.
- Geoapify: create a project in [MyProjects](https://myprojects.geoapify.com/) and copy that project's key. Check its current quota/pricing in your account.
- Openverse/Wikimedia photos work without another key. Google Maps directions are ordinary links, not a paid Google API integration.

Plain keys do not need quotes in this file. Do not paste keys into frontend files, screenshots, issues, or Git. `.gitignore` excludes `.env`. Restart Python after changing keys or the configured model. Changing the model may change quality, cost, and structured-output compatibility.

## 4. Install and build

```sh
uv sync --locked --python 3.13
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
```

`uv sync` creates `.venv` and installs the locked Python dependencies, including development tests. The pnpm commands install locked frontend dependencies, check TypeScript, and build `frontend/dist`. You do not need to activate `.venv` when using `uv run`.

The first installation needs internet access. The committed `uv.lock` and `frontend/pnpm-lock.yaml` keep dependency resolution repeatable.

## 5. Start the app

```sh
uv run uvicorn trippilot.api:app --host 127.0.0.1 --port 8000
```

Leave that terminal running. Open **http://127.0.0.1:8000/** in your browser. API documentation is at **http://127.0.0.1:8000/docs**; health is at **http://127.0.0.1:8000/api/health**. Stop the server with **Ctrl+C**.

Use the same host spelling each time (`127.0.0.1` rather than switching to `localhost`) because browser drafts and active references are stored per origin.

## 6. Try the complete workflow

Use public, fictional travel plans for testing, not sensitive booking details:

> Barcelona on November 25, 2026. Visit Casa Batlló at 10:00 for 90 minutes, then have lunch at El Nacional at 12:30 for an hour. Use only these two stops.

1. Choose **Build my day plan**. The app extracts your plan, then starts place/travel checks automatically.
2. If a location is ambiguous, choose the intended provider-listed result. The final choice resumes checking automatically.
3. Review the route estimate under the departure stop. **Open directions** opens Google Maps for those confirmed coordinates.
4. Edit a stop with the pencil and choose **Save & check** to resolve its location and update timing/map data.
5. Choose **Save trip**, name it, and open **My trips**. Reopen, rename, duplicate, or delete/undo it there.
6. After changing a saved itinerary, choose **Save changes**. These saves are explicit; local draft recovery is separate.

A new draft can be requested with a prompt such as “Plan a relaxed day in Barcelona on November 25, 2026, with architecture and a long lunch.” Model outputs vary. A valid app response may include a clarification or unresolved place; it should not invent provider results to make the demo succeed.

## 7. Verify your installation

```sh
uv run pytest -q
pnpm --dir frontend build
```

The pytest suite mocks model/provider responses and runs without API keys. It checks application behavior, not the quality of live model outputs. Live planning needs valid keys, internet access, and provider quota.

## Frontend development

Run the Python backend above in one terminal. In a second terminal at the project root:

```sh
pnpm --dir frontend dev
```

Open the URL Vite prints. Its `/api` proxy points to Python on port 8000. This gives frontend hot reload. To see frontend edits on port 8000 instead, rerun `pnpm --dir frontend build` and refresh the browser.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Command not found | Install that prerequisite and reopen the terminal; check your PATH. |
| Engine/version error | Use Node 24 and pnpm 11.25.0, then reinstall with the frozen lockfile. |
| Front page is 404 | Build `frontend/dist` **before** starting Python. Restart Python after the first build because the static mount is configured at startup. |
| Address already in use | Stop the other local server, or use another backend port. If using Vite, update its API proxy to match. |
| Missing/invalid API key | Check `.env` in the project root and restart Python. Check billing/quota in the provider account. |
| Location not found or multiple branches | Supply the full place name/address, or select a listed candidate. The model cannot guarantee a match. |
| Time remains missing | Confirm both route endpoints. If the route is unavailable or the proposal crosses midnight, the app leaves it unresolved. |
| No matching photo | No usable match was found in Wikimedia/Openverse. This does not mean the location failed. |
| Saved trip changed elsewhere | Reopen the latest saved version before saving. Your current working draft is kept; copy any desired edits first. |
| Old frontend after an update | Rebuild the frontend and refresh the browser. |

## Storage and backup

The default data directory is `.data` at the project root. `workspace.sqlite` stores saved trips and `checkpoints.sqlite` stores workflow state. Both may contain travel dates, source text, and bookings. Keep them out of Git.

Stop the app before copying these database files for a simple consistent backup. Set `TRIPPILOT_DATA_DIR` in the process environment to use a different directory. Deleting `.data` removes local saved trips and run history; the app does not offer recovery for that filesystem deletion.

Hosting, phone access over a hosted URL, public authentication, and public request limits are deferred. Keep the current server bound to `127.0.0.1` for local use.
