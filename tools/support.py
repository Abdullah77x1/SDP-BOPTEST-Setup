"""Shared local runtime guard, identities and exclusive ownership for new tools."""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'app'))
from compat_v1.transport import Client
TEMP = 'zon_reaTRooAir_y'
COOL = 'fcu_reaPCoo_y'
FAN = 'fcu_reaPFan_y'
OUT = 'zon_weaSta_reaWeaTDryBul_y'
SOLAR = 'zon_weaSta_reaWeaHGloHor_y'
FLAGS = ('con_oveTSetCoo_activate','con_oveTSetHea_activate','fcu_oveFan_activate','fcu_oveTSup_activate')
BASE = 'http://127.0.0.1:80'

def save(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, allow_nan=False)

def stamp():
    return time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+uuid.uuid4().hex[:8]

def digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

@contextmanager
def activity():
    directory = ROOT/'runtime'; directory.mkdir(exist_ok=True)
    with (directory/'activity.lock').open('a+b') as stream:
        stream.seek(0); stream.write(b'0'); stream.flush(); stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('Another verification or research run owns this package. Finish it first.') from exc
        try: yield
        finally:
            stream.seek(0)
            if os.name == 'nt': msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(stream,fcntl.LOCK_UN)

def docker(*args):
    result = subprocess.run(['docker',*args],capture_output=True,text=True,timeout=45)
    if result.returncode: raise RuntimeError('Docker command failed: '+result.stderr.strip())
    return result.stdout.strip()

def compose(*args):
    release = ROOT/'runtime/project1-boptest-0.9.0'
    return docker('compose','--project-directory',str(release),'--env-file',str(release/'.env'),'-p','boptest-team-v090','-f',str(release/'docker-compose.yml'),'-f',str(ROOT/'compose.team.yml'),*args)

def worker_identity(testid=None):
    worker = compose('ps','-q','worker')
    if not worker or '\n' in worker: raise RuntimeError('Exactly one package worker is required')
    if testid is None: return worker
    if not isinstance(testid,str) or len(testid)!=36 or any(c not in '0123456789abcdef-' for c in testid): raise ValueError('Invalid testid')
    code = "import hashlib,json,pathlib;p=pathlib.Path('/simulate')/"+repr(testid)+"/'model.fmu';print(json.dumps({'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}))"
    return json.loads(docker('exec',worker,'/miniconda/envs/pyfmi3/bin/python','-c',code))

def runtime():
    info = json.loads(docker('info','--format','{{json .}}'))
    if info['OSType']!='linux' or info['Architecture'] not in ('x86_64','amd64'): raise RuntimeError('Linux AMD64 Docker required')
    ids = {}
    for service, port in [('web','80'),('minio','9000'),('minio','9001')]:
        if compose('port',service,port) != '127.0.0.1:'+port: raise RuntimeError('Nonlocal or missing port binding: '+service)
    for service in ('web','worker','minio','mc','redis','provision'):
        container = compose('ps','-a','-q',service)
        if not container: raise RuntimeError('Missing package service '+service)
        # Never serialize Config.Env: the release has stock local credentials.
        ids[service] = json.loads(docker('inspect','--format','{{json .Image}}',container))
    fmu = ROOT/'runtime/project1-boptest-0.9.0/testcases/bestest_air/models/wrapped.fmu'
    return {'boptest':'0.9.0','case':'bestest_air','docker_version':info['ServerVersion'],
        'platform':'linux/amd64','image_ids':ids,'source_fmu_sha256':hashlib.sha256(fmu.read_bytes()).hexdigest(),
        'runner_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                         for folder in ('tools','research') for p in sorted((ROOT/folder).glob('*.py'))}}

def no_foreign_tests(client):
    # Anonymous select is used by the frozen client. The authenticated user-tests
    # endpoint cannot enumerate anonymous sessions. Read only this project Redis
    # index, including queued tests; never read another instance's model state.
    try:
        listener = socket.create_connection(('127.0.0.1',8765),timeout=1)
    except ConnectionRefusedError: pass
    except OSError as exc: raise RuntimeError('Cannot confirm dashboard port is free; stop the dashboard before proceeding') from exc
    else:
        listener.close()
        raise RuntimeError('A dashboard is listening on port 8765. Close it before research/verification.')
    redis = compose('ps','-q','redis')
    tests = docker('exec',redis,'redis-cli','--scan','--pattern','tests:*')
    if tests: raise RuntimeError('A test is already queued/running. Disconnect other clients first.')

def catalog(client):
    version = client.request('GET','version',instance=False)
    if version.get('version')!='0.9.0': raise RuntimeError('Expected API v0.9.0')
    cases = client.request('GET','testcases',instance=False)
    if not any(c.get('testcaseid')=='bestest_air' for c in cases): raise RuntimeError('bestest_air unavailable')
    return version

def measurement_gate(observation, expected_time):
    if abs(observation['time']-expected_time)>1e-6: raise ValueError('Unexpected simulator time')
    for key in (TEMP,COOL,FAN,OUT):
        value = observation[key]
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value): raise ValueError('Invalid measurement '+key)
    if observation[COOL]<-1e-6 or observation[FAN]<-1e-6: raise ValueError('Unexpected negative electrical power')

def metadata_gate(meta):
    for key, unit in [(TEMP,'K'),(OUT,'K'),(COOL,'W'),(FAN,'W')]:
        if meta['measurements'].get(key,{}).get('Unit')!=unit: raise ValueError('Missing or changed measurement units: '+key)

def cleanup(client):
    testid = client.testid
    client.stop()  # One mutation attempt. Original adapter verifies plain OK.
    if testid:
        worker = worker_identity()
        code = "import pathlib;print(int((pathlib.Path('/simulate')/"+repr(testid)+").exists()))"
        for _ in range(15):
            if docker('exec',worker,'/miniconda/envs/pyfmi3/bin/python','-c',code)=='0': return 'STOP_ACK_AND_INSTANCE_DIRECTORY_REMOVED'
            time.sleep(1)
        raise RuntimeError('Stop acknowledged but instance directory remains; cleanup unconfirmed')
    return 'NO_KNOWN_INSTANCE'
