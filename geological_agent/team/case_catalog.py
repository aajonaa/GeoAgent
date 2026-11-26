"""Read-only curated catalog and input bundles. No model calls in preflight."""
from copy import deepcopy
from functools import lru_cache
import hashlib,json
from pathlib import Path,PurePosixPath
from jsonschema import Draft202012Validator
from fastapi import HTTPException

ROOT=Path(__file__).parent/'case_library'

@lru_cache(maxsize=1)
def runtime_bundle():
    from ..bootstrap import build_registry
    return build_registry(human_input=True)

def runtime():return runtime_bundle()[0]


def safe_path(root,name):
    path=PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError('Invalid catalog-relative path')
    p=root/name
    if p.is_symlink() or not p.resolve().is_relative_to(root.resolve()):
        raise ValueError('Catalog file leaves its input root')
    return p


class CaseCatalog:
    def __init__(self,root=None):
        self.root=Path(root or ROOT)
        self.data=json.loads((self.root/'catalog.json').read_text(encoding='utf-8'))
        rows=self.data['items']
        if len(rows)!=44 or len({r['id'] for r in rows})!=44:
            raise ValueError('Expected exactly 44 unique curated source cases')
        self.items={r['id']:r for r in rows}
        self.revision=hashlib.sha256((self.root/'catalog.json').read_bytes()).hexdigest()[:16]

    def get(self,case_id):
        if case_id not in self.items:raise HTTPException(404,'Case not found')
        return self.items[case_id]

    def files(self,item):
        base=safe_path(self.root/'inputs',item['storage'])
        out={}
        for name,record in item['input_files'].items():
            raw=safe_path(base,name).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=record['sha256']:
                raise ValueError('案例输入校验失败：'+name)
            out[name]=raw
        return out

    @lru_cache(maxsize=64)
    def preflight(self,case_id):
        item=self.get(case_id);issues=list(item['load_issues']);details=[]
        self.files(item)
        registry=runtime()
        for name in item['tools']:
            if name not in registry.names():issues.append('当前运行时未注册：'+name)
        operations=item.get('operations',[])
        ids=[op.get('operation_id') for op in operations]
        if len(set(ids))!=len(ids):issues.append('操作编号重复')
        prior=set()
        # Only these explicit protocol bindings can defer their argument validation.
        deferred={'paths_from':{'paths'},'records_from':{'source'},
                  'window_from':{'inline_crossline_time_window'},
                  'waveform_from':{'input_path'},'amplitude_from':{'amplitude'},
                  'input_from':{'path','data_path','input_path'},'geometries_from':{'geometry','left','right'},
                  'labels_from':{'labels'},'values_from':{'data_path'}}
        for op in operations:
            name=op.get('tool');args=op.get('arguments',{})
            if name not in registry.names():continue
            schema=registry.get(name).definition.input_schema
            fields=set().union(*(v for k,v in deferred.items() if k in op))
            for error in Draft202012Validator(schema).iter_errors(args):
                if error.validator=='required' and not error.path and any(k not in args for k in schema.get('required',[])):
                    absent=set(schema.get('required',[]))-set(args)
                    if absent<=fields:
                        details.append('前序产物生成后校验参数：'+name);continue
                issues.append('参数接口需适配：'+name+' / '+('/'.join(map(str,error.path)) or error.validator))
            def refs(v):
                if isinstance(v,str):return [v]
                if isinstance(v,dict):return [v['operation_id']] if 'operation_id' in v else sum((refs(x) for x in v.values() if isinstance(x,(dict,list))),[])
                if isinstance(v,list):return sum((refs(x) for x in v if not isinstance(x,str)),[])
                return []
            for key in deferred:
                if key in op:
                    for ref in refs(op[key]):
                        if ref not in prior:issues.append('前序操作绑定未成立：'+str(ref))
            prior.add(op.get('operation_id'))
        issues=list(dict.fromkeys(issues))
        return {'ready':not issues,'status':'ready' if not issues else 'blocked','issues':issues,'notes':list(dict.fromkeys(details)),
                'message':'输入与接口预检通过，计算环境待实跑确认' if not issues else issues[0],
                'checks_scope':'File SHA-256, current native registration and declared schemas only; not scientific or Agent acceptance.',
                'dependency_check':'执行时确认；预检不导入全部科学库、不安装依赖、不调用模型'}

    def public(self,item):
        keep=('id','skill','source_skill_title','title','description','category','icon','input_label','output_label','version','case_id','data_kind','tools','operation_count','inputs','outputs','scope_notes','independent_check','prior_agent_record')
        return {**{k:deepcopy(item[k]) for k in keep},**self.preflight(item['id'])}

    def catalog(self):
        items=[self.public(i) for i in self.items.values()]
        return {'revision':self.revision,'categories':self.data['categories'],'items':items,
                'counts':{'total':len(items),'ready':sum(i['ready'] for i in items),'blocked':sum(not i['ready'] for i in items),
                          'prior_agent_records':sum(i['prior_agent_record'] for i in items)},
                'notice':'可加载表示输入与接口预检通过，仍需实跑确认环境与结果。已有实跑记录不代表所有案例已经验收。'}

    def prompt(self,item):
        return ('请完成“'+item['title']+'”案例。所需输入已放入当前对话。先读取 request.json 和 INPUTS.md，'
                '按当前匹配的 Skill 指导和原请求的科学参数、单位与数据来源执行。'
                '使用原生专业工具完成科学计算，不联网、不以 Python 重写专业算法；必要的文件组织可以使用通用工具。'
                '若存在前序操作依赖，只能从真实调用返回值和产物中绑定，不得猜测或补造中间结果。'
                '保持原输入不变。简洁给出结果、单位和局限，展示真实生成的图片／表格及下载链接；'
                '没有生成图片的操作只给实际数值或表格。样例不是实际找矿或资源量结论。'
                '缺少依赖时明确说明，未经独立核对不得宣称验收通过。')

def default_case_operations(query, origins, workspace):
    """Only bind a catalog launch with the original request and its exact launch prompt."""
    origin = (origins or {}).get('request.json') or {}
    case_id = origin.get('case_id')
    if not case_id:
        return ()
    library = CaseCatalog()
    item = library.items.get(case_id)
    question = query.rpartition("\nCurrent user request:\n")[2].strip()
    if not item or question != library.prompt(item) or origin.get('case_version') != item['version']:
        return ()
    declared = item['input_files'].get('request.json', {}).get('sha256')
    path = workspace / 'request.json'
    if not declared or not path.is_file() or path.is_symlink() or origin.get('sha256') != declared:
        return ()
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != declared:
        return ()
    request = json.loads(raw)
    if request.get('context', {}).get('workflow'):
        return ()
    return tuple(request.get('operations', ()))


def fixed_case_arguments(operations, name):
    matching = [op for op in operations if op['tool'] == name]
    if len(matching) == 1 and set(matching[0]) == {'operation_id', 'tool', 'arguments'}:
        return matching[0]['arguments']
    return None

def next_fixed_operation(operations, scheduled, exposed):
    """Schedule only standalone calls, in the exact order declared by the fixture."""
    if not operations or any(fixed_case_arguments(operations, op['tool']) is None for op in operations):
        return None
    for op in operations:
        if op['operation_id'] not in scheduled:
            return op if op['tool'] in exposed else None
    return None
