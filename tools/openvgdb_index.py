"""Index OpenVGDB cover references with schema-aware SQLite import and cache."""
import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".rv-image-cache" / "openvgdb-v29.json"
RELEASE_API = "https://api.github.com/repos/OpenVGDB/OpenVGDB/releases/tags/v29.0"
FALLBACK_URL = "https://github.com/OpenVGDB/OpenVGDB/releases/download/v29.0/openvgdb.zip"
HOSTS = {"gamefaqs.gamespot.com", "img.gamefaqs.net", "gamefaqs.akamaized.net",
         "www.gamefaqs.com", "gamefaqs.com", "www.mobygames.com",
         "cdn.mobygames.com", "images.launchbox-app.com", "gamesdb-images.launchbox.gg"}


def safe_url(url):
    if not isinstance(url, str) or len(url) > 800:
        return None
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme not in ("http", "https") or p.hostname not in HOSTS or p.username or p.password or p.port:
            return None
        if not re.search(r"\.(?:jpg|jpeg|png|webp)$", p.path, re.I):
            return None
        return urllib.parse.urlunsplit(("https", p.hostname, p.path, "", ""))
    except ValueError:
        return None


def system_key(s):
    return re.sub(r"[^a-z0-9]", "", s.casefold())


ALIASES = {
    "Nintendo Entertainment System": "Nintendo - Nintendo Entertainment System",
    "NES": "Nintendo - Nintendo Entertainment System",
    "Super Nintendo Entertainment System": "Nintendo - Super Nintendo Entertainment System",
    "Super Nintendo": "Nintendo - Super Nintendo Entertainment System",
    "SNES": "Nintendo - Super Nintendo Entertainment System",
    "Nintendo Famicom Disk System": "Nintendo - Family Computer Disk System",
    "Famicom Disk System": "Nintendo - Family Computer Disk System",
    "Nintendo Family Computer Disk System": "Nintendo - Family Computer Disk System",
    "Nintendo Game Boy": "Nintendo - Game Boy", "Game Boy": "Nintendo - Game Boy",
    "Nintendo Game Boy Color": "Nintendo - Game Boy Color", "Game Boy Color": "Nintendo - Game Boy Color",
    "Nintendo Game Boy Advance": "Nintendo - Game Boy Advance", "Game Boy Advance": "Nintendo - Game Boy Advance",
    "Nintendo DS": "Nintendo - Nintendo DS", "Nintendo Nintendo DS": "Nintendo - Nintendo DS",
    "Nintendo 3DS": "Nintendo - Nintendo 3DS", "Nintendo Nintendo 3DS": "Nintendo - Nintendo 3DS",
    "Nintendo 64": "Nintendo - Nintendo 64", "Nintendo GameCube": "Nintendo - GameCube",
    "Nintendo Wii": "Nintendo - Wii", "Nintendo Virtual Boy": "Nintendo - Virtual Boy",
    "Nintendo Pokemon Mini": "Nintendo - Pokemon Mini",
    "Sega Genesis": "Sega - Mega Drive - Genesis", "Sega Mega Drive": "Sega - Mega Drive - Genesis",
    "Sega Mega Drive Genesis": "Sega - Mega Drive - Genesis",
    "Sega Master System": "Sega - Master System - Mark III",
    "Sega CD": "Sega - Mega-CD - Sega CD", "Sega Mega CD": "Sega - Mega-CD - Sega CD",
    "Sega 32X": "Sega - 32X", "Sega Game Gear": "Sega - Game Gear",
    "Sega Saturn": "Sega - Saturn", "Sega Dreamcast": "Sega - Dreamcast", "Sega SG-1000": "Sega - SG-1000",
    "Sony PlayStation": "Sony - PlayStation", "Sony PlayStation 2": "Sony - PlayStation 2",
    "Sony PlayStation Portable": "Sony - PlayStation Portable", "Sony PSP": "Sony - PlayStation Portable",
    "Sony PlayStation Vita": "Sony - PlayStation Vita",
    "NEC PC Engine": "NEC - PC Engine - TurboGrafx 16",
    "NEC TurboGrafx-16": "NEC - PC Engine - TurboGrafx 16",
    "NEC PC Engine TurboGrafx 16": "NEC - PC Engine - TurboGrafx 16",
    "NEC TurboGrafx CD": "NEC - PC Engine CD - TurboGrafx-CD",
    "NEC PC Engine CD": "NEC - PC Engine CD - TurboGrafx-CD",
    "SNK Neo Geo Pocket": "SNK - Neo Geo Pocket",
    "SNK Neo Geo Pocket Color": "SNK - Neo Geo Pocket Color",
    "SNK Neo Geo CD": "SNK - Neo Geo CD", "SNK Neo Geo": "SNK - Neo Geo",
    "Atari 2600": "Atari - 2600", "Atari 5200": "Atari - 5200",
    "Atari 7800": "Atari - 7800", "Atari Lynx": "Atari - Lynx",
    "Atari Jaguar": "Atari - Jaguar", "Atari Jaguar CD": "Atari - Jaguar CD",
    "Coleco ColecoVision": "Coleco - ColecoVision", "ColecoVision": "Coleco - ColecoVision",
    "Mattel Intellivision": "Mattel - Intellivision", "Magnavox Odyssey2": "Magnavox - Odyssey2",
    "GCE Vectrex": "GCE - Vectrex", "Bandai WonderSwan": "Bandai - WonderSwan",
    "Bandai WonderSwan Color": "Bandai - WonderSwan Color", "Commodore 64": "Commodore - 64",
    "Commodore Amiga": "Commodore - Amiga", "3DO": "The 3DO Company - 3DO",
    "3DO Interactive Multiplayer": "The 3DO Company - 3DO",
    "Microsoft Xbox": "Microsoft - Xbox", "Microsoft Xbox 360": "Microsoft - Xbox 360"
}


