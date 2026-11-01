# Fieldnotes — a searchable workshop gallery

**Current scope is the local presenter demo. Start with `QUICK_DEMO.md` and `DEMO_STATUS.md`.** Public-event deployment and both-encoder training plans are paused. R1 received-raw cleanup is now fixed in source. The sections below retain the earlier application/deployment context; they are not the active work plan.

A photo-led presenter gallery, mobile student upload page, private moderation queue, and matching SigLIP 2 Giant backend. The user-supplied **120-photo real embedding export** is the seed input. There is no external vector database or frontend build/CDN dependency.

## What is implemented

- Responsive masonry gallery, collection filters, full-photo dialog, arbitrary text search with live inference, prepared search chips, scores, photo similarity, query-photo upload, photo maths, Unicode-safe tags/hybrid search and a fixed-basis embedding map.
- Separate mobile consent/join/upload page; phone JPEG compression, byte progress, safe retries, own submission status and withdrawal. One photo initially; organizers can open a three-photo wave.
- Private review workspace with multi-organizer revision checks, explicit selection/approve/reject/hide, intake controls and queue counts. Unreviewed images never enter presenter search/media/map.
- Strict ZIP/checksum/model import; one serialized SQLite owner; durable received uploads/jobs; supervised decoder processes, byte/pixel/time limits, duplicate content with independent consent records, restart reconciliation and immutable NumPy search snapshots.
- Real QR generation on the organizer side, decoding test and HTTP gateway stress tool. The QR points to the configured student origin; it is not an independent hosted service.
- Seed-only offline viewer: same presenter interface, only prepared query vectors, no GPU/Torch required. It does not embed new photos or arbitrary text.
- Linux GPU VM Docker Compose/Caddy deployment configuration, HTTPS public student route and loopback-only organizer listener.

Optional incremental mirroring of attendee assets is **not included** in this first release. The offline fallback deliberately uses the seed collection only, avoiding stale attendee-withdrawal visibility. No paid cloud deployment has been performed.

## Run locally (Python 3.11 or 3.12)

Create a dedicated environment, then:

```text
python -m pip install -e ".[model,test]"
fieldnotes prepare-model --model <local-checkpoint-directory>
fieldnotes serve --seed <complete-Colab-export.zip> --data <local-unsynchronized-data-directory> --model <local-checkpoint-directory> --mode live
```

The model downloads several GB only during `prepare-model`. Runtime reads the pinned local checkpoint with networking disabled. The model must match `google/siglip2-giant-opt-patch16-384`, revision `a713301b217d38485fb2204c808367d10bc3cc40`.

On first startup an organizer password is printed once, or provide `GALLERY_ADMIN_PASSWORD` in the environment before startup. Only its Argon2 hash is stored in the private runtime directory. The event code defaults to `INDORE26`; set `GALLERY_EVENT_CODE` before first initialization for a real workshop. Existing credentials/code remain attached to that event directory across restarts.

- Presenter: `http://127.0.0.1:7861/presenter`
- Moderator: `http://127.0.0.1:7861/moderator`
- Student preview: `http://127.0.0.1:7860/e/workshop?code=INDORE26`

Loopback links/QRs work on the host only. Student phones need the deployed public HTTPS origin. **Do not forward port 7861 publicly.** The default runtime data is stored outside this checkout under `SearchableGallery/fieldnotes-v1` in your local application-data directory; specify `--data` for separate events.

For a no-model preview use `--mode prepared` (the default); live-photo intake is paused and only exact prepared queries/photo-vector similarity work. The interface labels this mode. Start with `--mode live` for actual student processing.

`fieldnotes offline --data <existing-event-data-directory>` creates a separate seed-only database/viewer on port 7862. It copies only the reusable seed package, never the live event database/photos. First-run organizer credentials for that separate viewer follow the same environment/password rule. If using an independent laptop, supply `--seed <export.zip>` as well. Validate this offline installation before the event, not after the connection fails.

Keep runtime DB/photo data outside OneDrive/Dropbox/NFS. The source checkout can remain in OneDrive. On Linux protect data directories with mode 0700. The model needs a GPU for qualified workshop performance; CPU fallback is slow and has not been qualified as a live event path.

## Deploy to one Linux cloud GPU VM

