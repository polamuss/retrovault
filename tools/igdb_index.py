"""Optional IGDB cover-reference indexer. Network access is fail-closed behind maintainer approval."""
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from build import base_title

API = "https://api.igdb.com/v4/games"
TOKEN_API = "https://id.twitch.tv/oauth2/token"
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".rv-image-cache" / "igdb-links-v1.json"
MAX_TITLES = 300
MAX_REQUESTS = 450
MAX_SECONDS = 720
IMAGE_HOST = "images.igdb.com"

PLATFORM_ALIASES = {
    "Nintendo - Nintendo Entertainment System": {"nintendo entertainment system", "nes", "famicom"},
    "Nintendo - Super Nintendo Entertainment System": {"super nintendo entertainment system", "snes", "super famicom"},
    "Nintendo - Nintendo 64": {"nintendo 64", "n64"},
    "Nintendo - GameCube": {"nintendo gamecube", "gamecube", "gamecube"},
    "Nintendo - Wii": {"wii"},
    "Nintendo - Wii U": {"wii u"},
    "Nintendo - Game Boy": {"game boy"},
    "Nintendo - Game Boy Color": {"game boy color"},
    "Nintendo - Game Boy Advance": {"game boy advance", "gba"},
    "Nintendo - Nintendo DS": {"nintendo ds", "ds"},
    "Nintendo - Nintendo 3DS": {"nintendo 3ds", "3ds"},
    "Nintendo - Virtual Boy": {"virtual boy"},
    "Sega - Master System - Mark III": {"sega master system", "master system"},
    "Sega - Mega Drive - Genesis": {"sega genesis", "mega drive", "genesis"},
    "Sega - Mega-CD - Sega CD": {"sega cd", "mega cd", "sega mega cd"},
    "Sega - 32X": {"sega 32x", "32x"},
    "Sega - Game Gear": {"game gear"},
    "Sega - Saturn": {"sega saturn", "saturn"},
    "Sega - Dreamcast": {"sega dreamcast", "dreamcast"},
    "Sony - PlayStation": {"playstation", "ps1", "ps"},
    "Sony - PlayStation 2": {"playstation 2", "ps2"},
    "Sony - PlayStation 3": {"playstation 3", "ps3"},
    "Sony - PlayStation Portable": {"playstation portable", "psp"},
    "Sony - PlayStation Vita": {"playstation vita", "ps vita"},
    "Microsoft - Xbox": {"xbox"},
    "Microsoft - Xbox 360": {"xbox 360"},
    "Atari - 2600": {"atari 2600", "atari vcs"},
    "Atari - 5200": {"atari 5200"},
    "Atari - 7800": {"atari 7800"},
    "Atari - Lynx": {"atari lynx", "lynx"},
    "Atari - Jaguar": {"atari jaguar", "jaguar"},
    "Coleco - ColecoVision": {"colecovision"},
    "Mattel - Intellivision": {"intellivision"},
    "GCE - Vectrex": {"vectrex"},
    "Commodore - 64": {"commodore 64", "c64"},
    "Commodore - Amiga": {"amiga"},
    "The 3DO Company - 3DO": {"3do", "3do interactive multiplayer"},
}


def _norm(value):
    return base_title(str(value or ""))


