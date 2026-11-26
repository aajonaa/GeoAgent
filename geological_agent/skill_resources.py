"""Hash-bound, task-scoped access to reviewed Skill bundles; never executes code."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

from .tools import Tool, ToolDefinition, ToolFailure, ToolOutput, object_schema

ROOT = Path(__file__).resolve().parents[1] / 'catalog' / 'skills'
MAX_TOTAL = 80 * 1024 * 1024
MAX_FILE = 20 * 1024 * 1024


def _path(value):
    if (not value or '\\' in value or ':' in value or '\x00' in value
            or PurePosixPath(value).is_absolute()
            or any(p in ('', '.', '..') for p in value.split('/'))):
        raise ToolFailure('invalid_resource_path', 'Use an exact relative resource path from the manifest.')
    return value


def _bundle(skill_id, root):
    if not re.fullmatch(r'xiaoyu_[a-z0-9_]+', skill_id):
        raise ToolFailure('unknown_skill_resources', 'This skill has no imported resource bundle.')
    directory = root / skill_id.replace('_', '-')
    if directory.is_symlink() or not directory.resolve().is_relative_to(root.resolve()):
        raise ToolFailure('invalid_resource_path', 'Skill resource directory escaped the catalog.')
    manifest = directory / 'resources.json'
    archive = directory / 'resources.zip'
    if not manifest.is_file() or not archive.is_file():
        raise ToolFailure('missing_skill_resources', 'Skill resource bundle is not installed.')
    if manifest.is_symlink() or archive.is_symlink():
        raise ToolFailure('invalid_resource_path', 'Linked resource manifests and archives are not allowed.')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if data.get('skill_id') != skill_id:
        raise ToolFailure('resource_integrity', 'Skill and resource manifest identities differ.')
    if archive.stat().st_size > MAX_TOTAL:
        raise ToolFailure('resource_limit', 'Skill archive exceeds the bounded resource size.')
    raw = archive.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != data['archive_sha256']:
        raise ToolFailure('resource_integrity', 'Skill resource archive hash mismatch.')
    rows = data['files']
    names = [_path(r['path']) for r in rows]
    if len(names) != len(set(names)) or sum(r['bytes'] for r in rows) > MAX_TOTAL:
        raise ToolFailure('resource_integrity', 'Invalid or oversized resource manifest.')
    return archive, data


def operate(args, context, *, root=ROOT):
    context.check()
    archive, manifest = _bundle(args['skill_id'], root)
    rows = manifest['files']
    action = args.get('action', 'list')
    response = {'skill_id': args['skill_id'], 'action': action,
                'archive_sha256': manifest['archive_sha256'],
                'execution_performed': False}
    if action == 'list':
        offset, limit = args.get('offset', 0), args.get('limit', 50)
        if limit > 100:
            raise ToolFailure('invalid_arguments', 'List at most 100 resources per page.')
        response.update(files=rows[offset:offset + limit], total=len(rows),
                        next_offset=offset + limit if offset + limit < len(rows) else None)
        return ToolOutput(response)
    if action not in ('read', 'prepare'):
        raise ToolFailure('invalid_arguments', 'Unknown resource action.')
    with zipfile.ZipFile(archive) as z:
        actual = [i.filename for i in z.infolist()]
        if len(actual) != len(set(actual)) or set(actual) != {r['path'] for r in rows}:
            raise ToolFailure('resource_integrity', 'Archive members differ from the frozen manifest.')
        index = {r['path']: r for r in rows}

        def read(name):
            context.check()
            info = z.getinfo(name)
            row = index[name]
            mode = info.external_attr >> 16
            if (info.file_size != row['bytes'] or info.file_size > MAX_FILE
                    or (mode & 0o170000) == 0o120000):
                raise ToolFailure('resource_integrity', 'Invalid resource size or linked member.')
            raw = z.read(info)
            if hashlib.sha256(raw).hexdigest() != row['sha256']:
                raise ToolFailure('resource_integrity', 'Skill resource file hash mismatch.')
            return raw

        if action == 'read':
            name = _path(args.get('path', ''))
            if name not in index:
                raise ToolFailure('unknown_skill_resource', 'Resource is not in this skill manifest.')
            raw = read(name)
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                raise ToolFailure('binary_resource', 'Use prepare to copy binary resources into the task.') from None
            if '\x00' in text:
                raise ToolFailure('binary_resource', 'Use prepare to copy binary resources into the task.')
            start, size = args.get('offset', 0), args.get('limit', 12000)
            response.update(path=name, sha256=index[name]['sha256'], text=text[start:start+size],
                            total_characters=len(text), next_offset=start+size if start+size<len(text) else None)
            return ToolOutput(response)

        # Validate every member before creating anything in the task workspace.
        payloads = {r['path']: read(r['path']) for r in rows}
        prefix = '.agent/skill-resources/' + args['skill_id'] + '/' + manifest['archive_sha256'][:16]
        destination = context.path(prefix)
        targets = {name: context.path(prefix + '/' + _path(name)) for name in payloads}
        if not all(p.is_relative_to(destination) for p in targets.values()):
            raise ToolFailure('invalid_resource_path', 'Resource destination escaped its task directory.')
        for name, target in targets.items():
            if target.exists() and (not target.is_file() or target.read_bytes() != payloads[name]):
                raise ToolFailure('resource_destination_conflict', 'Existing task resource differs; it was not overwritten.')
        for name, target in targets.items():
            context.check()
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as f:
                    f.write(payloads[name])
        response.update(workspace_root=prefix, files_copied=len(targets),
                        message='Resources copied only. Dependencies and scientific workflows have not been executed or validated.')
        return ToolOutput(response)


def register_skill_resources(registry):
    text = {'type': 'string'}
    schema = object_schema({
        'skill_id': {**text, 'pattern': '^xiaoyu_[a-z0-9_]+$', 'description': 'Exact imported skill ID from skill_find.'},
        'action': {**text, 'enum': ['list', 'read', 'prepare'], 'default': 'list',
                   'description': 'List resources, read a UTF-8 slice, or copy the verified bundle into this task. No code executes.'},
        'path': {**text, 'maxLength': 400, 'description': 'Exact manifest-relative file path, required for read.'},
        'offset': {'type': 'integer', 'minimum': 0, 'default': 0, 'description': 'File-list row offset or text-character offset.'},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 12000, 'default': 50, 'description': 'Maximum list entries or characters returned.'},
    }, ['skill_id'])
    schema['allOf'] = [
        {'if': {'properties': {'action': {'const': 'read'}}, 'required': ['action']},
         'then': {'required': ['path']}},
        {'if': {'properties': {'action': {'const': 'list'}}},
         'then': {'properties': {'limit': {'maximum': 100}}}},
    ]
    registry.register(Tool(ToolDefinition('SkillReadResource',
        'Read or prepare frozen supporting files for an imported scientific skill; verifies SHA-256 and never executes scripts.',
        'Use after loading a Xiaoyu collection skill, when its referenced script, data, license or supporting document is needed.',
        schema, {'type':'object', 'required':['skill_id','action','archive_sha256','execution_performed'],
                 'properties':{'skill_id':text,'action':text,'archive_sha256':text,'execution_performed':{'const':False}}}),
        operate, pure=False))
