# -*- coding: utf-8 -*-
"""
DICOM-related Galaxy datatypes for a Galaxy–Orthanc hybrid workflow.

Classes:
    - DICOM:         single-file DICOM instance (.dcm / .dicom)
    - DICOMSeries:   composite dataset representing a DICOM series
    - DICOMReference:JSON "pointer" to DICOM study/series via DICOMweb

Design:
    * DICOM        -> Binary (structured binary container; not a simple image)
    * DICOMSeries  -> Directory (composite: multiple .dcm files)
    * DICOMReference -> Text (JSON manifest, no pixels)
"""

import os
import logging
import glob
import json
from typing import Optional

from galaxy.datatypes.binary import Binary
from galaxy.datatypes.data import Directory, Text
from galaxy.datatypes.metadata import MetadataElement
from galaxy.datatypes.protocols import DatasetProtocol

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Single-file DICOM instance
# ---------------------------------------------------------------------------

class DICOM(Binary):
    """
    Single DICOM instance datatype.

    Typical use: RTSTRUCT, SEG, SR, RTPLAN, or any single .dcm file.
    """

    file_ext = "dicom"

    # Common instance-level metadata (study/series/instance)
    MetadataElement(name="study_uid",  default=None, desc="StudyInstanceUID",  readonly=True)
    MetadataElement(name="series_uid", default=None, desc="SeriesInstanceUID", readonly=True)
    MetadataElement(name="sop_uid",    default=None, desc="SOPInstanceUID",    readonly=True)
    MetadataElement(name="modality",   default=None, desc="Modality",          readonly=True)
    MetadataElement(name="patient_id", default=None, desc="PatientID",         readonly=True)
    MetadataElement(name="study_date", default=None, desc="StudyDate",         readonly=True)
    MetadataElement(name="body_part",  default=None, desc="BodyPartExamined",  readonly=True)

    def get_mime(self):
        # Standard DICOM MIME type
        return "application/dicom"

    # ---- Sniffer ---------------------------------------------------------

    def sniff(self, filename: str) -> bool:
        """
        Try to determine if a file is DICOM.

        1) Check "DICM" at offset 128 (standard DICOM preamble).
        2) Fallback: attempt a light pydicom parse without pixel data.
        """
        # Fast preamble check
        try:
            with open(filename, "rb") as fh:
                head = fh.read(132)
            if len(head) >= 132 and head[128:132] == b"DICM":
                log.info(f"sniffer: header check: DICOM Debug - File: {filename}")
                return True
        except Exception:
            # fall through to pydicom path
            pass

        # Fallback: pydicom sniff
        try:
            import pydicom
        except ImportError:
            # Cannot confirm without pydicom; be conservative
            log.info("DICOM Sniff: pydicom not installed")
            return False

        try:
            ds = pydicom.dcmread(filename, stop_before_pixels=True, force=True)
            log.info(f"sniff: DICOM Debug - File: {filename}, reading metadata")
            # Presence of standard identifiers is enough to treat as DICOM
            if hasattr(ds, "SOPClassUID") or hasattr(ds, "StudyInstanceUID"):
                log.info(f"Has StudyInstanceUID? {getattr(ds, 'StudyInstanceUID', None)}")
                log.info(f"Has SeriesInstanceUID? {getattr(ds, 'SeriesInstanceUID', None)}")
                log.info(f"Has PatientID? {getattr(ds, 'PatientID', None)}")
                log.info(f"Modality: {getattr(ds, 'Modality', None)}")
                return True
        except Exception:
            log.exception("Failed to read DICOM metadata in sniff")
            return False

        return False

    # ---- Metadata extraction ---------------------------------------------

    def set_meta(self, dataset: DatasetProtocol, overwrite: bool = True, **kwd) -> None:

        """
        Populate metadata from the DICOM header (without reading pixel data).

        Runs automatically after upload/tool execution if Galaxy metadata
        job handling is enabled.
        """
        try:
            import pydicom
        except ImportError:
            # pydicom not available; leave metadata as defaults
            return

        try:
            ds = pydicom.dcmread(dataset.get_file_name(), stop_before_pixels=True, force=True)
            log.info(f"set_metaDICOM Debug - File: {dataset.get_file_name()}")
            log.info(f"Has StudyInstanceUID? {getattr(ds, 'StudyInstanceUID', None)}")
            log.info(f"Has SeriesInstanceUID? {getattr(ds, 'SeriesInstanceUID', None)}")
            log.info(f"Has PatientID? {getattr(ds, 'PatientID', None)}")
            log.info(f"Modality: {getattr(ds, 'Modality', None)}")
        except Exception:
            log.exception("Failed to read DICOM metadata in set_meta")
            return

        md = dataset.metadata
        md.study_uid  = getattr(ds, "StudyInstanceUID",  None)
        md.series_uid = getattr(ds, "SeriesInstanceUID", None)
        md.sop_uid    = getattr(ds, "SOPInstanceUID",    None)
        md.modality   = getattr(ds, "Modality",          None)
        md.patient_id = getattr(ds, "PatientID",         None)
        md.study_date = getattr(ds, "StudyDate",         None)
        md.body_part  = getattr(ds, "BodyPartExamined",  None)


# ---------------------------------------------------------------------------
#  Multi-file DICOM series (composite dataset)
# ---------------------------------------------------------------------------