def resolve_archive_url():
    """Resolve the current release asset name; retain a fallback for API outages."""
    req = urllib.request.Request(RELEASE_API, headers={
        "User-Agent": "RetroVault metadata index", "Accept": "application/vnd.github+json"
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read(2_000_001))
        assets = payload.get("assets", [])
        candidates = [a for a in assets if isinstance(a.get("name"), str)
                      and a["name"].lower().endswith(".zip")
                      and isinstance(a.get("browser_download_url"), str)]
        preferred = [a for a in candidates if "openvgdb" in a["name"].casefold()]
        selected = (preferred or candidates)
        if selected:
            return selected[0]["browser_download_url"]
    except Exception:
        pass
    return FALLBACK_URL


def _columns(conn, table):
    rows = conn.execute("PRAGMA table_info(" + table + ")").fetchall()
    return {str(row[1]).casefold(): str(row[1]) for row in rows}


def read_sqlite_rows(db_path):
    """Read known OpenVGDB schemas without assuming a single column spelling."""
    with sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        check = conn.execute("PRAGMA quick_check").fetchone()
        if not check or check[0] != "ok":
            raise ValueError("base SQLite OpenVGDB invalide")
        tables = {r[0].casefold(): r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for required in ("roms", "releases", "systems"):
            if required not in tables:
                raise ValueError("table OpenVGDB absente: " + required)
        roms, releases, systems = (tables[x] for x in ("roms", "releases", "systems"))
        rc, relc, sc = _columns(conn, roms), _columns(conn, releases), _columns(conn, systems)

        def col(columns, *names):
            for name in names:
                if name.casefold() in columns:
                    return columns[name.casefold()]
            return None

        rom_id = col(rc, "romID")
        release_rom_id = col(relc, "romID")
        rom_release_id = col(rc, "releaseID")
        release_pk = col(relc, "releaseID")
        if rom_id and release_rom_id:
            join = 'rel."' + release_rom_id + '" = rom."' + rom_id + '"'
        elif rom_release_id and release_pk:
            join = 'rel."' + release_pk + '" = rom."' + rom_release_id + '"'
        else:
            raise ValueError("relation ROMs/RELEASES non reconnue")
        system_id = col(rc, "systemID") or col(relc, "systemID")
        system_pk = col(sc, "systemID")
        system_name = col(sc, "systemName", "name")
        title = col(relc, "releaseTitleName", "releaseName", "title")
        cover = col(relc, "releaseCoverFront", "releaseCoverFrontURL", "coverFront", "cover_url")
        cover_table = "rel"
        if not cover:
            cover = col(rc, "releaseCoverFront", "releaseCoverFrontURL", "coverFront", "cover_url")
            cover_table = "rom"
        filename = col(rc, "romExtensionlessFileName", "romFileName", "filename")
        if not all((system_id, system_pk, system_name, title, cover)):
            raise ValueError("schéma OpenVGDB non reconnu (colonnes ROMs/RELEASES/SYSTEMS)")
        if not filename:
            filename = "''"
        else:
            filename = 'rom."' + filename.replace('"', '""') + '"'
        system_join = 'rom."' + system_id + '"' if system_id in rc.values() else 'rel."' + system_id + '"'
        query = (
            'SELECT DISTINCT sys."' + system_name + '", rel."' + title + '", ' + filename +
            ', ' + cover_table + '."' + cover + '" FROM "' + roms + '" AS rom '
            'JOIN "' + releases + '" AS rel ON ' + join + ' '
            'JOIN "' + systems + '" AS sys ON sys."' + system_pk + '" = ' + system_join +
            ' WHERE ' + cover_table + '."' + cover + '" IS NOT NULL AND ' + cover_table + '."' + cover + '" <> ""'
        )
        return conn.execute(query).fetchall()


def load_rows(url=None, cache_path=CACHE):
    cache_path = Path(cache_path)
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(cached, list) and cached:
            return cached
    except (OSError, ValueError):
        pass
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    url = url or resolve_archive_url()
    request = urllib.request.Request(url, headers={"User-Agent": "RetroVault metadata index"})
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with urllib.request.urlopen(request, timeout=60) as response:
            final_host = urllib.parse.urlparse(response.geturl()).hostname
            if final_host not in ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"):
                raise ValueError("hôte de téléchargement OpenVGDB non autorisé")
            archive = tmp / "openvgdb.zip"
            with archive.open("wb") as stream:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 50_000_000:
                        raise ValueError("archive OpenVGDB trop volumineuse")
                    stream.write(chunk)
        with zipfile.ZipFile(archive) as z:
            files = [i for i in z.infolist() if i.filename.lower().endswith((".sqlite", ".sqlite3", ".db"))
                     and 0 < i.file_size < 500_000_000]
            if len(files) != 1:
                raise ValueError("base SQLite absente ou ambiguë dans OpenVGDB")
            db = tmp / "openvgdb.sqlite"
            with z.open(files[0]) as source, db.open("wb") as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
        rows = read_sqlite_rows(db)

    result = []
    for system, title, filename, url in rows:
        if not isinstance(system, str) or not isinstance(title, str):
            continue
        url = safe_url(url)
        if not url:
            continue
        filename = re.sub(
            r"\.(?:zip|7z|nes|sfc|smc|gb|gbc|gba|n64|z64|v64|nds|bin|iso|cue|chd|md|gen|sms|gg|pce|a26|a78|lnx|j64|ws|wsc|rom)$",
            "", str(filename or ""), flags=re.I
        )
        result.append([system, title, filename, url])
    if not result:
        raise ValueError("aucune référence de jaquette OpenVGDB exploitable")
    cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def index_openvgdb(out, merged, base_title, write_json):
    stats = {"openvgdb_source_rows": 0, "openvgdb_matches": 0, "openvgdb_platforms": 0,
             "openvgdb_unmapped": [], "openvgdb_error": None}
    result = {}
    try:
        rows = load_rows()
    except Exception as error:
        stats["openvgdb_error"] = str(error)[:500]
        print("OpenVGDB indisponible:", stats["openvgdb_error"])
        return result, stats
    stats["openvgdb_source_rows"] = len(rows)
    targets = {system_key(s): s for s in merged}
    targets.update({system_key(a): s for a, s in ALIASES.items() if s in merged})
    pools = defaultdict(lambda: defaultdict(set))
    unknown = set()
    for system, title, filename, url in rows:
        sys = targets.get(system_key(system))
        if not sys:
            unknown.add(system)
            continue
        for key in {base_title(title), base_title(filename)} - {""}:
            pools[sys][key].add(url)
    stats["openvgdb_unmapped"] = sorted(unknown)
    for system, names in sorted(merged.items()):
        root = re.sub(r" \((?:Digital|PSN|Games on Demand|Download Play)\)$", "", system, flags=re.I)
        pool = pools.get(system) or pools.get(root)
        if not pool:
            continue
        index = {}
        for title in sorted(names):
            hits = pool.get(base_title(title), set())
            if hits:
                index[title] = sorted(hits)[:3]
        if index:
            path = "data/openvgdb/" + hashlib.sha256(system.encode()).hexdigest()[:16] + ".json"
            write_json(out / path, index)
            result[system] = path
            stats["openvgdb_matches"] += len(index)
    stats["openvgdb_platforms"] = len(result)
    return result, stats
