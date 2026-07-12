# 2026-07 Model Output Thumbnails

- Checked: 2026-07-12
- Issue: #66
- R2 prefix: `s3://3dgen-runs/site-data`

## Status

The canonical Windows GPU lane generated and published a real model-output thumbnail for every
successful benchmark cell. The final R2 audit found 274 fresh thumbnails, zero stale objects, and
zero failures. `partcrafter/chrome-espresso-machine` remains the single declared benchmark failure
and correctly has no thumbnail.

- Success cells: 274
- Declared failure cells: 1
- Final R2 inventory: 1,167 objects, including 274 `thumb.webp` objects
- Render fingerprint: `015a8dde0dd2c8d38e4c0d0f0aeeb62128b712b17a154e6769ae2103a77a458a`
- Output format: static 320 x 320 WebP with alpha, quality 85
- Total thumbnail bytes: 1,377,128
- Mean / minimum / maximum: 5,026.01 / 770 / 16,252 bytes

## Canonical Run

The final publish ran from `2026-07-11T18:15:01.432Z` through
`2026-07-11T18:28:13.331Z` (791.899 seconds) and rendered all 274 objects. Every cell reported:

```text
ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Ti (0x00002782) Direct3D11
vs_5_0 ps_5_0, D3D11)
```

The pinned render stack was Playwright 1.61.1, Chromium 149.0.7827.55 revision 1228, Three.js
0.185.1, Sharp 0.35.3, and Vite 8.1.3. The recipe uses the production viewer's orientation fix,
unit-box framing, camera `(1.2, 0.9, 1.6)`, RoomEnvironment/PMREM, and ACES filmic tone mapping.

An earlier process from a superseded fingerprint was found still running after its parent command
had been interrupted. Its process tree was stopped before a clean replacement pass. The final
pre-commit review then caught that removing an extra trailing blank line from a fingerprinted render
source had changed the recipe hash. The entire matrix was deliberately rendered once more under the
final clean-tree fingerprint above. The independent full audit below proves that none of the
superseded metadata remained.

## R2 Integrity Audit

The check-only pass ran from `2026-07-11T18:28:28.108Z` through
`2026-07-11T18:29:20.150Z` (52.042 seconds):

| Result | Count |
| --- | ---: |
| Fresh | 274 |
| Rendered | 0 |
| Stale | 0 |
| Failed | 0 |

For each cell, the audit re-read and decoded the WebP, checked its byte hash and dimensions, matched
the current source GLB ETag and size, and validated the stored source SHA-256, render fingerprint,
backend, and output SHA-256 metadata. Source reads and thumbnail writes use conditional S3 requests,
and source identity is checked again after publish so a concurrent GLB replacement cannot produce a
mixed cell.

## Manifest Probe

A real R2 `triposr/cartoon-apple/thumb.webp` was combined with the matching published GLB metadata
in a gitignored probe directory and passed `bench-harness site-data-snapshot --allow-partial`.
The resulting entry contained:

```text
/run-assets/triposr/cartoon-apple/thumb.webp?v=fe0d32b0cf3e5e76d5779bd07a1c1b58b9821c678a163a46f1b17391750e8c85
```

This confirms that the published bytes pass the Python/Pillow contract and that the manifest uses
the complete WebP SHA-256 for cache busting.

## Visual QA

The actual R2 `cartoon-apple` thumbnail was downloaded and inspected for all 11 models. All samples
were framed inside the square and rendered with transparent backgrounds. Textured models retained
their colors; geometry-only TripoSG and Direct3D-S2 results appeared as light PBR silhouettes, which
matches their material-less GLBs rather than indicating an image fallback. Additional local
production-output checks covered the SF3D arcade cabinet and TripoSR medieval longsword.

The Hunyuan thumbnail follows the same Worker authorization path as its GLB. Worker tests cover both
GET and HEAD denial before any R2 read for blocked regions.

## Command Shape

```powershell
pnpm thumbnail:generate -- s3://3dgen-runs/site-data `
  --expected-failure partcrafter/chrome-espresso-machine `
  --backend gpu `
  --report ../outputs/thumbnail-generation-report.json

pnpm thumbnail:check -- s3://3dgen-runs/site-data `
  --expected-failure partcrafter/chrome-espresso-machine `
  --backend gpu `
  --report ../outputs/thumbnail-check-report.json
```

The reports remain under gitignored `outputs/`; the stable render fingerprint and aggregate results
are recorded here for repository history.
