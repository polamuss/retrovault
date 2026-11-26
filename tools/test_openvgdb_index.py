"""Offline SQLite schema regression tests for OpenVGDB."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from openvgdb_index import read_sqlite_rows, safe_url

class OpenVGDBTests(unittest.TestCase):
    def test_documented_rom_release_system_join(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"openvgdb.sqlite"
            with sqlite3.connect(db) as conn:
                conn.executescript("""
                    CREATE TABLE SYSTEMS(systemID INTEGER PRIMARY KEY, systemName TEXT);
                    CREATE TABLE ROMs(romID INTEGER PRIMARY KEY, systemID INTEGER, romFileName TEXT, romExtensionlessFileName TEXT);
                    CREATE TABLE RELEASES(releaseID INTEGER PRIMARY KEY, romID INTEGER, releaseTitleName TEXT, releaseCoverFront TEXT);
                    INSERT INTO SYSTEMS VALUES(1, 'Nintendo Entertainment System');
                    INSERT INTO ROMs VALUES(10, 1, 'Game (USA).nes', 'Game (USA)');
                    INSERT INTO RELEASES VALUES(20, 10, 'Game', 'https://images.launchbox-app.com/example.jpg');
                """)
            rows=read_sqlite_rows(db)
        self.assertEqual(rows,[("Nintendo Entertainment System","Game","Game (USA)","https://images.launchbox-app.com/example.jpg")])

    def test_url_filter(self):
        self.assertEqual(safe_url("http://images.launchbox-app.com/cover.jpg"),"https://images.launchbox-app.com/cover.jpg")
        self.assertIsNone(safe_url("https://evil.example/cover.jpg"))

if __name__ == "__main__":
    unittest.main()
