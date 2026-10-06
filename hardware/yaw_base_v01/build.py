"""Build yaw-only printable parts with OpenSCAD; no third-party Python packages."""
import argparse, collections, concurrent.futures, datetime, hashlib, json, math
from pathlib import Path
import struct, subprocess, zipfile

ROOT=Path(__file__).resolve().parent
SCAD=ROOT/'yaw_base.scad'
CAD=r'C:\Program Files\OpenSCAD\openscad.com'
PARTS={'frame':('01_fixed_base',1),'carrier':('02_bearing_carrier',1),
       'cradle':('03_servo_cradle',1),'rotor':('04_rotating_top',1),
       'driver':('05_floating_drive_dog',1),'shim':('06_alignment_shim_1mm',4),
       'coupon':('07_fit_coupon',1)}

def run(cad,path,defs,extra=()):
 cmd=[cad,'-o',str(path)]
 for k,v in defs.items():cmd+=['-D',f'{k}={json.dumps(v)}']
 r=subprocess.run(cmd+list(extra)+[str(SCAD)],capture_output=True,encoding='utf-8',errors='replace',timeout=180)
 return r.returncode,r.stdout+r.stderr

def inspect_mesh(path):
 data=path.read_bytes();n=struct.unpack_from('<I',data,80)[0]
 if len(data)!=84+50*n:raise ValueError('Not a binary STL: '+str(path))
 edge=collections.Counter();orientation=collections.Counter();parent={};vol=0.;degenerate=0
 lo=[math.inf]*3;hi=[-math.inf]*3
 def find(v):
  parent.setdefault(v,v)
  while parent[v]!=v:parent[v]=parent[parent[v]];v=parent[v]
  return v
 for i in range(n):
  f=struct.unpack_from('<12fH',data,84+i*50);a,b,c=[tuple(round(f[3+j*3+k],5) for k in range(3)) for j in range(3)]
  for v in [a,b,c]:
   for k in range(3):lo[k]=min(lo[k],v[k]);hi[k]=max(hi[k],v[k])
  ab=[b[k]-a[k] for k in range(3)];ac=[c[k]-a[k] for k in range(3)]
  cross=[ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0]]
  degenerate+=sum(x*x for x in cross)<1e-15
  vol+=(a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6
  for u,v in [(a,b),(b,c),(c,a)]:
   key=tuple(sorted((u,v)));edge[key]+=1;orientation[key]+=1 if u<v else -1;parent[find(u)]=find(v)
 report={'triangles':n,'dimensions_mm':[round(hi[k]-lo[k],3) for k in range(3)],'volume_mm3':round(vol,4),
  'boundary_edges':sum(x==1 for x in edge.values()),'nonmanifold_edges':sum(x!=2 for x in edge.values()),
  'orientation_errors':sum(x!=0 for x in orientation.values()),'degenerate_triangles':degenerate,
  'components':len({find(v) for v in parent})}
 report['mesh_ok']=bool(n and vol>0 and report['components']==1 and not any(report[k] for k in ['boundary_edges','nonmanifold_edges','orientation_errors','degenerate_triangles']))
 report['fits_220mm_bed_with_margin']=max(report['dimensions_mm'][:2])<=200
 return report

def export_part(item,cad):
 key,(name,qty)=item;path=ROOT/'stl'/(name+'.stl')
 code,log=run(cad,path,{'part':key,'quality':80},['--export-format','binstl'])
 (ROOT/'qa'/(name+'.log')).write_text(log,encoding='utf-8')
 if code or 'ERROR:' in log or 'WARNING:' in log:raise RuntimeError(log)
 r=inspect_mesh(path);r.update(part=key,file='stl/'+path.name,quantity=qty,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
 if not r['mesh_ok'] or not r['fits_220mm_bed_with_margin']:raise RuntimeError(r)
 print(f"STL {key}: {r['dimensions_mm']}, pass",flush=True)
 return r

def check_case(case,cad):
 name,defs=case;path=ROOT/'qa'/(name+'.stl')
 if path.exists():path.unlink() # exact generated QA file only
 code,log=run(cad,path,dict(quality=32,qa_mode=True,**defs),['--export-format','binstl'])
 (ROOT/'qa'/(name+'.log')).write_text(log,encoding='utf-8')
 if 'ERROR:' in log:raise RuntimeError(log)
 if 'Current top level object is empty' in log and not path.exists():v=0
 elif code==0 and path.exists():v=abs(inspect_mesh(path)['volume_mm3'])
 else:raise RuntimeError(log)
 if v>0.1:raise RuntimeError(f'{name}: interference {v} mm3')
 print(f'QA {name}: {v} mm3',flush=True)
 return {'case':name,'overlap_volume_mm3':v,'passed':True}

def renders(cad):
 views=[('assembly',{'yaw':25},'245,-330,285,0,0,37'),
        ('exploded',{'yaw':0,'exploded':True},'240,-330,340,0,0,90'),
        ('drive_cutaway',{'yaw':0,'cutaway':True},'190,-240,210,0,0,40'),
        ('top',{'yaw':0},'0,-0.01,400,0,0,0')]
 for name,defs,camera in views:
  code,log=run(cad,ROOT/'preview'/(name+'.png'),dict(part='assembly',**defs),['--imgsize=1500,1100','--colorscheme=Tomorrow','--projection=o','--viewall','--camera='+camera])
  if code:raise RuntimeError(log)
  print('PNG '+name,flush=True)

def package():
 metadata=json.loads((ROOT/'qa'/'verification.json').read_text(encoding='utf-8'))
 if metadata['source_sha256']!=hashlib.sha256(SCAD.read_bytes()).hexdigest():raise RuntimeError('CAD changed after verification')
 files=[ROOT/n for n in ['README.md','CONTROL.md','BOM.csv','yaw_base.scad','build.py']]
 files+=sorted((ROOT/'stl').glob('*.stl'))+sorted((ROOT/'preview').glob('*.png'))+sorted((ROOT/'qa').glob('*.json'))
 for p in files:
  if not p.is_file():raise FileNotFoundError(p)
 manifest=ROOT/'SHA256SUMS.txt'
 manifest.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(ROOT).as_posix()+'\n' for p in files),encoding='utf-8')
 files.append(manifest)
 out=ROOT.parent/'yaw_base_v01_print_pack.zip'
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  for p in files:z.write(p,ROOT.name+'/'+p.relative_to(ROOT).as_posix())
 with zipfile.ZipFile(out) as z:
  if z.testzip():raise RuntimeError('ZIP check failed')
 print(f'ZIP {out}, {out.stat().st_size:,} bytes',flush=True)

