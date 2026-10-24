# Codex Cloud — single minimal ClipNest verification job

Repository kawakaze430/Fev-movie on main. Read AGENTS.md, delivery/ENGINEERING_H03.md, README.md, and this file.

The verified workflow run at commit 859635044a89fca2631fa03473d57029367cf8e5 passed 50 Python tests, the TypeScript build, public-data audits and 19 Playwright checks. DO NOT rerun already-passing steps to burn limited access. Read the latest Actions status first.

The genuine remaining task is a one-time PRIVATE import of actual Telegram files already checked out at root:
- messages.html, messages2.html, messages3.html, result.json and photos/
- Do not ask for ChatExport ZIP; the 32 MiB transfer limit is irrelevant to the GitHub checkout.
- Run the prepared helper from project root using a private directory OUTSIDE Git:
  python scripts/import_repository_export.py --source . --private-dir /tmp/clipnest-private --channel-id fev-one --channel-name "Fev Source"
- If it fails, diagnose only this importer and fix relevant code directly on main, never open a PR/new branch.
- Read private import report ONLY to report aggregate counts: messages, unique movies, links, posters, duplicates, missing fields and importer issues. Do not print or commit raw URLs, filenames carrying personal data, or private output.
- Do not publish imported movie records: distribution/poster rights have not been reviewed.
- If CI for latest main is failing, fix only the failing step and verify it in GitHub Actions.
- Do not spend AWS credits, configure accounts, write unrelated features, install on Windows or run Colab/Antigravity.
- Return verified counts, exact exit codes, latest main SHA, blockers, and link to newest clipnest-source ZIP artifact from GitHub Actions.

After that, STOP. All source coding outside true cloud/external blockers is owned by ChatGPT/GitHub workflow.
