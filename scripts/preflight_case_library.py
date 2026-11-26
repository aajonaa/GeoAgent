"""Batch input/interface preflight. No model calls or scientific execution."""
import argparse,json,os
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    os.environ['CUDA_VISIBLE_DEVICES']=''
    from geological_agent.team.case_catalog import CaseCatalog
    report=CaseCatalog().catalog()
    report['model_called']=False
    report['scientific_execution']=False
    report['acceptance_status']='not_performed'
    dest=Path(args.output);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'counts':report['counts'],'blocked':{i['skill']:i['issues'] for i in report['items'] if not i['ready']},'report':str(dest)},ensure_ascii=False))
    # Preparation blockers are reported separately; a corrupt file/schema raises
    # and exits nonzero. Exit zero never means scientific acceptance.
if __name__=='__main__':main()
