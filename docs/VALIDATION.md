# Validation evidence — 2026-10-23

Verified in this cloud instance with Node.js 24.19.0, Python 3.12.14, Pillow 12.3.0, Vite 7.3.7, Playwright 1.64.1, and Chromium 154.0.8037.57 on Debian 13.

| Check | Result |
| --- | --- |
| Fresh `bash scripts/setup.sh` | Passed: frozen npm installation, pinned Python dependency, tests, public validation, production build |
| Python importer suite | 45 passed; no skips |
| Public artifact and Git boundary unit tests | 5 passed; no skips |
| Large archive transfer tests | 25 passed; exact split/reassembly, hashes, private paths, corruption and overwrite rejection |
| Standalone AWS deployment tests | 14 passed with mocked AWS/HTTP operations; no live AWS deployment claimed |
| CloudShell deployment dry run | Passed against the actual built demo ZIP with explicit `--allow-demo`; no AWS calls or credentials required |
| TypeScript and Vite production build | Passed; JavaScript approximately 214 kB / 67 kB gzip |
| Public source and built artifact validation | Passed: 15 fictional, cleared demo records; permitted original art; no private artifacts |
| Browser suite against production build and preview | 21 passed, including desktop and mobile visual comparisons |
| Screenshot baselines | Generated from this implementation, visually reviewed, then compared in a separate run without updates; all displayed poster images loaded |
| `npm audit --audit-level=low` | Passed: zero reported vulnerabilities at check time |
| Saved development startup | Passed: HTTP 200 catalog, 12 initial cards → 15 after load more, two editions in a real demo detail dialog, zero browser page errors |

The importer tests use authored synthetic archives. They exercise traversal, symlink and case-collision rejection; expansion quotas; every message page and service message; direct poster and document metadata; repeated link labels; numeric movie names; explicit quality; missing and ambiguous fields; channel deduplication; idempotent imports; injected failure rollback; publication allowlists; and licensed image re-encoding and cleanup. They do not assert that an inaccessible real archive was imported.

Browser tests cover search, combined filters, sort, unknown quality without size inference, details and links, keyboard focus, watchlist persistence, empty/loading/failure states, mobile overflow, unsafe URL and private-field rejection, text escaping, and screenshots. Functional cases use synthetic intercepted data; visual cases use the checked-in demo catalog. See `tests/e2e/README.md` for browser pinning and how to reproduce the checks.

## Outstanding external prerequisites

- **Actual archive:** the attachment transfer failed because `ChatExport_2026-10-23.zip` exceeds the tool's 32 MiB limit. No authorized private archive path, storage URI, or `TELEGRAM_PRIVATE_DIR` value was available. Actual file/message totals, imported movies, poster matches, and real ambiguity reports are therefore unverified. Provide an accessible authorized private path to run the completed importer.
- **Content rights:** the user explicitly selected “Keep all imports private pending review.” No real channel content or poster has been cleared, published, or put in Git. The supplied public dataset is fictional. Future publication needs an explicit record/link allowlist and separate poster evidence.
- **AWS:** the identity manifest contains no connections; an AWS profile selector alone does not establish credentials. No Amplify app, account/region selection, GitHub App connection, AWS build, live URL, DNS/TLS, or external response headers have been verified. Deployment configuration and an external verification command are provided in `docs/DEPLOYMENT.md`.
- **Cloud configuration:** `install_script`, `start_skill`, and the `TELEGRAM_PRIVATE_DIR` path requirement were saved to an environment configuration draft. Saving did not apply or publish a new environment version. Review and save the draft in environment settings, then publish the environment when desired. Restoration in a new task has not been tested.
- **Remote CI:** a GitHub Actions workflow is supplied. Its remote execution is distinct from the local passing checks above and is not claimed here.

## Paths to finish the blocked operations

`scripts/archive_parts.py` transfers the original large archive as verified 30 MiB binary parts; it does not discard media or message pages. See `docs/IMPORTING.md` for local commands. Reassembly and the real import remain unrun until every part or an accessible original ZIP is supplied.

`scripts/deploy_amplify.py` can run in signed-in AWS CloudShell without connecting this coding environment to AWS. It uses the existing AWS CLI identity, creates or reuses an Amplify manual-hosting app, applies headers, uploads a validated public ZIP, waits for the job, and verifies public HTTPS bytes and headers. It rejects demo records by default and supports an explicit preview opt-in. AWS calls in the test suite are mocked; CloudShell execution and public browser verification remain external prerequisites. No live URL is available yet.
