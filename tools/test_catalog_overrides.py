"""Offline tests for persistent catalogue corrections."""
import json
import tempfile
import unittest
from pathlib import Path
from catalog_overrides import load_overrides, apply_catalog_overrides, apply_image_exclusions

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

    def test_image_exclusion_removes_reference_not_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            target=root/"data/art/index.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({"repo":"libretro","rows":{"Game":[0,"Game",0]}}),encoding="utf-8")
            images={'["NES","Game"]':{"path":"media/example.avif"}}
            overrides={"image_exclusions":[{"system":"NES","title":"Game","source":"libretro"}]}
            stats=apply_image_exclusions(root,overrides,images,{"art":{"NES":"data/art/index.json"}})
            payload=json.loads(target.read_text(encoding="utf-8"))
            self.assertNotIn("Game",payload["rows"])
            self.assertIn('["NES","Game"]',images)
            self.assertEqual(stats["catalog_image_references_removed"],1)

    def test_punctuation_variants_match_reviewed_title(self):
        overrides={"excluded":[{"system":"Emerson","title":"Geometrydash"}],
                   "title_overrides":[],"image_exclusions":[]}
        merged={"Emerson":{"Geometry Dash","Other"}}
        stats=apply_catalog_overrides(merged,overrides)
        self.assertEqual(merged["Emerson"],{"Other"})
        self.assertEqual(stats["catalog_excluded_titles"],1)

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
