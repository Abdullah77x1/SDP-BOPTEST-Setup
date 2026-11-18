"""SDP_TEAM_RESEARCH_1.0.0: new campaigns, independent of frozen D2 ledgers."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from support import *
from legacy_dataset import NativeElectric

VERSION='SDP_TEAM_RESEARCH_1.0.0'
HERE=ROOT/'research'
SET='con_oveTSetCoo_u'
GROUP_KEYS=('start_time','warmup_seconds','steps','weather','occupancy')

def validate(config):
    allowed={'config_id','partition','start_time','warmup_seconds','steps','step_seconds','weather','occupancy','policy','cooling_setpoint_c','schedule'}
    if set(config)!=allowed: raise ValueError('Config has missing/unknown keys: '+str(set(config)^allowed))
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',config['config_id']): raise ValueError('Use a new simple config_id (letters/numbers/_/-)')
    if config['partition'] not in ('development','validation','test'): raise ValueError('Unknown partition')
    for key in ('start_time','warmup_seconds','steps','step_seconds'):
        if type(config[key]) is not int: raise ValueError('Integer required: '+key)
    if config['step_seconds']!=300 or not 3<=config['steps']<=2016: raise ValueError('Use 300-second steps, 3..2016 advances (maximum 7 days)')
    if config['warmup_seconds']!=604800: raise ValueError('This runner keeps the validated seven-day native warmup')
    if config['start_time']%300 or config['start_time']<604800 or config['start_time']+config['steps']*300>365*86400: raise ValueError('Period must align to 300s and stay within benchmark year with nonnegative warmup')
    if config['weather']!='packaged_denver_tmy' or config['occupancy']!='packaged_schedule': raise ValueError('Custom weather/occupancy is not implemented; changing labels does not change physics')
    if config['policy'] not in ('native','fixed_cooling','scheduled_cooling'): raise ValueError('Unknown policy')
    def setpoint(value):
        if type(value) not in (int,float) or not math.isfinite(value) or not 18<=value<=30: raise ValueError('Cooling setpoint must be finite, 18..30 C')
    if config['policy']=='fixed_cooling': setpoint(config['cooling_setpoint_c'])
    elif config['cooling_setpoint_c'] is not None: raise ValueError('cooling_setpoint_c must be null unless fixed_cooling')
    blocks=config['schedule']
    if not isinstance(blocks,list): raise ValueError('schedule must be a list')
    if config['policy']!='scheduled_cooling' and blocks: raise ValueError('Schedule only applies to scheduled_cooling')
    if config['policy']=='scheduled_cooling' and not blocks: raise ValueError('Add at least one daily schedule block')
    prior=0
    for block in blocks:
        if set(block)!= {'start_second','end_second','cooling_setpoint_c'}: raise ValueError('Unknown schedule keys')
        a,b=block['start_second'],block['end_second']
        if type(a) is not int or type(b) is not int or a%300 or b%300 or not prior<=a<b<=86400: raise ValueError('Daily blocks must be sorted, nonoverlapping and aligned to 300s')
        setpoint(block['cooling_setpoint_c']); prior=b
    return config

def command(config,time_s):
    result=dict.fromkeys(FLAGS,0)
    target=config['cooling_setpoint_c'] if config['policy']=='fixed_cooling' else None
    for block in config['schedule']:
        if block['start_second']<=time_s%86400<block['end_second']: target=block['cooling_setpoint_c']
    if target is not None: result.update({FLAGS[0]:1,SET:target+273.15})
    return result

def reserve(config,identity, registry):
    """Exclusive receipts prevent reused IDs and overlapping-time cross-split leakage."""
    registry.mkdir(parents=True,exist_ok=True)
    start=config['start_time']-config['warmup_seconds']; end=config['start_time']+config['steps']*300
    signature={'fmu':identity['source_fmu_sha256'],'weather':config['weather'],'occupancy':config['occupancy']}
    for file in registry.glob('*.json'):
        old=json.loads(file.read_text())
        if old['config_id']==config['config_id']: raise ValueError('config_id already reserved, including failed attempts; choose a genuinely new experiment')
        if old['physical_signature']==signature and max(start,old['window_start'])<min(end,old['window_end']) and old['partition']!=config['partition']:
            raise ValueError('Overlapping simulation/warmup periods cannot cross dataset partitions, even with different policies')
    group=digest({**signature,**{k:config[k] for k in GROUP_KEYS}})[:20]
    save(registry/(config['config_id']+'.json'),{'config_id':config['config_id'],'config_sha256':digest(config),
        'group_id':group,'partition':config['partition'],'window_start':start,'window_end':end,'physical_signature':signature})
    return group

def write_csv(path,rows):
    if not rows: raise ValueError('No rows to export')
    with path.open('x',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)

def export(config,group,endpoints,native,actions,directory):
    integrator=NativeElectric(native)
    intervals=[]
    for i,(a,b) in enumerate(zip(endpoints,endpoints[1:])):
        power=integrator.interval(a['time'],b['time'])
        intervals.append({'run_id':config['config_id'],'group_id':group,'partition':config['partition'],
            'start_time_s':a['time'],'end_time_s':b['time'],'indoor_start_c':a[TEMP]-273.15,
            'indoor_end_c':b[TEMP]-273.15,'outdoor_start_c':a[OUT]-273.15,
            'solar_start_w_m2':a[SOLAR],'cooling_plus_fan_interval_kw':power['average_kw'],
            'cooling_plus_fan_interval_kwh':power['kwh'],
            'command_cooling_override':actions[i]['command'][FLAGS[0]],
            'command_cooling_setpoint_c':actions[i]['command'].get(SET,'')-273.15 if SET in actions[i]['command'] else '',
            'effective_cooling_setpoint_end_c':b[SET]-273.15})
    write_csv(directory/'rc_intervals.csv',intervals)
    rows=[]
    # Inputs are available at the origin. Labels are deliberately separate y__ columns.
    for i in range(1,len(endpoints)-6):
        now=endpoints[i]
        row={'run_id':config['config_id'],'group_id':group,'partition':config['partition'],'origin_time_s':now['time'],
             'x__indoor_c':now[TEMP]-273.15,'x__outdoor_c':now[OUT]-273.15,
             'x__solar_w_m2':now[SOLAR],'x__cooling_plus_fan_last_5min_kw':intervals[i-1]['cooling_plus_fan_interval_kw'],
             'x__effective_cooling_c':now[SET]-273.15,'x__next_override_committed':actions[i]['command'][FLAGS[0]],
             'x__next_setpoint_committed_c':actions[i]['command'][SET]-273.15 if SET in actions[i]['command'] else ''}
        for horizon in (1,2,3,6):
            row[f'y__indoor_{horizon*5}min_c']=endpoints[i+horizon][TEMP]-273.15
            row[f'y__cooling_plus_fan_{horizon*5}min_kw']=intervals[i+horizon-1]['cooling_plus_fan_interval_kw']
        rows.append(row)
    if rows: write_csv(directory/'ml_ready.csv',rows)
    return {'rc_rows':len(intervals),'ml_rows':len(rows),'ml_note':'No ML rows if the recording is too short for all 30-minute labels'}

def collect(config):
    validate(config)
    directory=None; client=None
    result={'runner':VERSION,'status':'FAIL','cleanup':'NOT_ATTEMPTED','advances_completed':0,'data_origin':'REAL_BOPTEST_ONLY'}
    with activity():
        identity=runtime()
        # Check other local API clients before consuming this new configuration ID.
        directory=HERE/'outputs'/(config['config_id']+'_'+stamp()); directory.mkdir(parents=True)
        client=Client(BASE,directory,timeout=180)
        try:
            catalog(client); no_foreign_tests(client)
            group=reserve(config,identity,HERE/'registry')
            save(directory/'config.json',config); save(directory/'runtime.json',identity)
            result.update({'group_id':group,'partition':config['partition'],'config_sha256':digest(config),'seed':None,
                           'seed_note':'No random policy or forecast uncertainty; packaged deterministic weather/schedules'})
            client.deploy(); metadata=client.discover(); metadata_gate(metadata)
            actual=worker_identity(client.testid); save(directory/'deployed_fmu.json',actual)
            if actual['sha256']!=identity['source_fmu_sha256']: raise ValueError('Deployed FMU identity mismatch')
            # Require the actual channel units and limits before any control mutation.
            for key in (SET,'con_oveTSetHea_u',*FLAGS):
                if key not in metadata['inputs']: raise ValueError('Missing control channel '+key)
            if metadata['inputs'][SET]['Unit']!='K': raise ValueError('Cooling command unit changed')
            start=config['start_time']
            current=client.request('PUT','initialize',{'start_time':start,'warmup_period':config['warmup_seconds']})
            measurement_gate(current,start)
            client.request('PUT','step',{'step':300})
            if float(client.request('GET','step'))!=300: raise ValueError('Step readback mismatch')
            save(directory/'initial_conditions.json',current)
            save(directory/'scenario_readback.json',client.request('GET','scenario'))
            endpoints=[current]; actions=[]
            with (directory/'decisions.jsonl').open('x',encoding='utf-8') as journal:
                for i in range(config['steps']):
                    t=start+i*300; body=command(config,t)
                    if SET in body:
                        bounds=metadata['inputs'][SET]
                        if not bounds['Minimum']<=body[SET]<=bounds['Maximum']: raise ValueError('Setpoint outside actual API limits')
                        if body[SET]<current['con_oveTSetHea_u']+.5: raise ValueError('Cooling command violates 0.5 K heating/cooling deadband; run stopped')
                    decision={'time_s':t,'known_at_s':t,'command':body,'policy':config['policy'],'precommitted_config_sha256':digest(config)}
                    journal.write(json.dumps(decision)+'\n'); journal.flush(); actions.append(decision)
                    current=client.request('POST','advance',body)
                    measurement_gate(current,t+300)
                    for flag in FLAGS:
                        if abs(current[flag]-body[flag])>1e-6: raise ValueError('Override activation/release readback mismatch: '+flag)
                    if SET in body and abs(current[SET]-body[SET])>1e-5: raise ValueError('Cooling setpoint readback mismatch')
                    endpoints.append(current)
                    result['advances_completed']+=1
                    if i%12==0: print(f'{i+1}/{config["steps"]} advances',flush=True)
            save(directory/'endpoints.json',endpoints)
            native=client.request('PUT','results',{'point_names':[COOL,FAN],'start_time':start,'final_time':start+config['steps']*300})
            save(directory/'native_electrical_history.json',native)
            result['exports']=export(config,group,endpoints,native,actions,directory)
            result['status']='PASS_COLLECTION'
        except BaseException as exc:
            result['error']=f'{type(exc).__name__}: {exc}'
        finally:
            try: result['cleanup']=cleanup(client)
            except Exception as exc: result['status']='FAIL'; result['cleanup']='UNCONFIRMED'; result['cleanup_error']=str(exc)
            if result['status']!='PASS_COLLECTION':
                # Never make partial/failed exports look like usable training data.
                for name in ('rc_intervals.csv','ml_ready.csv'):
                    p=directory/name
                    if p.exists(): p.rename(directory/('QUARANTINED_'+name))
            save(directory/'RESULT.json',result)
            save(directory/'ARTIFACT_SHA256.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.iterdir()) if p.is_file()})
    print(result['status']+': '+str(directory))
    if 'error' in result: print(result['error'])
    return 0 if result['status']=='PASS_COLLECTION' else 1

def wizard():
    print('NEW research run. No dashboard is bundled; close other BOPTEST clients first.')
    name=input('New configuration ID (e.g. member1_summer_native_01): ').strip()
    day=int(input('Benchmark day index 7..364 (0 = Jan 1, e.g. 174): ') or '174')
    hours=float(input('Recording hours, max 168 [1]: ') or '1')
    mode=input('Policy: native / fixed_cooling / scheduled_cooling [native]: ').strip() or 'native'
    setting=float(input('Cooling setpoint C [24]: ') or '24') if mode!='native' else None
    config={'config_id':name,'partition':input('Partition: development / validation / test [development]: ').strip() or 'development',
        'start_time':day*86400,'warmup_seconds':604800,'steps':int(hours*12),'step_seconds':300,
        'weather':'packaged_denver_tmy','occupancy':'packaged_schedule','policy':mode,
        'cooling_setpoint_c':setting if mode=='fixed_cooling' else None,
        'schedule':[{'start_second':8*3600,'end_second':18*3600,'cooling_setpoint_c':setting}] if mode=='scheduled_cooling' else []}
    if hours*12!=config['steps']: raise ValueError('Hours must be a multiple of five minutes')
    validate(config)
    configs=HERE/'configs'; configs.mkdir(exist_ok=True)
    path=configs/(name+'.json'); save(path,config)
    print(json.dumps(config,indent=2))
    if input('Run this new simulation now? Type RUN to execute: ').strip()!='RUN':
        print('Saved only: '+str(path)); return 0
    return collect(config)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('operation',choices=['wizard','validate','run']); parser.add_argument('--config',type=Path)
    args=parser.parse_args()
    try:
        if args.operation=='wizard': code=wizard()
        else:
            if args.config is None: raise ValueError('--config PATH is required for validate/run')
            config=validate(json.loads(args.config.read_text(encoding='utf-8')))
            code=collect(config) if args.operation=='run' else 0
            if args.operation=='validate': print('PASS: configuration only; no API request or simulation')
        sys.exit(code)
    except Exception as exc: print('FAIL:',exc,file=sys.stderr); sys.exit(1)
