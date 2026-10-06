"""Build V0.2 using the unchanged V0.1 STL audit helpers. Python 3.7+."""
from __future__ import annotations
import concurrent.futures
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('previous_build',ROOT.parent/'spring_launcher_v01'/'build.py')
cad=importlib.util.module_from_spec(spec)
spec.loader.exec_module(cad)
cad.ROOT=ROOT
cad.SCAD=ROOT/'launcher.scad'
PARTS={
 'body':('01_body',1),'deck':('02_deck',1),'slider':('03_slider',1),
 'pusher':('04_pusher',1),'buoy':('05_buoy_100x10',1),'grip':('06_cocking_grip',2),
 'base':('07_base',1),'cheek':('08_pitch_cheek',2),'retainer':('09_bearing_retainer',2),
 'post':('10_pitch_bridge_post',2),'pitch_arm':('11_pitch_arm',1),
 'horn_arm':('12_servo_horn_arm',1),'link':('13_link_50mm',1),'link_washer':('14_link_washer',2),
 'pitch_mount':('15_pitch_servo_mount',1),'tower':('16_common_trigger_tower',1),
 'handle':('17_pin_pull_handle',2),'adapter':('18_future_servo_adapter',1),
 'spool':('19_future_cable_spool',1),'pulley':('20_future_pulley',1),
 'pulley_spacer':('21_future_pulley_spacer',1),'coupon':('00_fit_coupon',1),
}

