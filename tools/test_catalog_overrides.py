"""Offline tests for persistent catalogue corrections."""
import json
import tempfile
import unittest
from pathlib import Path
from catalog_overrides import load_overrides, apply_catalog_overrides

class OverrideTests(unittest.TestCase):
    def test_exact_exclusion_and_title_correction(self):
        data={"version":1,"excluded":[{"system":"NES","title":"Fake"}],
              "title_overrides":[{"system":"NES","title":"Old Name","replacement":"New Name"}],
              "image_exclusions":[]}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"overrides.json"
            path.write_text(json.dumps(data),encoding="utf-8")
            overrides=load_overrides(path)
        merged={"NES":{"Fake","Old Name","Keep"}}
        stats=apply_catalog_overrides(merged,overrides)
        self.assertEqual(merged["NES"],{"New Name","Keep"})
        self.assertEqual(stats["catalog_excluded_titles"],1)
        self.assertEqual(stats["catalog_renamed_titles"],1)

    def test_unknown_image_source_is_rejected(self):
        data={"version":1,"excluded":[],"title_overrides":[],
              "image_exclusions":[{"system":"NES","title":"Game","source":"unknown"}]}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"overrides.json"
            path.write_text(json.dumps(data),encoding="utf-8")
            with self.assertRaises(ValueError):
                load_overrides(path)

if __name__ == "__main__":
    unittest.main()
