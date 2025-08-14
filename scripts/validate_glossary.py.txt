import json, os, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GDIR = ROOT / "glossary"
TERMS = GDIR / "terms"
INDEX = GDIR / "index.json"
SCHEMA = GDIR / "schema.v1.json"

errors = []

def load_json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        errors.append(f"[JSON] {p}: {e}")
        return None

def is_slug(s):
    return bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", s))

index = load_json(INDEX) or {}
files = index.get("files") or []
if not isinstance(files, list) or not files:
    errors.append("index.json must have a non-empty 'files' array.")

# 1) each file exists and is a slug
seen_ids = set()
for entry in files:
    fn = entry if isinstance(entry, str) else entry.get("file")
    if not fn:
        errors.append("index.json contains an invalid file entry (neither string nor {file:..}).")
        continue
    if "/" in fn or "\\" in fn:
        errors.append(f"File entry should be a basename only: {fn}")
    if not is_slug(fn.replace(".json","")):
        errors.append(f"Bad filename/slug: {fn} (use lowercase-hyphen format)")
    path = TERMS / fn
    if not path.exists():
        errors.append(f"Listed in index but missing on disk: {fn}")
        continue
    obj = load_json(path)
    if obj is None:
        continue
    # 2) id either missing or equals slug (enforce for consistency)
    slug = path.stem
    tid = obj.get("id", slug)
    if tid != slug:
        errors.append(f"{fn}: id '{tid}' should match filename slug '{slug}'")
    # 3) require at least a name
    names = obj.get("names", [])
    if not names:
        errors.append(f"{fn}: 'names' must contain at least one title string")
    # 4) duplicate ids
    if tid in seen_ids:
        errors.append(f"Duplicate id: {tid}")
    seen_ids.add(tid)

# 5) optional: validate tags against your palette (comment out if not needed)
TAGS = (GDIR / "tags.json")
if TAGS.exists():
    tags = set(json.loads(TAGS.read_text(encoding="utf-8")).keys())
    for fn in files:
        path = TERMS / (fn if isinstance(fn, str) else fn.get("file",""))
        if not path.exists(): continue
        obj = load_json(path) or {}
        for t in obj.get("tags", []):
            if t not in tags:
                errors.append(f"{path.name}: tag '{t}' not defined in tags.json")

if errors:
    print("\n❌ Glossary validation failed:\n- " + "\n- ".join(errors))
    sys.exit(1)
print("✅ Glossary validation passed.")