class DICOMSeries(Directory):
    """
    Composite Galaxy dataset representing a single DICOM series as a directory
    of individual .dcm instances.

    Expected storage layout in object store:

        dataset_XXX.dat              # stub (ignored by tools)
        dataset_XXX_files/           # dataset.extra_files_path
            000001.dcm
            000002.dcm
            ...
            MANIFEST.txt   (optional)

    We store series-level summary metadata, not per-slice metadata.
    """

    file_ext = "dicom_series"

    # Series-level metadata
    MetadataElement(name="study_uid",  default=None, desc="StudyInstanceUID",  readonly=True)
    MetadataElement(name="series_uid", default=None, desc="SeriesInstanceUID", readonly=True)
    MetadataElement(name="modality",   default=None, desc="Modality",          readonly=True)
    MetadataElement(name="patient_id", default=None, desc="PatientID",         readonly=True)
    MetadataElement(name="study_date", default=None, desc="StudyDate",         readonly=True)
    MetadataElement(name="body_part",  default=None, desc="BodyPartExamined",  readonly=True)
    MetadataElement(name="n_images",   default=0,    desc="Number of images",  readonly=True)

    def get_mime(self):
        # No single MIME describes a directory of DICOM files, but this is a hint.
        return "application/dicom"

    def set_meta(self, dataset: DatasetProtocol, overwrite: bool = True, **kwd) -> None:
        """
        Called by Galaxy after the dataset is created or after tools write it.

        - Locate the extra_files_path directory.
        - Count the .dcm files.
        - Sample one .dcm file for series-level metadata (StudyUID, SeriesUID,
          Modality, PatientID, StudyDate, BodyPart).
        """
        try:
            import pydicom
        except ImportError:
            # pydicom not available; we can still count files but not parse tags
            series_dir = dataset.extra_files_path
            if series_dir and os.path.isdir(series_dir):
                dcm_files = glob.glob(os.path.join(series_dir, "*.dcm"))
                dataset.metadata.n_images = len(dcm_files)
            return

        series_dir = dataset.extra_files_path
        if not series_dir or not os.path.isdir(series_dir):
            return

        dcm_files = sorted(glob.glob(os.path.join(series_dir, "*.dcm")))
        dataset.metadata.n_images = len(dcm_files)

        if not dcm_files:
            return

        # Read a single representative file for series-level tags
        try:
            ds = pydicom.dcmread(dcm_files[0], stop_before_pixels=True, force=True)
        except Exception:
            return

        md = dataset.metadata
        md.study_uid  = getattr(ds, "StudyInstanceUID",  None)
        md.series_uid = getattr(ds, "SeriesInstanceUID", None)
        md.modality   = getattr(ds, "Modality",          None)
        md.patient_id = getattr(ds, "PatientID",         None)
        md.study_date = getattr(ds, "StudyDate",         None)
        md.body_part  = getattr(ds, "BodyPartExamined",  None)

    def sniff(self, filename: str) -> bool:
        """
        In typical deployments, DICOMSeries datasets are created by tools
        (e.g. an Orthanc fetch tool) rather than uploaded directly.

        For that reason, we return False here and rely on explicit datatype
        assignment. If you later decide to allow uploads of pre-packed
        series directories, you could implement a custom sniffer.
        """
        return False


# ---------------------------------------------------------------------------
#  DICOM reference dataset (JSON pointer, no pixels)
# ---------------------------------------------------------------------------

class DICOMReference(Text):
    """
    JSON "pointer" datatype that references a DICOM study/series stored in
    an external DICOMweb-compatible server (e.g. Orthanc).

    The file contents are JSON, e.g.:

        {
          "dicomweb": {
            "qido": "https://orthanc.local/dicom-web",
            "wado": "https://orthanc.local/dicom-web",
            "stow": "https://orthanc.local/dicom-web"
          },
          "uids": {
            "StudyInstanceUID": "1.2.3.4...",
            "SeriesInstanceUIDs": ["1.2.3.4.1", "1.2.3.4.2"]
          },
          "tags": {
            "PatientID": "P123",
            "Modality": "MR",
            "StudyDate": "20250110"
          },
          "auth_profile": "orthanc-dev"
        }

    Tools and visualizations (e.g. OHIF) use this as a lightweight handle
    to query and stream actual DICOM data from Orthanc.
    """

    file_ext = "dicom_reference"

    # Summary metadata copied from the JSON "tags" section
    MetadataElement(name="study_uid",  default=None, desc="StudyInstanceUID",  readonly=True)
    MetadataElement(name="modality",   default=None, desc="Modality",          readonly=True)
    MetadataElement(name="patient_id", default=None, desc="PatientID",         readonly=True)
    MetadataElement(name="study_date", default=None, desc="StudyDate",         readonly=True)
    MetadataElement(name="description", default=None, desc="Study description", readonly=True)

    def get_mime(self):
        return "application/json"

    def sniff(self, filename: str) -> bool:
        """
        Detect JSON files that look like DICOMReference manifests.

        We check for top-level 'dicomweb' and 'uids' keys.
        """
        try:
            with open(filename, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return False

        if not isinstance(data, dict):
            return False

        has_dicomweb = isinstance(data.get("dicomweb"), dict)
        has_uids = isinstance(data.get("uids"), dict)
        return has_dicomweb and has_uids

    def set_meta(self, dataset: DatasetProtocol, overwrite: bool = True, **kwd) -> None:
        """
        Populate summary metadata from the JSON (if available).
        This gives you searchable fields in Galaxy for references.
        """
        try:
            with open(dataset.get_file_name(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return

        tags = data.get("tags", {}) or {}
        uids = data.get("uids", {}) or {}

        md = dataset.metadata
        md.study_uid   = uids.get("StudyInstanceUID") or tags.get("StudyInstanceUID")
        md.modality    = tags.get("Modality")
        md.patient_id  = tags.get("PatientID")
        md.study_date  = tags.get("StudyDate")
        md.description = tags.get("StudyDescription") or tags.get("SeriesDescription")
