# Private runtime artifacts

Keep these outside Git. The repository is source-only; uploading it does not publish the photo collection or start GPU hosting.

## Base model

- Model: `google/siglip2-giant-opt-patch16-384`
- Revision: `a713301b217d38485fb2204c808367d10bc3cc40`
- Snapshot folder must contain a `REVISION` file with exactly that revision.
- Use `python -m gallery.cli prepare-model --model /path/to/siglip2-giant` from `backend/` to prepare the pinned snapshot, or copy the existing verified cache.

## Campus adapter

Copy the original, unchanged `adapter_model.safetensors` from run `20261031_143330_run2/lora_adapter/` into `backend/models/adapters/campus-run2/`. The accompanying `adapter_config.json` and `README.md` must match the hashes in `manifest.json`; copy the originals if needed. Never merge or retrain the adapter as part of deployment.

The committed manifest records hashes, model identity, text-only targets and historical held-out metrics. Its source-run field is a portable run ID. The weights are not stored in Git. Campus startup refuses missing or corrupt artifacts with a message; `--text-profile base` remains the fallback.

## Gallery export

Use the verified `gallery_demo_campus.zip` full-gallery export or the original `gallery_data_120_siglip2_giant.zip` seed export. Provide it explicitly using `--seed`, or put it under `backend/seed/` (ignored by Git). It contains private photos, normalized image vectors and profile-labelled prepared text vectors.

The runtime validates the model revision, dimensions, normalization and archive checksums. Stored image vectors stay unchanged when switching text profiles.

## Backend host

Store model/adapter files, gallery exports, the event database and uploaded photos in durable storage. The current SQLite/in-memory broker design needs one owning backend process; do not autoscale multiple independent writers against the same database or treat ephemeral container disk as persistence. The GPU worker must be warmed for the workshop.

Never deploy password-free `--demo` mode publicly. Configure organizer authentication, HTTPS public origin, secure cookies and the presenter/student gateway before connecting the Vercel proxy. The authenticated gateway is now deployed on Modal; see DEPLOYMENT.md for the endpoint and exact-origin Vercel connection step.

No credentials, cloud tokens or passwords belong in this repository. `.env.example` contains only an empty frontend backend-address setting.
