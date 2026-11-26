"""Isolated file rendering worker. Inputs are workspace paths resolved by the caller."""
import hashlib
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile


def fill_fields(document, fields):
    from docx.oxml.ns import qn
    if not fields:
        return
    tokens = {'{{' + key + '}}': value for key,value in fields.items()}
    pattern = re.compile('|'.join(map(re.escape,tokens)))
    found = set()
    for part in document.part.package.parts:
        if part.content_type.split('.')[-2:] not in (['document','main+xml'], ['wordprocessingml','header+xml'],
                                                     ['wordprocessingml','footer+xml']):
            continue
        for paragraph in part.element.iter(qn('w:p')):
            nodes = list(paragraph.iter(qn('w:t')))
            texts = [n.text or '' for n in nodes]
            spans = []
            end = 0
            for node,text in zip(nodes,texts):
                spans.append((end,end + len(text),node))
                end += len(text)
            for match in reversed(list(pattern.finditer(''.join(texts)))):
                found.add(match.group())
                replacement = tokens[match.group()]
                for start,end,node in spans:
                    if start >= match.end() or end <= match.start() or start == end:
                        continue
                    text = node.text or ''
                    node.text = text[:max(0,match.start()-start)] + replacement + text[max(0,match.end()-start):]
                    node.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
                    replacement = ''
    if missing := sorted(tokens.keys()-found):
        raise ValueError('Missing template field(s): ' + ', '.join(missing)[:400])


def word(args):
    from docx import Document
    from docx.shared import Inches
    from PIL import Image
    if template := args.get('template'):
        with ZipFile(template) as archive:
            if sum(i.file_size for i in archive.infolist()) > 100*1024**2:
                raise ValueError('Template exceeds the expanded size limit.')
    document = Document(template)
    fill_fields(document,args.get('fields',{}))
    if title := args.get('title'):
        document.add_heading(title,0)
    for block in args.get('blocks',[]):
        kind = block['kind']
        if kind == 'paragraph':
            document.add_paragraph(block['text'])
        elif kind == 'heading':
            document.add_heading(block['text'],level=block.get('level',1))
        elif kind == 'table':
            rows = block['rows']
            width = len(rows[0])
            if any(len(row)!=width for row in rows):
                raise ValueError('Use the same number of cells in each table row.')
            table = document.add_table(rows=len(rows),cols=width)
            if 'Table Grid' in document.styles:
                table.style = 'Table Grid'
            for row,values in zip(table.rows,rows):
                for cell,value in zip(row.cells,values):
                    cell.text = value
        elif kind == 'image':
            with Image.open(block['path']) as image:
                if image.format not in ('PNG','JPEG') or image.width*image.height > 25_000_000:
                    raise ValueError('Select a PNG or JPEG under 25 megapixels.')
                image.verify()
            section = document.sections[-1]
            width = section.page_width-section.left_margin-section.right_margin
            document.add_picture(block['path'],width=min(Inches(6),width))
            if block.get('caption'):
                document.add_paragraph(block['caption'])
    document.save('report.docx')
    Document('report.docx')
    return {'files':['report.docx'],'blocks':len(args.get('blocks',[]))}


