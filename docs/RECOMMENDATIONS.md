# ClipNest content-based recommendation API

The React application works fully without an API. Suggestions use genre/year/title similarity with local watchlist IDs. Optional Python backend provides AWS Lambda-compatible endpoints.

## Endpoints
- GET /health
- GET /recommendations?seed=movie1,movie2&limit=6

Responses contain recommendation IDs, scores and brief reasons. There is no LLM dependency, storage of user browsing history, accounts, or tracking.

## Test
    python -m unittest discover -s tests/python -v

## Deploy after rights review
Prerequisites: approved public/data/movies.json; AWS CLI/SAM authenticated in your AWS account, with permission to create Lambda, IAM role and API Gateway.

    python scripts/validate_public.py
    python scripts/prepare_backend_catalog.py
    sam build --template-file infra/template.yaml
    sam deploy --guided

Supply AllowedOrigin as the actual Amplify HTTPS origin. Point VITE_RECOMMENDATIONS_API_URL in the Amplify build settings to the SAM output APIBaseUrl, then rebuild the frontend. Frontend automatically falls back to local recommendations if the API is absent or fails.

For nonproduction demo integration only, the staging command allows --allow-demo. Real Telegram history must not be put in backend/data or a Lambda ZIP without explicit rights review.

The backend has not been deployed to AWS; commands are instructions, not verification evidence.
