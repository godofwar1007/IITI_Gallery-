# Fieldnotes campus demo

Open PowerShell in this folder, then run:

```powershell
.\Demo.ps1 -OpenBrowser
```

Presenter: http://127.0.0.1:7861/presenter

The default is `campus-run2`: the pinned SigLIP 2 Giant image tower plus the unmerged run-2 TEXT adapter. No prototypes or tag blending are applied by default. Both profiles share one model in memory. Image vectors are preserved. Allow the GPU to warm up before arbitrary searches; saved searches work during warm-up.

Use **Campus-tuned search: on/off** above the photos for the before/after comparison. Off uses the base text tower. The switch clears the query cache. **Show scores** shows cosine similarity, not probabilities. Choose **Campus photographs** in the sidebar to restrict the results.

Fallback launch (stop the current server with Ctrl+C first):

```powershell
.\Demo.ps1 -TextProfile base -OpenBrowser
```

CLI equivalent, including environment override:

```powershell
$env:GALLERY_TEXT_PROFILE='campus-run2'
.\.venv\Scripts\python.exe -m gallery.cli serve --demo --mode live --text-profile campus-run2
```

Event data: `%LOCALAPPDATA%\SearchableGallery\demo-campus-run2`. The original `demo-v2` data is retained. The immutable source dataset and original training adapter are never changed. The copied adapter and its verified manifest are in `models\adapters\campus-run2`.

## Import / rebuild

Stop the servers before these commands. These are already completed on this laptop.

```powershell
.\.venv\Scripts\python.exe -m gallery.cli import-campus --demo --folder 'C:\Users\PARTH\OneDrive\Desktop\work\AIML\ML_workshop_data'
.\.venv\Scripts\python.exe -m gallery.cli prepare-queries --demo
.\.venv\Scripts\python.exe tools\build_standalone_preview.py
```

Import selects only active, demo-safe, non-people-flagged, confirmed records. Content hashes prevent duplicate assets. Canonical bytes follow EXIF correction, RGB, max 1024px, JPEG quality 95. Metadata preserves final reviewed visual captions, aliases (subplace aliases need explicit evidence), and supplied source notes. CREDITS.md records imported web-photo attribution.

Prepared query rebuild generates BOTH text profiles, updates only prepared text vectors/checksums in the 120-photo seed export, and writes `seed\gallery_demo_campus.zip` containing the whole visible gallery with existing image vectors. It does not re-embed images. Rebuild the standalone file after changing those exports.

## Offline backup

Open `Gallery_Preview.html` directly for a self-contained full-gallery backup. It supports saved queries in both profiles, browsing, similarity and the map. Arbitrary new text still requires the live model. It makes no external asset requests.

Or start a separate prepared viewer:

```powershell
.\.venv\Scripts\python.exe -m gallery.cli offline --demo
```

Open http://127.0.0.1:7862/presenter. It uses the full-gallery export, defaults to campus-run2, and does not load the GPU. It can run alongside live mode. If you rebuilt the export after creating an offline viewer, use a fresh `--data` event directory to avoid a stale offline database.

## Testing / evaluation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node tools\test_preview_runtime.cjs
.\.venv\Scripts\python.exe -u tools\integrate_run2.py
```

The integration checker imports idempotently, builds both prepared spaces, compares 5 seed + 5 campus image vectors under both profiles and against storage, checks text drift, checks ranking/cache changes, and fingerprints source files before/after. It requires the server to be stopped. Outputs: `integration-checks\real_gpu_checks.json`, `DEMO_QUERIES.md`, `CREDITS.md` and the test logs. The full-gallery demo query sheet is a qualitative check, not held-out accuracy: the gallery contains training and test photos. The adapter manifest records the earlier held-out training metrics.

For your own labelled held-out evaluation:

```powershell
.\.venv\Scripts\python.exe -m gallery.cli evaluate --demo --mode live --text-profile base --queries eval\test_queries.csv --output eval\base
.\.venv\Scripts\python.exe -m gallery.cli evaluate --demo --mode live --text-profile campus-run2 --queries eval\test_queries.csv --output eval\campus-run2
```

The evaluator excludes configured prototype references. Read DEMO_QUERIES.md for query limitations; named-place retrieval is not perfect, and exact person counting is not guaranteed.

## Optional new photos / cleanup

Add photos from the laptop using **Add photos** or **Take a photo**. Phone uploads are optional and need a reachable network address; the localhost QR is only reachable on this laptop. Student submissions require organizer review before indexing.

After stopping BOTH live and offline viewers, delete this event's local gallery data only if intended:

```powershell
.\.venv\Scripts\python.exe -m gallery.cli delete-data --confirm-delete
```

This leaves the source dataset, model snapshot, adapter, bundled exports and standalone backup intact. It deletes the event database and imported event files. Keep those exports private if you also want to retain no photos after a workshop.
