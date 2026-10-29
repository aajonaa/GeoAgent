"""Deterministic ESKS text projection; originals are never modified."""
import hashlib
import json
from pathlib import Path

POLICY = 'esks-source-bound-text-v1'


def project(record):
    parts, spans, issues = [], [], []
    cursor = 0

    def append(value, pointer, page=None, kind='text'):
        nonlocal cursor
        if isinstance(value, list):
            for i, child in enumerate(value):
                append(child, pointer + '/' + str(i), page, kind)
            return
        if not isinstance(value, str) or not value:
            return
        if parts:
            cursor += 2
        start = cursor
        # PostgreSQL text forbids U+0000. The visible symbol is a one-codepoint
        # projection, recorded explicitly; source bytes remain in the archive.
        count = value.count('\x00')
        if count:
            issues.append({'code': 'nul_display_projection', 'pointer': pointer, 'count': count})
            value = value.replace('\x00', '\u2400')
        parts.append(value)
        cursor += len(value)
        spans.append({'start_char': start, 'end_char': cursor, 'source_pointer': pointer,
                      'page': page, 'kind': kind})

    parsed = record.get('parsed_content')
    field = '/parsed_content'
    if not isinstance(parsed, list):
        parsed = record.get('content')
        field = '/content'
        if isinstance(parsed, str) and record.get('content_type') == 'json':
            parsed = json.loads(parsed)
            field += '/@json'
    if isinstance(parsed, str):
        append(parsed, field)
    elif isinstance(parsed, dict) and isinstance(parsed.get('content'), str):
        append(parsed['content'], field + '/content')
        refs = parsed.get('references')
        if isinstance(refs, (str, list)):
            append(refs, field + '/references', kind='reference')
    elif isinstance(parsed, list):
        for i, block in enumerate(parsed):
            pointer = field + '/' + str(i)
            if isinstance(block, str):
                append(block, pointer)
                continue
            if not isinstance(block, dict):
                issues.append({'code': 'unsupported_block', 'pointer': pointer})
                continue
            page = block.get('page_idx')
            page = page + 1 if type(page) is int and page >= 0 else None
            kind = str(block.get('type', 'unknown'))
            keys = {'text': ('text',), 'equation': ('text', 'latex'),
                    'table': ('table_caption', 'table_body', 'table_footnote'),
                    'image': ('image_caption', 'image_footnote'),
                    'list': ('list_items', 'text'), 'code': ('code_body', 'code_caption'),
                    'interline_equation': ('text', 'latex')}.get(kind)
            if keys is None:
                keys = ('text', 'content')
                issues.append({'code': 'unrecognized_block_type', 'pointer': pointer, 'type': kind})
            emitted = set()
            for key in keys:
                value = block.get(key)
                # Some parsers repeat an equation in text and latex.
                if isinstance(value, str) and value in emitted:
                    continue
                if isinstance(value, str):
                    emitted.add(value)
                append(value, pointer + '/' + key, page,
                       'reference' if block.get('sub_type') == 'ref_text' else kind)
    else:
        issues.append({'code': 'unsupported_content_structure', 'type': type(parsed).__name__})
    text = '\n\n'.join(parts)
    if not text.strip():
        issues.append({'code': 'empty_projected_text'})
    return {'body': text, 'sha256': hashlib.sha256(text.encode()).hexdigest(),
            'spans': spans, 'issues': issues, 'policy': POLICY,
            'has_original_pdf': False, 'scientific_quality_verified': False}


def load_record(root, path, offset, length, expected_sha):
    root = Path(root).resolve()
    source = (root / path).resolve()
    if not source.is_relative_to(root) or not source.is_file():
        raise ValueError('Source path is outside corpus')
    if type(offset) is not int or type(length) is not int or offset < 0 or not 0 < length <= 128 * 1024 * 1024:
        raise ValueError('Invalid bounded source range')
    with source.open('rb') as stream:
        stream.seek(offset)
        raw = stream.read(length)
    if len(raw) != length or hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError('Original record SHA-256 mismatch')
    return json.loads(raw)


def projected_document(root, row):
    record = load_record(root, row['record_path'], row['record_offset'], row['record_length'], row['record_sha'])
    result = project(record)
    if row.get('body_sha') and result['sha256'] != row['body_sha']:
        raise ValueError('Projected body SHA-256 mismatch')
    return result


def bindings(spans, start, end):
    return [s for s in spans if s['start_char'] < end and s['end_char'] > start]
