# IIT Indore · Fieldnotes Gallery

A searchable photo gallery for the Cynaptics ML workshop. Search with descriptions or campus place names, compare base vs campus-tuned text search, inspect cosine scores, and add photographs through the presenter or optional moderated student upload flow.

## What's in this repository

- `backend/gallery/`: the complete Python/FastAPI application, model broker, importer, catalogue, SQLite storage and canonical frontend source in `web/`.
- `backend/tests/` and `backend/tools/`: application tests and local verification/import tools.
- `frontend/`: dependency-free Vercel static build and backend proxy configuration.
- `backend/models/adapters/campus-run2/`: adapter configuration and checksummed manifest. Weights are a separate private artifact.

The photo ranking is left-to-right across each row, then onto the next row. SigLIP 2 Giant image embeddings stay fixed; the run-2 adapter changes only the text tower. Base text search remains available using the presenter toggle.

## Deploy the frontend on Vercel now

1. Import this GitHub repository into Vercel.
2. Set **Root Directory** to the repository root (`./`).
3. Choose **Framework Preset: Other**. `vercel.json` sets the install and build commands; leave Output Directory unset (the build generates Vercel Build Output API files).
4. Deploy. The committed `frontend/backend.json` supplies the deployed Modal backend address; no environment variables are needed for that address.

This publishes the real UI and routes API calls to the Modal backend. After Vercel creates your site, allow its exact origin on Modal as described in [DEPLOYMENT.md](DEPLOYMENT.md) before signing in through Vercel. No private photos or fake search responses are bundled into the frontend.

To override the committed backend address, add `GALLERY_BACKEND_URL=https://your-backend-host` in Vercel and **redeploy**. The build generates same-origin `/api/*` and `/health/*` proxies so authentication cookies and media links stay on the frontend hostname. Do not add a path, token or username/password to this variable. It is a backend address, not a secret.

The deployed single-origin gateway exposes both protected organizer APIs and student APIs. The original local launcher still serves separate ports. See [DEPLOYMENT.md](DEPLOYMENT.md) for the current endpoint, origin registration, persistent storage and cost controls.

## Build and test the frontend locally

Node.js 22 or newer:

```sh
npm ci
npm test
npm run build
```

Output: `.vercel/output/static` plus `.vercel/output/config.json`. Build output is ignored by Git. The UI source is shared with the backend rather than duplicated.

## Run the backend locally

Python 3.11 or 3.12. The model dependencies are deliberately not installed by the Vercel frontend build.

```sh
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -e '.[model,test]'
```

Provide the private verified gallery export, pinned base snapshot and unchanged adapter weights as described in [ARTIFACTS.md](ARTIFACTS.md), then:

```sh
python -m gallery.cli serve --demo --mode live --seed /path/to/gallery_demo_campus.zip --model /path/to/siglip2-giant --text-profile campus-run2
```

Presenter: `http://127.0.0.1:7861/presenter`. `--demo` is for loopback only and bypasses the organizer login locally. Never use it for the public deployment. On the prepared Windows laptop, `backend\Demo.ps1 -OpenBrowser` uses the local cached assets.

Base fallback: append `--text-profile base`. Once the actual adapter is present and valid, the live presenter can switch between profiles without loading a second model. Image embeddings do not need to be regenerated.

## Test scope

```sh
cd backend
python -m pytest -q
```

Tests requiring photo data skip when the private seed export is absent. Set `GALLERY_TEST_SEED` to its local path to run those tests. Manifest validation and frontend contract tests run without private photo data. Real GPU verification tools require the actual model and adapter, and are not simulated by the unit tests.

The backend suite now passes 45 tests. Live Modal verification also passed GPU search, authentication, student upload/moderation/embedding/withdrawal, and persistence across a full restart. The frontend has 4 passing build/routing tests. Cloud deployment verification is recorded separately in DEPLOYMENT.md and VALIDATION.md.

## Data and attribution

The prepared local gallery contains 120 seed photos and 132 approved campus photos. Photo datasets, embeddings, model weights, generated previews, local databases, logs and credentials are excluded from this source repository. See [ARTIFACTS.md](ARTIFACTS.md) and [campus photo credits](backend/CREDITS.md).

The campus adapter improves named-place search but is imperfect: `pod 1a` can still rank POD-1D; exact people counting is unreliable. Scores are cosine similarity, not probabilities.