Choose a VM/provider/spending window first. Candidate: one L4, persistent attached block disk with local filesystem, approximately 8 vCPU and 32 GiB RAM. These allocations are planning targets, not a measured cloud sizing guarantee. Free Colab is for seed preparation, not the sole live server.

1. Install NVIDIA driver, Docker Engine/Compose and NVIDIA Container Toolkit; verify container GPU access. Configure a hostname whose DNS points at the VM. Open 80/443 and restrict SSH as appropriate; do not open 7860/7861 to the internet.
2. Copy this source folder to the VM. Mount persistent block storage at `/srv/fieldnotes`; do not substitute an NFS/object-storage mount for the SQLite data directory.
3. Create `/srv/fieldnotes/data` and `/srv/fieldnotes/models`, owned by UID 10001. Copy the verified Colab ZIP to `/srv/fieldnotes/seed.zip`, readable by that UID. Protect attendee data from other host users.
4. Copy `.env.example` to `.env`, choose a strong organizer password/event code and set the real hostname. Keep `.env` out of version control.
5. `docker compose build`
6. `docker compose run --rm -e HF_HUB_OFFLINE=0 app prepare-model --model /models/giant`
7. `docker compose up -d`
8. Verify TLS and `/health/ready`, then create organizer forwarding:

```text
ssh -N -L 17861:127.0.0.1:7861 <operator>@<vm-address>
```

Open `http://127.0.0.1:17861/presenter` or `/moderator` locally and sign in. Each organizer uses their own browser session/forward. The QR dialog uses `https://<configured-hostname>/e/workshop?...`. If the venue blocks SSH, configure and test a secure organizer access alternative before the event; do not improvise by exposing the raw port.

Compose uses Linux host networking so the Caddy proxy can reach the app's loopback student listener. This deployment configuration has not been executed on a cloud VM in this task. Test it on the selected host, including TLS, firewall, storage mounts, abrupt restart and real phones before inviting attendees.

## Tests and limits

```text
python -m pytest -q
```

Integration tests use deterministic **explicit test doubles** for new inference to exercise failure cases. Prepared seed retrieval uses the actual exported vectors. Separate real HTTP/real-checkpoint tests are recorded in the QA report; these are distinct from mocked tests.

The stress tool requires the running event have **no existing student photos or queued jobs** and an organizer password in `GALLERY_ADMIN_PASSWORD`:

```text
python tools/stress_gateway.py --clients 500 --photos 900 --concurrency 16
```

It joins 500 cookie-isolated participants, opens the actual student URL, generates/decodes the QR, stresses QR responses/status polls, uploads generated ~300 KiB images, approves them through the API, drains the real configured model queue and withdraws its own generated fixtures. This can occupy the GPU for several minutes. It does not send emails or publish images externally. Run against a disposable rehearsal event; do not run against a real workshop in progress.

Results describe **loopback HTTP**, not public proxy/TLS/campus Wi-Fi, and do not guarantee that 500 physical phones will work in a hall. Browser visual QA was blocked by the browser permission gate in this session; responsive CSS, JS syntax and APIs were checked, but no visual browser pass is claimed.

## Event operation / deletion

Open the student page via the public QR; receive one photo first. Two moderators approve safe samples. Received, reviewed, processing and searchable are separate statuses. Keep the displayed search grid still while speaking; refresh when the new-photo notice appears. Scores are cosine rankings, not probabilities.

If internet disappears, switch to the separately prepared local seed viewer. It supports stored query vectors only. No local encoder means fresh cloud uploads/new text cannot be processed or displayed while disconnected.

Finish from Workshop settings by explicitly typing `DELETE STUDENT PHOTOS`. Intake closes, student sessions are revoked, attendee contributions disappear immediately, and unreferenced attendee files/vectors are purged. In-flight jobs cannot restore visibility. Cleanup continues while the app is running; verify completion before shutting it down. Rejected/withdrawn raw files and unreferenced decoder outputs are also cleaned. No automatic cloud backup/mirroring of attendee photos is created.

The current policy requires operator-controlled finish/deletion after the event; an unattended scheduled retention service is not claimed. Inspect any manual exports/provider snapshots separately. Stopping/terminating a GPU instance is not proof of deleting persistent disks or ending storage charges.

See `QA_REPORT.md` for measured checks and remaining venue/cloud qualification work.
