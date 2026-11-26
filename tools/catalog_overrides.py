"""Persistent, reviewed catalogue corrections shared by every published visitor."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILE = ROOT / "data" / "catalog-overrides.json"
ALLOWED_IMAGE_SOURCES = {"all", "fixed", "libretro", "launchbox", "gametdb", "openvgdb", "steamgriddb", "igdb"}


def load_overrides(path=DEFAULT_FILE):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "excluded": [], "title_overrides": [], "image_exclusions": []}
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Format catalog-overrides.json invalide")
    for field in ("excluded", "title_overrides", "image_exclusions"):
        if not isinstance(data.get(field, []), list):
            raise ValueError("Liste invalide: " + field)
    result = {k: list(data.get(k, [])) for k in ("excluded", "title_overrides", "image_exclusions")}
    result["version"] = 1
    seen = set()
    for row in result["excluded"]:
        system, title = _key(row)
        key = (system, title)
        if key in seen:
            raise ValueError("Exclusion en double: " + system + " / " + title)
        seen.add(key)
    seen.clear()
    for row in result["title_overrides"]:
        system, title = _key(row)
        replacement = row.get("replacement")
        if not isinstance(replacement, str) or not replacement.strip() or len(replacement) > 300:
            raise ValueError("Titre corrigé invalide")
        key = (system, title)
        if key in seen:
            raise ValueError("Correction en double: " + system + " / " + title)
        seen.add(key)
    seen.clear()
    for row in result["image_exclusions"]:
        system, title = _key(row)
        source = row.get("source", "all")
        if source not in ALLOWED_IMAGE_SOURCES:
            raise ValueError("Source d'image inconnue: " + str(source))
        key = (system, title, source)
        if key in seen:
            raise ValueError("Exclusion d'image en double")
        seen.add(key)
    return result


def _key(row):
    if not isinstance(row, dict):
        raise ValueError("Entrée de correction invalide")
    system, title = row.get("system"), row.get("title")
    if not isinstance(system, str) or not system.strip() or len(system) > 200:
        raise ValueError("Plateforme invalide")
    if not isinstance(title, str) or not title.strip() or len(title) > 300:
        raise ValueError("Titre invalide")
    return system, title


def apply_catalog_overrides(merged, overrides):
    """Apply exact platform/title corrections before indexing any artwork source."""
    stats = {"catalog_excluded_titles": 0, "catalog_renamed_titles": 0}
    excluded = {(r["system"], r["title"]) for r in overrides["excluded"]}
    for system, title in excluded:
        if system in merged and title in merged[system]:
            merged[system].remove(title)
            stats["catalog_excluded_titles"] += 1

    corrections = {(r["system"], r["title"]): r["replacement"] for r in overrides["title_overrides"]}
    for (system, old), new in corrections.items():
        names = merged.get(system)
        if names is None or old not in names:
            continue
        names.remove(old)
        names.add(new)
        stats["catalog_renamed_titles"] += 1
    return stats


def apply_image_exclusions(out, overrides, images, source_indexes):
    """Remove only selected artwork references; catalogue entries remain untouched."""
    import hashlib
    import json
    from pathlib import Path

    out = Path(out)
    stats = {"catalog_image_references_removed": 0}
    by_key = {}
    for row in overrides["image_exclusions"]:
        key = (row["system"], row["title"])
        by_key.setdefault(key, set()).add(row.get("source", "all"))

    for (system, title), sources in by_key.items():
        key = json.dumps([system, title], ensure_ascii=False, separators=(",", ":"))
        if "all" in sources or "fixed" in sources:
            if key in images:
                del images[key]
                stats["catalog_image_references_removed"] += 1
        for source in ("libretro", "launchbox", "gametdb", "openvgdb"):
            if "all" not in sources and source not in sources:
                continue
            field = {"libretro": "art", "launchbox": "launchbox_art", "gametdb": "gametdb_art", "openvgdb": "openvgdb_art"}[source]
            path = source_indexes.get(field, {}).get(system)
            if not path:
                continue
            file = out / path
            try:
                payload = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows = payload.get("rows", {}) if source == "libretro" else payload
            if isinstance(rows, dict) and title in rows:
                del rows[title]
                stats["catalog_image_references_removed"] += 1
                if source == "libretro":
                    payload["rows"] = rows
                file.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return stats
