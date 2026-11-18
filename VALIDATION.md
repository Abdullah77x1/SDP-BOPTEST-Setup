# Validation and limitations of this GitHub share package

## Tests performed for this repository variant

This repository is adapted from the previously supplied `BOPTEST_Team_Minimal(1).zip` (the v1.1 team package). The Stage 4D dashboard and legacy demo code were omitted; the research collector and frozen transport/source copies remain unchanged. Packaging changes include removing the demo-aware shutdown dependency and updating distribution integrity checks.

Offline Python tests are run against the material in this repository, including configuration validation, example CSV integration, overlap/split guards and source-integrity checks. **These offline tests do not prove a Docker installation works on the recipient's Windows computer.** On November 18, 2026, the extracted GitHub-ready copy was checked using Python 3.13 in this packaging environment: **17 unit tests passed, 2 Windows-only tests were skipped**, the distribution integrity check passed, and the sample experiment configuration validated without contacting BOPTEST. The runtime launchers still require Python 3.12; no Windows execution was performed here.

## Earlier recorded evidence from the original v1.1 package

The original `VALIDATION_REPORT.md` provided in the prior ZIP describes a prior live BOPTEST deployment, real short recording checks, and a relocated Windows installation. These claims apply to the **original v1.1 package**, not automatically to this dashboard-free GitHub derivative. That original report also includes a dashboard test, which is intentionally out of scope here.

A fresh end-to-end Docker installation, live `bestest_air` verification, and short collector run **should be repeated on a teammate's or advisor's computer** using this distribution before claiming fresh-device support. Docker is unavailable in this packaging environment; no new live BOPTEST run was performed for this version.

## What is and isn't implemented

- Included: original model downloader, local Docker stack, short live verification tool, five-minute dataset collector, native/fixed/scheduled cooling setpoints, period selection within one packaged model year, QA/cleanup receipts.
- Not included: Stage 4D dashboard, full original D2 collector, extra weather years, runtime-changing physical occupancy, trained ML or autonomous optimization, complete campaign evidence.
- Generated research outputs belong in `research/outputs/`, which is ignored by Git. Preserve full outputs separately for analysis.
