"""V10 deployment gates. No optimizer, package installation, or optical source edits."""
import argparse,datetime,hashlib,importlib.metadata,json,os,platform,struct,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
MODES=('both','optiland-cpu')
RESULT_PREFIX='DEPLOY_PROBE_RESULT='

def normalized(name):return name.lower().replace('_','-').replace('.','-')

def version_checks(snapshot,mode,version_getter=importlib.metadata.version):
    expected=dict(snapshot['global_packages'])
    expected['torch']='2.6.0+cpu' if mode=='optiland-cpu' else '2.6.0+cu118'
    results=[]
    for name,wanted in sorted(expected.items(),key=lambda row:row[0].lower()):
        if normalized(name) in ('pip','setuptools','wheel'):continue
        try:actual=version_getter(name)
        except importlib.metadata.PackageNotFoundError:actual=None
        results.append(dict(package=name,expected=wanted,actual=actual,passed=actual==wanted))
    return results

def detect_system():
    found=[];releases=[]
    if os.name=='nt':
        for name,fallback in [('ProgramFiles(x86)','C:/Program Files (x86)'),('ProgramFiles','C:/Program Files'),('LOCALAPPDATA','C:/missing')]:
            base=Path(os.environ.get(name,fallback))/'Microsoft/EdgeWebView/Application'
            found.extend(str(p) for p in base.glob('*/msedgewebview2.exe') if p.is_file())
        import winreg
        for view in (winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full',0,winreg.KEY_READ|view) as key:
                    releases.append(int(winreg.QueryValueEx(key,'Release')[0]))
            except OSError:pass
    return dict(windows_x64=os.name=='nt' and struct.calcsize('P')==8,webview2_runtime_found=bool(found),webview2_paths=sorted(set(found)),
                dotnet_release=max(releases,default=0),dotnet_462_or_later=max(releases,default=0)>=394802)

def worker(app,kind,expected_scipy):
    """Executed in a fresh process so Optiland and AutoLens do not share imports."""
    sys.path.insert(0,str(app))
    from native_sources import configure_optiland_runtime
    configure_optiland_runtime()
    import numpy as np,scipy
    actual=Path(scipy.__file__).resolve();private=(app/'vendor/native_runtime').resolve()
    if scipy.__version__!=expected_scipy or not actual.is_relative_to(private):raise RuntimeError('Private SciPy version/origin mismatch: '+scipy.__version__+' at '+str(actual))
    info=dict(scipy_version=scipy.__version__,scipy_file=str(actual),probe=kind)
    if kind=='optiland':
        from scipy.linalg import solve
        from optiland.optic import Optic
        from optiland.materials import IdealMaterial
        solution=solve(np.array([[3.,1.],[1.,2.]]),np.array([9.,8.]))
        if not np.allclose(solution,[2.,3.],rtol=0,atol=1e-12):raise RuntimeError('CPU linear algebra probe failed')
        optic=Optic()
        optic.add_surface(index=0,radius=np.inf,thickness=np.inf)
        optic.add_surface(index=1,radius=50.,thickness=5.,material=IdealMaterial(n=1.5),is_stop=True)
        optic.add_surface(index=2,radius=-50.,thickness=50.)
        optic.add_surface(index=3,radius=np.inf)
        optic.set_aperture('EPD',5.)
        optic.set_field_type('angle');optic.add_field(y=0.)
        optic.add_wavelength(value=.5876,is_primary=True)
        ray=optic.trace_generic(Hx=0.,Hy=0.,Px=.1,Py=.1,wavelength=.5876)
        values=np.asarray([np.asarray(ray.x).ravel()[0],np.asarray(ray.y).ravel()[0],np.asarray(ray.z).ravel()[0]],dtype=float)
        intensity=np.asarray(ray.i,dtype=float)
        if not np.isfinite(values).all() or not np.isfinite(intensity).all() or not (intensity>0).all():raise RuntimeError('Optiland finite transmitted-ray probe failed')
        info.update(optic_class=type(optic).__module__+'.'+type(optic).__name__,ray_xyz=values.tolist(),ray_intensity=intensity.tolist(),optimizer_called=False,cpu_math_passed=True)
    elif kind=='autolens-import':
        from native_sources import load_autolens
        module=load_autolens();info.update(module_file=module.__file__,optimizer_called=False)
    elif kind=='gpu':
        import torch
        if not torch.cuda.is_available():raise RuntimeError('CUDA is unavailable; both mode requires a compatible NVIDIA GPU and driver')
        tensor=torch.ones((8,8),device='cuda');valid=bool(torch.isfinite(tensor@tensor).all().item());torch.cuda.synchronize()
        if not valid:raise RuntimeError('GPU matrix probe returned non-finite values')
        info.update(gpu_name=torch.cuda.get_device_name(0),torch_version=torch.__version__,gpu_computation_ok=True,optimizer_called=False)
    else:raise ValueError('Unknown probe')
    return dict(passed=True,**info)

def run_worker(root,kind,expected_scipy,timeout=90):
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MPLBACKEND='Agg',MPLCONFIGDIR=str(root/'app/runtime_cache/deployment_mpl'))
    if kind!='gpu':env['CUDA_VISIBLE_DEVICES']='-1'
    command=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'--worker',kind,'--app',str(root/'app'),'--expected-scipy',expected_scipy]
    try:
        completed=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',env=env,timeout=timeout)
        rows=[line[len(RESULT_PREFIX):] for line in completed.stdout.splitlines() if line.startswith(RESULT_PREFIX)]
        if completed.returncode!=0 or not rows:return dict(passed=False,error='Worker failed',exit_code=completed.returncode,stderr=completed.stderr[-3000:],stdout=completed.stdout[-1500:])
        result=json.loads(rows[-1])
        if not result.get('passed'):result['passed']=False
        return result
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:return dict(passed=False,error=type(exc).__name__+': '+str(exc))

