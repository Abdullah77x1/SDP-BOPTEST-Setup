"""Causal BOPTEST dataset primitives. All times are simulator seconds.

This module has no network or ML dependency. Export is deliberately limited to
marked previews; it cannot release pilot evidence as a training dataset.
"""
from __future__ import annotations
import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

TEMP = 'zon_reaTRooAir_y'
OUT = 'zon_weaSta_reaWeaTDryBul_y'
COOL = 'fcu_reaPCoo_y'
FAN = 'fcu_reaPFan_y'
SET = 'con_oveTSetCoo_u'
FLAG = 'con_oveTSetCoo_activate'
STEP = 300
HORIZONS = (300, 600, 900, 1800)
# Explicit whitelist: arbitrary labels, future measurements and hidden FMU states
# cannot be smuggled into the feature specification.
SIGNALS = {
    TEMP: ('indoor_c', -273.15, 1), OUT: ('outdoor_c', -273.15, 1),
    COOL: ('cooling_endpoint_kw', 0, .001),
    FAN: ('fan_endpoint_kw', 0, .001),
    SET: ('effective_cooling_c', -273.15, 1), FLAG: ('cooling_override', 0, 1),
    'con_oveTSetHea_u': ('effective_heating_c', -273.15, 1),
    'con_oveTSetHea_activate': ('heating_override', 0, 1),
    'fcu_oveFan_u': ('effective_fan_fraction', 0, 1),
    'fcu_oveFan_activate': ('fan_override', 0, 1),
    'fcu_oveTSup_u': ('supply_setpoint_c', -273.15, 1),
    'fcu_oveTSup_activate': ('supply_override', 0, 1),
    'zon_weaSta_reaWeaHGloHor_y': ('solar_global_wm2', 0, 1),
    'zon_weaSta_reaWeaHDifHor_y': ('solar_diffuse_wm2', 0, 1),
    'zon_weaSta_reaWeaHDirNor_y': ('solar_direct_wm2', 0, 1),
    'zon_reaPLig_y': ('lighting_kw', 0, .001),
    'zon_reaPPlu_y': ('plug_kw', 0, .001),
    'fcu_reaFloSup_y': ('supply_mass_flow_kgs', 0, 1),
    'zon_reaCO2RooAir_y': ('co2_ppm', 0, 1),
    'zon_weaSta_reaWeaRelHum_y': ('outdoor_rh_fraction', 0, 1),
}
BOUNDARIES = {'Occupancy[1]', 'LowerSetp[1]', 'UpperSetp[1]',
              'TDryBul', 'HGloHor', 'HDirNor', 'HDifHor'}


class ContractError(ValueError):
    pass


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ContractError('Missing/non-numeric/nonfinite signal or timestamp')
    return value


@dataclass
class Boundary:
    """Archived forecast/schedule, actually acquired at issued_at, for valid_at."""
    name: str
    issued_at: int
    valid_at: int
    value: float
    source: str = 'archived_boptest_forecast'


@dataclass
class Action:
    """A committed/proposed open-loop command, NOT a later realized decision."""
    start: int
    end: int
    known_at: int
    command: dict
    source: str = 'precommitted'


@dataclass
class Run:
    run_id: str
    scenario: str
    controller: str
    initialization_id: str
    weather_id: str
    group_id: str
    partition: str
    analysis_start: int
    analysis_end: int
    initialization_start: int
    endpoints: list[dict]
    native: dict | None = None
    boundaries: list[Boundary] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    status: str = 'completed'
    quarantined: bool = False
    provenance: str = 'fabricated_fixture'
    control_history: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class FeatureSpec:
    signals: tuple = (TEMP, OUT)
    lags: tuple = (0, 300, 600, 900, 1800)
    interval_power: bool = True
    calendar: bool = True
    # (API forecast point, offset seconds from origin). Offset zero is current.
    boundaries: tuple = ()


