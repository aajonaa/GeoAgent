"""Browser replay for saved evidence and immutable generation controls."""
from argparse import ArgumentParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import base64
import json
import mimetypes

from playwright.sync_api import expect, sync_playwright

CID = 'c' * 32
RID = 'd' * 32
OLD = 'a' * 32
CURRENT = 'b' * 32
RESTORED = 'e' * 32
CITATION = 'K' + '1' * 16 + '_1'
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAD91JpzAAAAFElEQVR4nGP8z8DAwMDAxMDAwMAAAAwBAQDJ/pLvAAAAAElFTkSuQmCC')


def check(web: Path, output: Path, chrome: str, live=None, identity=None):
    output.mkdir(parents=True, exist_ok=True)
    prefix = 'public' if live else 'candidate'
    results, required_assets = [], set()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome, headless=True)
        for width in (1440, 390):
            context = browser.new_context(viewport={'width': width, 'height': 900 if width > 500 else 844}, locale='zh-CN')
            page = context.new_page(); page.set_default_timeout(10000)
            errors, restores = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            account = {'id': 'owner', 'username': 'owner', 'role': 'member', 'csrf': 'fixture'}
            citation = {'citation_id': CITATION, 'document_id': 'doc-1', 'title': '区域地质资料',
                        'source': 'saved.pdf', 'text': '保存的原文片段：证据上下文。', 'sha256': 'f' * 64,
                        'pages': [4], 'section_path': ['区域地质']}
            conversation = {'id': CID, 'title': '科研证据链与成果版本', 'generation': CURRENT,
                            'runs': [{'id': RID, 'cid': CID, 'query': '核对区域地质证据', 'status': 'completed',
                                      'answer': '关键结论已经核对 [' + CITATION + ']。', 'reason': '',
                                      'activity': {'mode': 'agent'}, 'events': [], 'created': 1,
                                      'finished_at': 2, 'generation': CURRENT}]}

            def generations(current):
                return [{'generation': current, 'current': True, 'created': 2, 'file_count': 1, 'bytes': len(PNG), 'action': 'snapshot'},
                        {'generation': OLD, 'current': False, 'created': 1, 'file_count': 1, 'bytes': len(PNG), 'action': 'snapshot'}]

            def serve(route):
                request = route.request; parsed = urlsplit(request.url); path = parsed.path; query = parse_qs(parsed.query)
                if not path.startswith('/api/'):
                    if live:
                        required_assets.add(path); return route.continue_()
                    if path == '/':
                        return route.fulfill(body=(web / 'index.html').read_text(encoding='utf-8').replace('__REGISTRATION_UI_CONFIG__', '{}'), content_type='text/html; charset=utf-8')
                    asset = web / Path(path).name
                    if asset.is_file(): return route.fulfill(path=str(asset), content_type=mimetypes.guess_type(asset.name)[0] or 'application/octet-stream')
                    return route.fulfill(status=404, body='Fixture asset not found')
                if path == '/api/me': return route.fulfill(json=account)
                if path == '/api/model-settings': return route.fulfill(json={'source': 'builtin', 'profiles': [], 'model': 'fixture'})
                if path == '/api/conversations': return route.fulfill(json=[conversation])
                if path == '/api/active-tasks': return route.fulfill(json={'tasks': [], 'requests': []})
                if path == '/api/hitl/requests': return route.fulfill(json={'enabled': False, 'requests': [], 'history': []})
                if path == f'/api/conversations/{CID}/files':
                    return route.fulfill(json={'generation': conversation['generation'], 'files': [{'name': 'figure.png', 'bytes': len(PNG), 'sha256': 'f' * 64}]})
                if path == f'/api/conversations/{CID}/generations':
                    return route.fulfill(json={'conversation_id': CID, 'items': generations(conversation['generation'])})
                if path == f'/api/conversations/{CID}/generation':
                    generation = query['id'][0]
                    return route.fulfill(json={'conversation_id': CID, 'generation': generation, 'file_count': 1, 'bytes': len(PNG),
                        'files': [{'name': 'figure.png', 'bytes': len(PNG), 'sha256': 'f' * 64}],
                        'figures': [{'name': 'figure.png', 'width': 2, 'height': 2, 'source': None,
                                     'coordinate_reference': None, 'source_coordinate_reference': None,
                                     'transform': None, 'units': None,
                                     'cartographic_scale': None, 'manifest': None}]})
                if path == f'/api/conversations/{CID}/generation-evidence':
                    return route.fulfill(json={'conversation_id': CID, 'generation': query['generation'][0],
                        'note': '仅展示答复中实际保存的引用 ID 与原文片段；支持或反驳关系未自动判定。',
                        'items': [{'run_id': RID, 'answer': conversation['runs'][0]['answer'], 'status': 'completed',
                                   'relation': 'saved_citation_only', 'items': [citation], 'unavailable_ids': [], 'conflicting_ids': []}]})
                if path == f'/api/conversations/{CID}/generation-compare':
                    return route.fulfill(json={'conversation_id': CID, 'left': query['left'][0], 'right': query['right'][0],
                        'changes': [{'name': 'figure.png', 'status': 'modified', 'left_sha256': '1' * 64, 'right_sha256': '2' * 64}],
                        'counts': {'added': 0, 'removed': 0, 'modified': 1, 'unchanged': 0}})
                if path == f'/api/conversations/{CID}/generation-restore' and request.method == 'POST':
                    source = query['generation'][0]; restores.append(source); conversation['generation'] = RESTORED
                    return route.fulfill(json={'generation': RESTORED, 'source_generation': source})
                if path == f'/api/conversations/{CID}/image': return route.fulfill(body=PNG, content_type='image/png')
                if path == f'/api/conversations/{CID}/download': return route.fulfill(body=PNG, content_type='application/octet-stream')
                if path == f'/api/conversations/{CID}': return route.fulfill(json=conversation)
                if path == f'/api/runs/{RID}/presentation':
                    return route.fulfill(json={'version': 1, 'run_id': RID, 'conversation_id': CID, 'generation': CURRENT,
                                               'status': 'completed', 'files': [], 'blocks': [],
                                               'citations': {'items': [citation], 'unavailable_ids': [], 'conflicting_ids': []}})
                if path == f'/api/runs/{RID}/history':
                    return route.fulfill(json={'run_id': RID, 'events': [], 'loaded_skills': [], 'next': 0, 'through': 0, 'has_more': False})
                if path == f'/api/runs/{RID}/events': return route.fulfill(body='', content_type='text/event-stream')
                if path == f'/api/runs/{RID}/scientific-images':
                    return route.fulfill(json={'run_id': RID, 'conversation_id': CID, 'generation': CURRENT, 'analyses': [], 'errors': []})
                if path.startswith('/api/runs/'): return route.fulfill(json=conversation['runs'][0])
                return route.fulfill(json=[])

            page.route('**/*', serve)
            page.add_init_script("window.EventSource=class{constructor(){this.readyState=1;}close(){this.readyState=2;}};")
            response = page.goto(live or 'http://orebogao.test', wait_until='domcontentloaded')
            if live: assert response.headers.get('x-oresage-release') == identity
            expect(page.locator('#app')).to_be_visible()
            if width <= 760: page.locator('#menu-button').click()
            page.get_by_role('button', name='科研证据链与成果版本', exact=True).click()
            expect(page.locator('[data-run="' + RID + '"] .citation-marker button')).to_be_visible()
            page.locator('[data-run="' + RID + '"] .citation-marker button').click()
            expect(page.locator('.citation-panel-content')).to_contain_text('结论上下文 · 原始答复')
            expect(page.locator('.citation-panel-content')).to_contain_text('支持或反驳需人工判断')
            expect(page.locator('.citation-panel-content')).to_contain_text('保存的原文片段：证据上下文。')
            page.get_by_role('button', name='关闭', exact=True).click()

            page.locator('#files-toggle').click()
            expect(page.locator('.versions-section')).to_contain_text('成果版本')
            expect(page.locator('.version-evidence')).to_contain_text('关键结论已经核对')
            expect(page.locator('.version-evidence')).to_contain_text('PDF 第 4 页')
            page.locator('.version-figure summary').click()
            expect(page.locator('.version-metadata')).to_contain_text('比例尺')
            expect(page.locator('.version-metadata')).to_contain_text('未记录')
            page.get_by_role('button', name='比较版本', exact=True).click()
            expect(page.locator('.version-compare')).to_contain_text('修改 1')
            page.once('dialog', lambda dialog: dialog.accept())
            page.get_by_role('button', name='恢复此版本为新版本', exact=True).click()
            expect(page.get_by_label('查看版本', exact=True)).to_have_value(RESTORED)
            assert restores == [CURRENT]
            page.screenshot(path=str(output / f'{prefix}-evidence-versions-{width}.png'))
            assert page.evaluate('document.documentElement.scrollWidth === innerWidth')
            assert not errors, errors
            results.append({'viewport': width, 'citation_context': True, 'saved_excerpt': True,
                            'figure_missing_metadata': True, 'comparison': True, 'restore_new_generation': True,
                            'no_horizontal_overflow': True, 'no_page_errors': True})
            context.close()
        browser.close()
    if live:
        needed = {'/', '/assets/app.js', '/assets/versions.js', '/assets/versions.css', '/assets/citations.js'}
        assert needed <= required_assets, needed - required_assets
    (output / 'result.json').write_text(json.dumps({'status': 'passed', 'release': identity, 'viewports': results}, ensure_ascii=False, indent=2), encoding='utf-8')
    return results


if __name__ == '__main__':
    parser = ArgumentParser(); parser.add_argument('--web', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--chrome', required=True); parser.add_argument('--live'); parser.add_argument('--identity')
    args = parser.parse_args(); check(args.web, args.output, args.chrome, args.live, args.identity)