def source_integrity(app):
    sys.path.insert(0,str(app))
    from native_sources import verify_autolens,verify_optiland
    return dict(autolens=verify_autolens(),optiland=verify_optiland())

def check(root,mode,*,system_probe=detect_system,version_getter=importlib.metadata.version,source_probe=source_integrity,worker_runner=run_worker,launch_only=False):
    report=dict(mode=mode,status='failed',ready=False,optiland_cpu_ready=False,autolens_gpu_ready=False,python=sys.version,python_executable=str(Path(sys.executable).resolve()),checked_at=datetime.datetime.now().astimezone().isoformat(timespec='seconds'),errors=[])
    try:
        if mode not in MODES:raise ValueError('Select both or optiland-cpu explicitly')
        if sys.version_info[:2]!=(3,11) or struct.calcsize('P')!=8:raise RuntimeError('Use Python 3.11 x64')
        app=root/'app';snapshot_path=root/'environment_snapshot.json';snapshot=json.loads(snapshot_path.read_text(encoding='utf-8'))
        report['policy_sha256']=hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        report['versions']=version_checks(snapshot,mode,version_getter)
        report['errors'].extend('Version mismatch: '+r['package']+' expected '+r['expected']+', actual '+str(r['actual']) for r in report['versions'] if not r['passed'])
        report['system']=system_probe()
        for key in ('windows_x64','webview2_runtime_found','dotnet_462_or_later'):
            if not report['system'].get(key):report['errors'].append('System prerequisite missing: '+key)
        report['catalog_files']=[]
        for relative,wanted in snapshot['required_catalog_files'].items():
            path=app/relative
            actual=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            report['catalog_files'].append(dict(path=relative,expected_sha256=wanted,actual_sha256=actual,passed=actual==wanted))
            if actual!=wanted:report['errors'].append('Required catalog file missing or changed: app/'+relative+'; see DEPLOY_FOR_AI.md')
        report['source_integrity']=source_probe(app)
        private=app/'vendor/native_runtime/scipy'
        if not (private/'__init__.py').is_file():report['errors'].append('Private SciPy installation is missing; global fallback is not accepted')
        if report['errors']:return report
        if launch_only:
            previous=json.loads((root/'deployment_check.json').read_text(encoding='utf-8'))
            if previous.get('status')!='ready' or previous.get('mode')!=mode or previous.get('policy_sha256')!=report['policy_sha256']:raise RuntimeError('Run deployment verification for this mode/policy before launching')
            report['probes']=previous.get('probes',{});report['probe_scope']='Previously completed engine probes; launch rechecks versions, files and system prerequisites'
        else:
            report['probes']={kind:worker_runner(root,kind,snapshot['private_packages']['scipy']) for kind in (('optiland','autolens-import','gpu') if mode=='both' else ('optiland',))}
        report['errors'].extend('Probe failed: '+kind for kind,result in report['probes'].items() if not result.get('passed'))
        required=('optiland','autolens-import','gpu') if mode=='both' else ('optiland',)
        if any(not report['probes'].get(kind,{}).get('passed') for kind in required):report['errors'].append('Required engine readiness not established')
        report['optiland_cpu_ready']=bool(report['probes'].get('optiland',{}).get('passed'))
        report['autolens_gpu_ready']=mode=='both' and all(report['probes'].get(kind,{}).get('passed') for kind in ('autolens-import','gpu'))
        report['native_3d_status']='not_tested; PyVista/VTK compatibility must be tested separately, no version was upgraded'
        report['ready']=not report['errors'];report['status']='ready' if report['ready'] else 'failed'
    except Exception as exc:report['errors'].append(type(exc).__name__+': '+str(exc))
    return report

def write_report(path,report):
    temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)

def bind_runtime(root):
    app=root/'app'
    (app/'python.path').write_text(str(Path(sys.executable).resolve())+'\n',encoding='utf-8')
    for name in ('runs','imports','runtime_cache'):(app/name).mkdir(exist_ok=True)

def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=MODES,default='both');parser.add_argument('--launch-check',action='store_true')
    parser.add_argument('--worker',choices=('optiland','autolens-import','gpu'));parser.add_argument('--app',type=Path);parser.add_argument('--expected-scipy',default='1.16.3');args=parser.parse_args(argv)
    if args.worker:
        try:result=worker(args.app.resolve(),args.worker,args.expected_scipy)
        except Exception as exc:result=dict(passed=False,error=type(exc).__name__+': '+str(exc))
        print(RESULT_PREFIX+json.dumps(result,ensure_ascii=True));return 0 if result['passed'] else 2
    mode=args.mode
    if args.launch_check:
        try:mode=json.loads((ROOT/'deployment_mode.json').read_text(encoding='utf-8'))['mode']
        except (OSError,ValueError,KeyError):print('No verified deployment mode. Run deploy.ps1 first.');return 2
    report=check(ROOT,mode,launch_only=args.launch_check)
    write_report(ROOT/('launch_check.json' if args.launch_check else 'deployment_check.json'),report)
    if not report['ready']:
        print(json.dumps(report,ensure_ascii=True,indent=2));return 2
    bind_runtime(ROOT)
    if not args.launch_check:write_report(ROOT/'deployment_mode.json',dict(mode=mode,policy_sha256=report['policy_sha256']))
    print(json.dumps(report,ensure_ascii=True,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