def validate_run(run):
    if run.status != 'completed' or run.quarantined:
        raise ContractError('Interrupted, quarantined or incomplete run is ineligible')
    if run.partition not in {'train', 'validation', 'protected_test', 'development'}:
        raise ContractError('Unknown partition')
    if not all((run.run_id, run.scenario, run.controller, run.initialization_id,
                run.weather_id, run.group_id)):
        raise ContractError('Missing run provenance')
    for t in (run.analysis_start, run.analysis_end, run.initialization_start): finite(t)
    if run.initialization_start > run.analysis_start or run.analysis_end <= run.analysis_start:
        raise ContractError('Invalid initialization/analysis window')
    if len(run.endpoints) < 2:
        raise ContractError('Insufficient endpoints')
    ts = [finite(s['time']) for s in run.endpoints]
    if any(b-a != STEP for a,b in zip(ts, ts[1:])):
        raise ContractError('Missing, duplicate, unordered or misaligned endpoint timestamp')
    if ts[0] > run.analysis_start or ts[-1] < run.analysis_end:
        raise ContractError('Endpoint coverage does not include analysis interval')
    if (run.analysis_start-ts[0]) % STEP or (run.analysis_end-ts[0]) % STEP:
        raise ContractError('Analysis boundary off endpoint grid')
    # Native history cannot be replaced with five-minute endpoint powers.
    if run.native is not None:
        times = run.native.get('time', [])
        if len(times) < 2: raise ContractError('Missing native history')
        for t in times: finite(t)
        if any(b<a or b-a>30 for a,b in zip(times,times[1:])):
            raise ContractError('Native history gap/order; 30-second maximum required')
        for key in (COOL, FAN):
            vals = run.native.get(key, [])
            if len(vals) != len(times): raise ContractError('Missing/misaligned native power')
            for v in vals: finite(v)


class NativeElectric:
    """Trapezoids of ordered native W samples, retaining event duplicates.

    Duplicate-time jumps have zero duration; the pre-event sample closes the
    preceding segment and post-event sample opens the next. No extrapolation,
    sparse endpoint substitution, invented zeros or negative-value clipping.
    Returns electrical joules, kWh, and interval-average kW.
    """
    def __init__(self,native):
        if native is None: raise ContractError('Native power unavailable; endpoint substitution prohibited')
        ts=native.get('time',[])
        if len(ts)<2: raise ContractError('Missing native timestamps')
        for t in ts: finite(t)
        if any(b<a or b-a>30 for a,b in zip(ts,ts[1:])):
            raise ContractError('Invalid native cadence')
        power=[]
        for name in (COOL,FAN):
            vals=native.get(name,[])
            if len(vals)!=len(ts): raise ContractError('Missing native electrical signal')
            power.append([finite(v) for v in vals])
        # Prefix integral makes all row/horizon queries O(1), rather than
        # rescanning an entire multi-day run for every feature and label.
        total=0.;self.cumulative={ts[0]:0.}
        for i in range(1,len(ts)):
            total+=sum((v[i-1]+v[i])*.5*(ts[i]-ts[i-1]) for v in power)
            self.cumulative[ts[i]]=total

    def interval(self,start,end):
        if end-start!=STEP: raise ContractError('Exactly one five-minute interval required')
        if start not in self.cumulative or end not in self.cumulative:
            raise ContractError('Native interval boundary absent')
        joules=self.cumulative[end]-self.cumulative[start]
        return {'joules':joules,'kwh':joules/3_600_000,'average_kw':joules/STEP/1000}


def interval_electric(native,start,end):
    return NativeElectric(native).interval(start,end)


def boundary_value(run, name, valid_at, origin):
    if name not in BOUNDARIES: raise ContractError('Boundary not approved for features')
    matches=[]
    for b in run.boundaries:
        for v in (b.issued_at,b.valid_at,b.value): finite(v)
        if b.source != 'archived_boptest_forecast':
            raise ContractError('Unverified boundary provenance')
        if b.name==name and b.valid_at==valid_at and b.issued_at<=origin:
            matches.append(b)
    if not matches: raise ContractError('No boundary vintage available at prediction origin')
    latest=max(b.issued_at for b in matches)
    values={b.value for b in matches if b.issued_at==latest}
    if len(values)!=1: raise ContractError('Conflicting boundary vintage')
    return values.pop()


def known_actions(run, origin, horizon):
    result=[]
    allowed={SET,FLAG,'con_oveTSetHea_activate','fcu_oveFan_activate','fcu_oveTSup_activate'}
    for t in range(origin,origin+horizon,STEP):
        candidates=[a for a in run.actions if a.start==t and a.end==t+STEP
                    and a.known_at<=origin and a.source in {'precommitted','proposed'}]
        if len(candidates)!=1:
            raise ContractError('Action path unavailable/ambiguous at origin; no realized-action backfill')
        a=candidates[0]
        for v in (a.start,a.end,a.known_at): finite(v)
        if not set(a.command)<=allowed or FLAG not in a.command:
            raise ContractError('Unsupported/missing future command')
        cmd=dict(a.command)
        for v in cmd.values(): finite(v)
        for flag in [FLAG,'con_oveTSetHea_activate','fcu_oveFan_activate','fcu_oveTSup_activate']:
            if cmd.get(flag,0) not in (0,1): raise ContractError('Non-binary command flag')
        if any(cmd.get(f,0) for f in allowed-{SET,FLAG}):
            raise ContractError('Only cooling intervention in this prepared contract')
        if cmd[FLAG] and (SET not in cmd or not 278.15<=cmd[SET]<=308.15):
            raise ContractError('Invalid proposed cooling setpoint')
        result.append({'start':t,'end':t+STEP,'known_at':a.known_at,
                       'source':a.source,'command':cmd})
    return result


