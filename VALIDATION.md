# Deployment verification

Checked 2026-11-01.

- Frontend: `npm test` — 4 passed; `npm run build` passed with the committed Modal URL and same-origin API proxies.
- Backend: full suite — 45 passed; follow-up gateway/profile checks — 6 passed after GPU status reporting was added.
- Actual cloud GPU: NVIDIA A10 (L4 was capacity-constrained; one-worker A10G fallback was used).
- Live HTTPS smoke test passed: readiness, password login, Secure cookies, rejected untrusted Origin, protected private media, both text profiles, arbitrary GPU text search and profile-cache clearing.
- Student pipeline passed against the deployed GPU: join/consent, upload, decode, review/approve, embedding/searchable status and withdrawal cleanup. Synthetic test image was withdrawn; the gallery returned to 252 photos.
- Persistence restart check passed: after an explicit stop and redeploy, the original login cookie remained valid, gallery counts and creation timestamps were unchanged, and the instance ID changed.
- Photos, weights, generated credentials and test session cookies are not in Git. Adapter artifact hashes were checked before uploading the original files to the private Modal volume.

Private detailed reports are generated under ignored `integration-checks/`. Vercel production is live at https://iiti-gallery.vercel.app. The exact origin is registered in the Modal runtime secret. End-to-end checks passed through Vercel, including Secure-cookie login, rejection of untrusted origins, protected media, both GPU search profiles, arbitrary queries, and the full student upload/review/embed/withdraw flow. The gallery returned to 252 photos after test cleanup. The production frontend was checked for connected-backend configuration and horizontal result ordering. GitHub is connected for automatic frontend deployments from main. See DEPLOYMENT.md.

## Open gallery update

The public deployment now permits anonymous gallery/status/media/search and base/campus profile comparison. Moderation, tag edits, managed uploads, hiding/deleting photos and event settings still require organizer authentication. The updated backend suite passes 46 tests, including explicit anonymous-access and protected-management checks; frontend routing/build tests remain 4 passed.
