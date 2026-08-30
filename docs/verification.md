# Public snapshot verification

Checked on 2026-08-30 using Windows and Python 3.11.7. This is software verification on synthetic data, not methodological validation or a live-provider benchmark.

| Check | Observed result |
| --- | --- |
| Automated tests | 91 passed; 1 optional private-workbook test skipped |
| Python compilation | Source and scripts compiled successfully |
| Synthetic workspace launcher | Two fictional transcripts; four offset/hash-validated evidence records; no external model calls |
| Browser review | Three accepts and one edit recorded; 4/4 records resolved |
| Derived edit | Separate reviewer-derived artifact retained; prior source/output records preserved |
| Export gate | Export unavailable while review was incomplete; available after complete resolution |
| Export contents | Four evidence records; Excel sheets Evidence, Review History, Methods; no error-typed cells |
| CFIR cached demo | Five stages; nine artifacts; nine Excel exports; one deliberate QA conflict |
| UI checks | Shared setup, import, method, overview, and evidence views inspected; actual screenshots captured |
| Narrow layout | 390px viewport requested; 375px content/client width after scrollbar; no horizontal overflow on evidence screen |
| Browser console | No warning/error entries observed during the checked workflow |
| Package build | Wheel built locally; packaged workspace stylesheet confirmed present |
| Reference preservation | All 15 prompt Markdown/framework YAML files byte-identical to the source checkout |
| License and citation | MIT license and matching CITATION.cff included in the public selection; citation request is not an extra license condition |

## Reproduce

```bash
python -m pytest -q
python -m compileall -q src scripts
python scripts/run_workspace_demo.py --dry-run
python scripts/run_workspace_demo.py --no-serve
python scripts/run_interview_demo.py
python scripts/package_public_release.py --dry-run
```

The release packager selects source/configuration/documentation and synthetic fixtures explicitly. It omits runtime studies, raw data, outputs, build caches, credentials, and Git history, scans selected text for common secret/private-path patterns, checks blank environment examples and local Markdown links, and can write a ZIP with a SHA-256 inventory. Screenshots require separate visual review. These checks reduce release risk; they are not a comprehensive security audit.

## What was not verified

- Live provider requests, current model pricing, or SMTP delivery.
- Model coding quality, calibration accuracy, clinical utility, or research findings.
- Hosted deployment, authenticated users, or production security.
- A full accessibility audit or performance/load benchmark.
- The GitHub Actions matrix: it is configured for Windows/Linux and Python 3.11/3.12 but has not run remotely before publication.

The two README screenshots are unaltered captures of the functioning local interface using synthetic content. The evidence-review image shows the completed synthetic review state reached through actual browser actions.