def main():
 p=argparse.ArgumentParser();p.add_argument('--cad',default=CAD);p.add_argument('--render-only',action='store_true');p.add_argument('--package',action='store_true');p.add_argument('--package-only',action='store_true');a=p.parse_args()
 for folder in ['stl','qa','preview']:(ROOT/folder).mkdir(exist_ok=True)
 if not a.render_only and not a.package_only:
  with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:meshes=list(ex.map(lambda item:export_part(item,a.cad),PARTS.items()))
  (ROOT/'qa'/'meshes.json').write_text(json.dumps(meshes,indent=2),encoding='utf-8')
  cases=[('full_rotation_envelope',{'part':'collision','yaw':0}),('dog_fit',{'part':'dog_collision','yaw':0}),
         ('bearing_clearance',{'part':'bearing_collision','yaw':25}),('servo_envelope_fit',{'part':'servo_collision','yaw':0})]
  with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:checks=list(ex.map(lambda c:check_case(c,a.cad),cases))
  result={'date_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_sha256':hashlib.sha256(SCAD.read_bytes()).hexdigest(),
   'checks':checks,'method':'Conservative rotationally symmetric moving envelope vs filled fixed envelopes. Dog fit checked in one co-rotating pose. Simplified bought bearing and servo envelopes checked separately.',
   'limits':'Decorative engraving omitted, circular resolution 32. Bought hardware must be measured. No physical, torque, load, accuracy, electrical or fatigue validation. Full CAD rotation clearance is NOT servo travel capability.'}
  (ROOT/'qa'/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 if not a.package_only:renders(a.cad)
 if a.package or a.package_only:package()

if __name__=='__main__':main()
