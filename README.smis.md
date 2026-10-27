# SMIS's Galaxy fork (`smisai/galaxy`)

SMIS runs Galaxy from this fork, branch **`smis/release_26.1`**, which starts at Galaxy's release tag
**`v26.1.2`** (2026-10-25). The fork carries only what a Galaxy plugin cannot do; everything Galaxy's
extension points can carry (tools, visualization plugins, workflows, interactive tools, job routing)
lives in `smisai/smis-galaxy-extensions`. See `docs/SMIS_Repository_Organization.md` in the SMIS core
repository.

## What the fork adds to Galaxy v26.1.2

| Change | Files |
|---|---|
| DICOM datatypes: `dicom`/`dcm` (single instance; `dcm` overrides upstream's `images:Dicom` registration), `dicom_series` (composite), `dicom_reference` (DICOMweb pointer), with sniffers | `lib/galaxy/datatypes/dicom.py`; registrations in `lib/galaxy/config/sample/datatypes_conf.xml.sample` |

The datatypes stay in the fork; they are not offered upstream (project decision, 2026-10-27).

## History

- Until 2026-10-27 SMIS followed Galaxy's `dev` (branch `dev` on this fork, kept for its history: the
  datatypes' original commits and the SMIS tools before they moved to `smis-galaxy-extensions`).
- 2026-10-27: moved to the release line. The Galaxy database was downgraded by three migrations
  (`e96dd6fd5863` → `fac9c76612f9`, 26.1.2's head) with Galaxy's own `scripts/db.py downgrade`.

## Taking a newer Galaxy release

Point releases (26.1.x): merge the new tag into `smis/release_26.1`. A new minor (26.2): branch
`smis/release_26.2` from its tag, re-apply the change above, rebuild the Galaxy image (its venv follows
`lib/galaxy/dependencies/pinned-requirements.txt`), run SMIS's suites, and update
`deployment/versions.yaml` in SMIS core. Never run an unreleased Galaxy against the SMIS database:
it migrates the schema forward, and going back needs a downgrade.

## Working with the checkout in SMIS

SMIS's deployment bind-mounts this checkout into the Galaxy appliance container, which rewrites
`config/` and `tool-data/` when it starts. Restore them before any git operation:
`git checkout -- config tool-data`.
