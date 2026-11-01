# Modal backend + Vercel frontend

## Backend endpoint

https://ppp3work--iiti-fieldnotes.us-east.modal.run/presenter

The presenter requires an organizer password. It is stored in the private Modal secret `iiti-gallery-runtime-v1`, not in Git. The operator's local credential file is outside this repository. Student access uses the separate workshop code and consent flow; it cannot access presenter media or organizer APIs.

The model uses the pinned SigLIP 2 Giant image tower and the unchanged run-2 text adapter. One GPU worker maximum (L4 preferred, A10G fallback when L4 capacity is unavailable), zero minimum, 120-second idle scale-down, 300-second request and startup limits. A cold visit can take longer because the GPU/model must start. Keep it warm by opening the presenter before the workshop. GPU and persistent-volume usage are billable.

Volumes: `iiti-gallery-assets-v1` for the cached checkpoint, adapter and verified gallery export; `iiti-gallery-event-v1` for the event database, imported seed files and new uploads. The database has one owner. Deployment updates use **recreate**, not overlapping rolling workers. Database transactions trigger durable volume commits; deleting a deployment does not delete the volumes.

## Deploy the frontend

1. Import this GitHub repository into Vercel.
2. Root Directory `./`, Framework **Other**, leave Output Directory unset.
3. The build reads the public backend address from `frontend/backend.json`. Optionally override it with `GALLERY_BACKEND_URL` in Vercel. No Modal token or organizer password goes into Vercel or Git.
4. Deploy and copy the exact Vercel site URL.
5. Allow that origin on the backend using the command below and recreate the deployment. This final connection requires the real frontend URL; it cannot be completed before the Vercel project exists.

```sh
python backend/tools/connect_frontend.py https://YOUR-SITE.vercel.app
python -m modal deploy backend/deploy/modal_app.py --strategy recreate
```

These commands require authorized Modal credentials in the operator's environment or existing CLI profile. Do not paste credentials into source files. The public backend address itself is not a secret.

Before step 5, the direct Modal presenter works. Vercel API routing can reach the backend, but mutating requests from the unapproved frontend origin are deliberately rejected. Once connected, use the Vercel hostname consistently: login cookies are scoped to the site where you sign in. Backend QR links then point to that Vercel origin.

## Recreate the backend

Modal SDK 1.5.5 was used for the initial deployment. Cloud configuration is in `backend/deploy/modal_app.py`; application logic is in `backend/gallery/`.

First deployment only, with the private verified artifacts on the operator's machine:

```sh
python backend/tools/bootstrap_modal.py --gallery /private/gallery_demo_campus.zip --adapter /private/campus-run2 --organizer-file /private/organizer.json
python -m modal deploy backend/deploy/modal_app.py --strategy recreate
```

The bootstrap generates an organizer password if the specified private file does not exist, creates a named Modal secret without printing its contents, uploads the gallery and adapter, and downloads the pinned base model into the assets volume. It does not train anything. Do not put the organizer file under the source checkout.

## Verify / stop

```sh
curl https://ppp3work--iiti-fieldnotes.us-east.modal.run/health/ready
python -m modal app logs iiti-fieldnotes-gallery --tail 30
python -m modal app stop iiti-fieldnotes-gallery
```

The health check should return `ready: true` and `inference: live`. Organizer status reports the active text profile and actual GPU. Stopping the app disables its endpoint; deleting volumes is a separate destructive operation. Normal idle scale-down keeps the endpoint deployed and allows it to start on the next request.
