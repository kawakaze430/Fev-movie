"""AWS Lambda HTTP API adapter. Deploy only with a cleared public catalog."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from .engine import recommend
except ImportError:
    from engine import recommend


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    path = Path(os.environ.get("CLIPNEST_CATALOG_PATH", str(Path(__file__).parent / "data" / "movies.json")))
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("kind") not in ("public", "demo") or not isinstance(data.get("movies"), list):
        raise ValueError("The configured catalog must be a validated public or synthetic demo catalog")
    return data


def _response(status: int, data: dict[str, Any], origin: str) -> dict[str, Any]:
    allowed = os.environ.get("CLIPNEST_ALLOWED_ORIGIN", "*")
    headers = {"content-type": "application/json", "cache-control": "no-store"}
    if allowed == "*" or origin == allowed:
        headers["access-control-allow-origin"] = allowed
        headers["access-control-allow-methods"] = "GET, OPTIONS"
        headers["access-control-allow-headers"] = "Content-Type"
        headers["vary"] = "Origin"
    return {"statusCode": status, "headers": headers, "body": json.dumps(data, ensure_ascii=False)}


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    req = event.get("requestContext", {}).get("http", {})
    method = str(req.get("method", event.get("httpMethod", "GET"))).upper()
    origin = (event.get("headers") or {}).get("origin", "")
    path = str(event.get("rawPath", event.get("path", "/"))).rstrip("/")
    if method == "OPTIONS":
        return _response(204, {}, origin)
    if method != "GET":
        return _response(405, {"error": "Method not allowed"}, origin)
    if path in ("/health", "/api/health"):
        return _response(200, {"status": "ok", "service": "clipnest-recommendations"}, origin)
    if path not in ("/recommendations", "/api/recommendations"):
        return _response(404, {"error": "Not found"}, origin)
    query = event.get("queryStringParameters") or {}
    seed = str(query.get("seed", ""))[:2048].split(",")
    try:
        limit = max(1, min(int(query.get("limit", 8)), 24))
    except (ValueError, TypeError):
        return _response(400, {"error": "Invalid limit"}, origin)
    try:
        data = _catalog()
        results = recommend(data["movies"], seed, limit)
    except (OSError, ValueError, TypeError):
        return _response(503, {"error": "Catalog unavailable"}, origin)
    return _response(200, {"recommendations": results, "catalogKind": data["kind"]}, origin)
