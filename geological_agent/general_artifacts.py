"""Workspace file tools attached to the three existing general-purpose skills."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

from . import general_renderer, tools
from .tools import Tool, ToolDefinition, ToolFailure, ToolOutput, artifact, object_schema

WORD = 'GeoWordDocument'
PDF = 'GeoPDFPages'
IMAGE = 'GeoIllustration'
GUIDES = {
    'xiaoyu_docx': (WORD, '按模板填充字段，生成含可编辑表格、图片和引用的 Word 报告。',
        '生成 Word 时优先用 GeoWordDocument。若用户提供模板，用 template 和 fields 填入正文或表格中的 {{字段}}。'
        '用 blocks 按顺序添加标题、段落、表格、插图或参考文献。交付返回的 DOCX。'),
    'xiaoyu_pdf': (PDF, '读取 PDF 指定页、按顺序摘页、合并，并保留来源页码。',
        '先用 GeoPDFPages 的 inspect 操作读取所需页，页码从 1 开始。扫描页缺文字时查看原图。'
        '用 assemble 按来源和页码顺序生成 PDF，并交付可追溯到原文件和页码的 JSON 清单。'),
    'image_workflow': (IMAGE, '按描述生成和修改可编辑矢量插图、示意图，导出 SVG 和 PNG。',
        '用户要求生成插图时，按描述设计构图、配色、图形与文字，调用 GeoIllustration 输出可编辑 SVG 和 PNG。'
        '优先用 path、polygon、circle 和 text 描绘对象。修改现有插图时先读取 SVG，再提交修改后的完整图形。'
        '尺寸用整数，颜色用十六进制或颜色名，属性直接写到元素上。使用内联矢量形状。'),
}

def extend_skill(skill, resolved):
    guide = GUIDES.get(skill.summary.id)
    if not guide or guide[0] not in resolved:
        return skill
    name, description, instructions = guide
    return replace(skill, summary=replace(skill.summary, description=skill.summary.description + ' ' + description),
                   instructions=instructions + '\n\n' + skill.instructions, tool_names=(*skill.tool_names, name))

def string(limit):
    return {'type':'string','minLength':1,'maxLength':limit}

def array(item, limit, minimum=1):
    return {'type':'array','items':item,'minItems':minimum,'maxItems':limit}

def variant(kind, fields, required):
    return object_schema({'kind':{'const':kind}, **fields}, ['kind', *required])

def register_general_tools(registry):
    path = string(240)
    blocks = {'oneOf': [
        variant('paragraph', {'text':string(8000)}, ['text']),
        variant('heading', {'text':string(300),'level':{'type':'integer','minimum':0,'maximum':6}}, ['text']),
        variant('table', {'rows':array(array({'type':'string','maxLength':2000},16),100)}, ['rows']),
        variant('image', {'path':path,'caption':string(500)}, ['path']),
    ]}
    word = object_schema({'title':string(300),'template':path,
        'fields':{'type':'object','maxProperties':80,'propertyNames':string(100),'additionalProperties':{'type':'string','maxLength':4000}},
        'blocks':array(blocks,120)})
    word['anyOf'] = [{'required':[key]} for key in ('blocks','template','title')]
    word['dependentRequired'] = {'fields':['template']}
    source = object_schema({'path':path,'pages':array({'type':'integer','minimum':1},150)}, ['path'])
    pdf = object_schema({'operation':{'enum':['inspect','assemble']},'sources':array(source,20)}, ['operation','sources'])
    image = object_schema({'svg':string(100000),'width':{'type':'integer','minimum':64,'maximum':2048},
                           'height':{'type':'integer','minimum':64,'maximum':2048}}, ['svg','width','height'])
    for name, schema, description, handler in [
        (WORD,word,'Create an editable DOCX, optionally fill {{fields}} in a template, append headings, text, native tables and PNG/JPEG images.',word_document),
        (PDF,pdf,'Inspect PDF page text or assemble selected pages from multiple files with a source map. Pages are one-based. Omit pages to select all (inspect previews the first five).',pdf_pages),
        (IMAGE,image,'Render an original inline vector illustration designed by the agent as editable SVG and PNG. Use svg/g/path/rect/circle/ellipse/line/polygon/polyline/text/tspan and presentation attributes.',illustration),
    ]:
        registry.register(Tool(ToolDefinition(name,description,description,schema,{'type':'object'}),handler))

def input_file(ctx, name, extensions):
    file = ctx.path(name)
    if file.suffix.lower() not in extensions or not file.is_file() or not 0 < file.stat().st_size <= 50*1024*1024:
        raise ToolFailure('invalid_input_file','Select a supported workspace file of at most 50 MiB.',retryable=True)
    return str(file)

def word_document(args,ctx):
    args = dict(args)
    if 'template' in args:
        args['template'] = input_file(ctx,args['template'],{'.docx'})
    args['blocks'] = [{**b,'path':input_file(ctx,b['path'],{'.png','.jpg','.jpeg'})}
                      if b['kind']=='image' else b for b in args.get('blocks',[])]
    return render('word',args,ctx)

def pdf_pages(args,ctx):
    sources = [{**s,'name':s['path'],'path':input_file(ctx,s['path'],{'.pdf'})} for s in args['sources']]
    return render('pdf',{**args,'sources':sources},ctx)

def illustration(args,ctx):
    return render('illustration',args,ctx)

def render(kind,args,ctx):
    vendor = Path(tools.__file__).resolve().parents[2]/'vendor/general-artifacts-v1'
    if not vendor.is_dir():
        raise ToolFailure('renderer_unavailable','The general artifact renderer dependencies are unavailable.')
    ctx.workspace.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='oresage-render-') as scratch:
        directory = Path(scratch)
        request = directory/'request.json'
        request.write_text(json.dumps(args),encoding='utf-8')
        command = [sys.executable,'-I','-B',general_renderer.__file__,str(vendor),kind,str(request)]
        with subprocess.Popen(command,cwd=directory,env={'LANG':'C.UTF-8','PATH':'/usr/bin:/bin'},
                              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) as proc:
            try:
                while True:
                    ctx.check()
                    try:
                        proc.wait(timeout=.15)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                if proc.poll() is None:
                    proc.kill()
        if proc.returncode or not (directory/'result.json').is_file():
            raise ToolFailure('render_failed','Rendering failed or exceeded the processing limit.',retryable=True)
        result = json.loads((directory/'result.json').read_bytes())
        if 'error' in result:
            raise ToolFailure('invalid_document',result['error'],retryable=True)
        files = result.pop('files',[])
        prefix = kind + '-' + uuid.uuid4().hex[:14]
        published = []
        try:
            for name in files:
                ctx.check()
                target = ctx.path(prefix + '-' + name)
                with target.open('xb') as out:
                    published.append(target)
                    with (directory/name).open('rb') as stream:
                        shutil.copyfileobj(stream,out)
        except BaseException:
            for target in published:
                target.unlink(missing_ok=True)
            raise
        return ToolOutput({**result,'files':[p.name for p in published]},tuple(artifact(p,ctx) for p in published))
