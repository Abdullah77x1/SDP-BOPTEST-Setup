# Capability and source audit

Audited the actual downloaded official v0.9.0 source, its `bestest_air/models/wrapped.mo`, `models/BESTESTAir`, `models/Resources`, compilation/data-generation scripts and local D2 sources. API reference: [official v0.9 guide](https://ibpsa.github.io/project1-boptest/docs-userguide/api.html). Local pinned source controls when a current web page differs.

| Variation | Physical support in pinned case | New runner |
|---|---|---|
| Different seasons/periods | `PUT initialize` chooses start seconds/warmup; `PUT scenario` also offers named periods | Custom aligned periods within packaged model year; fixed native seven-day warmup; 3..2016 advances |
| Cooling setpoint policy | `con_oveTSetCoo_u` in K plus activation flag; actual bounds checked | Native, fixed and daily scheduled cooling |
| Heating, fan, supply temperature | Exposed through their own overwrite channels in wrapped.mo | Not implemented; flags remain released |
| Electricity tariff | API scenario supports constant/dynamic/highly_dynamic | Original default remains; no tariff variation exposed by this runner |
| Forecast uncertainty | Scenario supports uncertainty parameters and seeds | Not exposed here; uncertainty changes forecasts, not the physical weather year |
| Different physical weather year/site | No live API weather-file replacement; physical ReaderTMY3 is embedded in the model | Pending model/resource rebuild |
| Different physical occupancy | No occupancy overwrite input in wrapped.mo; occupancy schedule drives thermal/latent/CO2 loads | Pending model/resource rebuild |
| More noisy sensors | Can be derived after recording, with recorded seed and clean/noisy distinction | Not implemented; cannot be represented as physical building changes |

The shipped weather is Denver/Stapleton TMY (`DRYCOLD.mos`); it is a typical meteorological year, not a collection of independent historical years. Choosing July instead of January changes which part of that weather sequence is simulated. Renaming occupancy/weather fields or altering a forecast does not change physical gains/weather. The new configuration validator rejects such requests.

## Exact pending work for physical occupancy/weather variants

Use a **separate custom test case and ID**, keeping `bestest_air` intact. `models/compile_fmu.py` currently compiles `BESTESTAir.TestCases.TestCase_Ideal`. It instantiates `BaseClasses.Case900FF`, which extends `Case600FF`.

For occupancy, modify `BaseClasses/OccupancyLoad.mo`'s `sch` CombiTimeTable and/or `Case600FF.mo`'s `occ_density` (currently 2/48), with coherent sensible/latent/CO2 gains. Review the separate lighting/plug schedules in `InternalLoad.mo` and thermostat occupancy schedule parameters (`Thermostat_T.mo`) rather than assuming they automatically follow people. To support runtime occupancy commands, design an explicit physical SignalExchange overwrite feeding those gains and recompile; no such input exists in the pinned wrapper.

For weather, replace the physical `ReaderTMY3.weaDat.filNam` resource reference in `Case600FF.mo` (currently a Buildings-library `DRYCOLD.mos` reference) with a correctly converted new weather resource. Check location, solar, humidity, time zone and annual coverage. Package the corresponding resource in the compiled FMU. The release also carries `models/Resources/DRYCOLD.mos` and generated `weather.csv`; changing only that forecast CSV does not change the embedded physical model.

Recompile/wrap with the original documented Modelica/Buildings toolchain (`models/library_versions.json`, `models/compile_fmu.py`, root `parsing/README.md`). Regenerate consistent resource data using `models/generate_data.py`; that script requires a baseline annual result CSV and generates weather, occupancy/internal-gain/setpoint boundary tables. Do not fabricate that prerequisite CSV. Review `config.json`, `days.json`, `kpis.json` and named-period discovery for the new model; do not reuse old timing/identity claims without qualification. Reprovision under a new case ID, record model/resource/toolchain hashes, and verify weather alignment, occupancy heat/CO2 response, forecasts, power integration, native control, override/release and cleanup. This rebuild/qualification is pending; no custom-weather or custom-occupancy case is distributed or claimed tested.

## Reuse decision for the historical D2 stack

Available in the original project:

- Collector **SDP_D2_COLLECTOR_1.0.1**, module `stage4e_d2i_1_v1_0_1`: collector, metadata-receipt correction, live entry and fabricated regression fixtures.
- Evidence adapter **SDP_D2_EVIDENCE_ADAPTER_1.1.0**, module `stage4e_d2_prep02`: adapter, SQLite registry, pair orchestration and preservation checks.
- Related `stage4e_d2i_1`, `stage4e_d0`, `stage4e_d1_v2`, `stage4e_runtime_preflight`, canonical manifests, control/schema checks, pairing and five-minute dataset primitives in `stage4e/dataset.py`.

Those original live entries bind canonical run slots, source hashes, consumed-attempt records, approval/prerequisite receipts, local container identities and fixed original paths. Copying a few files would not make a standalone portable D2 collector. We preserve them and do not manufacture authorizations, runtime qualification, raw data or reset ledgers. Their old README qualification state describes that historical package, not this new portable runner.

The new runner reuses the frozen transport adapter and copies **the whole unchanged `stage4e/dataset.py`** as `research/legacy_dataset.py`, importing its NativeElectric integration only. SOURCE_INVENTORY.json records source hashes. Other D2 controls informed explicit new checks; this is not a claim of full D2 equivalence. No original experiment output is shipped.
