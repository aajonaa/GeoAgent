"""Browser replay uses API fixtures while loading candidate or public assets."""
from argparse import ArgumentParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import json
import mimetypes
import time

from playwright.sync_api import expect, sync_playwright

ASK, AGENT, HISTORY = 'a' * 32, 'b' * 32, 'c' * 32
CREATED = 'd' * 32
RUN_IDS = [character * 32 for character in '1234']
QUERY = '分析区域地质与植被关系'
EDITED_PLAN = {
    'objective': '核对区域地质、植被与已授权证据的关系',
    'scope': '仅使用已授权区域资料 <img src=x onerror="window.__planBrowserXss=1">',
    'materials': '区域地质图、钻孔记录与已上传资料',
    'tools': '资料检索、表格整理与证据核对',
    'deliverables': '结论、关键证据表与局限说明',
    'acceptance': ['结论引用可追溯来源', '交付证据表', '说明数据或方法局限'],
}
HISTORY_PLAN = {
    'objective': '从历史执行事件恢复研究计划',
    'scope': '历史结果对应的研究范围',
    'materials': '已归档地质资料',
    'tools': '证据核对',
    'deliverables': '历史研究结论',
    'acceptance': ['历史结论可追溯', '历史局限已说明'],
}


def check(web: Path, output: Path, chrome: str, live=None, identity=None):
    output.mkdir(parents=True, exist_ok=True)
    prefix = 'public' if live else 'candidate'
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome, headless=True)
        for width in (1440, 390):
            context = browser.new_context(
                viewport={'width': width, 'height': 900 if width > 500 else 844},
                locale='zh-CN', accept_downloads=True,
            )
            page = context.new_page()
            page.set_default_timeout(10000)
            errors, api_requests, continued_assets = [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            account = {'id': 'owner', 'username': 'owner', 'role': 'member',
                       'csrf': 'fixture', 'release': identity or 'candidate-fixture'}
            titles = {ASK: '询问模式直达提交', AGENT: '执行计划与结果回执', HISTORY: '历史事件计划回执'}
            conversations = {cid: {'id': cid, 'title': title, 'runs': []} for cid, title in titles.items()}
            conversations[CREATED] = {'id': CREATED, 'title': '新建研究对话', 'runs': []}
            submissions = []

            def run_record(rid, cid, query, mode, plan=None, status='running', answer=''):
                activity = {'mode': mode, 'loaded_skills': {}}
                events = []
                if plan is not None:
                    activity['plan'] = plan
                    events.append({'kind': 'plan_confirmed', 'plan': plan})
                if status != 'running':
                    activity['tool_count'] = 0
                    events.append({'kind': 'finished', 'status': status, 'answer': answer,
                                   'activity': activity, 'created': 1, 'finished_at': int(time.time()),
                                   'elapsed_seconds': 2, 'turns': 1, 'reason': ''})
                return {'id': rid, 'cid': cid, 'query': query, 'mode': mode, 'status': status,
                        'answer': answer, 'activity': activity, 'events': events,
                        'created': 1, 'finished_at': int(time.time()) if status != 'running' else None,
                        'elapsed_seconds': 2, 'turns': 1, 'reason': ''}

            # Omit activity.plan so only the persisted event can restore this receipt.
            conversations[HISTORY]['runs'].append(run_record(
                RUN_IDS[3], HISTORY, '恢复历史计划回执', 'agent', HISTORY_PLAN,
                status='completed', answer='历史结果：已对照确认计划完成核验。'))
            conversations[HISTORY]['runs'][0]['activity'].pop('plan')

            def find_run(rid):
                return next(run for conversation in conversations.values()
                            for run in conversation['runs'] if run['id'] == rid)

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
                    # Flat and aliased asset routes resolve into this web root.
                    asset = web / Path(path).name
                    if asset.is_file():
                        return route.fulfill(path=str(asset), content_type=mimetypes.guess_type(asset.name)[0] or 'application/octet-stream')
                    return route.fulfill(status=404, body='Fixture asset not found')

                api_requests.append((request.method, path))
                if path == '/api/me':
                    return route.fulfill(json=account)
                if path == '/api/model-settings':
                    return route.fulfill(json={'source': 'builtin', 'profiles': [], 'model': 'fixture'})
                if path == '/api/conversations':
                    if request.method == 'POST':
                        return route.fulfill(json=conversations[CREATED])
                    return route.fulfill(json=list(conversations.values()))
                if path == '/api/active-tasks':
                    return route.fulfill(json={'tasks': [], 'requests': []})
                if path == '/api/hitl/requests':
                    return route.fulfill(json={'enabled': False, 'requests': [], 'history': []})
                if path.startswith('/api/conversations/'):
                    parts = path.strip('/').split('/')
                    cid = parts[2]
                    if len(parts) == 4 and parts[3] == 'runs' and request.method == 'POST':
                        payload = request.post_data_json
                        submissions.append(payload)
                        index = len(submissions) - 1
                        rid = RUN_IDS[index]
                        record = run_record(rid, cid, payload['query'], payload.get('mode', 'agent'), payload.get('plan'))
                        conversations[cid]['runs'].append(record)
                        return route.fulfill(json={'id': rid, 'status': 'running'})
                    if len(parts) == 4 and parts[3] == 'files':
                        return route.fulfill(json={'files': [], 'generation': 'fixture'})
                    if len(parts) == 3:
                        return route.fulfill(json=conversations.get(cid, {'id': cid, 'title': '', 'runs': []}))
                if path.startswith('/api/runs/'):
                    parts = path.strip('/').split('/')
                    rid = parts[2]
                    record = find_run(rid)
                    if len(parts) == 4 and parts[3] == 'history':
                        return route.fulfill(json={'run_id': rid, 'events': [
                            {'id': index, 'data': event} for index, event in enumerate(record['events'], 1)],
                            'loaded_skills': [], 'next': len(record['events']),
                            'through': len(record['events']), 'has_more': False})
                    if len(parts) == 4 and parts[3] == 'events':
                        return route.fulfill(body='', content_type='text/event-stream')
                    if len(parts) == 4 and parts[3] == 'presentation':
                        return route.fulfill(json={'version': 1, 'run_id': rid, 'conversation_id': record['cid'],
                                                   'generation': 'fixture', 'blocks': [], 'files': []})
                    if len(parts) == 3:
                        return route.fulfill(json=record)
                return route.fulfill(json=[])

            # Live mode continues every static asset to the public origin.
            page.route('**/*', serve)
            page.add_init_script("""
                window.__planSources = [];
                window.EventSource = class {
                  static CONNECTING = 0; static OPEN = 1; static CLOSED = 2;
                  constructor(url) { this.url = url; this.readyState = 1; window.__planSources.push(this); }
                  close() { this.readyState = 2; }
                };
            """)

            def open_conversation(cid):
                if width <= 760:
                    page.locator('#menu-button').click()
                page.get_by_role('button', name=titles[cid], exact=True).click()
                expect(page.locator('#chat-title')).to_have_text(titles[cid])

            def choose_mode(mode):
                page.locator('#composer-mode label').filter(has_text='执行' if mode == 'agent' else '询问').click()
                expect(page.locator(f'input[name=mode][value={mode}]')).to_be_checked()

            def submit():
                page.locator('#send').click()

            def finish(rid, answer):
                page.evaluate("""({rid, answer}) => {
                  const source = window.__planSources.find(item => item.url.includes('/api/runs/' + rid + '/events'));
                  if (!source) throw new Error('Missing fixture EventSource for ' + rid);
                  source.onmessage({data: JSON.stringify({kind:'finished', status:'completed', answer,
                    created:1, finished_at:Math.floor(Date.now()/1000), elapsed_seconds:2, turns:1,
                    activity:{loaded_skills:{}}}), lastEventId:'99'});
                }""", {'rid': rid, 'answer': answer})
                record = find_run(rid)
                record['status'] = 'completed'
                record['answer'] = answer
                record['events'].append({'kind': 'finished', 'status': 'completed', 'answer': answer,
                                         'activity': record['activity'], 'created': 1,
                                         'finished_at': int(time.time()), 'elapsed_seconds': 2,
                                         'turns': 1, 'reason': ''})

            def assert_layout(stage, modal=False):
                assert page.evaluate('document.documentElement.scrollWidth === innerWidth'), f'{stage}: horizontal page overflow'
                if modal:
                    box = page.locator('#plan-dialog').bounding_box()
                    assert box and box['x'] >= 0 and box['y'] >= 0, f'{stage}: dialog is outside the viewport'
                    assert box['x'] + box['width'] <= width + 1, f'{stage}: dialog overflows horizontally'
                    assert box['y'] + box['height'] <= page.viewport_size['height'] + 1, f'{stage}: dialog overflows vertically'
                    expect(page.locator('#plan-confirm')).to_be_visible()
                assert not errors, f'{stage}: {errors}'

            response = page.goto(live or 'http://orebogao.test', wait_until='domcontentloaded')
            if live:
                assert response.headers.get('x-oresage-release') == identity
            expect(page.locator('#app')).to_be_visible()
            page.wait_for_function("typeof window.GeoAgentPlan?.open === 'function'")
            open_conversation(ASK)

            # Ask must reach the run POST without a modal or creation side effect.
            choose_mode('ask')
            page.locator('#prompt').fill(QUERY)
            submit()
            expect(page.locator('#plan-dialog')).to_be_hidden()
            ask_turn = page.locator(f'[data-run="{RUN_IDS[0]}"]')
            expect(ask_turn).to_be_visible()
            assert len(submissions) == 1, submissions
            assert submissions[0] == {'query': QUERY, 'mode': 'ask'}, submissions[0]
            expect(ask_turn.locator('[data-plan-receipt]')).to_have_count(0)
            page.wait_for_function("window.__planSources.length === 1")
            finish(RUN_IDS[0], '询问完成：请以原始文献为准。')
            expect(ask_turn.locator('.answer')).to_have_text('询问完成：请以原始文献为准。')
            assert_layout('ask direct submission')

            open_conversation(AGENT)
            choose_mode('agent')
            page.locator('#prompt').fill(QUERY)
            submit()
            expect(page.locator('#plan-dialog')).to_be_visible()
            assert len(submissions) == 1, 'Agent mode POSTed before confirmation'
            for field, value in EDITED_PLAN.items():
                if field == 'acceptance':
                    page.locator('#plan-acceptance').fill('\n'.join(value))
                else:
                    page.locator('#plan-' + field).fill(value)
            assert_layout('edited confirmation', modal=True)
            page.locator('#plan-dialog').screenshot(path=str(output / f'{prefix}-plan-dialog-{width}.png'))
            page.locator('#plan-cancel').click()
            expect(page.locator('#plan-dialog')).to_be_hidden()
            assert len(submissions) == 1, 'Cancel submitted a task'
            submit()
            expect(page.locator('#plan-dialog')).to_be_visible()
            for field, value in EDITED_PLAN.items():
                expected = '\n'.join(value) if field == 'acceptance' else value
                expect(page.locator('#plan-' + field)).to_have_value(expected)
            page.locator('#plan-cancel').click()

            # Reload restores both drafts but still refuses an unconfirmed POST.
            page.reload(wait_until='domcontentloaded')
            expect(page.locator('#app')).to_be_visible()
            page.wait_for_function("typeof window.GeoAgentPlan?.open === 'function'")
            open_conversation(AGENT)
            expect(page.locator('#prompt')).to_have_value(QUERY)
            choose_mode('agent')
            submit()
            expect(page.locator('#plan-dialog')).to_be_visible()
            assert len(submissions) == 1, 'Reload submitted an unconfirmed draft'
            for field, value in EDITED_PLAN.items():
                expected = '\n'.join(value) if field == 'acceptance' else value
                expect(page.locator('#plan-' + field)).to_have_value(expected)
            page.locator('#plan-confirm').click()
            expect(page.locator('#plan-dialog')).to_be_hidden()
            agent_turn = page.locator(f'[data-run="{RUN_IDS[1]}"]')
            expect(agent_turn).to_be_visible()
            assert len(submissions) == 2, submissions
            payload = submissions[1]
            assert set(payload) == {'query', 'mode', 'plan'}, payload
            assert payload['query'] == QUERY and payload['mode'] == 'agent'
            assert payload['plan'] == EDITED_PLAN, payload['plan']
            agent_turn = page.locator(f'[data-run="{RUN_IDS[1]}"]')
            expect(agent_turn).to_be_visible()
            receipt = agent_turn.locator('[data-plan-receipt]')
            expect(receipt).to_have_count(1)
            expect(receipt).to_contain_text('研究计划与验收标准 · 已确认')
            expect(receipt).to_contain_text('验收 3 项')
            for criterion in EDITED_PLAN['acceptance']:
                expect(receipt).to_contain_text(criterion)
            assert receipt.locator('img, script').count() == 0, 'Receipt interpreted plan text as HTML'
            assert page.evaluate('window.__planBrowserXss') is None
            assert page.evaluate("Object.keys(localStorage).filter(key => key.endsWith(':plan')).length") == 0
            page.wait_for_function("window.__planSources.some(item => item.url.includes('/api/runs/" + RUN_IDS[1] + "/events'))")
            finish(RUN_IDS[1], '执行完成：已按确认计划整理证据与局限。')
            expect(agent_turn.locator('.answer')).to_have_text('执行完成：已按确认计划整理证据与局限。')
            receipt.locator('summary').click()
            receipt.scroll_into_view_if_needed()
            page.screenshot(path=str(output / f'{prefix}-plan-result-{width}.png'))
            assert_layout('confirmed result')

            # Completed activity restores the receipt without resubmitting.
            page.reload(wait_until='domcontentloaded')
            expect(page.locator('#app')).to_be_visible()
            page.wait_for_function("typeof window.GeoAgentPlan?.open === 'function'")
            open_conversation(AGENT)
            agent_turn = page.locator(f'[data-run="{RUN_IDS[1]}"]')
            expect(agent_turn.locator('[data-plan-receipt]')).to_have_count(1)
            expect(agent_turn.locator('[data-plan-receipt]')).to_contain_text('结论引用可追溯来源')
            expect(agent_turn.locator('.answer')).to_contain_text('已按确认计划整理证据与局限')
            expect(page.locator('#plan-dialog')).to_be_hidden()
            assert len(submissions) == 2, 'Reload submitted a persisted run again'

            # Summary-only activity must recover the receipt from history.
            open_conversation(HISTORY)
            history_turn = page.locator(f'[data-run="{RUN_IDS[3]}"]')
            expect(history_turn.locator('[data-plan-receipt]')).to_have_count(0)
            history_turn.locator('.activity > summary').click()
            history_receipt = history_turn.locator('[data-plan-receipt]')
            expect(history_receipt).to_have_count(1)
            expect(history_receipt).to_contain_text('从历史执行事件恢复研究计划')
            expect(history_receipt).to_contain_text('历史结论可追溯')
            expect(history_turn.locator('.answer')).to_contain_text('已对照确认计划完成核验')
            history_receipt.locator('summary').click()
            history_receipt.scroll_into_view_if_needed()
            page.screenshot(path=str(output / f'{prefix}-history-plan-{width}.png'))
            assert_layout('history event receipt')
            if live:
                assert '/assets/research-plan.js' in continued_assets
                assert '/assets/app.js' in continued_assets
                assert '/assets/style.css' in continued_assets
                assert all(path.startswith('/api/') or path in ('/', '/assets/app.js', '/assets/style.css')
                           or path.startswith(('/assets/', '/vendor/', '/knowledge-', '/case-assets/', '/scientific-assets/', '/data-inventory-assets/'))
                           for path in continued_assets), continued_assets
            assert not errors, errors
            results.append({
                'viewport': width, 'ask_direct_post': True, 'agent_waits_for_confirmation': True,
                'editable_fields_and_criteria': True, 'cancel_preserves_draft': True,
                'reload_restores_draft': True, 'confirmed_payload': EDITED_PLAN,
                'run_receipt': True, 'result_receipt': True, 'reload_receipt_persistence': True,
                'history_event_receipt': True, 'receipt_text_safety': True,
                'commit_clears_plan_draft': True, 'no_horizontal_overflow': True,
                'no_dialog_overflow': True, 'no_page_errors': True,
                'submission_count': len(submissions), 'api_requests_intercepted': len(api_requests),
                'live_static_assets_continued': len(continued_assets) if live else 0,
            })
            context.close()
        browser.close()
    report = {'status': 'passed', 'release': identity, 'mode': 'live-api-fixture' if live else 'candidate',
              'viewports': results, 'screenshots': sorted(path.name for path in output.glob(f'{prefix}-*.png'))}
    (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('--web', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--chrome', default=r'C:\Program Files\Google\Chrome\Application\chrome.exe')
    parser.add_argument('--live')
    parser.add_argument('--identity')
    args = parser.parse_args()
    if bool(args.live) != bool(args.identity):
        parser.error('--live and --identity must be supplied together')
    print(json.dumps(check(args.web, args.output, args.chrome, args.live, args.identity), ensure_ascii=False))
