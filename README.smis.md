# SMIS's Galaxy fork (`smisai/galaxy`)

SMIS runs Galaxy from this fork. The fork carries only what a Galaxy plugin cannot do; everything that
Galaxy's extension points can carry (tools, visualization plugins, workflows, interactive tools, job
routing) lives in `smisai/smis-galaxy-extensions`. See `docs/SMIS_Repository_Organization.md` in the
SMIS core repository.

## What the fork adds to upstream Galaxy

| Change | Files | Status |
|---|---|---|
| DICOM datatypes: `dicom`/`dcm` (single instance), `dicom_series` (composite), `dicom_reference` (DICOMweb pointer), with sniffers | `lib/galaxy/datatypes/dicom.py`; registrations in `lib/galaxy/config/sample/datatypes_conf.xml.sample` | to be offered upstream as a pull request |
| `hocr` datatype points at `galaxy.datatypes.text:Html` (the `galaxy.datatypes.html` module it named no longer exists) | `lib/galaxy/config/sample/datatypes_conf.xml.sample` | to be offered upstream |

The SMIS and DICOM tools that were here until 2026-10-27 moved, with their history, to
`smis-galaxy-extensions` (`tools/smis`, `tools/dicom`).

## Upstream

- Follows Galaxy's `dev` branch; GitHub branch `dev` is upstream `dev` plus the changes above.
- Last upstream merge: `dev` at 118e885c52 (2026-09-10; Galaxy 26.2.dev, after `release_26.1`).
- To take a newer upstream: merge upstream `dev` (or a release branch) into `dev`, re-run SMIS's
  end-to-end tests, and update the line above.

## Working with the checkout in SMIS

SMIS's deployment bind-mounts this checkout into the Galaxy appliance container, which rewrites
`config/` and `tool-data/` when it starts. Restore them before any git operation:
`git checkout -- config tool-data`.
