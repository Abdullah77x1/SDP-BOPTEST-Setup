"""A real three-advance disposable installation check, separate from all demos."""
import argparse
import json
import platform
import sys
from integrity import check
from support import *

def verify(offline=False):
    directory = ROOT/'verification'/stamp(); directory.mkdir(parents=True)
    report = {'status':'FAIL','kind':'OFFLINE_ONLY' if offline else 'LIVE_INSTALLATION_TEST',
              'python':platform.python_version(),'advances_completed':0,'cleanup':'NOT_ATTEMPTED'}
    client = None
    try:
        check()
        if sys.version_info[:2]!=(3,12): raise RuntimeError('Python 3.12 required')
        if offline:
            report['status']='PASS_OFFLINE_ONLY'; report['live_simulation']='UNVERIFIED'
        else:
            with activity():
                try:
                    report['runtime']=runtime()
                    client = Client(BASE,directory,timeout=180)
                    catalog(client); no_foreign_tests(client)
                    client.deploy(); meta=client.discover(); metadata_gate(meta)
                    report['deployed_fmu']=worker_identity(client.testid)
                    if report['deployed_fmu']['sha256']!=report['runtime']['source_fmu_sha256']: raise ValueError('Deployed FMU differs from official source')
                    start=174*86400
                    current=client.request('PUT','initialize',{'start_time':start,'warmup_period':604800})
                    measurement_gate(current,start)
                    client.request('PUT','step',{'step':300})
                    if float(client.request('GET','step'))!=300: raise ValueError('Step readback mismatch')
                    report['initialization']={'start_time':start,'warmup_period':604800,'step':300}
                    report['observations']=[]
                    for i in range(3):
                        current=client.request('POST','advance',dict.fromkeys(FLAGS,0))
                        measurement_gate(current,start+(i+1)*300)
                        report['observations'].append(current); report['advances_completed']+=1
                    report['status']='PASS'
                finally:
                    if client:
                        try: report['cleanup']=cleanup(client)
                        except Exception as exc:
                            report['status']='FAIL'; report['cleanup']='UNCONFIRMED'; report['cleanup_error']=str(exc)
    except Exception as exc: report['status']='FAIL'; report['error']=str(exc)
    save(directory/'REPORT.json',report)
    (directory/'REPORT.txt').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(report['status']+': '+str(directory.relative_to(ROOT)))
    if 'error' in report: print(report['error'])
    return 0 if report['status'].startswith('PASS') else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--offline',action='store_true')
    sys.exit(verify(parser.parse_args().offline))
