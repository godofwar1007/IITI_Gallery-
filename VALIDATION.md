# Source publication validation

Checked 2026-11-01 before the initial source push:

- Frontend: `npm ci --ignore-scripts`, `npm test` (3 passed), `npm run build` passed.
- Backend: all 42 tests passed in the clean repository checkout using the existing Python environment and private `GALLERY_TEST_SEED` export. Photo/model artifacts are not committed.
- Publication inventory excludes photos, binary embeddings, model weights, databases, previews, local environments, cloud tokens and generated logs.
- Git-staged adapter config and README hashes match the original checksummed artifacts. Git attributes preserve those bytes across platforms.
- Missing backend produces an explicit frontend setup state; no fake gallery results are generated.

This validates source/build behavior, not a live Vercel/Modal deployment. The user will connect Vercel next. Backend hosting, single-origin gateway routing, authenticated public settings, durable storage and end-to-end proxy/upload verification remain the next phase.
