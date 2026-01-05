#!/usr/bin/env python3
import argparse
import json
import logging
import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def load_source_config(catalog_path, source_id):
    with open(catalog_path, 'r') as f:
        catalog = json.load(f)
    
    for src in catalog.get('sources', []):
        if src['id'] == source_id:
            return src
    raise ValueError(f"Source ID '{source_id}' not found in catalog")

def query_qido(source_config, study_uid, series_uid):
    qido_root = source_config['qidoRoot']
    auth = source_config.get('auth', {})
    headers = {}
    
    if 'token' in auth:
        headers['Authorization'] = f"Bearer {auth['token']}"
    
    # QIDO-RS: Search for Series
    # URL: {qidoBase}/studies/{study}/series?SeriesInstanceUID={series}
    # Using vague search to verify existence and get tags
    url = f"{qido_root}/studies/{study_uid}/series"
    params = {'SeriesInstanceUID': series_uid}
    
    log.info(f"Querying QIDO-RS: {url}")
    try:
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise SystemExit(f"Failed to query QIDO-RS: {e}")

    if not data or len(data) == 0:
        raise SystemExit(f"Series {series_uid} not found in Study {study_uid}")
    
    # Return first match (should be unique for UID)
    return data[0]

def dicom_json_to_flat_tags(dicom_json):
    # Flatten QIDO JSON (00100020: {Value: [..]}) to generic tags
    # This is a simplified mapping for the JSON manifest
    tags = {}
    
    # Helper to extract value
    def get_val(tag_id):
        tag = dicom_json.get(tag_id, {})
        if 'Value' in tag and tag['Value']:
            return tag['Value'][0]
        return None

    # DICOM Tags map
    TAG_MAP = {
        '0020000D': 'StudyInstanceUID',
        '0020000E': 'SeriesInstanceUID',
        '00080060': 'Modality',
        '00100020': 'PatientID',
        '00080020': 'StudyDate',
        '00081030': 'StudyDescription',
        '0008103E': 'SeriesDescription'
    }

    for tag_id, name in TAG_MAP.items():
        val = get_val(tag_id)
        # Handle dict/name struct if complex
        if isinstance(val, dict) and 'Alphabetic' in val:
             val = val['Alphabetic']
        tags[name] = val
        
    return tags

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--source_id', required=True)
    parser.add_argument('--study_uid', required=True)
    parser.add_argument('--series_uid', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    # 1. Load Config
    try:
        src = load_source_config(args.catalog, args.source_id)
    except Exception as e:
        raise SystemExit(str(e))

    # 2. Query QIDO
    qido_metadata = query_qido(src, args.study_uid, args.series_uid)
    
    # 3. Extract Tags
    tags = dicom_json_to_flat_tags(qido_metadata)
    
    # 4. Construct Output JSON
    output_data = {
        "dicomweb": {
            "qido": src.get('qidoRoot'),
            "wado": src.get('wadoRoot'),
            "stow": src.get('stowRoot'),
            "auth_profile": src.get('id')
        },
        "uids": {
            "StudyInstanceUID": args.study_uid,
            "SeriesInstanceUIDs": [args.series_uid]
        },
        "tags": tags
    }
    
    # Add auth token if present (WARNING: Persisting sensitive token in dataset)
    # Ideally should rely on source_id lookup, but for standalone reference, copying token.
    if 'auth' in src and 'token' in src['auth']:
        output_data['dicomweb']['auth_token'] = src['auth']['token']

    with open(args.out, 'w') as f:
        json.dump(output_data, f, indent=2)

if __name__ == "__main__":
    main()
