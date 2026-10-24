# ClipNest — Telegram-to-movie discovery project

## Verified facts
- Repository: kawakaze430/Fev-movie (target branch main).
- This repository contains an existing Telegram export at the root: messages.html, messages2.html, messages3.html, result.json, photos, and related exported assets.
- React 19 / TypeScript / Vite catalog source is now included, copied from the earlier tested telegram_to_web starter.
- The deployed frontend reads only public/data/movies.json, which currently contains **fictional demo** entries and original abstract artwork.
- Actual imported history has not yet been processed, rights-reviewed, or published.
- AWS deployment has not been verified.

## Features
- Responsive poster gallery, search, filtering by genre/year/channel/quality, watchlist and external link viewer.
- Browser-based recommendation shelf, with optional Python backend Lambda API.
- Multi-channel Telegram HTML ZIP importer with private-by-default outputs, source IDs, deduplication, metadata uncertainty and approval-gated publication.
- npm, Python unit tests, Playwright, Amplify build, and public-data validation.

## Start
    npm ci
    npm run dev

## Verify
    python -m pip install -r requirements.txt
    python -m unittest discover -s tests/python -v
    python scripts/validate_public.py
    npm run build
    python scripts/validate_public.py --site dist --built

GitHub Actions on main runs these checks and produces a source-only downloadable ZIP artifact after each run. It does not include raw Telegram export files.

## Import data securely
Do not publish real records or raw external URLs without evidence of distribution rights.
Use the importer in an external private directory:
    python -m importer import /private/channel.zip --private-dir /private/catalog --channel-id channel-one --channel-name "Channel One"
See docs/IMPORTING.md (when present) for publication and review details.

The current root export must stay out of public/ and dist/. Since the original export was previously committed to a PUBLIC repository, set the repository private and assess removal of old Git history. A .gitignore file cannot undo publication.

## AWS
Amplify can host the frontend (build output dist). The Python recommendation API needs separate API Gateway/Lambda deployment; the static site works without it. Configure VITE_RECOMMENDATIONS_API_URL only when the API is ready, including CORS. No AWS account/credits/keys are required to build locally.

For next actions, read AGENTS.md, CODEX_NEXT_PROMPT.md and delivery/ENGINEERING_H03.md.
