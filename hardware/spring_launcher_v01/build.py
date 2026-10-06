"""Export and inspect prototype CAD. Python standard library, OpenSCAD 2021.01+."""
from __future__ import annotations
import argparse
import collections
import concurrent.futures
import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parent
SCAD=ROOT/'launcher.scad'
DEFAULT_CAD=Path(r'C:\Program Files\OpenSCAD\openscad.com')
PARTS={
 'body':('01_cassette_body',1),'deck':('02_fixed_deck',1),
 'slider':('03_lower_slider',1),'pusher':('04_upper_pusher',1),
 'base':('05_stand_base',1),'cheek':('06_angle_cheek',2),
 'spacer':('07_pitch_spacer',4),'buoy':('08_buoy_100x10',1),
 'cocking_fork':('09_removable_cocking_fork',1),
 'fit_coupon':('10_hole_fit_coupon',1),'slot_coupon':('11_slot_fit_coupon',1),
}

def run_cad(cad,output,definitions,extra=()):
 cmd=[str(cad),'-o',str(output)]
 for k,v in definitions.items():cmd+=['-D',f'{k}={json.dumps(v)}']
 cmd+=list(extra)+[str(SCAD)]
 result=subprocess.run(cmd,capture_output=True,encoding='utf-8',errors='replace',timeout=240)
 return result.returncode,result.stdout+result.stderr

