"""Persistent, reviewed catalogue corrections shared by every published visitor."""
import json
import re
import unicodedata
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


def _title_key(value):
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]", "", text)


def apply_catalog_overrides(merged, overrides):
    """Apply exact platform/title corrections after catalogue enrichment and before remaining indexes."""
    stats = {"catalog_excluded_titles": 0, "catalog_renamed_titles": 0, "catalog_renamed_pairs": []}
    excluded = [(r["system"], r["title"]) for r in overrides["excluded"]]
    for system, title in excluded:
        names = merged.get(system)
        if names is None:
            continue
        matches = [name for name in names if _title_key(name) == _title_key(title)]
        if len(matches) == 1:
            names.remove(matches[0])
            stats["catalog_excluded_titles"] += 1

    corrections = {(r["system"], r["title"]): r["replacement"] for r in overrides["title_overrides"]}
    for (system, old), new in corrections.items():
        names = merged.get(system)
        if names is None:
            continue
        matches = [name for name in names if _title_key(name) == _title_key(old)]
        if len(matches) != 1:
            continue
        names.remove(matches[0])
        names.add(new)
        stats["catalog_renamed_titles"] += 1
        stats["catalog_renamed_pairs"].append([system, matches[0], new])
    return stats


def apply_image_exclusions(out, overrides, images, source_indexes):
    """Remove only selected artwork references; catalogue entries remain untouched."""
    import json
    from pathlib import Path

    out = Path(out)
    stats = {"catalog_image_references_removed": 0}
    by_key = {}
    for row in overrides["image_exclusions"]:
        key = (row["system"], row["title"])
        by_key.setdefault(key, set()).add(row.get("source", "all"))

    for (system, title), sources in by_key.items():
        if "all" in sources or "fixed" in sources:
            for image_key in list(images):
                try:
                    image_system, image_title = json.loads(image_key)
                except (TypeError, ValueError):
                    continue
                if image_system == system and _title_key(image_title) == _title_key(title):
                    del images[image_key]
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
            matching_titles = [name for name in rows if _title_key(name) == _title_key(title)] if isinstance(rows, dict) else []
            if matching_titles:
                removed = [rows.pop(name) for name in matching_titles]
                if source == "libretro":
                    stats["catalog_image_references_removed"] += len(removed)
                else:
                    stats["catalog_image_references_removed"] += sum(len(value) if isinstance(value, list) else 1 for value in removed)
                if source == "libretro":
                    payload["rows"] = rows
                file.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return stats
