# AI Studio implementation

Started 2026-11-22 from a5207d6, branch codex/ai-slides-render-free.

## Architecture

FastAPI/Jinja2 serves an isolated Studio for teacher, admin and super_admin. Browser parses documents and generates editable PPTX. PostgreSQL stores owned decks, immutable revisions, step leases and quota reservations. OpenRouter uses separate configuration and zero-priced allowlisted models.

Studio tables use independent SQLAlchemy metadata. Application startup never creates them. An explicit migration command is required after database backup and production provider confirmation. Feature flag defaults off.

## Work order

- Validate browser libraries and native animation compatibility with a five-slide fixture.
- Implement isolated schemas, persistence, quotas, step guards and provider checks.
- Build three input modes, PDF page selection, source review and field locks.
- Connect planning, authoring, preview, editing, revisions and browser export.
- Add resource links, physics simulations, source credits and administration.
- Verify offline API regressions, build, browser flow and PowerPoint compatibility.

## Audit

Checkout uses FastAPI, synchronous SQLAlchemy sessions, global CSRF dependency, shared Jinja templates and static vanilla JavaScript. No Render blueprint is present. Render deployment branch/build/start settings remain unverified. Local DATABASE_URL identifies Neon, production is unverified. A separate Studio OpenRouter key is configured locally and was tested live. No committed tests existed at baseline. Syntax check passed for 166 application Python files.

Windows Node runtime is exclusively docker exec codex-skill-env, Node 22.23.5. Python uses the existing project .venv. Docker /workspace is persistent and project sources are copied for builds. Desktop PowerPoint is installed. Native motion remains gated until actual Slide Show verification.

## UI direction

Reuse Be Vietnam Pro and the existing Smart TKB shell. Use a pale blue workspace, navy typography, blue actions and white document canvas. A left library pane, focused lesson form and large slide preview organize authoring. Advanced fields expand on demand. Source selection and teacher confirmation stay adjacent to their inputs.
