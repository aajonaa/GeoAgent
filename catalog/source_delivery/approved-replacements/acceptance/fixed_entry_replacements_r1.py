"""Two allowlisted, matrix-only offline CPU operations; no dependency installs."""
import os
_ROOT=os.path.dirname(os.path.abspath(__file__))
_CACHE=os.path.join(_ROOT,'cache-fixed-entry')
os.environ.update(MPLCONFIGDIR=os.path.join(_CACHE,'matplotlib'),NUMBA_CACHE_DIR=os.path.join(_CACHE,'numba'),
 XDG_CACHE_HOME=os.path.join(_CACHE,'xdg'),CUDA_VISIBLE_DEVICES='',NVIDIA_VISIBLE_DEVICES='none',PROJ_NETWORK='OFF',
 LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false',GEOTOOL_LANGSMITH_ENABLED='0',OMP_NUM_THREADS='1',
 OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',NUMBA_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import socket
import sys
from threading import Event

OPERATIONS=('ScipyGroundwaterFrequencyResponse','StatsmodelsSeasonalFlowForecast')


class NoModels:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'torch','tensorflow','tensorboard','jax'}:
            raise ImportError('Training/model imports are outside this fixed CPU profile')


def deny_network(*args,**kwargs):
    raise RuntimeError('Scientific operations in this profile are offline only')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--operation',choices=OPERATIONS,required=True)
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--arguments-file',required=True)
    options=parser.parse_args()
    workspace=Path(options.workspace).resolve(strict=True)
    source=Path(options.arguments_file)
    if source.is_symlink() or not source.resolve(strict=True).is_relative_to(workspace):
        raise ValueError('Arguments JSON must belong to the explicit workspace')
    raw=source.read_bytes()
    if len(raw)>4_000_000:raise ValueError('Arguments exceed the shared contract budget')
    arguments=json.loads(raw)
    sys.path.insert(0,str(Path(__file__).resolve().parent/'candidate'))
    sys.meta_path.insert(0,NoModels())
    socket.socket.connect=deny_network
    socket.create_connection=deny_network
    from geological_agent.bootstrap import build_registry
    from geological_agent.contracts import ToolCall
    from geological_agent.settings import Settings
    from geological_agent.tools import ToolExecutionContext,ToolExecutor
    registry,_,_=build_registry()
    result=ToolExecutor(registry).execute(ToolCall('fixed-explicit-replacement',options.operation,arguments),
        ToolExecutionContext('independent-explicit-replacements',workspace,(options.operation,),Settings(),Event()))
    print(json.dumps(asdict(result),allow_nan=False))
    return 0 if result.status=='ok' else 1


if __name__=='__main__':raise SystemExit(main())
