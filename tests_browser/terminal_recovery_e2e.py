"""Browser replay for status-matched terminal recovery actions."""
from argparse import ArgumentParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import json
import mimetypes
import time

from playwright.sync_api import expect, sync_playwright

CID = 'c' * 32
RUNS = {status: character * 32 for status, character in zip(
    ('completed', 'stopped', 'failed', 'incomplete', 'budget_exhausted', 'interrupted', 'cancelled'), '1234567')}
CREATED = 'e' * 32
PROMPTS = {
    'follow_up': '请基于上一轮答复和已保存成果，进一步说明关键结论、支持依据、局限和仍待研究的问题。',
    'derive': '请基于本轮已保存的答复和成果，整理一份新的研究内容。',
    'resume': '请先读取同一对话中上一轮运行的执行详情和已保存文件，再从中断位置继续。',
    'retry': '请保留同一对话中的原始问题、执行上下文和已保存文件，重试上次失败的任务。',
}


def check(web: Path, output: Path, chrome: str, live=None, identity=None):
    output.mkdir(parents=True, exist_ok=True)
    prefix = 'public' if live else 'candidate'
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome, headless=True)
        for width in (1440, 390):
            context = browser.new_context(viewport={'width': width, 'height': 900 if width > 500 else 844},
                                          locale='zh-CN')
            page = context.new_page()
            page.set_default_timeout(10000)
            errors, submissions, recovery_calls, continued_assets = [], [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            account = {'id': 'owner', 'username': 'owner', 'role': 'member', 'csrf': 'fixture'}
            fail_retry = [True]
            records = {}
            for status, rid in RUNS.items():
                answer = '已完成答复：区域地质与植被关系已核对。' if status == 'completed' else ''
                reason = '模型服务响应异常' if status == 'failed' else ''
                events = []
                if status in ('incomplete', 'budget_exhausted', 'interrupted'):
                    events = [
                        {'kind': 'tool_start', 'id': 'missing-data', 'name': 'web_search',
                         'arguments': {'query': '补充区域地质资料'}},
                        {'kind': 'tool_result', 'id': 'missing-data', 'name': 'web_search',
                         'result': {'status': 'error', 'error': {'code': 'web_timeout', 'message': '来源服务超时'}}},
                    ]
                events.append({'kind': 'finished', 'status': status, 'answer': answer, 'reason': reason,
                               'created': 1, 'finished_at': int(time.time()), 'elapsed_seconds': 8,
                               'turns': 1, 'generation': 'generation-' + status})
                records[rid] = {'id': rid, 'cid': CID, 'query': '分析区域地质与植被关系',
                                'status': status, 'answer': answer, 'reason': reason, 'activity': {'mode': 'agent'},
                                'events': events, 'created': 1, 'finished_at': int(time.time()),
                                'elapsed_seconds': 8, 'generation': 'generation-' + status}
            conversation = {'id': CID, 'title': '终态恢复与下一步动作', 'runs': list(records.values())}

            def serve(route):
                request = route.request
                parsed = urlsplit(request.url)
                path, query = parsed.path, parse_qs(parsed.query)
                if not path.startswith('/api/'):
                    if live:
                        continued_assets.append(path)
                        return route.continue_()
                    if path == '/':
                        html = (web / 'index.html').read_text(encoding='utf-8').replace('__REGISTRATION_UI_CONFIG__', '{}')
                        return route.fulfill(body=html, content_type='text/html; charset=utf-8')
                    asset = web / Path(path).name
                    if asset.is_file():
                        return route.fulfill(path=str(asset), content_type=mimetypes.guess_type(asset.name)[0] or 'application/octet-stream')
                    return route.fulfill(status=404, body='Fixture asset not found')
                if path == '/api/me':
                    return route.fulfill(json=account)
                if path == '/api/model-settings':
                    return route.fulfill(json={'source': 'builtin', 'profiles': [], 'model': 'fixture'})
                if path == '/api/conversations':
                    if request.method == 'POST':
                        return route.fulfill(json={'id': CREATED, 'title': '新建研究对话', 'runs': []})
                    return route.fulfill(json=[conversation])
                if path == '/api/active-tasks':
                    return route.fulfill(json={'tasks': [], 'requests': []})
                if path == '/api/hitl/requests':
                    return route.fulfill(json={'enabled': False, 'requests': [], 'history': []})
                if path.startswith('/api/conversations/'):
                    parts = path.strip('/').split('/')
                    if len(parts) == 4 and parts[3] == 'runs' and request.method == 'POST':
                        payload = request.post_data_json
                        submissions.append(payload)
                        rid = 'f' * 31 + format(len(submissions), 'x')
                        record = {'id': rid, 'cid': CID, 'query': payload['query'], 'status': 'running',
                                  'answer': '', 'activity': {'mode': 'agent', 'plan': payload.get('plan')},
                                  'events': [], 'created': 1, 'finished_at': None}
                        records[rid] = record; conversation['runs'].append(record)
                        return route.fulfill(json={'id': rid, 'status': 'running'})
                    if len(parts) == 4 and parts[3] == 'files':
                        return route.fulfill(json={'files': [], 'generation': 'fixture'})
                    if len(parts) == 3:
                        return route.fulfill(json=conversation)
                if path.startswith('/api/runs/'):
                    parts = path.strip('/').split('/')
                    rid = parts[2]
                    if len(parts) == 4 and parts[3] == 'recovery':
                        action = request.post_data_json.get('action')
                        recovery_calls.append((rid, action))
                        if action == 'retry' and fail_retry[0]:
                            return route.fulfill(status=403, json={'detail': 'CSRF validation failed'})
                        return route.fulfill(json={'action': action, 'query': PROMPTS[action], 'mode': 'agent',
                                                   'conversation_id': CID, 'source_run_id': rid,
                                                   'execution': 'new_run', 'message': '已准备续写草稿。原运行和成果版本保留。'})
                    record = records.get(rid, {'id': rid, 'cid': CID, 'status': 'running', 'query': '', 'answer': '', 'activity': {}})
                    if len(parts) == 4 and parts[3] == 'history':
                        return route.fulfill(json={'run_id': rid, 'events': [
                            {'id': index, 'data': event} for index, event in enumerate(record.get('events', []), 1)],
                            'loaded_skills': [], 'next': len(record.get('events', [])),
                            'through': len(record.get('events', [])), 'has_more': False})
                    if len(parts) == 4 and parts[3] == 'events':
                        return route.fulfill(body='', content_type='text/event-stream')
                    if len(parts) == 4 and parts[3] == 'presentation':
                        return route.fulfill(json={'version': 1, 'run_id': rid, 'conversation_id': CID,
                                                   'generation': 'fixture', 'blocks': [], 'files': []})
                    if len(parts) == 3:
                        return route.fulfill(json=record)
                return route.fulfill(json=[])

            page.route('**/*', serve)
            page.add_init_script("""
                window.__recoverySources = [];
                window.EventSource = class {
                  static CONNECTING = 0; static OPEN = 1; static CLOSED = 2;
                  constructor(url) { this.url = url; this.readyState = 1; window.__recoverySources.push(this); }
                  close() { this.readyState = 2; }
                };
            """)
            response = page.goto(live or 'http://orebogao.test', wait_until='domcontentloaded')
            if live:
                assert response.headers.get('x-oresage-release') == identity
            expect(page.locator('#app')).to_be_visible()
            if width <= 760:
                page.locator('#menu-button').click()
            page.get_by_role('button', name='终态恢复与下一步动作', exact=True).click()
            expect(page.locator('#chat-title')).to_have_text('终态恢复与下一步动作')

            original_snapshot = json.dumps({rid: records[rid] for rid in RUNS.values()}, sort_keys=True)

            def submit_recovery(turn, label, prompt_key, source_status, action):
                turn.get_by_role('button', name=label, exact=True).click()
                expect(page.locator('#prompt')).to_have_value(PROMPTS[prompt_key])
                expect(page.locator('input[name=mode][value=agent]')).to_be_checked()
                before = len(submissions)
                page.locator('#send').click()
                expect(page.locator('#plan-dialog')).to_be_visible()
                assert len(submissions) == before
                page.get_by_role('button', name='确认并执行', exact=True).click()
                assert len(submissions) == before + 1
                payload = submissions[-1]
                assert payload['query'] == PROMPTS[prompt_key]
                assert payload['mode'] == 'agent' and payload['plan']['acceptance']
                assert payload['source_run_id'] == RUNS[source_status]
                assert payload['recovery_action'] == action
                new_rid = 'f' * 31 + format(len(submissions), 'x')
                expect(page.locator('[data-run="' + new_rid + '"]')).to_be_visible()
                page.wait_for_function("window.__recoverySources.some(source => source.url.includes('/api/runs/" + new_rid + "/events'))")
                page.evaluate("""rid => {
                  const source = window.__recoverySources.find(item => item.url.includes('/api/runs/' + rid + '/events'));
                  source.onmessage({data: JSON.stringify({kind:'finished', status:'completed', answer:'续写完成',
                    created:1, finished_at:Math.floor(Date.now()/1000), elapsed_seconds:1, turns:1,
                    activity:{loaded_skills:{}}}), lastEventId:'99'});
                }""", new_rid)
                expect(page.locator('#send')).to_be_enabled()

            completed = page.locator('[data-run="' + RUNS['completed'] + '"]')
            expect(completed.locator('.run-recovery')).to_contain_text('本轮已完成')
            expect(completed.get_by_role('button', name='继续追问', exact=True)).to_be_visible()
            expect(completed.get_by_role('button', name='基于成果生成', exact=True)).to_be_visible()
            assert submissions == []
            submit_recovery(completed, '继续追问', 'follow_up', 'completed', 'follow_up')
            submit_recovery(completed, '基于成果生成', 'derive', 'completed', 'derive')
            expect(completed).to_be_visible()
            completed.scroll_into_view_if_needed()
            page.screenshot(path=str(output / f'{prefix}-recovery-completed-{width}.png'))

            stopped = page.locator('[data-run="' + RUNS['stopped'] + '"]')
            expect(stopped.locator('.run-recovery')).to_contain_text('任务已停止')
            submit_recovery(stopped, '从停止位置继续', 'resume', 'stopped', 'resume')

            failed = page.locator('[data-run="' + RUNS['failed'] + '"]')
            expect(failed.locator('.run-recovery')).to_contain_text('执行失败')
            failed.get_by_role('button', name='保留上下文重试', exact=True).click()
            expect(failed.locator('.run-recovery-status')).to_contain_text('准备失败')
            assert page.locator('#prompt').input_value() == ''
            fail_retry[0] = False
            submit_recovery(failed, '保留上下文重试', 'retry', 'failed', 'retry')

            for status, title in [('incomplete', '部分完成'), ('budget_exhausted', '预算已耗尽'),
                                  ('interrupted', '执行中断')]:
                partial = page.locator('[data-run="' + RUNS[status] + '"]')
                expect(partial.locator('.run-recovery')).to_contain_text(title)
                expect(partial.get_by_role('button', name='查看未完成项', exact=True)).to_be_visible()
                expect(partial.get_by_role('button', name='继续未完成部分', exact=True)).to_be_visible()
                partial.get_by_role('button', name='查看未完成项', exact=True).click()
                expect(partial.locator('.run-open-items')).to_be_visible()
                expect(partial.locator('.run-open-items')).to_contain_text('web_search · 1 次未完成')
                expect(partial.locator('.run-recovery')).to_contain_text('未完成事项')
                if status == 'incomplete':
                    partial.scroll_into_view_if_needed()
                    page.screenshot(path=str(output / f'{prefix}-recovery-partial-{width}.png'))

            cancelled = page.locator('[data-run="' + RUNS['cancelled'] + '"]')
            expect(cancelled.locator('.run-recovery')).to_contain_text('任务已停止')
            expect(cancelled.get_by_role('button', name='从停止位置继续', exact=True)).to_be_visible()
            page.screenshot(path=str(output / f'{prefix}-recovery-states-{width}.png'), full_page=True)
            assert (RUNS['completed'], 'follow_up') in recovery_calls
            assert (RUNS['completed'], 'derive') in recovery_calls
            assert (RUNS['stopped'], 'resume') in recovery_calls
            assert (RUNS['failed'], 'retry') in recovery_calls
            assert json.dumps({rid: records[rid] for rid in RUNS.values()}, sort_keys=True) == original_snapshot
            assert page.evaluate('document.documentElement.scrollWidth === innerWidth')
            assert not errors, errors
            if live:
                required_assets = {'/', '/assets/app.js', '/assets/recovery.js', '/assets/images.js',
                                   '/assets/style.css', '/assets/research-plan.js'}
                assert required_assets <= set(continued_assets), required_assets - set(continued_assets)
            results.append({'viewport': width, 'completed_actions': True, 'derive_execution': True,
                            'plan_gate': True, 'stopped_resume': True, 'failed_retry': True,
                            'partial_items': True, 'partial_variants': True, 'source_context_payload': True,
                            'original_preserved': True, 'no_horizontal_overflow': True, 'no_page_errors': True})
            context.close()
        browser.close()
    (output / 'result.json').write_text(json.dumps({'status': 'passed', 'release': identity, 'viewports': results},
                                                  ensure_ascii=False, indent=2), encoding='utf-8')
    return results


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('--web', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--chrome', required=True)
    parser.add_argument('--live')
    parser.add_argument('--identity')
    args = parser.parse_args()
    check(args.web, args.output, args.chrome, args.live, args.identity)
