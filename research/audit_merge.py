"""Reject cross-device duplicate runs and overlapping-period split leakage."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from run import validate

def audit(directories):
    records=[]; identifiers=set()
    for directory in directories:
        directory=Path(directory)
        seal=json.loads((directory/'ARTIFACT_SHA256.json').read_text())
        actual={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file() and p.name!='ARTIFACT_SHA256.json'}
        if actual!=seal: raise ValueError('Run artifacts were changed after collection: '+directory.name)
        config=validate(json.loads((directory/'config.json').read_text()))
        result=json.loads((directory/'RESULT.json').read_text())
        runtime=json.loads((directory/'runtime.json').read_text())
        if result['status']!='PASS_COLLECTION' or result['cleanup']!='STOP_ACK_AND_INSTANCE_DIRECTORY_REMOVED': raise ValueError('Incomplete/unconfirmed run: '+config['config_id'])
        if config['config_id'] in identifiers: raise ValueError('Duplicate config_id across devices: '+config['config_id'])
        identifiers.add(config['config_id'])
        records.append({'id':config['config_id'],'signature':(runtime['source_fmu_sha256'],config['weather'],config['occupancy']),
            'partition':config['partition'],'start':config['start_time']-config['warmup_seconds'],
            'end':config['start_time']+config['steps']*300})
    if not records: raise ValueError('No completed run directories supplied')
    for i,a in enumerate(records):
        for b in records[i+1:]:
            if a['signature']==b['signature'] and max(a['start'],b['start'])<min(a['end'],b['end']) and a['partition']!=b['partition']:
                raise ValueError('Cross-device overlapping periods have different partitions: '+a['id']+' / '+b['id'])
    return {'status':'PASS_PARTITION_AUDIT','runs':len(records),
        'note':'No models fitted or CSVs merged. Keep all rows of each recorded physical period in its assigned partition.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_directories',nargs='+',type=Path)
    try: print(json.dumps(audit(parser.parse_args().run_directories),indent=2))
    except Exception as exc: print('FAIL:',exc,file=sys.stderr); sys.exit(1)
