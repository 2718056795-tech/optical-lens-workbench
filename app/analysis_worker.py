import argparse,json,traceback
from pathlib import Path
from engine_io import write_json


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);args=parser.parse_args()
    request=json.loads(Path(args.request).read_text(encoding='utf-8'));out=Path(request['out_dir']);out.mkdir(parents=True,exist_ok=True)
    def progress(message,**details):
        print(message,json.dumps(details,ensure_ascii=False),flush=True)
        write_json(out/'progress.json',dict(status='running',message=message,**details))
    try:
        progress('准备独立处方与分析条件')
        engine=request.get('engine','optiland')
        if engine=='autolens':
            from analysis_isolation import install
            install('autolens')
            from autolens_analysis import run_analysis
        elif engine=='optiland':
            from analysis_isolation import install
            install('optiland')
            from extended_analysis import run_analysis
        else:raise ValueError('未知分析内核')
        result=run_analysis(request,progress)
        from analysis_isolation import report
        result['engine']=engine;result['engine_isolation']=report(engine)
        write_json(out/'result.json',result);write_json(out/'progress.json',dict(status='finished',message='分析完成'))
        return 0
    except Exception as exc:
        error=traceback.format_exc();write_json(out/'progress.json',dict(status='failed',error=str(exc),details=error));print(error,flush=True);return 1


if __name__=='__main__':raise SystemExit(main())
