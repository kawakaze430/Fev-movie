import json
import os
import tempfile
import unittest
from pathlib import Path

from backend.engine import recommend
from backend.lambda_handler import handler, _catalog

MOVIES = [
    {"id": "s1", "title": "Space One", "year": 2020, "genres": ["Sci-Fi"], "synopsis": "Interstellar travel"},
    {"id": "s2", "title": "Space Two", "year": 2021, "genres": ["Sci-Fi"], "synopsis": "Galaxy travel"},
    {"id": "r1", "title": "Romance", "year": 2019, "genres": ["Romance"], "synopsis": "Love story"},
    {"id": "d1", "title": "Drama", "year": 2022, "genres": ["Drama"], "synopsis": "Family conflicts"},
]

class RecommendationTests(unittest.TestCase):
    def test_seed_is_excluded(self):
        data = recommend(MOVIES, ["s1"], 3)
        self.assertNotIn("s1", [row["id"] for row in data])
        self.assertEqual(data[0]["id"], "s2")

    def test_no_seed_still_works(self):
        self.assertEqual(len(recommend(MOVIES, [], 2)), 2)

    def test_empty_and_limit(self):
        self.assertEqual(recommend([], [], 6), [])
        self.assertEqual(recommend(MOVIES, [], 0), [])
        self.assertLessEqual(len(recommend(MOVIES, [], 100)), 24)

    def test_unknown_seed_does_not_crash(self):
        self.assertEqual(len(recommend(MOVIES, ["unknown"], 3)), 3)

    def test_lambda_handler(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "movies.json"
            p.write_text(json.dumps({"kind": "demo", "movies": MOVIES}))
            os.environ["CLIPNEST_CATALOG_PATH"] = str(p)
            _catalog.cache_clear()
            try:
                event = {"rawPath": "/recommendations", "queryStringParameters": {"seed": "s1", "limit": "3"}}
                response = handler(event)
                self.assertEqual(response["statusCode"], 200)
                self.assertEqual(json.loads(response["body"])["recommendations"][0]["id"], "s2")
            finally:
                os.environ.pop("CLIPNEST_CATALOG_PATH", None)
                _catalog.cache_clear()

if __name__ == "__main__":
    unittest.main()
