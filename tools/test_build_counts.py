"""Offline tests for source-entry and duplicate counting inputs."""
import unittest
from build import parse_dat

class BuildCounterTests(unittest.TestCase):
    def test_xml_parser_preserves_duplicate_rows(self):
        raw='<datafile><game name="Game"/><game name="Game"/></datafile>'
        self.assertEqual(parse_dat(raw),["Game","Game"])

    def test_dat_parser_preserves_duplicate_rows(self):
        raw='game ( name "Game" )\ngame ( name "Game" )'
        self.assertEqual(parse_dat(raw),["Game","Game"])

if __name__ == "__main__":
    unittest.main()
