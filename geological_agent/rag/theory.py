"""Recall and order verified passages for general questions about geological models."""
import re
import unicodedata


_SUBJECTS = (
    (r"造山型|orogenic", ("造山型", "orogenic")),
    (r"卡林型|carlin", ("卡林型", "carlin")),
    (r"浅成低温热液|epithermal", ("浅成低温热液", "epithermal")),
    (r"斑岩型|porphyry", ("斑岩", "porphyry")),
    (r"金矿|金成矿|gold deposit|gold mineralization", ("金矿", "金成矿", "gold deposit", "golddeposit", "gold mineralization", "goldmineralization")),
    (r"流体包裹体|fluid inclusion", ("流体包裹体", "fluid inclusion")),
    (r"成矿作用|ore formation|metallogen", ("成矿作用", "ore formation", "metallogen")),
)
_INTENT = re.compile(
    r"理论|(?:成因|成矿)(?:模型|模式|机制)|(?:流体|物质)(?:有哪些)?来源|综述|基本原理|"
    r"\b(?:theor(?:y|ies)|models?|mechanisms?|review|origin of (?:ore.forming )?fluids?)\b", re.I)
_SPECIFIC = re.compile(
    r"附近|周边|范围为|矿点|矿区|实例|以.{1,30}为例|《|\b(?:nearby|case study|according to|doi:)\b|"
    r"\b10\.\d{4,9}/|\bK[a-f0-9]{32}_\d+|\b[A-Z]+[-_]\d+", re.I)
_CASE_TITLE = re.compile(
    r"为例|资源(?:量|储量)|潜力|试验研究|勘探预测|控矿因素|"
    r"\b(?:case study|resource estimate|fluid inclusion measurements?)\b", re.I)
_PARENT = re.compile(
    r"综述|概论|研究进展|述评|理论|分类|(?:主要|不同)(?:类型|模型|模式)|(?:成因|成矿)(?:模型|模式|机制)|"
    r"\b(?:review|overview|genetic\s*models?|metallogenic\s*models?|genesis\s*models?|"
    r"mineralization\s*mechanisms?|viable\s*models?|classification)\b", re.I)
_PARENT_SQL = (
    "%综述%", "%研究进展%", "%述评%", "%理论%", "%成矿模式%", "%成矿模型%", "%成因模型%",
    "%成矿机制%", "%分类%", "%review%", "%overview%", "%genetic%model%", "%metallogenic%model%",
    "%viable%model%", "%classification%",
)
_SECTION = re.compile(r"摘要|引言|结论|讨论|成因|成矿|流体来源|abstract|introduction|conclusions?|discussion|genesis|fluid sources?", re.I)
_BIB = re.compile(r"参考文献|文献目录|采集对照|下载清单|\breferences\b|\bbibliography\b", re.I)
_START_OF_REFERENCE = re.compile(
    r"(?:^|(?<=\n)|(?<=\d))\s*[A-Z][A-Za-z'’\-]{1,34}(?:\s*,\s*|\s+)(?:[A-Z]\.\s*){1,4}"
)
_JOURNAL_COORDINATES = re.compile(
    r"\b(?:Vol\.|No\.|pp?\.|ISSN|Springer-Verlag)\s*\d*|"
    r"\b(?:18|19|20)\d{2}\s*\)\.\s+[A-Z]|\d{1,4}\s*[,，:]\s*\d{2,4}\s*[–\-]\s*\d{2,4}"
)
_REFERENCE_ENTRY = re.compile(
    r"\b[A-Z][A-Za-z'’\-]{2,35}(?:\s*,\s*|\s+)(?:[A-Z]\.\s*){1,4}.{0,300}?\([^)]{0,8}(?:19|20)\d{2}[a-z]?\)"
)
_EXPLANATION = re.compile(
    r"(?:流体|物质)(?:主要|可能|可|最可能)?(?:来自|来源于|源自|起源于)|"
    r"变质脱挥发|成矿端元|富集岩石圈地幔|板片脱水|流体不混溶|流体混合|硫化作用|"
    r"(?:提出|归纳|认为|比较|解释).{0,28}(?:模型|模式|机制)|"
    r"(?:模型|模式|机制).{0,28}(?:认为|强调|解释|认为是|包括)|"
    r"\b(?:derived from|sourced from|fluid mixing|metamorphic devolatilization|"
    r"magmatic fluids?|sedimentary origin|sulfidation|genetic models?|fluid sources?)\b", re.I)


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())


def subject(query):
    """Keep local, explicit-document and exact identifier requests on their existing path."""
    value = normalized(query)
    if len(value) > 210 or not _INTENT.search(value) or _SPECIFIC.search(value):
        return ()
    # A named mine immediately preceding 金矿 is a local genesis question.
    compact = re.sub(r'^(?:请|搜索|查找|介绍|请介绍|解释|关于|比较|总结)+\s*', '', value)
    match = re.match(r'^([\u3400-\u9fff]{1,12})金矿', compact)
    if match and not any(re.search(pattern, match[1], re.I) for pattern, _ in _SUBJECTS[:4]):
        if match[1] not in {'各种', '主要', '不同', '常见', '典型', '全球', '我国', '世界'}:
            return ()
    if re.search(r"\b(?:at the|in the|of the)\s+[^,?]{1,50}\s+gold deposit\b", value, re.I):
        return ()
    return next((terms for pattern, terms in _SUBJECTS if re.search(pattern, value, re.I)), ())


