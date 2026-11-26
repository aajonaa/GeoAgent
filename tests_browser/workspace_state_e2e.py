"""Browser replay for account-scoped task state and durable local drafts."""
from argparse import ArgumentParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import json
import mimetypes

from playwright.sync_api import expect, sync_playwright

A, B, C, RUN, INPUT = [character * 32 for character in 'abcde']
NEW = 'f' * 32


def check(web: Path, output: Path, chrome: str, live=None, identity=None):
    output.mkdir(parents=True, exist_ok=True)
    prefix = 'public' if live else 'candidate'
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome, headless=True)
        for width in (1440, 390):
            context = browser.new_context(viewport={'width': width, 'height': 900 if width > 500 else 844}, locale='zh-CN', accept_downloads=True)
            page = context.new_page()
            page.set_default_timeout(10000)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            account = {'id': 'owner', 'username': 'owner', 'role': 'member', 'csrf': 'fixture'}
            active = {'enabled': True}
            request = {'id': INPUT, 'cid': C, 'rid': RUN, 'state': 'pending', 'title': '补充地质参数',
                       'question': '请提供目标系数', 'reason': '任务缺少系数', 'missing': ['系数'], 'options': ['2', '3']}
            conversations = {
                A: {'id': A, 'title': '正在执行的地质任务'},
                B: {'id': B, 'title': '另一段研究对话'},
                C: {'id': C, 'title': '补充地质参数'},
                NEW: {'id': NEW, 'title': '首次提交的新对话'},
            }
            created = []

            def open_conversation(cid):
                if width <= 760:
                    page.locator('#menu-button').click()
                page.get_by_role('button', name=conversations[cid]['title'], exact=True).click()

            def serve(route):
                parsed = urlsplit(route.request.url)
                path, query = parsed.path, parse_qs(parsed.query)
                if path.startswith('/api/'):
                    if path == '/api/me':
                        return route.fulfill(json=account) if account['id'] else route.fulfill(status=401, json={'detail': '未登录'})
                    if path == '/api/login':
                        username = (route.request.post_data_json or {}).get('username')
                        account.update(id=username, username=username)
                        return route.fulfill(json=account)
                    if path == '/api/logout':
                        account.update(id=None, username=None)
                        return route.fulfill(json={'ok': True})
                    if path == '/api/model-settings':
                        return route.fulfill(json={'source': 'builtin', 'profiles': [], 'model': 'fixture'})
                    if path == '/api/conversations':
                        if route.request.method == 'POST':
                            if NEW not in created:
                                created.append(NEW)
                            return route.fulfill(json=conversations[NEW])
                        visible = [A, B, C] if account['id'] == 'owner' else [B, *created]
                        return route.fulfill(json=[conversations[cid] for cid in visible])
                    if path == '/api/active-tasks':
                        tasks = [{'id': RUN, 'cid': A, 'title': conversations[A]['title'], 'query': '检索区域地质资料',
                                  'status': 'running', 'created': 1, 'elapsed_seconds': 65}] if active['enabled'] and account['id'] == 'owner' else []
                        requests = [request] if not active['enabled'] and account['id'] == 'owner' else []
                        return route.fulfill(json={'tasks': tasks, 'requests': requests})
                    if path == '/api/hitl/requests':
                        return route.fulfill(json={'enabled': True, 'requests': [request] if query.get('cid') == [C] else [], 'history': []})
                    if path == '/api/conversations/' + A:
                        status = 'running' if active['enabled'] else 'completed'
                        return route.fulfill(json={**conversations[A], 'runs': [{'id': RUN, 'cid': A, 'query': '检索区域地质资料', 'status': status,
                                                                                  'answer': '已完成' if status == 'completed' else '', 'activity': {}}]})
                    if path == '/api/conversations/' + C:
                        return route.fulfill(json={**conversations[C], 'runs': [{'id': RUN, 'cid': C, 'query': '补充地质参数', 'status': 'needs_input',
                                                                                  'answer': request['question'], 'activity': {}}]})
                    if path == '/api/conversations/' + NEW + '/runs' and route.request.method == 'POST':
                        return route.fulfill(json={'id': RUN, 'status': 'running'})
                    if path in ('/api/conversations/' + B, '/api/conversations/' + NEW, '/api/conversations/' + C + '/files', '/api/conversations/' + B + '/files', '/api/conversations/' + A + '/files', '/api/conversations/' + NEW + '/files'):
                        return route.fulfill(json={**conversations.get(path.split('/')[3], {'id': path.split('/')[3], 'title': ''}), 'runs': [], 'files': [], 'generation': 'fixture'})
                    if path.startswith('/api/runs/') and path.endswith('/presentation'):
                        return route.fulfill(json={'version': 1, 'run_id': path.split('/')[3], 'conversation_id': C, 'generation': 'fixture', 'blocks': [], 'files': []})
                    if path.startswith('/api/runs/') and path.endswith('/history'):
                        return route.fulfill(json={'run_id': path.split('/')[3], 'events': [], 'loaded_skills': [], 'next': 0, 'through': None, 'has_more': False})
                    if path.startswith('/api/runs/') and path.endswith('/events'):
                        return route.fulfill(body='', content_type='text/event-stream')
                    if path.startswith('/api/runs/'):
                        return route.fulfill(json={'id': RUN, 'status': 'running' if active['enabled'] else 'needs_input'})
                    return route.fulfill(json=[])
                if live:
                    return route.continue_()
                if path == '/':
                    html = (web / 'index.html').read_text(encoding='utf-8').replace('__REGISTRATION_UI_CONFIG__', '{}')
                    return route.fulfill(body=html, content_type='text/html; charset=utf-8')
                asset = web / Path(path).name
                if asset.is_file():
                    return route.fulfill(path=asset, content_type=mimetypes.guess_type(asset.name)[0] or 'application/octet-stream')
                return route.fulfill(body='')

            page.route('**/*', serve)
            response = page.goto(live or 'http://orebogao.test', wait_until='domcontentloaded')
            if live:
                assert response.headers.get('x-oresage-release') == identity
            expect(page.locator('#app')).to_be_visible()
            expect(page.locator('#global-task')).to_be_visible()
            expect(page.locator('#global-task-title')).to_contain_text(conversations[A]['title'])
            open_conversation(A)
            expect(page.locator('#global-task-open')).to_be_hidden()
            open_conversation(B)
            expect(page.locator('#global-task')).to_be_visible()
            expect(page.locator('#global-task-open')).to_be_visible()
            page.locator('#prompt').fill('刷新后仍应保留的研究草稿')
            page.wait_for_timeout(250)
            open_conversation(A)
            open_conversation(B)
            expect(page.locator('#prompt')).to_have_value('刷新后仍应保留的研究草稿')
            page.reload(wait_until='domcontentloaded')
            expect(page.locator('#app')).to_be_visible()
            open_conversation(B)
            expect(page.locator('#prompt')).to_have_value('刷新后仍应保留的研究草稿')
            page.screenshot(path=str(output / f'{prefix}-global-state-{width}.png'))

            active['enabled'] = False
            open_conversation(C)
            card = page.locator('[data-input-request-id="' + INPUT + '"]')
            expect(card).to_be_visible(timeout=15000)
            expect(page.locator('#global-task-title')).to_contain_text('需要补充信息')
            card.locator('textarea').fill('使用系数 2，并保留原始单位')
            card.get_by_role('button', name='2', exact=True).click()
            card.locator('input[type=file]').set_input_files({'name': '系数说明.txt', 'mimeType': 'text/plain', 'buffer': b'coefficient=2'})
            expect(card.get_by_text('系数说明.txt · 已保存到本机', exact=True)).to_be_visible()
            page.reload(wait_until='domcontentloaded')
            expect(page.locator('#app')).to_be_visible()
            open_conversation(C)
            card = page.locator('[data-input-request-id="' + INPUT + '"]')
            expect(card).to_be_visible(timeout=15000)
            expect(card.locator('textarea')).to_have_value('使用系数 2，并保留原始单位')
            expect(card.get_by_role('button', name='2', exact=True)).to_have_attribute('aria-pressed', 'true')
            expect(card.get_by_text('系数说明.txt · 已保存到本机', exact=True)).to_be_visible()
            page.screenshot(path=str(output / f'{prefix}-hitl-draft-{width}.png'))

            if width <= 760:
                page.locator('#menu-button').click()
            page.locator('#logout').click()
            expect(page.locator('#auth-form')).to_be_visible()
            page.locator('#username').fill('other')
            page.locator('#password').fill('Synthetic-Password-2026')
            page.locator('#auth-submit').click()
            expect(page.locator('#app')).to_be_visible()
            expect(page.locator('#account-name')).to_have_text('other')
            expect(page.locator('#global-task')).to_be_hidden()
            expect(page.get_by_role('button', name=conversations[C]['title'], exact=True)).to_have_count(0)
            open_conversation(B)
            expect(page.locator('#prompt')).to_have_value('')
            if width <= 760:
                page.locator('#menu-button').click()
            page.locator('#new-chat').click()
            expect(page.locator('#chat-title')).to_have_text(conversations[NEW]['title'])
            page.locator('#prompt').fill('首次提交后不应再次出现的草稿')
            page.locator('#send').click()
            expect(page.locator('[data-run="' + RUN + '"]')).to_be_visible()
            page.reload(wait_until='domcontentloaded')
            expect(page.locator('#app')).to_be_visible()
            expect(page.locator('#prompt')).to_have_value('')
            assert page.evaluate('document.documentElement.scrollWidth === innerWidth')
            assert not errors, errors
            results.append({'viewport': width, 'global_task': True, 'composer_restore': True, 'hitl_text_option_file_restore': True,
                            'account_isolation': True, 'first_submission_clears_new_draft': True,
                            'no_horizontal_overflow': True, 'no_page_errors': True})
            context.close()
        browser.close()
    (output / 'result.json').write_text(json.dumps({'status': 'passed', 'release': identity, 'viewports': results}, ensure_ascii=False, indent=2), encoding='utf-8')
    return results


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
