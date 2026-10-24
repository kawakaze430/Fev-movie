# Catalog architecture and trust boundaries

The static React application reads a versioned public catalog. Python imports Telegram desktop exports offline. No browser or build step executes the HTML export, its JavaScript, CSS, or JSON. Text inside an export is data, never an instruction to the importer or an operator.

## Private ingestion

Raw ZIPs, extracted media, message inventories, source text, original links, diagnostics, and the aggregate private catalog belong in a private directory outside the Git checkout. Supply that directory explicitly to the importer. A chat attachment is not automatically present on the cloud machine. The attachment transfer tool used in this session accepts at most 32 MiB; larger archives need an authorized accessible path or storage URI. Do not put cloud credentials in a URI or command history.

Each import has a channel identity and archive digest. Parse every nested `messages*.html` page, retain source message identifiers, and associate a poster only through explicit message structure or a documented joined-message relationship. Preserve uncertainty in a report. A file size never determines resolution. Deduplication combines compatible records conservatively and retains provenance; a remake with a different year remains separate.

## Publication

Imports are private by default. A rights manifest explicitly selects records and approved destination URLs and documents the basis for distribution and poster use. Publication creates a reduced `movies.json`; it does not copy HTML exports or raw message bodies. Unapproved records, URLs, and posters remain private. Public validation runs independently during the frontend build/deployment workflow.

The checked-in catalog is fictional demonstration material with original abstract poster art. It proves the browsing workflow without implying the uploaded channel has been parsed or cleared. Replace it only with validated, explicitly approved public output.

## Browser

React renders strings as text. Catalog links allow only safe HTTP(S) URLs, open with `noopener noreferrer`, and do not embed or proxy the linked movie. No third-party runtime fonts, analytics, or poster service is required. Favorites stay in the browser. The static host never receives raw archives or private catalogs.

## Hosting

AWS Amplify Hosting builds the Vite app from the committed lockfile and serves `dist`. The repository contains build configuration and security headers; creating an Amplify app, connecting GitHub, selecting an AWS account/region, and verifying a live deployment are separate operations. Cloud credentials and a deployable rights-cleared dataset must be verified before claiming production publication.