def pdf(args):
    from pypdf import PdfReader, PdfWriter
    assembling = args['operation']=='assemble'
    writer = PdfWriter() if assembling else None
    pages, sources = [], []
    for spec in args['sources']:
        reader = PdfReader(spec['path'])
        if reader.is_encrypted:
            raise ValueError('Provide an unlocked PDF.')
        count = len(reader.pages)
        selected = spec.get('pages',range(1,1+(count if assembling else min(5,count))))
        if not selected or len(pages)+len(selected) > (150 if assembling else 20):
            raise ValueError('Select between 1 and 150 output pages, or up to 20 pages for inspection.')
        if any(n<1 or n>count for n in selected):
            raise ValueError(f"Page outside 1–{count} in {spec['name']}.")
        with open(spec['path'],'rb') as fp:
            digest = hashlib.file_digest(fp,'sha256').hexdigest()
        sources.append({'file':spec['name'],'page_count':count,'sha256':digest})
        for n in selected:
            page = reader.pages[n-1]
            record = {'source':spec['name'],'source_page':n}
            if assembling:
                writer.add_page(page)
                record['output_page'] = len(pages)+1
            else:
                text = page.extract_text() or ''
                record.update(text=text[:1600],truncated=len(text)>1600)
            pages.append(record)
    if not assembling:
        return {'sources':sources,'pages':pages}
    with open('pages.pdf','wb') as out:
        writer.write(out)
    if len(PdfReader('pages.pdf').pages)!=len(pages):
        raise ValueError('Exported page count differs from the selection.')
    Path('sources.json').write_text(json.dumps({'sources':sources,'pages':pages},ensure_ascii=False,indent=2),encoding='utf8')
    return {'files':['pages.pdf','sources.json'],'page_count':len(pages)}


SVG = 'http://www.w3.org/2000/svg'
SHAPES = set('svg g path rect circle ellipse line polygon polyline text tspan title desc'.split())
ATTRS = set(('viewBox width height x y x1 x2 y1 y2 cx cy r rx ry d points fill stroke stroke-width stroke-linecap '
             'stroke-linejoin stroke-dasharray opacity fill-opacity stroke-opacity fill-rule transform font-size '
             'font-family font-weight text-anchor dominant-baseline dx dy').split())


def illustration(args,vendor):
    from defusedxml.ElementTree import fromstring
    import xml.etree.ElementTree as ET
    import resvg_py
    from PIL import Image
    from io import BytesIO
    root = fromstring(args['svg'],forbid_dtd=True)
    if root.tag not in ('svg','{'+SVG+'}svg'):
        raise ValueError('Provide one SVG root element.')
    for i,node in enumerate(root.iter()):
        tag = node.tag.removeprefix('{'+SVG+'}')
        if i>=1500 or tag not in SHAPES or (i and tag=='svg') or set(node.attrib)-ATTRS:
            raise ValueError('Use supported inline vector elements and presentation attributes only.')
        for value in node.attrib.values():
            if re.search(r'url\s*\(|[\\\x00-\x08]',value,re.I):
                raise ValueError('External resources are not supported.')
        node.tag = '{'+SVG+'}'+tag
        if tag in ('text','tspan'):
            node.set('font-family','Noto Sans CJK SC')
    width,height = args['width'],args['height']
    root.attrib.setdefault('viewBox',f'0 0 {width} {height}')
    root.set('width',str(width))
    root.set('height',str(height))
    ET.register_namespace('',SVG)
    svg = ET.tostring(root,encoding='unicode')
    png = resvg_py.svg_to_bytes(svg_string=svg,font_files=[str(vendor/'NotoSansCJKsc-Regular.otf')])
    with Image.open(BytesIO(png)) as result:
        if result.size != (width,height) or result.convert('RGBA').getchannel('A').getbbox() is None:
            raise ValueError('No visible shapes were rendered at the requested dimensions.')
    Path('illustration.svg').write_text(svg,encoding='utf8')
    Path('illustration.png').write_bytes(png)
    return {'files':['illustration.svg','illustration.png'],'width':width,'height':height}


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU,(24,25))
    resource.setrlimit(resource.RLIMIT_AS,(1536*1024**2,1536*1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE,(100*1024**2,100*1024**2))
    vendor,kind,request = sys.argv[1:]
    sys.path.insert(0,vendor)
    args = json.loads(Path(request).read_bytes())
    try:
        if kind == 'illustration':
            result = illustration(args,Path(vendor))
        else:
            result = {'word':word,'pdf':pdf}[kind](args)
    except Exception as exc:
        result = {'error':str(exc)[:450] if isinstance(exc,ValueError) else
                  f'{type(exc).__name__} while reading or rendering the input.'}
    Path('result.json').write_text(json.dumps(result),encoding='utf8')


if __name__=='__main__':
    main()