def mentions(value, terms):
    compact = value.replace(' ', '')
    return any(term.replace(' ', '') in compact for term in terms)


def parent_score(title, terms):
    name = normalized(title)
    if not mentions(name, terms) or _BIB.search(name):
        return 0
    return 2 * bool(_PARENT.search(name)) + int(not _CASE_TITLE.search(name))


def parent_patterns(terms):
    return ([f'%{term}%' for term in terms], list(_PARENT_SQL))


def bibliography(row):
    body = row.get('text') or ''
    first = body.lstrip()
    paragraphs = [paragraph for paragraph in body.split('\n\n') if paragraph.strip()]
    if len(paragraphs) >= 2 and sum(
            bool(_START_OF_REFERENCE.match(p.lstrip()) and re.search(r'\b(?:19|20)\d{2}\b', p))
            for p in paragraphs) >= max(2, (len(paragraphs)+1)//2):
        return True
    return (_START_OF_REFERENCE.match(first) is not None
            and (len(_START_OF_REFERENCE.findall(body)) >= 2 or len(_JOURNAL_COORDINATES.findall(body)) >= 3
                 or len(_REFERENCE_ENTRY.findall(body)) >= 2))


def evidence_grade(row, terms):
    title = normalized(row.get('title'))
    meta = row.get('metadata') or {}
    sections = meta.get('physical_section_path') or meta.get('section_path') or []
    heading = normalized(' '.join(str(part) for part in sections))
    body = normalized(row.get('text'))
    # File names and bibliographic mentions are useful navigation, but the
    # actual explanation must survive in the original passage.
    if (_BIB.search(heading) or _BIB.search(title) or body.startswith(('{"row"', 'references', '参考文献'))
            or bibliography(row)):
        return 0
    # Chinese PDF projections may separate the characters of a single word.
    evidence = re.sub(r'(?<=[\u3400-\u9fff]) (?=[\u3400-\u9fff])', '', body)
    direct = mentions(evidence, terms)
    matches = _EXPLANATION.findall(evidence)
    if not (direct or mentions(' '.join((title, heading)), terms)) or not matches:
        return 1
    if len(matches) >= 2 and (direct or _PARENT.search(heading)):
        return 3
    return 2


def context_input(row):
    context = [str(part) for part in (row.get('metadata') or {}).get('section_path', []) if _SECTION.search(str(part))]
    # Section labels frequently duplicate the catalog title in structured PDFs.
    heading = ' / '.join(dict.fromkeys([row['title'], *context]))[:240]
    return heading + '\n\n' + row['rerank_input']


def preferred_parent(row, terms):
    metadata = row.get('metadata') or {}
    heading = ' '.join(metadata.get('section_path') or [])
    title = row.get('title')
    domain = normalized(title) + ' ' + normalized(heading)
    return (2 * bool(mentions(domain, terms)) + max(parent_score(title, terms), parent_score(heading, terms)))


def general_explanation(row, terms):
    body = normalized(row.get('text'))
    titles = row.get('metadata') or {}
    name = normalized((titles.get('section_path') or [row.get('title')])[0])
    if not mentions(name, terms):
        return 0
    if re.search(r'金矿床.{0,9}分类|金成矿作用与|金矿.{0,8}综述|\ban overview\b', name):
        return 2
    return int(bool(re.search(r'\b(?:review|classification)\b|不同(?:成因|模型)|两种.{0,12}模型|三种.{0,12}模式', name+' '+body)))


def select(candidates, terms, limit):
    """Select verified evidence across sources without cloning one paper's passages."""
    eligible = [row for row in candidates if row.get('selection_reason') in ('selected', 'outside_result_limit')]
    unique = {row['citation_id']: row for row in reversed(eligible)}
    graded = [(evidence_grade(row, terms), row) for row in unique.values()]
    def order(item):
        grade, row = item
        broad = ('金矿' in terms or 'metallogen' in terms) and grade >= 2
        return (-general_explanation(row, terms) if broad else 0, -grade,
                -preferred_parent(row, terms) if grade >= 2 else 0, -row['rerank_score'], row['citation_id'])

    ranked = sorted(graded, key=order)
    chosen, deferred = [], []
    documents, texts = set(), set()
    for grade, row in ranked:
        if grade == 0:
            continue
        body = re.sub(r'\s+', '', normalized(row['text']))
        if body in texts:
            continue
        texts.add(body)
        keys = {('title', normalized(row['title']).replace(' ', '')),
                ('source', row.get('source_sha') or row.get('sha256') or row['document_id'])}
        if keys & documents:
            deferred.append(row)
            continue
        documents.update(keys)
        chosen.append(row)
    limit = max(1, min(8, int(limit)))
    result = chosen[:limit]
    for row in deferred:
        if len(result) >= limit:
            break
        key = row.get('sha256')
        start, end = row.get('start_char'), row.get('end_char')
        if key and type(start) is int and type(end) is int and any(
                key == other.get('sha256') and type(other.get('start_char')) is int
                and type(other.get('end_char')) is int
                and min(end, other['end_char']) - max(start, other['start_char']) > .4 * (end - start)
                for other in result):
            continue
        result.append(row)
    return result
