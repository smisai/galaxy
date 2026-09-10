#!/usr/bin/env python3
"""Build an OHIF "DICOM JSON" index for a Galaxy dicom_series dataset.

OHIF's dicomjson data source loads a study from a JSON document instead of a
DICOMweb server:

    {"studies": [{"StudyInstanceUID": ..., "series": [{"SeriesInstanceUID": ...,
        "instances": [{"metadata": {<naturalized header>}, "url": "dicomweb:<file url>"}]}]}]}

Every instance URL points at Galaxy's own composite-file endpoint
(``/api/datasets/<id>/display?filename=<file>``), so OHIF fetches pixels from
Galaxy through the SMIS gateway with the user's session; no DICOMweb server is
involved. URLs are root-relative on purpose: OHIF and Galaxy share the gateway
origin.
"""
import argparse
import json
import os
import sys

import pydicom
from pydicom.dataelem import DataElement
from pydicom.multival import MultiValue
from pydicom.sequence import Sequence
from pydicom.valuerep import PersonName

SKIP_VR = {"OB", "OW", "OF", "OD", "OL", "OV", "UN"}
STUDY_KEYS = ["StudyInstanceUID", "StudyDate", "StudyTime", "PatientName", "PatientID", "AccessionNumber",
              "PatientAge", "PatientSex", "StudyDescription"]
SERIES_KEYS = ["SeriesInstanceUID", "SeriesNumber", "SeriesDescription", "Modality", "SliceThickness", "SeriesDate"]


def jsonable(value):
    if isinstance(value, PersonName):
        return str(value)
    if isinstance(value, (MultiValue, list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, Sequence):
        return [naturalize(item) for item in value]
    if isinstance(value, bytes):
        return None
    if isinstance(value, (int, float, str)) or value is None:
        return value
    try:
        return float(value)  # DSValue / ISValue
    except (TypeError, ValueError):
        return str(value)


def naturalize(ds) -> dict:
    out = {}
    for elem in ds:
        assert isinstance(elem, DataElement)
        if elem.tag.is_private or elem.VR in SKIP_VR or elem.tag == 0x7FE00010 or not elem.keyword:
            continue
        v = jsonable(elem.value)
        if v is None and elem.VR != "SQ":
            continue
        out[elem.keyword] = v
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--series_dir", required=True, help="extra_files_path of the dicom_series dataset")
    ap.add_argument("--dataset_id", required=True, help="encoded Galaxy id of the dicom_series dataset")
    ap.add_argument("--url_prefix", default="/api/datasets", help="root-relative Galaxy dataset API prefix")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    files = sorted(f for f in os.listdir(args.series_dir) if f.lower().endswith(".dcm"))
    if not files:
        print("no .dcm files in series directory", file=sys.stderr)
        return 1

    studies = {}
    n = 0
    for name in files:
        path = os.path.join(args.series_dir, name)
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True)
        except Exception as e:  # noqa: BLE001
            print(f"skip {name}: {e}", file=sys.stderr)
            continue
        meta = naturalize(ds)
        study_uid = meta.get("StudyInstanceUID")
        series_uid = meta.get("SeriesInstanceUID")
        if not study_uid or not series_uid:
            print(f"skip {name}: missing Study/SeriesInstanceUID", file=sys.stderr)
            continue
        study = studies.setdefault(study_uid, {"StudyInstanceUID": study_uid, "series": {}})
        for k in STUDY_KEYS:
            study.setdefault(k, meta.get(k, ""))
        series = study["series"].setdefault(series_uid, {"SeriesInstanceUID": series_uid, "instances": []})
        for k in SERIES_KEYS:
            series.setdefault(k, meta.get(k, ""))
        series["instances"].append({
            "metadata": meta,
            "url": f"dicomweb:{args.url_prefix}/{args.dataset_id}/display?filename={name}",
        })
        n += 1

    out = {"studies": []}
    for study in studies.values():
        series_list = []
        for s in study["series"].values():
            s["instances"].sort(key=lambda i: (i["metadata"].get("InstanceNumber") or 0))
            series_list.append(s)
        study["series"] = series_list
        study["NumInstances"] = sum(len(s["instances"]) for s in series_list)
        study["Modalities"] = "/".join(sorted({s.get("Modality") or "" for s in series_list} - {""}))
        out["studies"].append(study)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    print(f"indexed {n} instances in {len(studies)} studies for dataset {args.dataset_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
