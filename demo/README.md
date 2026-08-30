# QualFrame synthetic interview demo

This is a deterministic, network-free demonstration of the real QualFrame runner. It uses only the fictional transcripts and reference file under `demo/fixtures/` and replays checked-in stage responses from `demo/cached_responses/`.

Run from the repository root:

```powershell
python scripts\run_interview_demo.py
```

The command prints stage progress, verifies that exactly one deliberately seeded QA conflict reached the review queue, exports every parsed artifact to Excel, and writes the presentation page to `demo/presentation/index.html`.

The page is a read-only summary for an interview. It is not a general-purpose QualFrame UI, and its synthetic rows are not research evidence.

See `docs/interview_demo_handover.md` for the presenter script, smoke test, capability boundaries, and planned product increments.
