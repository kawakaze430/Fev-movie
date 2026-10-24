# ENGINEERING H03 — ClipNest direct-main migration

Canonical repository: https://github.com/kawakaze430/Fev-movie
Target: main (no PR or new branch)

## Current state
IMPLEMENTED / NOT FULLY TESTED
- React movie-catalog app and fictional demonstration dataset.
- Multi-channel Telegram HTML importer and public-data gate.
- Browser-local watchlist and metadata recommendation shelf.
- Separate Python recommendation API and unit tests.
- GitHub Actions CI, source artifact ZIP packaging, Amplify frontend build config.

BLOCKED / EXTERNAL
- Legal rights review for actual full-length movie links and poster reproduction.
- Real import of checked-in Telegram root export into approved private storage.
- Public repository includes raw exported media: must be made private; history remediation must be decided.
- AWS Amplify connection, Lambda deployment and live HTTPS/domain verification require AWS account authorization.

NOT YET VERIFIED IN THIS SESSION
- npm ci / TypeScript production build on Fev-movie.
- All Python tests and Playwright suite after migration.
- Real 3,000+ record count, link correctness and poster-to-message joins.
- Lambda on AWS and live website URL.

## Important
Do not confuse this repository with kawakaze430/telegram_to_web: it supplied the previously tested starter code. The real Telegram export is in Fev-movie. The original 32 MiB attachment limit is irrelevant to files that Codex checks out via GitHub.

The public site intentionally remains a demo until a rights-cleared publication pass succeeds.

## Minimum next Codex Cloud job
Read CODEX_NEXT_PROMPT.md. Run only missing tests and the private import inventory. CI is responsible for routine builds and the source-only ZIP. Report counts and stop, rather than adding new features.
