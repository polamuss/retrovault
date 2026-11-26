"""Offline IGDB matching and fail-closed gate tests. No network calls."""
import os
import unittest
from unittest.mock import patch
from collections import Counter
import igdb_index as igdb

class IGDBTests(unittest.TestCase):
    def test_disabled_gate_never_requests_oauth(self):
        with patch.dict(os.environ, {"RV_IGDB_APPROVED":"false","RV_IGDB_REQUESTED":"true"}), \
             patch.object(igdb, "_token", side_effect=AssertionError("network must not be used")):
            self.assertEqual(igdb.main(),0)

    def test_exact_platform_and_short_title(self):
        rows=[{"id":1,"name":"DOOM","platforms":[{"name":"Nintendo Entertainment System"}],
               "cover":{"image_id":"cover_123"}}]
        result=igdb.choose_match(rows,["DOOM (USA)"],"Nintendo - Nintendo Entertainment System",Counter())
        self.assertEqual(result,"https://images.igdb.com/igdb/image/upload/t_cover_big/cover_123.jpg")

    def test_homonym_on_wrong_platform_is_rejected(self):
        rows=[{"id":1,"name":"Doom","platforms":[{"name":"PC (Microsoft Windows)"}],
               "cover":{"image_id":"cover_123"}}]
        stats=Counter()
        result=igdb.choose_match(rows,["Doom"],"Nintendo - Nintendo Entertainment System",stats)
        self.assertIsNone(result)
        self.assertEqual(stats["no_exact_platform_cover"],1)

    def test_ambiguous_platform_matches_are_rejected(self):
        rows=[
            {"id":1,"name":"Game","platforms":[{"name":"Nintendo Entertainment System"}],"cover":{"image_id":"a"}},
            {"id":2,"name":"Game","platforms":[{"name":"Nintendo Entertainment System"}],"cover":{"image_id":"b"}},
        ]
        stats=Counter()
        self.assertIsNone(igdb.choose_match(rows,["Game"],"Nintendo - Nintendo Entertainment System",stats))
        self.assertEqual(stats["ambiguous"],1)

if __name__ == "__main__":
    unittest.main()
