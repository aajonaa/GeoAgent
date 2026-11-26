"""Browser replay for observed task summaries and grouped tool receipts."""
from argparse import ArgumentParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import json
import mimetypes
import time

from playwright.sync_api import expect, sync_playwright

CID, RID = 'c' * 32, 'r' * 32


def check(web: Path, output: Path, chrome: str, live=None, identity=None):
    output.mkdir(parents=True, exist_ok=True)
    prefix = 'public' if live else 'candidate'
    results = []
    events = [
        {'kind': 'status', 'message': 'Model is working', 'phase': 'execution', 'turn': 1},
        {'kind': 'knowledge_sources', 'status': 'ok', 'references': [
            {'title': '地质资料摘要', 'source': 'https://example.org/geology', 'snippet': '区域地质说明'}]},
        {'kind': 'tool_start', 'id': 'search-1', 'name': 'web_search', 'arguments': {'query': '区域地质资料'}},
        {'kind': 'tool_result', 'id': 'search-1', 'name': 'web_search', 'duration_seconds': 1.2,
         'result': {'status': 'ok', 'data': {'results': [{'title': '公开地质资料', 'url': 'https://example.org/geology'}]}}},
        {'kind': 'tool_start', 'id': 'search-2', 'name': 'web_search', 'arguments': {'query': '补充地质资料'}},
        {'kind': 'tool_result', 'id': 'search-2', 'name': 'web_search', 'duration_seconds': 2.4,
         'result': {'status': 'error', 'error': {'code': 'web_timeout', 'message': 'Missing dataset', 'retryable': True}}},
        {'kind': 'tool_start', 'id': 'raster-1', 'name': 'GeoRasterIndexAnalysis',
         'arguments': {'index': 'NDVI', 'path': 'inputs/geology.tif', 'api_token': 'never-render-this'}},
        {'kind': 'stream_end', 'request_id': 'review-stream', 'phase': 'review', 'complete': False, 'duration_seconds': 3},
        {'kind': 'diagnostic', 'category': 'review_evidence', 'blocking': False, 'phase': 'review', 'turn': 2},
        {'kind': 'stage_timing', 'active': 'review_wait', 'totals_seconds': {
            'runtime': 1, 'model_wait': 3, 'model_stream': 2, 'tools': 8, 'retrieval': 2, 'review_wait': 4}},
    ]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome, headless=True)
        for width in (1440, 390):
            context = browser.new_context(viewport={'width': width, 'height': 900 if width > 500 else 844},
                                          locale='zh-CN', accept_downloads=True)
            page = context.new_page()
            page.set_default_timeout(10000)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            terminal = {'status': 'running'}
            account = {'id': 'owner', 'username': 'owner', 'role': 'member', 'csrf': 'fixture'}

            def history_events():
                result = list(events)
                if terminal['status'] != 'running':
                    result.append({'kind': 'finished', 'status': terminal['status'], 'answer': '', 'turns': 2,
                                   'elapsed_seconds': 20, 'created': 1, 'finished_at': int(time.time()),
                                   'reason': '等待补充信息' if terminal['status'] == 'needs_input' else ''})
                return result

            def serve(route):
                parsed = urlsplit(route.request.url)
                path, query = parsed.path, parse_qs(parsed.query)
                if path.startswith('/api/'):
                    if path == '/api/me':
                        return route.fulfill(json=account)
                    if path == '/api/model-settings':
                        return route.fulfill(json={'source': 'builtin', 'profiles': [], 'model': 'fixture'})
                    if path == '/api/conversations':
                        return route.fulfill(json=[{'id': CID, 'title': '长任务执行与审核'}])
                    if path == '/api/active-tasks':
                        tasks = [{'id': RID, 'cid': CID, 'title': '长任务执行与审核', 'query': '分析区域地质与植被',
                                  'status': terminal['status'], 'created': 1, 'elapsed_seconds': 20}] if terminal['status'] == 'running' else []
                        return route.fulfill(json={'tasks': tasks, 'requests': []})
                    if path == '/api/hitl/requests':
                        return route.fulfill(json={'enabled': False, 'requests': [], 'history': []})
                    if path == '/api/conversations/' + CID:
                        return route.fulfill(json={'id': CID, 'title': '长任务执行与审核', 'runs': [{
                            'id': RID, 'cid': CID, 'query': '分析区域地质与植被', 'status': terminal['status'],
                            'answer': '', 'reason': '', 'created': 1, 'elapsed_seconds': 20, 'activity': {
                                'mode': 'agent', 'tool_count': 3, 'timing': events[-1]}}]})
                    if path.startswith('/api/conversations/') and path.endswith('/files'):
                        return route.fulfill(json={'files': [], 'generation': ''})
                    if path == '/api/runs/' + RID + '/history':
                        records = history_events()
                        return route.fulfill(json={'run_id': RID, 'events': [
                            {'id': index, 'data': data} for index, data in enumerate(records, 1)],
                            'loaded_skills': [], 'next': len(records), 'through': len(records), 'has_more': False})
                    if path == '/api/runs/' + RID:
                        return route.fulfill(json={'id': RID, 'cid': CID, 'status': terminal['status'],
                                                   'query': '分析区域地质与植被', 'answer': '', 'activity': {'mode': 'agent', 'timing': events[-1]}})
                    if path == '/api/runs/' + RID + '/events':
                        body = ''.join('id: ' + str(index) + '\ndata: ' + json.dumps(data, ensure_ascii=False) + '\n\n'
                                       for index, data in enumerate(history_events(), 1))
                        return route.fulfill(body=body, content_type='text/event-stream')
                    if path.startswith('/api/runs/') and path.endswith('/presentation'):
                        return route.fulfill(json={'version': 1, 'run_id': RID, 'conversation_id': CID,
                                                   'generation': 'fixture', 'blocks': [], 'files': []})
                    if path.startswith('/api/runs/') and '/receipts/' in path:
                        return route.fulfill(json={'status': 'error', 'error': {'message': 'Missing dataset'}},
                                             headers={'Content-Disposition': 'attachment; filename="tool-result.json"'})
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
            page.add_init_script("""
                window.__taskSummarySources = [];
                window.EventSource = class {
                  constructor(url) { this.url = url; this.readyState = 1; window.__taskSummarySources.push(this); }
                  close() { this.readyState = 2; }
                };
            """)
            response = page.goto(live or 'http://orebogao.test', wait_until='domcontentloaded')
            if live:
                assert response.headers.get('x-oresage-release') == identity
            def open_task():
                if width <= 760:
                    page.locator('#menu-button').click()
                page.get_by_role('button', name='长任务执行与审核', exact=True).click()

            expect(page.locator('#app')).to_be_visible()
            open_task()
            turn = page.locator('[data-run="' + RID + '"]')
            expect(turn).to_be_visible()
            page.wait_for_function('window.__taskSummarySources.length > 0')
            page.evaluate("""events => {
              const source = window.__taskSummarySources[0];
              events.forEach((data, index) => source.onmessage({data:JSON.stringify(data),lastEventId:String(index + 1)}));
            }""", events)
            overview = turn.locator('.run-overview')
            expect(overview.locator('.run-milestone-count')).to_have_text('关键里程碑 · 2')
            turn.locator('.activity > summary').click()
            expect(turn.locator('.run-current-stage')).to_have_text('当前阶段 · 等待结果审核')
            expect(turn.locator('.run-milestone-count')).to_have_text('关键里程碑 · 2')
            open_items = turn.locator('.run-open-items')
            expect(open_items).to_be_visible()
            expect(open_items.locator('summary')).to_contain_text('未完成事项 · 4')
            expect(open_items).to_contain_text('web_search · 1 次未完成 · 可重试')
            expect(open_items).to_contain_text('GeoRasterIndexAnalysis · 1 次执行中')
            expect(open_items).to_contain_text('模型响应中断 · 核对结果')
            expect(open_items).to_contain_text('运行检查仍需处理')
            assert 'never-render-this' not in turn.text_content()
            groups = turn.locator('.timeline-tool-groups')
            expect(groups).to_be_visible()
            assert groups.evaluate('node => node.open') is False
            expect(groups.locator(':scope > summary')).to_contain_text('3 次 · 1 未完成')
            groups.locator(':scope > summary').click()
            source_group = groups.locator('.timeline-tool-domain').filter(has_text='公开网页来源')
            expect(source_group.locator(':scope > summary')).to_contain_text('2 次 · 1 未完成')
            source_group.locator(':scope > summary').click()
            search_group = source_group.locator('.timeline-tool-group').filter(has_text='web_search')
            expect(search_group.locator(':scope > summary')).to_contain_text('1 未完成')
            search_group.locator(':scope > summary').click()
            failed = search_group.locator('.timeline-entry[data-state=error]')
            expect(failed).to_have_count(1)
            failed.locator(':scope > summary').click()
            expect(failed).to_contain_text('搜索服务响应超时')
            failed.get_by_text('调用参数与完整返回值（凭证已遮蔽）', exact=True).click()
            expect(failed).to_contain_text('Missing dataset')
            with page.expect_download() as download_info:
                failed.get_by_role('link', name='下载执行记录').click()
            assert download_info.value.suggested_filename == 'tool-result.json'
            overview.scroll_into_view_if_needed()
            page.screenshot(path=str(output / f'{prefix}-task-summary-{width}.png'))

            terminal['status'] = 'needs_input'
            page.reload(wait_until='domcontentloaded')
            expect(page.locator('#app')).to_be_visible()
            open_task()
            turn = page.locator('[data-run="' + RID + '"]')
            turn.locator('.activity > summary').click()
            expect(turn.locator('.timeline-history-pager .timeline-note')).to_have_text('执行记录已全部加载。展开每一项查看详情。')
            expect(turn.locator('.run-current-stage')).to_have_text('当前阶段 · 本轮已结束')
            expect(turn.locator('.run-milestone-count')).to_have_text('关键里程碑 · 2')
            expect(turn.locator('.run-open-items')).to_be_visible()
            expect(turn.locator('.run-open-items summary')).to_have_text('未完成事项 · 4')
            expect(turn.locator('.run-open-items')).to_contain_text('web_search · 1 次未完成 · 可重试')
            expect(turn.locator('.run-open-items')).to_contain_text('本轮尚未交付完整结果')
            page.screenshot(path=str(output / f'{prefix}-task-partial-{width}.png'))

            terminal['status'] = 'completed'
            page.reload(wait_until='domcontentloaded')
            expect(page.locator('#app')).to_be_visible()
            open_task()
            turn = page.locator('[data-run="' + RID + '"]')
            turn.locator('.activity > summary').click()
            expect(turn.locator('.timeline-history-pager .timeline-note')).to_have_text('执行记录已全部加载。展开每一项查看详情。')
            expect(turn.locator('.run-current-stage')).to_have_text('当前阶段 · 本轮已结束')
            expect(turn.locator('.run-milestone-count')).to_have_text('关键里程碑 · 2')
            expect(turn.locator('.run-open-items')).to_be_hidden()
            expect(turn.locator('.timeline-tool-groups')).to_contain_text('1 未完成')
            assert page.evaluate('document.documentElement.scrollWidth === innerWidth')
            assert not errors, errors
            results.append({'viewport': width, 'current_stage': True, 'observed_milestones': True,
                            'incomplete_items': True, 'grouped_tools': True, 'full_receipt_download': True,
                            'partial_terminal': True, 'completed_cleanup': True,
                            'no_horizontal_overflow': True, 'no_page_errors': True})
            context.close()
        browser.close()
    (output / 'result.json').write_text(json.dumps({'status': 'passed', 'release': identity, 'viewports': results},
                                                  ensure_ascii=False, indent=2), encoding='utf-8')
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
