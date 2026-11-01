# Deployment verification

Checked 2026-11-01.

- Frontend: `npm test` — 4 passed; `npm run build` passed with the committed Modal URL and same-origin API proxies.
- Backend: full suite — 45 passed; follow-up gateway/profile checks — 6 passed after GPU status reporting was added.
- Actual cloud GPU: NVIDIA A10 (L4 was capacity-constrained; one-worker A10G fallback was used).
- Live HTTPS smoke test passed: readiness, password login, Secure cookies, rejected untrusted Origin, protected private media, both text profiles, arbitrary GPU text search and profile-cache clearing.
- Student pipeline passed against the deployed GPU: join/consent, upload, decode, review/approve, embedding/searchable status and withdrawal cleanup. Synthetic test image was withdrawn; the gallery returned to 252 photos.
- Persistence restart check passed: after an explicit stop and redeploy, the original login cookie remained valid, gallery counts and creation timestamps were unchanged, and the instance ID changed.
- Photos, weights, generated credentials and test session cookies are not in Git. Adapter artifact hashes were checked before uploading the original files to the private Modal volume.

Private detailed reports are generated under ignored `integration-checks/`. No Vercel project exists yet: the repo contains the correct backend proxy URL, but its actual frontend origin must be registered after Vercel creates it. See DEPLOYMENT.md.