def write_json(name,value):
 (ROOT/'qa'/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def export_all():
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  rows=list(pool.map(lambda item:cad.export_part(item,cad.DEFAULT_CAD),PARTS.items()))
 write_json('meshes.json',rows)
 if any(not r['passes_mesh_checks'] or not r['fits_assumed_220mm_bed'] or abs(r['bounds_mm'][0][2])>.001 for r in rows):
  raise RuntimeError('STL audit failure; inspect qa/meshes.json')

def refresh():
 keys=['body','deck','pusher','cheek','retainer','pitch_arm','pitch_mount','tower','grip']
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  updates=list(pool.map(lambda k:cad.export_part((k,PARTS[k]),cad.DEFAULT_CAD),keys))
 old=json.loads((ROOT/'qa'/'meshes.json').read_text(encoding='utf-8'))
 by_key={r['part']:r for r in old+updates}
 rows=[by_key[k] for k in PARTS]
 write_json('meshes.json',rows)
 if any(not r['passes_mesh_checks'] or abs(r['bounds_mm'][0][2])>.001 for r in rows):raise RuntimeError('Mesh audit failed')

def checks():
 cases=[]
 cases.append(('mount_fixed',dict(part='qa_mount')))
 for t in [0,18,36,40.9]:cases.append(('drive_'+str(t),dict(part='qa_drive',travel=t)))
 for a in [0,15,30,45]:
  cases.append(('stand_'+str(a),dict(part='qa_stand',pitch=a,automatic=True)))
  cases.append(('stand_forward_'+str(a),dict(part='qa_stand',pitch=a,travel=36,automatic=True)))
  cases.append(('bridge_'+str(a),dict(part='qa_bridge',pitch=a)))
 for t in [0,18,36]:cases.append(('trigger_'+str(t),dict(part='qa_trigger',travel=t,automatic=True)))
 cases.append(('pin_retracted',dict(part='qa_pin',travel=0,pin_lift=38)))
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  rows=list(pool.map(lambda c:cad.collision_case(cad.DEFAULT_CAD,*c),cases))
 write_json('interference.json',rows)
 if any(not r['empty_intersection'] for r in rows):raise RuntimeError('Interference found; inspect report')
 write_json('verification.json',{
  'cad_sha256':hashlib.sha256(cad.SCAD.read_bytes()).hexdigest(),
  'core_sha256':hashlib.sha256((ROOT.parent/'spring_launcher_v01'/'launcher.scad').read_bytes()).hexdigest(),
  'scope':'Sampled CAD intersections; stand uses conservative cassette envelopes. mount_fixed offsets its QA copy 0.05 mm from intentional mating planes. Not a physical safety, tolerance or launch-distance certification.',
  'hard_stop':'41 mm is intentional surface contact; travel 40.9 mm is tested for free-space approach.',
  'case_count':len(rows),'all_sampled_intersections_empty':True})

def renders():
 scenes=[('manual_20deg',dict(pitch=20,automatic=False),'360,-480,310,65,-20,90'),
         ('automatic_20deg',dict(pitch=20,automatic=True),'360,-480,310,65,-20,90'),
         ('automatic_side',dict(pitch=0,automatic=True),'82,-600,100,82,0,100'),
         ('trigger_manual',dict(part='trigger_detail',automatic=False),'230,-300,220,60,-5,55'),
         ('trigger_automatic',dict(part='trigger_detail',automatic=True),'230,-300,220,60,-5,55')]
 for name,defs,camera in scenes:
  code,log=cad.run_cad(cad.DEFAULT_CAD,ROOT/'preview'/(name+'.png'),dict(quality=64,**defs),
    ['--imgsize=1400,1000','--colorscheme=Tomorrow','--projection=o','--viewall','--camera='+camera])
  (ROOT/'qa'/(name+'.log')).write_text(log,encoding='utf-8')
  if code or 'ERROR:' in log or 'WARNING:' in log:raise RuntimeError(log)
  print('PNG '+name,flush=True)

def package():
 meta=json.loads((ROOT/'qa'/'verification.json').read_text(encoding='utf-8'))
 if meta['cad_sha256']!=hashlib.sha256(cad.SCAD.read_bytes()).hexdigest():raise RuntimeError('CAD changed since verification')
 if meta['core_sha256']!=hashlib.sha256((ROOT.parent/'spring_launcher_v01'/'launcher.scad').read_bytes()).hexdigest():raise RuntimeError('Shared CAD changed since verification')
 rows=json.loads((ROOT/'qa'/'meshes.json').read_text(encoding='utf-8'))
 if not all(r['passes_mesh_checks'] and r['fits_assumed_220mm_bed'] for r in rows):raise RuntimeError('Unverified mesh')
 hashes={}
 files=[p for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.zip' and p.name not in ['drive_41.stl','drive_41.log','06_cocking_fork.stl','06_cocking_fork.log','obsolete_cocking_fork.stl','manifest.json']]
 # The two read-only V0.1 dependencies are included; keep both folders together.
 files += [ROOT.parent/'spring_launcher_v01'/name for name in ['launcher.scad','build.py']]
 for p in files:hashes[str(p.relative_to(ROOT.parent))]=hashlib.sha256(p.read_bytes()).hexdigest()
 write_json('manifest.json',hashes)
 files.append(ROOT/'qa'/'manifest.json')
 out=ROOT.parent/'spring_launcher_v02_modular_pack.zip'
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  for p in sorted(set(files)):z.write(p,str(p.relative_to(ROOT.parent)))
 with zipfile.ZipFile(out) as z:
  if z.testzip():raise RuntimeError('ZIP CRC failure')
 print('ZIP '+str(out),flush=True)

if __name__=='__main__':
 for name in ['stl','qa','preview']:(ROOT/name).mkdir(exist_ok=True)
 jobs=sys.argv[1:] or ['export','checks','renders']
 for job in jobs:
  if job.startswith('part:'):
   key=job.split(':',1)[1]
   row=cad.export_part((key,PARTS[key]),cad.DEFAULT_CAD)
   rows=json.loads((ROOT/'qa'/'meshes.json').read_text(encoding='utf-8'))
   rows=[row if r['part']==key else r for r in rows]
   write_json('meshes.json',rows)
  else:{'export':export_all,'refresh':refresh,'checks':checks,'renders':renders,'package':package}[job]()
