# Codex Cloud: minimal test-only handoff

Continue ClipNest from main at kawakaze430/Fev-movie. Read AGENTS.md, CODEX_NEXT_PROMPT.md, delivery/ENGINEERING_H03.md and README.md.

You have limited model time. Do NOT create a new branch or PR. Do NOT add cosmetic features, rewrite the UI, or rerun checks that GitHub Actions already passed.

1. Open the latest ClipNest verified build workflow. Identify failures or skipped tests. Reproduce ONLY missing or failed ones, then fix the actual blocker and commit directly to main.
2. In a PRIVATE temporary working directory, inventory the already checked-out root Telegram export. It has messages.html, messages2.html, messages3.html, result.json and photos. The original 32 MiB chat transfer limit NO LONGER blocks this GitHub checkout. Do NOT request the archive again.
3. Safely create a temporary ZIP from extracted Telegram export files if necessary to call the existing Python importer. Parse every message page and preserve poster associations. Record counts of posts, recognized films, links, duplicates and missing fields. Keep original links and private catalog OUTSIDE GitHub and outside public/ and dist/.
4. Verify backend recommendation Lambda handler tests and full integration with React only if CI did not already cover them.
5. If AWS authenticated tools are available, perform read-only deployment preflight; do NOT deploy unreviewed records or spend credits without explicit authorization.
6. Prepare a source-only updated ZIP (or link to GitHub Actions clipnest-source artifact) containing the completed application and tests, excluding raw exports.
7. Return pass/fail/blocked with exact commands, exit codes, verified import counts, repository SHA, and source artifact location.

No local Codex, Windows installs, Colab or Antigravity unless cloud checks are genuinely blocked. Complete this limited batch and STOP.
