from fastapi.testclient import TestClient
from geological_agent.team.server import create_app

class Runner:
    def stop(self,rid):pass

def test_profile_page_resources_do_not_grant_anonymous_access(tmp_path):
    app=create_app(tmp_path/'state',runner=Runner())
    with TestClient(app,base_url='http://127.0.0.1') as c:
        page=c.get('/');assert page.status_code==200
        assert 'id="auth-form" method="post"' in page.text and 'type="submit" disabled>登录' in page.text
        assert 'id="profile-open"' in page.text and 'id="profile-dialog"' in page.text
        assert 'id="app" class="shell" hidden' in page.text
        assert c.get('/api/profile').status_code==401
        assert c.get('/profile').status_code==404
        for name in ('profile.js','profile.css'):assert c.get('/assets/'+name).status_code==200
        assert c.get('/assets/profile_service.py').status_code==404
    app.state.store.db.close()

def test_profile_resource_hook_preserves_web_boundary(tmp_path):
    app=create_app(tmp_path/'state',runner=Runner())
    with TestClient(app,base_url='http://127.0.0.1') as c:
        response=c.get('/assets/profile.js')
        assert response.headers['cache-control']=='no-store' and response.headers['referrer-policy']=='no-referrer'
        assert "script-src 'self'" in response.headers['content-security-policy'] and 'unsafe-inline' not in response.headers['content-security-policy']
        assert c.get('/',headers={'host':'external.invalid'}).status_code==403
        assert c.patch('/api/profile',json={'organization':'Unit'},headers={'origin':'https://external.invalid'}).status_code==403
    app.state.store.db.close()
