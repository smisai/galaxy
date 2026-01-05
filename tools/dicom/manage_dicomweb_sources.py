#!/usr/bin/env python3
import argparse
import json
from copy import deepcopy
from typing import Optional

SCHEMA = "galaxy_dicomweb_sources_v1"

def load_catalog(path: Optional[str]) -> dict:
    if not path:
        return {"schema": SCHEMA, "sources": []}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "sources" not in data:
        raise SystemExit("Input catalog is not valid JSON catalog with 'sources'")
    data.setdefault("schema", SCHEMA)
    if not isinstance(data["sources"], list):
        raise SystemExit("'sources' must be a list")
    return data

def normalize_url(u: str) -> str:
    u = (u or "").strip()
    return u.rstrip("/") if u else u

def parse_caps(s: str) -> dict:
    if not s or not s.strip():
        return {}
    try:
        caps = json.loads(s)
    except Exception as e:
        raise SystemExit(f"Capabilities JSON parse error: {e}")
    if not isinstance(caps, dict):
        raise SystemExit("Capabilities JSON must be an object/dict")
    return caps

def upsert_source(catalog: dict, src: dict, must_exist: bool):
    sources = catalog["sources"]
    for i, s in enumerate(sources):
        if s.get("id") == src["id"]:
            sources[i] = src
            return
    if must_exist:
        raise SystemExit(f"Source id '{src['id']}' not found for update")
    sources.append(src)

def remove_source(catalog: dict, sid: str):
    before = len(catalog["sources"])
    catalog["sources"] = [s for s in catalog["sources"] if s.get("id") != sid]
    if len(catalog["sources"]) == before:
        raise SystemExit(f"Source id '{sid}' not found for removal")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=None)
    ap.add_argument("--action", choices=["add","update","remove"], required=True)
    ap.add_argument("--id", default="")
    ap.add_argument("--label", default="")
    ap.add_argument("--qido", default="")
    ap.add_argument("--wado", default="")
    ap.add_argument("--wado_uri", default="")
    ap.add_argument("--stow", default="")
    ap.add_argument("--auth_token", default="")
    ap.add_argument("--capabilities", default="")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    catalog = load_catalog(args.inp)
    catalog = deepcopy(catalog)

    if args.action in ("add","update"):
        sid = args.id.strip()
        if not sid:
            raise SystemExit("--id required for add/update")

        src = {
            "id": sid,
            "label": args.label.strip() or sid,
            "qidoRoot": normalize_url(args.qido),
            "wadoRoot": normalize_url(args.wado),
            "wadoUriRoot": normalize_url(args.wado_uri) or None,
            "stowRoot": normalize_url(args.stow) or None,
            "auth": {"token": args.auth_token.strip()} if args.auth_token.strip() else {},
            "capabilities": parse_caps(args.capabilities),
        }
        if not src["qidoRoot"] or not src["wadoRoot"]:
            raise SystemExit("qidoRoot and wadoRoot are required")

        upsert_source(catalog, src, must_exist=(args.action=="update"))

    elif args.action == "remove":
        sid = args.id.strip()
        if not sid:
            raise SystemExit("--id required for remove")
        remove_source(catalog, sid)

    catalog["schema"] = SCHEMA

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
