"""Account analytics from immutable task traces and provider usage receipts."""
from collections import Counter
from datetime import datetime, time as day_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import json, re, threading, time
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from .usage_audit import token_usage

TZ = ZoneInfo('Asia/Shanghai')


def timestamp(value, fallback=0):
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (AttributeError, TypeError, ValueError):
        return fallback


def period(start, end):
    today = datetime.now(TZ).date()
    try:
        first = datetime.strptime(start, '%Y-%m-%d').date() if start else today - timedelta(days=29)
        last = datetime.strptime(end, '%Y-%m-%d').date() if end else today
        if first > last or last > today or (last - first).days > 3660:
            raise ValueError()
    except ValueError:
        raise HTTPException(400, 'Invalid date range (maximum 3661 days)') from None
    return {'start': first.isoformat(), 'end': last.isoformat(), 'days': (last - first).days + 1,
            'from': datetime.combine(first, day_time.min, TZ).timestamp(),
            'until': datetime.combine(last + timedelta(days=1), day_time.min, TZ).timestamp(),
            'timezone': 'Asia/Shanghai', 'daily_average_basis': 'selected calendar days, including days without activity'}


class Analytics:
    def __init__(self, store, audit):
        self.store, self.audit = store, audit
        self.cache, self.lock = {}, threading.RLock()

    def lines(self, path):
        # A partial final line from an active writer is retried on the next refresh.
        with path.open(encoding='utf-8', errors='replace') as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        yield row
                except (ValueError, TypeError):
                    continue

    def trace(self, run):
        path = self.store.root / 'traces' / (run['id'] + '.jsonl')
        if not path.is_file():
            return {'missing': True, 'calls': [], 'tools': [], 'skills': [], 'retrievals': []}
        st = path.stat();key = (st.st_mtime_ns, st.st_size, run['model'])
        with self.lock:
            if path in self.cache and self.cache[path][0] == key:
                return self.cache[path][1]
            out = {'missing': False, 'calls': [], 'tools': [], 'skills': [], 'retrievals': []}
            tool_calls, pending = [], {}
            requested = 0; requested_at = run['created']
            for row in self.lines(path):
                event = row.get('event', '')
                at = timestamp(row.get('time'), run['created'])
                if event in ('model_requested','completion_review_requested'):
                    requested += 1; requested_at = at
                if event in ('model_responded', 'completion_review_responded'):
                    response = row.get('response') or {}
                    out['calls'].append({'time': at, 'rid': run['id'], 'category': 'task',
                        'model': run['model'] if run['model']!='unknown' else (response.get('provider_metadata') or {}).get('model') or 'unknown', 'reported_model': (response.get('provider_metadata') or {}).get('model'),
                        'usage': token_usage(response.get('usage')), 'source': 'historical_trace'})
                elif event in ('model_failed', 'completion_review_failed'):
                    out['calls'].append({'time': at, 'rid': run['id'], 'model': run['model'],
                        'usage': token_usage(None), 'source': 'historical_trace', 'error_type': 'historical_failure'})
                elif event == 'tool_requested':
                    call = row.get('call') or {};identifier = str(call.get('id') or len(tool_calls))
                    pending.setdefault(identifier,[]).append(len(tool_calls))
                    tool_calls.append({'time': at, 'rid': run['id'], 'name': call.get('name', 'unknown'), 'call_id': identifier,'status':'unknown','cached':False})
                elif event in ('tool_completed', 'tool_failed'):
                    result = row.get('result') or {}
                    waiting=pending.get(str(result.get('call_id')),[])
                    if waiting:tool_calls[waiting.pop(0)].update(status=result.get('status',event),cached=bool(result.get('cached')))
                elif event == 'skill_loaded':
                    out['skills'].append({'time': at, 'rid': run['id'], 'skill': row.get('skill_id', 'unknown'),
                        'source': row.get('source'), 'exposed_tools': row.get('exposed_tools', [])})
                elif event == 'knowledge_completed':
                    result = row.get('result') or {}
                    out['retrievals'].append({'time': at, 'rid': run['id'], 'query': result.get('query', row.get('query', '')),
                        'status': result.get('status'), 'duration_ms': result.get('duration_ms'),
                        'references': result.get('references', []), 'candidates': len(result.get('candidates') or []), 'source': 'agent'})
            out['tools']=tool_calls
            for _ in range(max(0,requested-len(out['calls']))):
                out['calls'].append({'time':requested_at,'rid':run['id'],'model':run['model'],'usage':token_usage(None),'source':'historical_trace','error_type':'unrecorded_response'})
            self.cache[path] = (key, out)
            return out

    def data(self):
        with self.store.lock:
            users = [dict(r) for r in self.store.db.execute('SELECT id,username,role,disabled FROM users')]
            runs = [dict(r) for r in self.store.db.execute(
                'SELECT r.id,c.uid,r.created,r.finished_at,r.status,r.turns FROM runs r JOIN conversations c ON c.id=r.cid ORDER BY r.created DESC')]
            models = {}
            for r in self.store.db.execute("SELECT e.rid,e.data FROM events e WHERE json_extract(e.data,'$.kind')='model_config'"):
                try:
                    d = json.loads(r['data']);models[r['rid']] = (d.get('profile') or {}).get('model') or 'unknown'
                except (ValueError, TypeError, AttributeError):
                    pass
        result = {u['id']: {**u, 'runs': [], 'calls': [], 'tools': [], 'skills': [], 'retrievals': [], 'missing_traces': 0} for u in users}
        for uid, item in result.items():
            tracked, attempts, outcomes = set(), {}, {}
            path = self.audit.root / (uid + '.jsonl')
            if path.is_file():
                for row in self.lines(path):
                    event = row.get('event')
                    if event == 'model_attempt':
                        attempts[row['call_id']] = row
                        if row.get('category') == 'task' and row.get('rid'):
                            tracked.add(row['rid'])
                    elif event in ('model_usage', 'model_error'):
                        # A duplicate terminal receipt cannot count a call twice.
                        old = outcomes.get(row['call_id'])
                        if old is None or event == 'model_usage':
                            outcomes[row['call_id']] = row
                    elif event == 'knowledge_search':
                        item['retrievals'].append(row)
                for call_id, row in attempts.items():
                    done = outcomes.get(call_id, {})
                    item['calls'].append({**row, **done, 'time': row['time'], 'usage': done.get('usage', token_usage(None)), 'source': 'provider_receipt'})
            item['_tracked'] = tracked
        for run in runs:
            item = result.get(run['uid'])
            if item is None:
                continue
            run['model'] = models.get(run['id'], 'unknown')
            record = self.trace(run);item['runs'].append(run)
            item['missing_traces'] += int(record['missing'])
            if run['id'] not in item['_tracked']:
                item['calls'].extend(record['calls'])
            for key in ('tools', 'skills', 'retrievals'):
                item[key].extend(record[key])
        return result

    def summarize(self, item, bounds):
        selected = lambda rows: [r for r in rows if bounds['from'] <= r.get('time', 0) < bounds['until']]
        calls = selected(item['calls'])
        total = sum((r.get('usage') or {}).get('total_tokens') or 0 for r in item['calls'])
        period_tokens = sum((r.get('usage') or {}).get('total_tokens') or 0 for r in calls)
        model_counts = Counter(str(r.get('model') or 'unknown') for r in calls)
        return {'id': item['id'], 'username': item['username'], 'role': item['role'], 'disabled': item['disabled'],
            'total_tokens': total, 'period_tokens': period_tokens, 'daily_average_tokens': round(period_tokens / bounds['days'], 2),
            'input_tokens': sum((r.get('usage') or {}).get('input_tokens') or 0 for r in calls),
            'output_tokens': sum((r.get('usage') or {}).get('output_tokens') or 0 for r in calls),
            'model_calls': len(calls), 'models': dict(model_counts), 'tool_calls': len(selected(item['tools'])),
            'skill_loads': len(selected(item['skills'])), 'retrieval_calls': len(selected(item['retrievals'])),
            'missing_usage_calls': sum((r.get('usage') or {}).get('total_tokens') is None for r in calls),
            'all_time_missing_usage_calls': sum((r.get('usage') or {}).get('total_tokens') is None for r in item['calls']),
            'missing_traces': item['missing_traces'], 'runs': len(item['runs'])}


