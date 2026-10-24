# AWS Amplify Hosting

This project deploys a static Vite build, not the archive importer. Amplify receives
only `dist/`. Never upload a Telegram ZIP, private import registry, review report,
rights manifest, or raw export to this repository or to Hosting. The included
catalog contains fictional demo records and original artwork. A successful demo
deployment does not establish clearance for imported content.

## Deploy a reviewed ZIP from AWS CloudShell

`scripts/deploy_amplify.py` is standalone: Python 3.9+ and AWS CLI v2 are its only
requirements. It uses your existing signed-in AWS identity, applies `customHttp.yml`
through the Amplify API, uploads the prepared public ZIP, waits for the job, and
checks every deployed file and the HTTPS security headers. It does not need a
GitHub connection or build source in CloudShell. No app is deleted on failure.

The supplied site currently contains fictional demo records because the actual
Telegram archive is still unavailable to the importer. **The script rejects that
demo by default.** All real imports remain private until explicitly cleared for
distribution. For the actual catalog, first import the full archive and publish
reviewed records as described in the root README, then build and validate the
public site. Package the contents of `dist/` as `site.zip`, with `index.html` at the
ZIP root. Never use the Telegram export ZIP as the deployment ZIP.

In the intended AWS account, open **CloudShell**. Upload the deployment bundle
containing `deploy_amplify.py`, `site.zip`, `customHttp.yml`, and `release.json`,
extract it, and enter that folder. With a reviewed **public** catalog:

```sh
python3 deploy_amplify.py --dry-run
python3 deploy_amplify.py --region ap-south-1
```

The default region is Mumbai (`ap-south-1`); override it for another intended
region. Add `--expected-sha256 HEX_DIGEST` using the site ZIP digest from
`release.json` to verify the exact release artifact. Successful execution prints
the app ID, job state, and actual public `https://main.…amplifyapp.com` URL after
checking that all uploaded files are reachable and match the reviewed ZIP.

To validate the currently supplied **fictional demo ZIP only**, without contacting
AWS or changing resources:

```sh
python3 deploy_amplify.py --dry-run --allow-demo
```

Only add `--allow-demo` to a real deployment command if you explicitly want a
labelled demo preview. This never imports or publishes your Telegram history.

If a deployment stops after creating an app, reuse the printed ID:

```sh
python3 deploy_amplify.py --app-id YOUR_APP_ID --region ap-south-1
```

The existing app must be a manually deployed `WEB` app without a Git provider.
Its custom headers are replaced with the supplied configuration. A successful
upload alone is not reported as a verified deployment; the job must succeed and
the public HTTPS artifact/header comparisons must pass. Browser tests against
the resulting URL remain a separate final interaction check.

The AWS identity needs the applicable Amplify create/get/update app, get/create
branch, create/start deployment, and get-job permissions. Identity verification
uses `sts:GetCallerIdentity`. The script never asks for keys or logs the temporary
signed upload URL. In this coding environment no usable AWS identity is currently
configured, so no real AWS deployment has been executed here.

## Local release check

Use the pinned Node 24 toolchain and Python 3.12. In the repository root:

```sh
npm ci
python -m venv /tmp/frame-release-venv
/tmp/frame-release-venv/bin/python -m pip install -r requirements.txt
/tmp/frame-release-venv/bin/python -m unittest discover -s tests/python -v
/tmp/frame-release-venv/bin/python -m unittest discover -s scripts -p 'test_*.py' -v
/tmp/frame-release-venv/bin/python scripts/validate_public.py
npm run build
/tmp/frame-release-venv/bin/python scripts/validate_public.py --site dist --built
python scripts/audit_git.py
```

Run the browser tests documented in the root README before release. Screenshot
baselines should be reviewed visually and updated intentionally; a newly accepted
baseline is not evidence of a comparison against an earlier design.

The GitHub workflow runs functional browser tests with Playwright's installed
Chromium. Screenshot comparison tests are explicitly excluded there because the
checked-in visual baselines were captured with the local system Chromium. Run
visual comparisons with that same browser/version, or intentionally regenerate
and review baselines for a new pinned browser. A checked-in workflow is deployment
preparation; its remote result is unknown until a GitHub Actions run completes.

## Connect the GitHub repository

1. Sign in to the intended AWS account and region. Open **AWS Amplify → Deploy
   an app → GitHub** and authorize the AWS Amplify GitHub App only for
   `kawakaze430/telegram_to_web`.
2. Select the release branch (normally `main`). Use the checked-in `amplify.yml`
   and the managed Amazon Linux 2023 build image. The build installs Node 24 and
   Python 3.12.14 with the image's nvm/pyenv tools, then uses a temporary Python
   environment. These provisioners must be available in the selected build image;
   their first execution in AWS remains part of external deployment verification.
   No application secrets are required for
   the static demo site.
3. Keep the app root at the repository root and output directory at `dist`.
   Disable public preview branches unless their content has also passed review.
   The public site has no server-side archive upload route.
4. Save and deploy. Record the app ID, branch, region, build job ID, and resulting
   `https://…amplifyapp.com` URL outside the private archive. If attaching a domain,
   configure DNS and verify the issued TLS certificate before announcing it.

At preparation time no usable AWS identity is configured and the AWS CLI is not
installed. No Amplify app or deployment has been created or externally verified.
All actual channel imports are to remain private pending rights review, as
requested; the fictional demo catalog is the only supplied deployable dataset.

The console user needs permission to create/manage the intended Amplify app and
authorize its GitHub connection. An organization administrator may need to approve
the GitHub App. Grant access only to this repository. Static Hosting does not
require an IAM service role for an SSR backend; do not attach administrator
credentials to the build. No AWS access key belongs in source or frontend
environment variables (Vite variables are embedded in public JavaScript).

`customHttp.yml` supplies CSP and other response headers. This app uses local
artwork/fonts and external links that open in another tab. Third-party embeds and
inline scripts are intentionally unsupported. Confirm the headers in the deployed
responses; local Vite hosting does not apply Amplify's configuration.

## Verify the deployed site

Use the actual URL returned by Amplify, not a local development address:

```sh
python scripts/verify_deployment.py https://YOUR-BRANCH.YOUR-APP.amplifyapp.com
```

Then run the project's browser tests against that URL using their documented
base-URL setting. Check desktop/mobile browsing, search, filters, details, poster
loading, and external links. Verify that `/data/movies.json` matches the released
catalog. DNS, TLS, Amplify response headers, and the external site are not verified
until these checks have executed against the real deployed address.

To trigger a later deployment with an already configured AWS CLI identity:

```sh
aws amplify start-job --app-id YOUR_APP_ID --branch-name main --job-type RELEASE --region YOUR_REGION
```

Use the intended existing profile rather than a new key in chat. This command
requires `amplify:StartJob` for the selected app branch. Inspect the returned job
with `aws amplify get-job` and wait for `SUCCEED` before doing the external checks.

## Publishing reviewed imports

Run the importer locally against the authorized private storage path. Review every
missing/ambiguous field and supply explicit record, link, and poster clearance in
a private rights manifest. Use `python -m importer publish --help` to build only
the approved public projection. A source URL appearing in a Telegram message is
not evidence that the linked film can be distributed. A poster appearing in the
export is not a license. The publication command must be rerun after later channel
imports; imports themselves never update the public site.

Commit only the approved public JSON and sanitized, licensed poster assets after
running the release checks. All other imported data stays in private storage.
