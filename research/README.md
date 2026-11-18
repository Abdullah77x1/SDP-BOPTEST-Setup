# Independent research runner 1.0.0

This is a new collector, **SDP_TEAM_RESEARCH_1.0.0**. It is separate from Stage 4D and from the historical D2 collector/adapter; it does not consume, reset or emulate their ledgers. It produces new simulator recordings and CSVs. It does not train ML, calibrate RC models, establish energy savings, or claim to reproduce the complete D2 acceptance pipeline.

## Beginner workflow

Use `GENERATE_DATASET.cmd` and its guided prompts. The default one-hour recording has 12 five-minute advances after a seven-day native warmup. For useful identification, plan longer windows and independent held-out periods; a short smoke test is not a research dataset. The runner caps each recording at seven days to prevent accidental annual jobs. Benchmark day **0 is Jan 1**; these are model-year times, not today's calendar dates. The wizard starts at midnight; the advanced configuration can use any aligned start time within the packaged year, with a nonnegative seven-day warmup.

Available policies:

- `native`: embedded thermostat, with all external override flags explicitly released.
- `fixed_cooling`: override only the cooling setpoint throughout the recording.
- `scheduled_cooling`: daily nonoverlapping five-minute-aligned blocks; release to native outside them. The wizard creates an 08:00–18:00 block; advanced JSON can define several blocks.

Cooling values are entered in degrees C and converted to K for the API. The runner checks actual input bounds and a 0.5 K heating/cooling deadband against the current heating setpoint. It stops if the requested command is invalid; it does not silently change it. Heating/fan/supply-temperature policies are not implemented here.

Advanced commands, from the extracted folder after setup (no source editing required):

```powershell
.\.venv\Scripts\python.exe -B research\run.py validate --config research\example_native.json
.\.venv\Scripts\python.exe -B research\run.py run --config research\example_native.json
```

Give every new attempt a new configuration ID. `example_native.json` is a template; copy it and use a unique ID. A failed attempt remains reserved. Each recording creates a new timestamped output folder; existing files are never overwritten. There is no automatic resume, initialization retry or advance retry. Raw API receipts record mutation attempts. A lost select response can leave an unknown testid; cleanup is then explicitly UNCONFIRMED and must be investigated.

## What is recorded

`config.json` records the policy, 300-second step, seven-day warmup and exact start/duration. `runtime.json` records the API/model version, Docker version, image IDs, official FMU SHA-256 and new runner source hashes. `deployed_fmu.json` checks the actual deployed FMU against that source. `initial_conditions.json`, `scenario_readback.json`, `runtime_metadata.json`, `raw_api.jsonl`, `decisions.jsonl`, `endpoints.json` and `native_electrical_history.json` retain raw measurements, settings, decisions and native-cadence power history. The default has no randomization and records seed=null; no claim of seed-based weather variation is made.

Only a `RESULT.json` with `PASS_COLLECTION` and confirmed removal is usable. Partial CSVs from a failure are renamed with `QUARANTINED_`. The final artifact manifest seals that output. This is collection QA, not scientific acceptance or evidence that the data are sufficiently exciting for identification.

## CSV meaning and units

`rc_intervals.csv` has start/end temperature in C, start weather, committed cooling commands, endpoint effective cooling setting, and interval cooling-plus-fan electrical demand in kW and kWh. Retained raw endpoints and native history allow more RC features to be derived later. No undocumented heat-gain parameters are invented.

`ml_ready.csv` separates `x__` origin-time features from `y__` future labels. It uses indoor/outdoor temperature, solar, the **previous** interval's cooling-plus-fan average, current effective cooling setting and the next precommitted command. The committed-setpoint column is empty when override is released; do not fill it with a future realized setting. Targets are indoor temperature and cooling-plus-fan interval-average kW at +5/+10/+15/+30 minutes. At +30, power covers minutes 25–30, not the whole half hour. A 12-step recording produces six ML origins. Shorter recordings can produce no ML file; this is reported.

Power averages integrate the actual ordered native W history using the unchanged `NativeElectric` primitive from the original `stage4e/dataset.py`. Event duplicates are preserved and native gaps greater than 30 seconds are rejected. The runner never substitutes sparse endpoint power for interval averages. Raw API outputs are simulator measurements; degrees-C conversion, electrical sums/integrals, feature rows and future targets are derived quantities. No scaling, imputation or clipping is performed.

The old simulator's **“AC”** label meant its own HVAC demand variable. Here the electrical target is **cooling equipment electricity + fan electricity**. Gas/delivered heating, lighting and plugs are excluded. This is a better-specified boundary, not proof that the old AC series measured the same thing.

## Avoid misleadingly low ML errors

Assign entire physical periods to development/validation/test **before** inspecting errors. All paired policies, overlapping windows and warmups must stay in one partition. Our registry rejects cross-partition overlap for the same model/weather/occupancy; paired runs get the same group ID. It does not randomly split rows or fit transforms. Do not train on `y__`, run/group/partition identifiers, future endpoints or posthoc outcomes. Fit scaling/feature selection only on training groups; tune on validation and reserve final test groups.

Each computer has its own registry. Coordinate a shared period/partition plan across all four members before merging CSVs; the local guard cannot detect somebody else's run. Group by connected overlapping warmup/recording windows when merging; different group IDs alone are insufficient. A single TMY year and fixed occupancy limit independence/generalization. Report persistence baselines, active-equipment subsets, startup periods and error by forecast horizon. Native thermostat data can be very predictable; that alone does not establish leakage or real-world accuracy.

Exchange complete successful run folders, not only CSVs. Before combining data from devices, run the cross-device guard with all intended run directories:

```powershell
.\.venv\Scripts\python.exe -B research\audit_merge.py "path to first completed run" "path to second completed run"
```

It verifies the recorded file seal and rejects duplicate configuration IDs, incomplete cleanup and overlapping warmup/recording periods assigned to different partitions. It does not merge files or fit a model. A FAIL must be resolved in the experiment/split plan before ML use; do not bypass it by randomly splitting rows.