def _public_cover(image_id):
    if not isinstance(image_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", image_id):
        return None
    return f"https://{IMAGE_HOST}/igdb/image/upload/t_cover_big/{image_id}.jpg"


def _authorized():
    # Two independent gates are required. Secrets alone never authorize a request.
    return (os.environ.get("RV_IGDB_APPROVED", "").strip().lower() == "true"
            and os.environ.get("RV_IGDB_REQUESTED", "").strip().lower() == "true")


def _token(client_id, client_secret):
    query = urllib.parse.urlencode({
        "client_id": client_id, "client_secret": client_secret,
        "grant_type": "client_credentials"
    })
    request = urllib.request.Request(TOKEN_API + "?" + query, method="POST",
                                     headers={"User-Agent": "RetroVault IGDB indexer"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read(256_001))
    token = payload.get("access_token")
    if not isinstance(token, str) or not token or len(token) > 4096:
        raise ValueError("Réponse OAuth Twitch invalide")
    return token


def _search_title(title):
    original = base_title(title)
    while True:
        shorter = re.sub(r"\s*(?:\([^()]*\)|\[[^\[\]]*\])\s*$", "", title).strip()
        if shorter == title or not shorter or base_title(shorter) != original:
            break
        title = shorter
    return title


def _query(title):
    safe = title.replace("\\", " ").replace('"', " ").replace(";", " ")
    return ('search "' + safe + '"; fields id,name,first_release_date,'
            'platforms.name,alternative_names.name,cover.image_id; limit 50;')


def _request(title, client_id, token, stats):
    body = _query(title).encode("utf-8")
    request = urllib.request.Request(API, data=body, method="POST", headers={
        "Client-ID": client_id,
        "Authorization": "Bearer " + token,
        "Content-Type": "text/plain",
        "User-Agent": "RetroVault IGDB cover reference indexer",
    })
    stats["api_requests"] += 1
    with urllib.request.urlopen(request, timeout=25) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Réponse IGDB trop volumineuse")
    result = json.loads(raw)
    if not isinstance(result, list):
        raise ValueError("Réponse IGDB invalide")
    return result


def choose_match(rows, names, system, stats):
    expected_titles = {_norm(n) for n in names if _norm(n)}
    allowed_platforms = {_norm(n) for n in PLATFORM_ALIASES.get(system, set())}
    if not allowed_platforms:
        stats["unmapped_platform"] += 1
        return None
    matches = []
    for row in rows:
        if not isinstance(row, dict) or type(row.get("id")) is not int:
            continue
        candidates = [row.get("name")]
        candidates.extend(x.get("name") for x in row.get("alternative_names", []) if isinstance(x, dict))
        if not any(_norm(n) in expected_titles for n in candidates if isinstance(n, str)):
            continue
        platform_names = {
            _norm(p.get("name")) for p in row.get("platforms", [])
            if isinstance(p, dict) and isinstance(p.get("name"), str)
        }
        if not platform_names.intersection(allowed_platforms):
            continue
        image_id = row.get("cover", {}).get("image_id") if isinstance(row.get("cover"), dict) else None
        url = _public_cover(image_id)
        if url:
            matches.append((row["id"], url))
    unique = {row[0]: row[1] for row in matches}
    if len(unique) != 1:
        stats["ambiguous" if len(unique) > 1 else "no_exact_platform_cover"] += 1
        return None
    return next(iter(unique.values()))


def main():
    if not _authorized():
        print("IGDB désactivé : approbation administrateur et activation manquantes.")
        return 0
    client_id = os.environ.get("IGDB_CLIENT_ID", "").strip()
    client_secret = os.environ.get("IGDB_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print("IGDB désactivé : identifiants absents.")
        return 0

    out = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    index_path, report_path = out / "data/index.json", out / "data/report.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    snapshot = json.loads((out / index["catalog_snapshot"]).read_text(encoding="utf-8"))
    try:
        cached = json.loads(CACHE.read_text(encoding="utf-8"))
        if not isinstance(cached, dict):
            cached = {}
    except (OSError, ValueError):
        cached = {}
    overrides_path = Path(__file__).resolve().parents[1] / "data" / "catalog-overrides.json"
    try:
        overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        overrides = {"image_exclusions": []}
    suppressed = {(r.get("system"), r.get("title")) for r in overrides.get("image_exclusions", [])
                  if r.get("source") in ("all", "igdb")}

    stats = Counter()
    groups = []
    all_groups = {}
    previous_refs = set()
    previous_covers = set()
    fixed_images = index.get("images", {})
    for system, row in snapshot.items():
        names, aliases = row
        def group_key(name):
            key = base_title(name)
            return aliases.get(key, key)
        groups_by_key = defaultdict(list)
        for name in names:
            groups_by_key[group_key(name)].append(name)
        all_groups[system] = groups_by_key
        refs = set()
        covers = set()
        for field in ("art", "launchbox_art", "gametdb_art", "openvgdb_art", "steamgriddb_art"):
            path = index.get(field, {}).get(system)
            if not path:
                continue
            try:
                payload = json.loads((out / path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if field == "art":
                payload = payload.get("rows", {})
                for name, value in payload.items():
                    refs.add(name)
                    if isinstance(value, list) and value and value[0] == 0:
                        covers.add(name)
            elif field == "launchbox_art":
                for name, values in payload.items():
                    refs.add(name)
                    if isinstance(values, list) and any(isinstance(v, list) and len(v) > 1 and v[1] in (0, 1) for v in values):
                        covers.add(name)
            else:
                refs.update(payload.keys())
                if field in ("gametdb_art", "openvgdb_art"):
                    covers.update(payload.keys())
        for raw_key in fixed_images:
            try:
                image_system, image_title = json.loads(raw_key)
            except (TypeError, ValueError):
                continue
            if image_system == system:
                refs.add(image_title)
                covers.add(image_title)
        previous_refs.update((system, n) for n in refs)
        previous_covers.update((system, n) for n in covers)
        for group, editions in groups_by_key.items():
            if system not in PLATFORM_ALIASES:
                stats["unmapped_platform"] += 1
                continue
            if not group or any((system, n) in suppressed for n in editions):
                if any((system, n) in suppressed for n in editions):
                    stats["moderation_excluded"] += 1
                continue
            if any(n in covers for n in editions):
                stats["already_covered"] += 1
                continue
            title_names = sorted(editions, key=lambda n: (base_title(n) != group, len(n), n))
            groups.append((system, group, title_names[:12]))

    # Reuse positive cache entries and still-valid negative entries before any network call.
    now = int(time.time())
    jobs = []
    for system, group, names in groups:
        key = system + "|" + group
        old = cached.get(key)
        if isinstance(old, dict) and old.get("url") and _public_cover(old.get("image_id")):
            continue
        if isinstance(old, dict) and not old.get("url") and now - int(old.get("checked", 0)) < 30 * 86400:
            stats["negative_cache_hits"] += 1
            continue
        jobs.append((system, group, names))

    # Spread the bounded sample over platforms to avoid spending the budget on one console.
    by_system = defaultdict(list)
    for job in jobs:
        by_system[job[0]].append(job)
    ordered = []
    while by_system:
        for system in list(by_system):
            ordered.append(by_system[system].pop(0))
            if not by_system[system]:
                del by_system[system]
    deadline = time.monotonic() + MAX_SECONDS
    token = None
    if ordered:
        try:
            token = _token(client_id, client_secret)
        except Exception:
            stats["oauth_errors"] += 1
            print("IGDB OAuth indisponible. Les résultats déjà en cache sont conservés.")
    attempted = 0
    if token:
        for system, group, names in ordered:
            if attempted >= MAX_TITLES or stats["api_requests"] >= MAX_REQUESTS or time.monotonic() >= deadline:
                stats["budget_stopped"] += 1
                break
            attempted += 1
            try:
                title = _search_title(names[0])
                rows = _request(title, client_id, token, stats)
                url = choose_match(rows, names, system, stats)
                image_id = url.rsplit("/", 1)[-1].removesuffix(".jpg") if url else None
                cached[system + "|" + group] = {"image_id": image_id, "checked": now}
                if url:
                    stats["matched_groups"] += 1
                if attempted % 1 == 0:
                    CACHE.parent.mkdir(parents=True, exist_ok=True)
                    CACHE.write_text(json.dumps(cached, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            except Exception:
                stats["api_errors"] += 1
                # Do not cache transient errors as permanent negative matches.
                continue
            time.sleep(0.27)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cached, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    paths = {}
    additional_editions = 0
    additional_groups = 0
    new_covered_editions = 0
    new_cover_editions = 0
    newly_covered_groups = 0
    for system, row in snapshot.items():
        names, aliases = row
        rows = {}
        groups_with_result = set()
        for name in names:
            group = aliases.get(base_title(name), base_title(name))
            old = cached.get(system + "|" + group)
            image_id = old.get("image_id") if isinstance(old, dict) else None
            url = _public_cover(image_id)
            if not url or (system, name) in suppressed:
                continue
            rows[name] = [url]
            additional_editions += 1
            groups_with_result.add(group)
            if (system, name) not in previous_refs:
                new_covered_editions += 1
            if (system, name) not in previous_covers:
                new_cover_editions += 1
        if rows:
            path = "data/igdb/" + hashlib.sha256(system.encode()).hexdigest()[:16] + ".json"
            target = out / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            paths[system] = path
            additional_groups += len(groups_with_result)
            for group in groups_with_result:
                editions = all_groups.get(system, {}).get(group, [])
                if editions and not any((system, edition) in previous_refs for edition in editions):
                    newly_covered_groups += 1

    index["igdb_art"] = paths
    report.update(
        igdb_enabled=True,
        igdb_additional_editions=additional_editions,
        igdb_additional_groups=additional_groups,
        igdb_newly_covered_editions=new_covered_editions,
        igdb_new_cover_editions=new_cover_editions,
        igdb_newly_covered_groups=newly_covered_groups,
        igdb_lookups_this_run=attempted,
        igdb_api_requests=stats["api_requests"],
        igdb_diagnostics=dict(stats),
    )
    report["game_editions_with_image_reference"] = report.get("game_editions_with_image_reference", 0) + new_covered_editions
    report["game_editions_without_image_reference"] = max(0, report.get("game_editions_without_image_reference", 0) - new_covered_editions)
    report["game_editions_with_cover_reference"] = report.get("game_editions_with_cover_reference", 0) + new_cover_editions
    report["game_title_groups_with_image_reference"] = min(
        report.get("game_title_groups", 0),
        report.get("game_title_groups_with_image_reference", 0) + newly_covered_groups
    )
    for _ in range(3):
        report["site_bytes"] = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
        index["report"] = report
        index_path.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        report_path.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("IGDB : " + str(attempted) + " recherches, " + str(additional_groups) + " groupes avec jaquette. Erreurs API : " + str(stats["api_errors"]))
    if report["site_bytes"] > 950_000_000:
        raise SystemExit("Site supérieur à 950 Mo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