def install_usage_routes(app, auth, store, audit):
    service = Analytics(store, audit)
    app.state.usage_analytics = service

    @app.get('/api/admin/usage')
    def overview(request: Request, start: str = '', end: str = ''):
        auth(request, admin=True);bounds = period(start, end)
        data = service.data()
        return {'period': bounds, 'items': [service.summarize(u, bounds) for u in data.values()],
            'accounting_errors': audit.errors,
            'coverage': 'Provider-reported tokens only. Missing usage is unknown, not zero. Historical unrecorded auxiliary requests cannot be reconstructed. Total is all-time; other metrics use selected dates.'}

    @app.get('/api/admin/usage/users/{uid}')
    def detail(uid: str, request: Request, start: str = '', end: str = '', page: int = 1):
        auth(request, admin=True);bounds = period(start, end)
        if not 1 <= page <= 100000:
            raise HTTPException(400, 'Invalid page')
        item = service.data().get(uid)
        if item is None:
            raise HTTPException(404, 'User not found')
        selected = lambda rows: sorted((r for r in rows if bounds['from'] <= r.get('time', 0) < bounds['until']), key=lambda r:r.get('time',0), reverse=True)
        models = {}
        for call in selected(item['calls']):
            name = str(call.get('model') or 'unknown');row = models.setdefault(name, {'model': name, 'calls': 0, 'tokens': 0, 'missing_usage': 0, 'reported_models': set()})
            row['calls'] += 1;row['tokens'] += (call.get('usage') or {}).get('total_tokens') or 0
            row['missing_usage'] += (call.get('usage') or {}).get('total_tokens') is None
            if call.get('reported_model'):row['reported_models'].add(str(call['reported_model']))
        for row in models.values():row['reported_models'] = sorted(row['reported_models'])
        tools = {}
        for call in selected(item['tools']):
            row = tools.setdefault(call['name'], {'name': call['name'], 'calls': 0, 'failed': 0, 'cached': 0, 'unknown': 0})
            row['calls'] += 1;row['failed'] += call['status'] in ('error','failed','tool_failed');row['cached'] += call['cached'];row['unknown'] += call['status']=='unknown'
        skill_events = selected(item['skills']);retrievals = selected(item['retrievals']);runs = [r for r in item['runs'] if bounds['from'] <= r['created'] < bounds['until']]
        return audit.safe({'summary': service.summarize(item, bounds), 'period': bounds, 'models': list(models.values()),
            'tools': sorted(tools.values(),key=lambda r:-r['calls']), 'skills': dict(Counter(r['skill'] for r in skill_events)),
            'skill_details': skill_events[:50], 'retrievals': retrievals[:50], 'model_details': selected(item['calls'])[:50],
            'detail_limit': 50, 'runs': runs[(page-1)*50:page*50], 'total_runs': len(runs), 'page': page})

    @app.get('/api/admin/usage/users/{uid}/conversations')
    def conversations(uid: str, request: Request, offset: int = 0, limit: int = 30):
        auth(request, admin=True)
        if not 0 <= offset <= 1000000 or not 1 <= limit <= 100:
            raise HTTPException(400, 'Invalid conversation page')
        with store.lock:
            if not store.db.execute('SELECT 1 FROM users WHERE id=?', (uid,)).fetchone():
                raise HTTPException(404, 'User not found')
            rows = [dict(row) for row in store.db.execute(
                'SELECT c.id,c.title,c.created,c.updated, '
                '(SELECT count(*) FROM runs r WHERE r.cid=c.id) AS run_count '
                'FROM conversations c WHERE c.uid=? ORDER BY c.created DESC,c.id DESC LIMIT ? OFFSET ?',
                (uid, limit + 1, offset))]
        return JSONResponse(audit.safe({'items': rows[:limit],
                            'next_offset': offset + limit if len(rows) > limit else None}),
                            headers={'Cache-Control': 'no-store'})

    @app.get('/api/admin/usage/conversations/{cid}')
    def conversation(cid: str, request: Request, after: int = 0, limit: int = 30):
        auth(request, admin=True)
        if not 0 <= after <= 2**63 - 1 or not 1 <= limit <= 100:
            raise HTTPException(400, 'Invalid run page')
        with store.lock:
            record = store.db.execute(
                'SELECT c.id,c.title,c.uid,u.username FROM conversations c JOIN users u ON u.id=c.uid WHERE c.id=?',
                (cid,)).fetchone()
            if record is None:
                raise HTTPException(404, 'Conversation not found')
            rows = [dict(row) for row in store.db.execute(
                'SELECT r.rowid AS cursor,r.id,r.created,r.finished_at,r.status,r.turns,'
                "json_extract(a.data,'$.profile.model') AS model, json_extract(a.data,'$.mode') AS mode "
                'FROM runs r LEFT JOIN run_activity a ON a.rid=r.id '
                'WHERE r.cid=? AND r.rowid>? ORDER BY r.rowid LIMIT ?',
                (cid, after, limit + 1))]
        next_after = rows[limit - 1]['cursor'] if len(rows) > limit else None
        for row in rows:
            row.pop('cursor')
        return JSONResponse(audit.safe({'conversation': dict(record), 'items': rows[:limit],
                            'next_after': next_after}),
                            headers={'Cache-Control': 'no-store'})

    @app.get('/api/admin/usage/runs/{rid}/logs')
    def logs(rid: str, request: Request, offset: int = 0, limit: int = 100, source: str = ''):
        auth(request, admin=True)
        if (not re.fullmatch('[a-f0-9]{32}', rid) or not 0 <= offset <= 1000000
                or not 1 <= limit <= 100 or source not in ('', 'task_trace', 'task_events')):
            raise HTTPException(400, 'Invalid log request')
        with store.lock:
            record = store.db.execute(
                'SELECT cid,status,created,finished_at,query,answer,reason,turns FROM runs WHERE id=?', (rid,)
            ).fetchone()
            if record is None:
                raise HTTPException(404, 'Run not found')
        path = store.root / 'traces' / (rid + '.jsonl')
        rows = []
        has_trace = path.is_file()
        if source == 'task_trace' and not has_trace:
            raise HTTPException(409, 'Trace is unavailable; reopen the task')
        use_trace = has_trace and source != 'task_events'
        if use_trace:
            for i, row in enumerate(service.lines(path)):
                if i < offset:continue
                if len(rows)>limit:break
                if row.get('event') in ('model_responded','completion_review_responded'):
                    response = row.get('response') or {}
                    row = {k:v for k,v in row.items() if k!='response'} | {'usage': token_usage(response.get('usage'))}
                rows.append(row)
        else:
            with store.lock:
                rows = [json.loads(r[0]) for r in store.db.execute('SELECT data FROM events WHERE rid=? ORDER BY seq LIMIT ? OFFSET ?',(rid,limit+1,offset))]
        data = {'items': audit.safe(rows[:limit]), 'next_offset': offset + limit if len(rows) > limit else None,
                'source': 'task_trace' if use_trace else 'task_events', 'redacted': True}
        if offset == 0:
            # Read the original user turn and final publication from the broker,
            # including runs with absent, partial or historical trace files.
            run = dict(record)
            run['prompt_text'] = run.pop('query')
            run['reply_text'] = run.pop('answer')
            data['run'] = audit.safe(run, text_limit=120_000)
            data['run']['truncated'] = [name for name in ('prompt_text', 'reply_text', 'reason')
                                         if len(run.get(name) or '') > 120_000]
        return JSONResponse(data, headers={'Cache-Control': 'no-store'})
