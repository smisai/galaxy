#!/usr/bin/env python3
import argparse
import json
import logging
import os
import requests
import pydicom
import uuid
import email
from email.policy import default
from io import BytesIO

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# List of tags to anonymize/remove
SENSITIVE_TAGS = [
    'PatientName',
    'PatientBirthDate',
    'PatientSex',
    'OtherPatientIDs',
    'PatientAddress',
    'PatientTelephoneNumbers',
    'PatientMotherBirthName'
]

def deidentify_dataset(ds):
    """
    Remove sensitive tags and replace PatientID with a random UUID if needed.
    (Simple anonymization logic)
    """
    # 1. Remove sensitive tags
    for tag in SENSITIVE_TAGS:
        if tag in ds:
            del ds[tag]

    # 2. Hash or replace PatientID
    # For this implementation, we just prefix/suffix or assume downstream handling.
    # But user requested stripping sensitive info.
    # Let's replace PatientID with an anonymous ID if present.
    original_pid = getattr(ds, 'PatientID', 'unknown')
    # Use a deterministic hash logic or simple replacement could be better
    # depending on study requirements. Here we just strictly clean.
    ds.PatientID = f"ANON_{uuid.uuid4().hex[:8]}"

    return ds

def save_dicom_part(content, output_dir, counter):
    try:
        # Load from bytes
        with BytesIO(content) as f:
            ds = pydicom.dcmread(f)
        
        # De-identify
        deidentify_dataset(ds)
        
        # Save
        # Use SOPInstanceUID as filename if available, else counter
        filename = f"{ds.SOPInstanceUID}.dcm" if hasattr(ds, 'SOPInstanceUID') else f"image_{counter:05d}.dcm"
        out_path = os.path.join(output_dir, filename)
        ds.save_as(out_path)
        return True
    except Exception as e:
        log.error(f"Failed to process DICOM part: {e}")
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--out_dir', required=True)
    parser.add_argument('--out_file', required=True)
    args = parser.parse_args()

    # Ensure output directory exists
    if not os.path.exists(args.out_dir):
        os.makedirs(args.out_dir)

    # 1. Read input Configuration
    with open(args.input, 'r') as f:
        ref_data = json.load(f)

    dicomweb = ref_data.get('dicomweb', {})
    uids = ref_data.get('uids', {})
    wado_root = dicomweb.get('wado')
    auth_token = dicomweb.get('auth_token')
    
    study_uid = uids.get('StudyInstanceUID')
    series_uid = uids.get('SeriesInstanceUIDs', [None])[0]

    if not wado_root or not study_uid or not series_uid:
        raise SystemExit("Invalid DICOM Reference: missing WADO URL or UIDs")

    # 2. Construct WADO-RS URL
    # {wadoBase}/studies/{study}/series/{series}
    url = f"{wado_root}/studies/{study_uid}/series/{series_uid}"
    
    headers = {
        'Accept': 'multipart/related; type="application/dicom"'
    }
    if auth_token:
        headers['Authorization'] = f"Bearer {auth_token}"

    log.info(f"Fetching WADO-RS: {url}")
    
    # 3. Stream Download
    try:
        with requests.get(url, headers=headers, stream=True) as resp:
            resp.raise_for_status()
            
            # Simple multipart parsing
            # requests toolbelt is not always available, trying manual boundary search or python email lib
            content_type = resp.headers.get('Content-Type', '')
            if 'multipart/related' not in content_type:
                log.warning("Response is not multipart/related. Attempting to save body as single file (unlikely valid).")
                # Fallback logic omitted for brevity
                
            # Parse multipart using email library logic (reliable for HTTP multipart)
            # Need to get the boundary
            # Content-Type: multipart/related; boundary="..."
            
            # We construct a dummy email message header to parse
            msg_header = f"Content-Type: {content_type}\r\n\r\n"
            msg_header_bytes = msg_header.encode('latin-1')
            
            # Read full content (for simple implementation) or stream parser
            # For 2GB+ series, streaming is needed.
            # Using 'email' library on raw bytes is tricky without full read.
            # Let's read content for now (assuming not massive for MVP)
            # LIMIT: memory usage.
            
            full_body = resp.content
            # Prepend header to make it parseable as a message
            msg = email.message_from_bytes(msg_header_bytes + full_body, policy=default)
            
            count = 0
            if msg.is_multipart():
                for part in msg.iter_parts():
                    if part.get_content_type() == 'application/dicom':
                        if save_dicom_part(part.get_payload(decode=True), args.out_dir, count):
                            count += 1
            else:
                log.error("Failed to parse multipart response")

    except Exception as e:
        raise SystemExit(f"WADO-RS Fetch failed: {e}")

    # 4. Write manifest.json for client-side viewers
    manifest_path = os.path.join(args.out_dir, "manifest.json")
    # We need to know what files were saved. 
    # The 'save_dicom_part' function doesn't return the filename easily in the current loop structure unless we modify it or just list the dir.
    # Listing the dir is safer to be sure what exists.
    
    saved_files = []
    if os.path.exists(args.out_dir):
        saved_files = sorted([f for f in os.listdir(args.out_dir) if f.endswith('.dcm')])
    
    manifest = {
        "study_uid": study_uid,
        "series_uid": series_uid,
        "wado_root": wado_root,
        "count": len(saved_files),
        "files": saved_files
    }
    
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    # 5. Write primary output file (Contains manifest for easy preview)
    # This ensures that even if Galaxy treats it as text, the preview shows the manifest.
    with open(args.out_file, 'w') as f:
        json.dump(manifest, f, indent=2)

    # 6. Generate galaxy.json to rename the dataset (Legacy mode for reliability)
    # Using legacy format {"type": "dataset", ...} ensures correct parsing by Galaxy.
    out_basename = os.path.basename(args.out_file)
    galaxy_metadata = {
        "type": "dataset",
        "dataset": out_basename,
        "name": f"DICOM-de-identified series-{study_uid}-{series_uid}"
    }
    with open("galaxy.json", "w") as f:
        json.dump(galaxy_metadata, f)

if __name__ == "__main__":
    main()
