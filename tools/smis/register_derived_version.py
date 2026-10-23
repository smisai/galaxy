#!/usr/bin/env python3
"""Register the objects a Galaxy step wrote into the research plane as a derived version (SMIS design §6.4, F1.1).

The step that produced the objects (a segmentation, a dose calculation, a converter) stored them into a
research DICOMweb source; this step tells the SMIS manifest service what was done: the next version of
the dataset = the source version plus those series, read back by the service from the source (never taken
from this tool's word), with the transformation record built from the Galaxy job: actor (the step's tool,
or the user for a manual step), tool name and version, parameters, the Galaxy job, history and user.

  register_derived_version.py --manifest-url URL --dataset ID --source-version N --objects objects.txt
      --kind computation --identifiability pseudonymized --tool-name T --tool-version V
      [--container-digest sha256:...] [--actor-kind tool|human|llm] [--prompt-version P]
      [--research-source research-dicomweb] [--title T] [--parameters JSON] [--galaxy-workdir DIR]
      [--galaxy-history H] [--galaxy-user EMAIL] [--dry-run] --out receipt.json

objects.txt: one "study_uid series_uid" (or "study_uid,series_uid") per line; '#' comments; or a JSON list
of {"study_uid", "series_uid"} objects. Exit 1 with the service's reason when the version is refused.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import requests


def read_objects(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("["):
        items = json.loads(text)
        return [{"study_uid": str(o["study_uid"]), "series_uid": str(o["series_uid"])} for o in items]
    out = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = re.split(r"[,\s\t]+", line)
        if len(parts) < 2:
            raise SystemExit(f"objects: expected 'study_uid series_uid', got {line!r}")
        out.append({"study_uid": parts[0], "series_uid": parts[1]})
    if not out:
        raise SystemExit("objects: no series listed")
    return out


def galaxy_job_id(workdir: str | None) -> str | None:
    """Galaxy's job working directory ends in .../<n>/<job id>; the id is the last all-digit component."""
    if not workdir:
        return None
    for part in reversed(Path(workdir).parts):
        if part.isdigit():
            return part.lstrip("0") or "0"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest-url", default=os.environ.get("MANIFEST_SERVICE_URL", "http://manifest-service:5000"))
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--source-version", type=int, required=True)
    ap.add_argument("--objects", type=Path, required=True)
    ap.add_argument("--kind", required=True, choices=["curation", "preprocessing", "harmonization", "computation"])
    ap.add_argument("--identifiability", required=True, choices=["identified", "pseudonymized", "de-identified-unlinked", "aggregate", "model"])
    ap.add_argument("--actor-kind", default="tool", choices=["tool", "human", "llm"])
    ap.add_argument("--prompt-version")
    ap.add_argument("--tool-name", required=True)
    ap.add_argument("--tool-version", required=True)
    ap.add_argument("--container-digest")
    ap.add_argument("--research-source", default="research-dicomweb")
    ap.add_argument("--title")
    ap.add_argument("--description")
    ap.add_argument("--parameters", default="{}", help="JSON object: the declared inputs that changed the outcome")
    ap.add_argument("--galaxy-workdir")
    ap.add_argument("--galaxy-history")
    ap.add_argument("--galaxy-user")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    objects = read_objects(a.objects)
    try:
        parameters = json.loads(a.parameters or "{}")
        if not isinstance(parameters, dict):
            raise ValueError("not an object")
    except ValueError as e:
        raise SystemExit(f"--parameters must be a JSON object: {e}")
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    actor = {"kind": a.actor_kind, "id": a.galaxy_user if a.actor_kind == "human" and a.galaxy_user else a.tool_name, "version": a.tool_version}
    if a.prompt_version:
        actor["prompt_version"] = a.prompt_version
    tool = {"name": a.tool_name, "version": a.tool_version}
    if a.container_digest:
        tool["container_digest"] = a.container_digest
    transformation = {"kind": a.kind, "actor": actor, "identifiability": a.identifiability, "tool": tool,
                      "parameters": {**parameters, **({"galaxy_user": a.galaxy_user} if a.galaxy_user else {})},
                      "started": now, "finished": now}
    if a.description:
        transformation["description"] = a.description
    derivation = {"transformation": transformation, "inputs": [{"dataset_id": a.dataset, "version": a.source_version}]}
    job_id = galaxy_job_id(a.galaxy_workdir)
    if job_id:
        derivation["galaxy"] = {"job_id": job_id}
    body = {"source": {"dataset_id": a.dataset, "version": a.source_version}, "derivation": derivation,
            "objects": {"source": a.research_source, "series": objects}, "dry_run": a.dry_run}
    if a.title:
        body["dataset"] = {"title": a.title}
    url = f"{a.manifest_url.rstrip('/')}/manifests/{a.dataset}/versions"
    r = requests.post(url, json=body, timeout=900)
    try:
        reply = r.json()
    except ValueError:
        reply = {"raw": r.text[:2000]}
    receipt = {"request": {"url": url, "dataset": a.dataset, "source_version": a.source_version, "n_series": len(objects),
                           "transformation": transformation, "galaxy": {"job_id": job_id, "history_id": a.galaxy_history}},
               "status_code": r.status_code, "response": reply}
    if r.ok and not a.dry_run:
        lin = requests.get(f"{a.manifest_url.rstrip('/')}/manifests/{a.dataset}/lineage", params={"version": reply.get("version")}, timeout=60)
        if lin.ok:
            receipt["lineage"] = [f"{n['dataset_id']}@v{n['version']}" for n in lin.json().get("nodes", [])]
    a.out.write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if not r.ok or (a.dry_run and not reply.get("ok", False)):
        detail = reply.get("detail", reply) if isinstance(reply, dict) else reply
        report = (detail.get("report") if isinstance(detail, dict) else None) or (reply.get("report") if isinstance(reply, dict) else None)
        if report:
            errs = [f"{f['code']} {f['path']}: {f['message']}" for f in report.get("findings", []) if f.get("severity") == "error"]
            print(f"refused ({r.status_code}): " + "; ".join(errs[:10]), file=sys.stderr)
        else:
            msg = detail.get("message", detail) if isinstance(detail, dict) else detail
            print(f"refused ({r.status_code}): {json.dumps(msg)[:1500]}", file=sys.stderr)
        return 1
    if a.dry_run:
        print(f"dry run: {a.dataset}@v{reply.get('version')} would register (report ok)")
    else:
        print(f"registered {a.dataset}@v{reply.get('version')} ({len(objects)} series); lineage {' -> '.join(receipt.get('lineage', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