def build_rows(run, spec=FeatureSpec(), task='observational', partition_window=None):
    """Return marked rows in memory; no training/export side effect.

    Edge origins without full lookback/horizon are excluded. Interior gaps and
    missing requested channels are errors, not imputed or silently dropped.
    partition_window is [first allowed support time,last allowed support time].
    """
    validate_run(run)
    if run.partition=='protected_test': raise ContractError('Protected evaluation access denied in preparation')
    if task not in {'observational','action_conditioned'}: raise ContractError('Unknown task')
    if not spec.lags or 0 not in spec.lags or len(set(spec.lags))!=len(spec.lags):
        raise ContractError('Unique lags including current value required')
    if any(not isinstance(x,int) or x<0 or x%STEP for x in spec.lags):
        raise ContractError('Lags must be nonnegative five-minute multiples')
    if any(s not in SIGNALS for s in spec.signals): raise ContractError('Unapproved feature signal')
    if any(n not in BOUNDARIES or not isinstance(o,int) or o<0 or o>1800 or o%STEP
           for n,o in spec.boundaries): raise ContractError('Invalid boundary feature')
    lo,hi=partition_window or (run.analysis_start,run.analysis_end)
    if lo<run.analysis_start or hi>run.analysis_end or hi<=lo:
        raise ContractError('Partition window outside eligible analysis')
    index={e['time']:e for e in run.endpoints}
    electric=NativeElectric(run.native)
    rows=[]
    lookback=max(spec.lags)+(STEP if spec.interval_power else 0)
    for origin in sorted(index):
        support_start=origin-lookback
        if support_start<lo or origin+max(HORIZONS)>hi: continue
        features={}
        for lag in spec.lags:
            e=index.get(origin-lag)
            if e is None: raise ContractError('Lag endpoint missing')
            for signal in spec.signals:
                alias,offset,scale=SIGNALS[signal]
                features[f'{alias}__lag{lag}s']=(finite(e.get(signal))+offset)*scale
            if spec.interval_power:
                features[f'hvac_interval_kw__lag{lag}s']=electric.interval(
                    origin-lag-STEP,origin-lag)['average_kw']
        if spec.calendar:
            angle=2*math.pi*(origin%86400)/86400
            features.update(time_day_sin=math.sin(angle),time_day_cos=math.cos(angle),
                            benchmark_day=int(origin//86400))
        for name,offset in spec.boundaries:
            features[f'boundary::{name}__plus{offset}s']=boundary_value(run,name,origin+offset,origin)
        targets={}
        for horizon in HORIZONS:
            end=origin+horizon
            e=index.get(end)
            if e is None: raise ContractError('Target endpoint missing')
            interval=electric.interval(end-STEP,end)
            targets[f'indoor_c__plus{horizon}s']=finite(e.get(TEMP))-273.15
            targets[f'hvac_interval_kw__plus{horizon}s']=interval['average_kw']
        action_path=known_actions(run,origin,max(HORIZONS)) if task=='action_conditioned' else []
        rows.append({'classification':'DEVELOPMENT_PREVIEW_NOT_TRAINING_RELEASE',
            'run_id':run.run_id,'scenario':run.scenario,'controller':run.controller,
            'initialization_id':run.initialization_id,'initialization_start':run.initialization_start,
            'weather_id':run.weather_id,'group_id':run.group_id,'partition':run.partition,
            'provenance':run.provenance,'task':task,'origin_time':origin,
            'observed_control_state':{k:v for k,v in index[origin].items()
                if k.endswith('_activate') or k.endswith('_u')},
            'support_start':support_start,'support_end':origin+max(HORIZONS),
            'features':features,'targets':targets,'known_action_path':action_path})
    return rows


def validate_partitions(runs, embargo=3600):
    """No split of matched/overlapping runs, shared initialization or group.

    Use complete candidate runs, not selected outcome-dependent subwindows.
    Warmup footprint is included. Equal weather file alone is not sufficient
    dependence; overlapping/nearby windows within that file are grouped.
    """
    if embargo<0: raise ContractError('Negative embargo')
    for r in runs: validate_run(r)
    if len({r.run_id for r in runs})!=len(runs): raise ContractError('Duplicate run ID')
    for i,a in enumerate(runs):
        for b in runs[i+1:]:
            related=(a.group_id==b.group_id or a.initialization_id==b.initialization_id)
            if a.weather_id==b.weather_id:
                related |= max(a.initialization_start,b.initialization_start) <= min(a.analysis_end,b.analysis_end)+embargo
            if related and a.partition!=b.partition:
                raise ContractError('Dependent trajectory group crosses partitions')
    return True


def write_preview(rows, path):
    """Exclusive-create JSONL: never overwrite evidence or claim release."""
    if not rows: raise ContractError('No preview rows')
    if any(r.get('classification')!='DEVELOPMENT_PREVIEW_NOT_TRAINING_RELEASE'
           or r.get('partition')=='protected_test' for r in rows):
        raise ContractError('Training/protected release prohibited')
    with Path(path).open('x',encoding='utf-8') as f:
        for r in rows: f.write(json.dumps(r,allow_nan=False)+'\n')


def read_stage4c(directory, arm):
    """Read-only adapter for preserved local A/B. Never approves training use."""
    d=Path(directory)
    status=json.loads((d/'status.json').read_text())
    if status.get('classification')!='VERIFIED_COLLECTION': raise ContractError('Unverified pilot collection')
    if arm not in {'A','B'}: raise ContractError('Unknown arm')
    plan=json.loads((d/'frozen_plan.json').read_text())
    with (d/f'{arm}_observations_SI.csv').open(newline='',encoding='utf-8-sig') as f:
        endpoints=[{k:float(v) for k,v in row.items() if k!='sample_kind'} for row in csv.DictReader(f)]
    native=json.loads((d/'native_results.json').read_text())
    # Only actual archived forecast vintages are admissible, never a weather-file
    # reconstruction labelled as if it had been issued by the operational API.
    boundaries=[]
    advanced=False
    for line in (d/'raw_api.jsonl').read_text().splitlines():
        record=json.loads(line)
        if '/advance/' in record['url']: advanced=True
        if record.get('method')=='PUT' and '/forecast/' in record['url'] and record.get('http_status')==200:
            if advanced: raise ContractError('Adapter cannot establish later forecast issue time')
            import base64
            response=json.loads(base64.b64decode(record['raw_body_base64']))
            data=response.get('payload',response)
            # Stage4C's sole forecast was obtained at the initialized start,
            # before any advances. Adapter refuses non-matching history below.
            issued=plan['scenario_start']
            if data['time'][0]!=issued: raise ContractError('Unproven forecast issue time')
            for key,values in data.items():
                if key=='time' or key not in BOUNDARIES: continue
                if len(values)!=len(data['time']): raise ContractError('Misaligned forecast')
                boundaries.extend(Boundary(key,issued,t,v) for t,v in zip(data['time'],values))
    with (d/f'{arm}_commands.csv').open(newline='',encoding='utf-8-sig') as f:
        control_history=list(csv.DictReader(f))
    return Run(f'stage4c_{arm}',plan['scenario'],'native' if arm=='A' else 'fixed_pulse',
        f'stage4c_{arm}_initialization','bestest_air_v090_weather','exposed_peak_cool_family',
        'development',plan['scenario_start'],plan['scenario_start']+plan['evaluation_seconds'],
        plan['scenario_start']-plan['warmup_seconds'],endpoints,native,boundaries,
        provenance='preserved_stage4c_development_only',control_history=control_history)


def read_stage4d(directory, interrupted=False):
    """Stage4D has endpoints, NOT integrated power history; full rows must fail."""
    if interrupted: raise ContractError('Interrupted Stage4D evidence is excluded')
    d=Path(directory)
    state=json.loads((d/'FINAL_DASHBOARD_STATE.json').read_text())
    if not state.get('budget_complete') or state.get('error') is not None:
        raise ContractError('Stage4D completion not verified')
    # The state history is a UI subset; full advance observations are canonical.
    steps=[json.loads(s) for s in (d/'autonomous_steps.jsonl').read_text().splitlines()]
    if not steps: raise ContractError('No Stage4D observations')
    # Recover the full initialization from the actual successful scenario response,
    # never reverse-convert rounded UI fields into raw simulator measurements.
    first=None
    import base64
    for line in (d/'connection_0001/raw_api.jsonl').read_text().splitlines():
        r=json.loads(line)
        if '/scenario/' in r['url'] and r.get('method')=='PUT' and r.get('http_status')==200:
            response=json.loads(base64.b64decode(r['raw_body_base64']))
            first=response.get('payload',response).get('time_period')
            break
    if not isinstance(first,dict) or TEMP not in first:
        raise ContractError('Full initial observation unavailable')
    endpoints=[first]+[s['observation'] for s in steps]
    start=steps[0]['start']
    return Run('stage4d_replacement','peak_cool_day','comfort_rule','stage4d_replacement_init',
        'bestest_air_v090_weather','exposed_peak_cool_family','development',start,steps[-1]['end'],
        start-604800,endpoints,None,status='completed',
        provenance='preserved_stage4d_development_only',
        control_history=[{'start':s['start'],'end':s['end'],'command':s['command'],
                          'sent_utc':s['sent_utc'],'received_utc':s['received_utc']}
                         for s in steps])
