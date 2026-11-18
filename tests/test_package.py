"""Offline regressions. Fabricated samples are never scientific evidence."""
import json
import hashlib
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools')); sys.path.insert(0,str(ROOT/'research'))
import run
import support
import audit_merge
def config():
    return {'config_id':'fixture_native','partition':'development','start_time':174*86400,
        'warmup_seconds':604800,'steps':12,'step_seconds':300,'weather':'packaged_denver_tmy',
        'occupancy':'packaged_schedule','policy':'native','cooling_setpoint_c':None,'schedule':[]}
class ResearchTests(unittest.TestCase):
    def test_unknown_weather_or_occupancy_rejected(self):
        for key in ('weather','occupancy'):
            c=config(); c[key]='new_custom'; self.assertRaises(ValueError,run.validate,c)
    def test_limits_finite_alignment_and_year(self):
        for key,value in [('steps',2017),('step_seconds',60),('start_time',1),('steps',True),('warmup_seconds',0)]:
            c=config(); c[key]=value; self.assertRaises(ValueError,run.validate,c)
        c=config(); c.update(policy='fixed_cooling',cooling_setpoint_c=float('nan')); self.assertRaises(ValueError,run.validate,c)
    def test_schedule_activation_and_release(self):
        c=config(); c.update(policy='scheduled_cooling',schedule=[{'start_second':28800,'end_second':64800,'cooling_setpoint_c':24}])
        run.validate(c)
        self.assertEqual(run.command(c,28800)[support.FLAGS[0]],1)
        self.assertEqual(run.command(c,64800),dict.fromkeys(support.FLAGS,0))
    def test_overlapping_blocks_rejected(self):
        c=config(); c.update(policy='scheduled_cooling',schedule=[{'start_second':0,'end_second':600,'cooling_setpoint_c':24},{'start_second':300,'end_second':900,'cooling_setpoint_c':25}])
        self.assertRaises(ValueError,run.validate,c)
    def test_exclusive_ids_and_grouped_policy_pair(self):
        with tempfile.TemporaryDirectory() as d:
            registry=Path(d); a=config(); identity={'source_fmu_sha256':'fixture'}
            group=run.reserve(a,identity,registry)
            self.assertRaises(ValueError,run.reserve,a,identity,registry)
            b=config(); b.update(config_id='fixture_fixed',policy='fixed_cooling',cooling_setpoint_c=25)
            self.assertEqual(group,run.reserve(b,identity,registry))
    def test_changed_id_cannot_leak_overlapping_windows(self):
        with tempfile.TemporaryDirectory() as d:
            registry=Path(d); identity={'source_fmu_sha256':'fixture'}
            run.reserve(config(),identity,registry)
            b=config(); b.update(config_id='fixture_test',partition='test',start_time=175*86400)
            self.assertRaises(ValueError,run.reserve,b,identity,registry)
            b['start_time']=200*86400; run.reserve(b,identity,registry)
    def test_causal_features_future_labels_native_energy(self):
        c=config(); endpoints=[]; start=c['start_time']
        for i in range(13):
            endpoints.append({'time':start+i*300,support.TEMP:290+i,support.OUT:280+i,support.SOLAR:100+i,run.SET:298.15})
        native={'time':list(range(start,start+3601,30)),support.COOL:[100]*121,support.FAN:[20]*121}
        actions=[{'command':dict.fromkeys(support.FLAGS,0)} for _ in range(12)]
        import csv
        with tempfile.TemporaryDirectory() as d:
            result=run.export(c,'group',endpoints,native,actions,Path(d))
            self.assertEqual(result['rc_rows'],12); self.assertEqual(result['ml_rows'],6)
            with (Path(d)/'ml_ready.csv').open() as f: row=next(csv.DictReader(f))
            self.assertAlmostEqual(float(row['x__indoor_c']),291-273.15)
            self.assertAlmostEqual(float(row['y__indoor_30min_c']),297-273.15)
            self.assertAlmostEqual(float(row['x__cooling_plus_fan_last_5min_kw']),.12)
            self.assertAlmostEqual(float(row['y__cooling_plus_fan_30min_kw']),.12)
            with (Path(d)/'rc_intervals.csv').open() as f: interval=next(csv.DictReader(f))
            self.assertAlmostEqual(float(interval['cooling_plus_fan_interval_kwh']),.01)
    def test_sparse_power_is_not_endpoint_substitution(self):
        self.assertRaises(ValueError,run.NativeElectric,{'time':[0,300],support.COOL:[100,100],support.FAN:[20,20]})
    def test_duplicate_event_integral(self):
        times=list(range(0,301,30)); times.insert(6,150)
        values=[100 if t<=150 else 200 for t in times]; values[6]=200
        result=run.NativeElectric({'time':times,support.COOL:values,support.FAN:[0]*len(times)}).interval(0,300)
        self.assertAlmostEqual(result['joules'],45000)
    def test_activity_lock_releases_on_error(self):
        with tempfile.TemporaryDirectory() as d, patch.object(support,'ROOT',Path(d)):
            with self.assertRaisesRegex(RuntimeError,'fixture'):
                with support.activity(): raise RuntimeError('fixture')
            with support.activity(): pass
    def test_activity_lock_blocks_other_process(self):
        with support.activity():
            result=subprocess.run([sys.executable,'-B','-c',"from support import activity\nwith activity(): pass"],cwd=ROOT/'tools',capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0); self.assertIn('Another verification or research run',result.stderr)
    @unittest.skipUnless(sys.platform=='win32','Windows CMD launcher test')
    def test_cmd_preserves_failure_code_after_pause(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            (folder/'SETUP_FIRST.cmd').write_bytes((ROOT/'SETUP_FIRST.cmd').read_bytes())
            (folder/'Setup.ps1').write_text('exit 37\n')
            result=subprocess.run(['cmd.exe','/d','/c',str(folder/'SETUP_FIRST.cmd')],input='\n',capture_output=True,text=True)
            self.assertEqual(result.returncode,37)
    @unittest.skipUnless(sys.platform=='win32','Windows PowerShell prerequisite test')
    def test_verify_prerequisite_failure_has_nonzero_report(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            for name in ('Verify.ps1','Common.ps1'): shutil.copyfile(ROOT/name,folder/name)
            result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(folder/'Verify.ps1')],capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            report=json.loads(next((folder/'verification').glob('*/REPORT.json')).read_text(encoding='utf-8-sig'))
            self.assertEqual(report['status'],'FAIL'); self.assertEqual(report['live_simulation'],'NOT_RUN')
    def test_preserved_collector_rejects_recomputed_distribution_hash(self):
        from integrity import check
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            (folder/'research').mkdir()
            for name in ('legacy_dataset.py','SOURCE_INVENTORY.json'):
                shutil.copyfile(ROOT/'research'/name,folder/'research'/name)
            target=folder/'research/legacy_dataset.py'
            target.write_bytes(target.read_bytes()+b'\n# fabricated tamper fixture\n')
            (folder/'SHA256SUMS.json').write_text(json.dumps({
                'research/legacy_dataset.py':hashlib.sha256(target.read_bytes()).hexdigest(),
                'research/SOURCE_INVENTORY.json':hashlib.sha256((folder/'research/SOURCE_INVENTORY.json').read_bytes()).hexdigest()}))
            self.assertRaisesRegex(ValueError,'Original-source mismatch: research/legacy_dataset.py',check,folder)
    def test_measurement_and_unit_gate(self):
        self.assertRaises(ValueError,support.measurement_gate,{'time':1},0)
        self.assertRaises(ValueError,support.metadata_gate,{'measurements':{}})
    def test_foreign_session_refused(self):
        with patch.object(support.socket,'create_connection',side_effect=ConnectionRefusedError),patch.object(support,'compose',return_value='fixture-redis'),patch.object(support,'docker',return_value='tests:fixture'):
            self.assertRaises(RuntimeError,support.no_foreign_tests,None)
    def test_other_dashboard_blocks_before_redis_or_deployment(self):
        from unittest.mock import Mock
        with patch.object(support.socket,'create_connection',return_value=Mock()),patch.object(support,'compose') as compose:
            self.assertRaisesRegex(RuntimeError,'dashboard is listening',support.no_foreign_tests,None)
            compose.assert_not_called()
    def test_failed_initialize_still_cleans_and_cannot_export_success(self):
        class Broken:
            testid='fixture'
            def __init__(self,*a,**kw): pass
            def deploy(self): return self.testid
            def discover(self): return {'inputs':{k:{'Unit':'K'} for k in (run.SET,'con_oveTSetHea_u',*support.FLAGS)}}
            def request(self,*a,**kw): raise RuntimeError('fixture initialization failure')
        with tempfile.TemporaryDirectory() as d:
            home=Path(d)
            with patch.object(run,'activity',return_value=nullcontext()),patch.object(run,'HERE',home),patch.object(run,'runtime',return_value={'source_fmu_sha256':'fixture'}),patch.object(run,'Client',Broken),patch.object(run,'catalog'),patch.object(run,'no_foreign_tests'),patch.object(run,'metadata_gate'),patch.object(run,'worker_identity',return_value={'sha256':'fixture'}),patch.object(run,'cleanup',return_value='STOP_ACK_AND_INSTANCE_DIRECTORY_REMOVED') as cleanup:
                self.assertEqual(run.collect(config()),1)
                cleanup.assert_called_once()
            result=json.loads(next((home/'outputs').glob('*/RESULT.json')).read_text())
            self.assertEqual(result['status'],'FAIL'); self.assertIn('initialization failure',result['error'])
            self.assertFalse(list((home/'outputs').glob('*/*.csv')))
            self.assertTrue((home/'registry/fixture_native.json').is_file())
    def test_cross_device_merge_rejects_leakage_and_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            paths=[]
            for index in range(2):
                folder=Path(d)/str(index);folder.mkdir();paths.append(folder)
                c=config(); c.update(config_id='member_'+str(index),partition='development' if index==0 else 'test')
                (folder/'config.json').write_text(json.dumps(c))
                (folder/'runtime.json').write_text(json.dumps({'source_fmu_sha256':'fixture'}))
                (folder/'RESULT.json').write_text(json.dumps({'status':'PASS_COLLECTION','cleanup':'STOP_ACK_AND_INSTANCE_DIRECTORY_REMOVED'}))
                (folder/'ARTIFACT_SHA256.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}))
            self.assertRaisesRegex(ValueError,'different partitions',audit_merge.audit,paths)
            c['partition']='development';(paths[1]/'config.json').write_text(json.dumps(c))
            (paths[1]/'ARTIFACT_SHA256.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths[1].iterdir() if p.name!='ARTIFACT_SHA256.json'}))
            self.assertEqual(audit_merge.audit(paths)['runs'],2)
            self.assertRaisesRegex(ValueError,'Duplicate',audit_merge.audit,[paths[0],paths[0]])
if __name__=='__main__': unittest.main()
