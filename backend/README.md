# Backend: deploy to Modal

This folder contains the Python application and GPU model runtime. **Do not import this folder as a separate Vercel project.** The deployed GPU backend is on Modal; only the repository-root frontend build belongs on Vercel.

Live website: https://iiti-gallery.vercel.app

Backend endpoint: https://ppp3work--iiti-fieldnotes.us-east.modal.run

See [DEPLOYMENT.md](../DEPLOYMENT.md) for deployment, persistence, authentication boundaries and the frontend proxy. See [ARTIFACTS.md](../ARTIFACTS.md) for the private model, adapter and gallery exports required to run locally.

GitHub's `Backend checks` workflow runs tests for API/frontend contracts, adapter integrity validation, prepared-vector validation and transaction persistence without requiring private photos or a GPU. The full private-artifact suite and live GPU smoke checks are documented in [VALIDATION.md](../VALIDATION.md).
