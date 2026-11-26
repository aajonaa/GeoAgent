"""Page integration checks complement, rather than replace, actual browser tests."""
from contextlib import closing
import html,json,secrets,sqlite3,re
from fastapi.testclient import TestClient
from geological_agent.team.server import create_app
from geological_agent.team import migrations
from geological_agent.team.verification_policy import Settings,KeyRing
from geological_agent.team.verification_service import VerificationService
from geological_agent.team.sms_provider import MockProvider
from geological_agent.team.registration_service import RegistrationPolicy

class Runner:
    def stop(self,rid):pass

def test_default_page_keeps_login_and_registration_disabled(tmp_path):
    app=create_app(tmp_path/'state',runner=Runner())
    with TestClient(app,base_url='http://127.0.0.1') as c:
        page=c.get('/')
        assert page.status_code==200 and 'id="auth-form"' in page.text
        config=json.loads(html.unescape(re.search(r'data-config="([^"]+)"',page.text)[1]))
        assert config['mode']=='disabled'
        assert c.post('/api/register',json={}).status_code==403
        assert page.headers['referrer-policy']=='no-referrer'
        assert "script-src 'self'" in page.headers['content-security-policy']
        assert page.headers['cache-control']=='no-store'
    app.state.store.db.close()

def test_page_uses_actual_nonsecret_server_settings(tmp_path):
    root=tmp_path/'state';root.mkdir()
    with closing(sqlite3.connect(root/'team.sqlite3',isolation_level=None)) as c:
        c.execute('PRAGMA foreign_keys=ON');migrations.migrate(c)
    key=secrets.token_bytes(32);provider=MockProvider()
    def factory(s):return VerificationService(s,settings=Settings(mode='mock',environment='test',digits=8,cooldown=7,allowed_regions=('NANP',)),keys=KeyRing('test',{'test':key}),provider=provider)
    app=create_app(root,runner=Runner(),verification_factory=factory,registration_policy=RegistrationPolicy(mode='invite_sms',environment='test'))
    with TestClient(app,base_url='http://127.0.0.1') as c:
        page=c.get('/')
        config=json.loads(html.unescape(re.search(r'data-config="([^"]+)"',page.text)[1]))
        assert config=={'mode':'invite_sms','digits':8,'cooldown':7,'allowed_regions':['NANP'],'default_region':None}
        assert '__REGISTRATION_UI_CONFIG__' not in page.text
        assert key.hex() not in page.text and 'code_digest' not in page.text
        assert set(config)=={'mode','digits','cooldown','allowed_regions','default_region'}
    app.state.store.db.close()

def test_registration_assets_same_origin_and_no_other_files(tmp_path):
    app=create_app(tmp_path/'state',runner=Runner())
    with TestClient(app,base_url='http://127.0.0.1') as c:
        for name in ('registration.js','registration.css','app.js','style.css'):
            assert c.get('/assets/'+name).status_code==200
        assert c.get('/assets/registration_service.py').status_code==404
        assert c.get('/',headers={'host':'external.invalid'}).status_code==403
        assert c.post('/api/auth/sms/send',json={},headers={'origin':'https://external.invalid'}).status_code==403
    app.state.store.db.close()