def mesh_report(path):
 data=path.read_bytes()
 if len(data)<84:raise ValueError('Not a binary STL')
 n=struct.unpack_from('<I',data,80)[0]
 if len(data)!=84+50*n:raise ValueError('Unexpected STL length')
 edges=collections.Counter(); directions=collections.Counter();parent={}
 bounds=[[math.inf]*3,[-math.inf]*3];vol=0.;degenerate=0
 def find(v):
  parent.setdefault(v,v)
  while parent[v]!=v:parent[v]=parent[parent[v]];v=parent[v]
  return v
 for i in range(n):
  vals=struct.unpack_from('<12fH',data,84+50*i)
  tri=[tuple(round(vals[3+j*3+k],5) for k in range(3)) for j in range(3)]
  a,b,c=tri
  for v in tri:
   for k in range(3):bounds[0][k]=min(bounds[0][k],v[k]);bounds[1][k]=max(bounds[1][k],v[k])
  ab=[b[k]-a[k] for k in range(3)];ac=[c[k]-a[k] for k in range(3)]
  cross=(ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0])
  if sum(v*v for v in cross)<1e-15:degenerate+=1
  vol+=(a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6
  for u,v in ((a,b),(b,c),(c,a)):
   edge=tuple(sorted((u,v)));edges[edge]+=1;directions[edge]+=1 if u<v else -1
   parent[find(u)]=find(v)
 r={'triangles':n,'bounds_mm':bounds,'dimensions_mm':[round(bounds[1][k]-bounds[0][k],3) for k in range(3)],
    'solid_envelope_volume_cm3':round(vol/1000,5),'boundary_edges':sum(v==1 for v in edges.values()),
    'nonmanifold_edges':sum(v!=2 for v in edges.values()),'inconsistent_edge_orientation':sum(v!=0 for v in directions.values()),
    'degenerate_triangles':degenerate,'connected_components':len({find(v) for v in parent})}
 r['passes_mesh_checks']=bool(n and vol>0 and r['connected_components']==1 and not any(r[k] for k in (
   'boundary_edges','nonmanifold_edges','inconsistent_edge_orientation','degenerate_triangles')))
 r['fits_assumed_220mm_bed']=all(v<=200 for v in r['dimensions_mm'][:2])
 return r

def export_part(item,cad):
 part,(name,qty)=item;out=ROOT/'stl'/(name+'.stl')
 code,log=run_cad(cad,out,{'part':part,'quality':80},['--export-format','binstl'])
 (ROOT/'qa'/(name+'.log')).write_text(log,encoding='utf-8')
 if code or not out.exists() or 'ERROR:' in log or 'WARNING:' in log:raise RuntimeError(f'{part}: {log}')
 r=mesh_report(out);r.update(part=part,file=f'stl/{out.name}',quantity=qty)
 print(f"STL {part}: {r['dimensions_mm']}, mesh_ok={r['passes_mesh_checks']}",flush=True)
 return r

def collision_case(cad,name,defs):
 path=ROOT/'qa'/(name+'.stl')
 if path.exists():path.unlink() # only this explicitly named generated QA output
 code,log=run_cad(cad,path,dict(quality=32,qa_mode=True,**defs),['--export-format','binstl'])
 (ROOT/'qa'/(name+'.log')).write_text(log,encoding='utf-8')
 if 'Current top level object is empty' in log and not path.exists():
  r={'case':name,'empty_intersection':True,'overlap_volume_mm3':0}
 elif code==0 and path.exists():
  report=mesh_report(path);r={'case':name,'empty_intersection':False,'overlap_volume_mm3':round(report['solid_envelope_volume_cm3']*1000,4)}
 else:raise RuntimeError(f'Collision check {name}: {log}')
 print(f"QA {name}: {r['overlap_volume_mm3']} mm3",flush=True);return r

def build_checks(cad):
 cases=[]
 for t in [0,14,28,42,56,61]:cases.append((f'drive_t{t}',{'part':'collision_static_moving','travel':t}))
 for t in [0,28,56]:cases.append((f'buoy_t{t}',{'part':'collision_buoy','travel':t}))
 for t in [0,56]:cases.append((f'tool_t{t}',{'part':'collision_tool','travel':t}))
 for a in [0,5,10,15,20,25,30,35,40,45]:cases.append((f'stand_a{a}',{'part':'collision_stand','pitch':a}))
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:return list(ex.map(lambda c:collision_case(cad,*c),cases))

def tool_clearance_checks():
 """Conservative lower corner of fork bounding box, not a hand clearance model."""
 source=SCAD.read_text(encoding='utf-8')
 def scalar(name):
  match=re.search(r'\b'+name+r'\s*=\s*([0-9.]+)\s*;',source)
  if not match:raise ValueError('Expected numeric SCAD constant: '+name)
  return float(match.group(1))
 rows=[]
 for t in [0,56]:
  for a in range(46):
   rad=math.radians(a)
   z=scalar('stand_pivot_z')+(scalar('slider_cx')+t-scalar('cocking_reach')-scalar('pivot_x'))*math.sin(rad)+(scalar('bar_z')+2-scalar('pivot_z'))*math.cos(rad)
   rows.append({'angle_deg':a,'travel_mm':t,'fork_lowest_z_mm':round(z,3),'clearance_above_base_top_mm':round(z-scalar('stand_base_t'),3)})
 if any(r['clearance_above_base_top_mm']<=0 for r in rows):raise RuntimeError('Cocking tool would intersect base-height plane')
 result={'method':'conservative rigid bounding-box lower Z; angles 0..45 at 1-degree increments; two stroke endpoints',
         'not_checked':'hands, gloves, accessories, elastic deformation, retention strength',
         'minimum_clearance_above_base_top_mm':min(r['clearance_above_base_top_mm'] for r in rows),'cases':rows}
 (ROOT/'qa'/'tool_clearance_report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 print('Tool/base plane clearance: '+str(result['minimum_clearance_above_base_top_mm'])+' mm',flush=True)

def package():
 metadata=json.loads((ROOT/'qa'/'verification_metadata.json').read_text(encoding='utf-8'))
 if metadata['cad_source_sha256']!=hashlib.sha256(SCAD.read_bytes()).hexdigest():raise RuntimeError('CAD changed after checks; run --checks again')
 files=[ROOT/n for n in ['README.md','STATUS.md','BOM.csv','calibration.csv','launcher.scad','build.py','dimensions.svg']]
 files+=sorted((ROOT/'stl').glob('*.stl'))+sorted((ROOT/'preview').glob('*.png'))
 files+=sorted((ROOT/'qa').glob('*.json'))+sorted((ROOT/'qa').glob('*.log'))
 if len(list((ROOT/'stl').glob('*.stl')))!=len(PARTS):raise RuntimeError('Incomplete STL set')
 for file in files:
  if not file.is_file():raise FileNotFoundError(file)
 manifest=''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+f.relative_to(ROOT).as_posix()+'\n' for f in files)
 (ROOT/'SHA256SUMS.txt').write_text(manifest,encoding='utf-8')
 files.append(ROOT/'SHA256SUMS.txt')
 out=ROOT.parent/'spring_launcher_v01_print_pack.zip'
 with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
  for f in files:archive.write(f,'spring_launcher_v01/'+f.relative_to(ROOT).as_posix())
 with zipfile.ZipFile(out) as archive:
  if archive.testzip() is not None:raise RuntimeError('ZIP integrity failure')
 print(f'ZIP {out} ({out.stat().st_size:,} bytes; {len(files)} files)',flush=True)

def renders(cad):
 views=[
  ('assembly_20deg',{'part':'assembly','pitch':20},'300,-360,480,80,0,60'),
  ('assembly_45deg',{'part':'assembly','pitch':45},'180,-280,600,80,0,65'),
  ('cassette_cutaway',{'part':'cassette','cutaway':True,'show_projectile':False},'280,-350,220,75,0,15'),
  ('cassette_loaded',{'part':'cassette'},'280,-350,260,85,0,20'),
  ('cassette_released',{'part':'cassette','travel':56},'280,-350,260,85,0,20'),
  ('buoy',{'part':'buoy'},'130,-150,160,0,0,4'),
  ('cocking_tool_45deg',{'part':'assembly','pitch':45,'show_tool':True,'show_projectile':False},'180,-280,600,80,0,65'),
 ]
 for name,defs,camera in views:
  code,log=run_cad(cad,ROOT/'preview'/(name+'.png'),dict(quality=64,**defs),[
    '--imgsize=1500,1050','--colorscheme=Tomorrow','--projection=o','--viewall','--camera='+camera])
  (ROOT/'qa'/(name+'_render.log')).write_text(log,encoding='utf-8')
  if code:raise RuntimeError(log)
  print('PNG '+name,flush=True)

def main():
 p=argparse.ArgumentParser();p.add_argument('--cad',default=str(DEFAULT_CAD));p.add_argument('--parts',nargs='*')
 p.add_argument('--checks',action='store_true');p.add_argument('--renders',action='store_true');p.add_argument('--package',action='store_true');args=p.parse_args();cad=Path(args.cad)
 for name in ['stl','qa','preview']:(ROOT/name).mkdir(exist_ok=True)
 selected=list(PARTS.items()) if args.parts is None else [(k,PARTS[k]) for k in args.parts]
 if selected:
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:result=list(ex.map(lambda item:export_part(item,cad),selected))
  full_result=[]
  for key,(name,quantity) in PARTS.items():
   path=ROOT/'stl'/(name+'.stl')
   if path.exists():
    row=mesh_report(path);row.update(part=key,file='stl/'+path.name,quantity=quantity,sha256=hashlib.sha256(path.read_bytes()).hexdigest());full_result.append(row)
  (ROOT/'qa'/'mesh_report.json').write_text(json.dumps(full_result,indent=2,ensure_ascii=False),encoding='utf-8')
  if not all(r['passes_mesh_checks'] and r['fits_assumed_220mm_bed'] for r in result):raise RuntimeError('Mesh/bed-envelope check failed')
 if args.checks:
  checks=build_checks(cad);(ROOT/'qa'/'interference_report.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
  if any(abs(r['overlap_volume_mm3'])>0.1 for r in checks):raise RuntimeError('CAD interference found; inspect QA')
  tool_clearance_checks()
  metadata={'generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cad_source_sha256':hashlib.sha256(SCAD.read_bytes()).hexdigest(),
            'interference_cases':len(checks),'qa_circular_resolution':32,'decorative_engraving_omitted':True,
            'limits':'Rigid sampled CAD geometry only; not physical validation, tolerance analysis or safety certification.'}
  (ROOT/'qa'/'verification_metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
 if args.renders:renders(cad)
 if args.package:package()

if __name__=='__main__':main()
