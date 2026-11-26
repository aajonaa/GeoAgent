"""Real Chromium + private loopback ASGI + real SQLite + Python-only Mock capture.

No fixture HTTP endpoint, request-body log, HAR or browser trace is created.
Run only in the task's filesystem/network namespace (see run_browser_remote.py).
"""
from contextlib import contextmanager,closing
from dataclasses import replace
from pathlib import Path
from threading import Thread
import json,os,secrets,socket,sqlite3,time,traceback
import uvicorn
from playwright.sync_api import sync_playwright,expect
from geological_agent.team import migrations
from geological_agent.team.server import create_app,COOKIE
from geological_agent.team.store import digest
from geological_agent.team.activity_store import ActivityStore
from geological_agent.team.verification_service import VerificationService
from geological_agent.team.verification_policy import Settings,KeyRing
from geological_agent.team.sms_provider import MockProvider
from geological_agent.team.registration_service import RegistrationPolicy

W=Path(os.environ['P12_WORKSPACE']);E=Path(os.environ['P23_EVIDENCE']);D=Path(os.environ['P23_BROWSER_DATA'])
PASSWORD=secrets.token_urlsafe(24);PHONE='+8613800138000';results=[];ports=set()
class Runner:
    def stop(self,rid):pass
class Clock:
    def __init__(self):self.offset=0
    def __call__(self):return time.time()+self.offset

@contextmanager
def environment(browser,name,mobile=False,disabled=False):
    root=D/name;root.mkdir(parents=True)
    with closing(sqlite3.connect(root/'team.sqlite3',isolation_level=None)) as c:
        c.execute('PRAGMA foreign_keys=ON');migrations.migrate(c)
    provider=MockProvider();clock=Clock();key=KeyRing('browser-only',{'browser-only':secrets.token_bytes(32)})
    def factory(store):return VerificationService(store,settings=Settings(mode='mock',environment='test',default_region='CN',cooldown=2,edge_limit=200,ip_hour_limit=100),keys=key,provider=provider,clock=clock)
    app=create_app(root,runner=Runner(),verification_factory=factory,registration_policy=RegistrationPolicy(mode='disabled' if disabled else 'invite_sms',environment='test'))
    s=app.state.store;token=s.invite()
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];ports.add(port)
    config=uvicorn.Config(app,host='127.0.0.1',port=port,access_log=False,log_level='critical',proxy_headers=False)
    server=uvicorn.Server(config);thread=Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    limit=time.monotonic()+10
    while not server.started and thread.is_alive() and time.monotonic()<limit:time.sleep(.02)
    assert server.started,'isolated ASGI startup'
    context=browser.new_context(viewport={'width':390,'height':844} if mobile else {'width':1440,'height':1000},locale='zh-CN')
    page=context.new_page();page.set_default_timeout(6000);faults=[];requests=[];responses=[]
    page.on('pageerror',lambda error:faults.append(type(error).__name__))
    page.on('request',lambda req:requests.append({'path':req.url.split('?')[0].split('#')[0].removeprefix('http://127.0.0.1:'+str(port)),'method':req.method,'referer':req.headers.get('referer','')}))
    page.on('response',lambda response:responses.append((response.url.split('?')[0].removeprefix('http://127.0.0.1:'+str(port)),response.status)))
    values={'app':app,'store':s,'provider':provider,'clock':clock,'token':token,'page':page,'context':context,'url':'http://127.0.0.1:'+str(port),'requests':requests,'responses':responses,'faults':faults}
    try:yield values
    finally:
        context.close();server.should_exit=True;thread.join(8);sock.close();s.db.close()
        assert not thread.is_alive(),'isolated server cleanup'

def open_registration(v):
    v['page'].goto(v['url']+'/#join='+v['token']);expect(v['page'].locator('#registration')).to_be_visible()
    expect(v['page'].locator('#reg-invitation')).not_to_have_text('正在检查邀请…')

def fill(v,username='browser-user',phone=PHONE):
    page=v['page']
    for name,text in [('username',username),('password',PASSWORD),('confirm',PASSWORD),('organization',' Test University '),('phone',phone)]:page.locator('#reg-'+name).fill(text)

def send(v):
    page=v['page'];page.locator('#reg-send').click()
    expect(page.locator('#reg-sms-status')).to_contain_text('请求已受理')
    assert any(path=='/api/auth/sms/send' and status==202 for path,status in v['responses'])
    row=v['store'].db.execute('SELECT verification_id FROM sms_verifications ORDER BY rowid DESC LIMIT 1').fetchone()
    # This access is server-side test memory. It is never an HTTP/API response.
    code=v['provider'].captured_for_test(row[0])[1]
    assert code and code not in page.locator('body').inner_text()
    page.locator('#reg-code').fill(code);return code

def registered(v):
    v['page'].locator('#reg-submit').click()
    expect(v['page'].locator('#app')).to_be_visible(timeout=15000)
    expect(v['page'].locator('#account-name')).to_have_text('browser-user')

def login(v,name='browser-user'):
    page=v['page'];page.locator('#username').fill(name);page.locator('#password').fill(PASSWORD);page.locator('#auth-submit').click()
    expect(page.locator('#app')).to_be_visible(timeout=15000)

def counts(v):
    c=v['store'].db
    return {t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('users','user_profiles','invite_uses','business_events','auth')}

def snapshot(v,name):
    p=v['page'];assert '#' not in p.url
    p.screenshot(path=str(E/'screenshots'/name),full_page=True,mask=[p.locator('#reg-password'),p.locator('#reg-confirm'),p.locator('#reg-code'),p.locator('#password')])

def record(ids,details=None):
    for id in ids:results.append({'id':id,'status':'Pass','details':details or 'Actual Chromium UI and isolated ASGI/SQLite assertions'})

def run(browser,ids,fn,**kwargs):
    name=ids[0].lower()
    try:
        with environment(browser,name,**kwargs) as v:fn(v)
        record(ids)
    except Exception as exc:
        # Do not persist Playwright's input-value/URL/credential-rich call log.
        frames=[{'function':f.name,'line':f.lineno} for f in traceback.extract_tb(exc.__traceback__) if f.filename.endswith('registration_e2e.py')]
        for id in ids:results.append({'id':id,'status':'Fail','error_type':type(exc).__name__,'test_frames':frames})
        print(json.dumps({'case':name,'status':'Fail','error_type':type(exc).__name__,'test_frames':frames}),flush=True)
    (E/'progress.json').write_text(json.dumps({'scenarios':results,'completed':len(results)},indent=2))

def success(v):
    p=v['page'];open_registration(v);expect(p.locator('#reg-invitation')).to_contain_text('邀请有效')
    assert '#' not in p.url and v['token'] not in p.content()
    snapshot(v,'desktop-registration.png')
    fill(v);code=send(v)
    p.locator('#reg-verify').click();expect(p.locator('#reg-sms-status')).to_contain_text('预检查通过')
    assert counts(v)['users']==0 and v['store'].db.execute('SELECT used FROM invites').fetchone()[0]==0
    registered(v);assert counts(v)=={'users':1,'user_profiles':1,'invite_uses':1,'business_events':1,'auth':1}
    cookies=v['context'].cookies();session=next(c for c in cookies if c['name']==COOKIE)
    assert session['httpOnly'] and session['sameSite']=='Strict'
    assert p.evaluate("document.cookie.indexOf('geotool_team_session=') < 0")
    assert p.evaluate('localStorage.length')==0 and p.evaluate('sessionStorage.length')==0
    assert all(v['token'] not in req['referer'] and '#' not in req['path'] for req in v['requests'])
    assert all(secret not in p.content() for secret in [PASSWORD,code,v['token']])
    snapshot(v,'desktop-home.png');p.reload();expect(p.locator('#app')).to_be_visible()
    p.locator('#logout').click();expect(p.locator('#auth-form')).to_be_visible();login(v)
    assert v['faults']==[]

def invalid_invite(v,state):
    s=v['store']
    with s.lock,s.db:
        if state=='invalid':v['token']=secrets.token_urlsafe(32)
        if state=='expired':s.db.execute('UPDATE invites SET expires=?',(time.time()-1,))
        if state=='used':s.db.execute('UPDATE invites SET used=1')
        if state=='revoked':s.db.execute('UPDATE invites SET revoked_at=?',(time.time(),))
    open_registration(v);p=v['page'];expect(p.locator('#reg-invitation')).to_contain_text('邀请无效')
    expect(p.locator('#reg-submit')).to_be_disabled();expect(p.locator('#reg-username')).to_be_disabled()
    assert counts(v)['users']==0

def invalid_phone(v):
    open_registration(v);v['page'].locator('#reg-phone').fill('invalid');v['page'].locator('#reg-send').click()
    expect(v['page'].locator('#reg-phone-error')).to_contain_text('手机号')
    assert not any(req['path']=='/api/auth/sms/send' for req in v['requests'])

def missing(v):
    open_registration(v);v['page'].locator('#reg-phone').fill(PHONE);send(v);v['page'].locator('#reg-submit').click()
    expect(v['page'].locator('#reg-username-error')).to_contain_text('用户名')
    assert v['page'].locator('#reg-username').get_attribute('aria-invalid')=='true'
    assert not any(req['path']=='/api/register' for req in v['requests'])
    v['page'].locator('#reg-code').fill('');snapshot(v,'desktop-field-error.png')

def mismatch(v):
    open_registration(v);fill(v);send(v);v['page'].locator('#reg-confirm').fill(PASSWORD+'x');v['page'].locator('#reg-submit').click()
    expect(v['page'].locator('#reg-confirm-error')).to_contain_text('不一致')
    assert counts(v)['users']==0

def username_conflict(v):
    v['store'].create_user('browser-user',PASSWORD,invite=v['store'].invite())
    open_registration(v);fill(v);send(v);v['page'].locator('#reg-submit').click()
    expect(v['page'].locator('#reg-error')).to_contain_text('冲突');assert counts(v)['users']==1 and counts(v)['user_profiles']==0

def phone_conflict(v):
    s=v['store'];old=s.create_user('existing-user',PASSWORD,invite=s.invite())
    open_registration(v);fill(v);send(v)
    with s.lock,migrations.transaction(s.db):ActivityStore(s.db).create_profile(old,now=time.time(),phone_number=PHONE,phone_verified_at=time.time())
    v['page'].locator('#reg-submit').click();expect(v['page'].locator('#reg-error')).to_contain_text('失效')
    assert counts(v)['users']==1 and counts(v)['invite_uses']==0

def wrong_code(v):
    open_registration(v);fill(v);code=send(v);v['page'].locator('#reg-code').fill(('0' if code[0]!='0' else '1')+code[1:])
    v['page'].locator('#reg-verify').click();expect(v['page'].locator('#reg-code-error')).to_contain_text('错误')
    assert v['store'].db.execute('SELECT attempt_count FROM sms_verifications').fetchone()[0]==1 and counts(v)['users']==0

def expired_code(v):
    open_registration(v);fill(v);send(v);v['clock'].offset=301;v['page'].locator('#reg-verify').click()
    expect(v['page'].locator('#reg-code-error')).to_contain_text('过期');assert counts(v)['users']==0

def sms_unavailable(v):
    open_registration(v);fill(v);service=v['app'].state.verification_service;service.settings=replace(service.settings,mode='disabled')
    v['page'].locator('#reg-send').click();expect(v['page'].locator('#reg-sms-status')).to_contain_text('暂时不可用')
    assert v['provider'].call_count_for_test()==0

def rate_limit(v):
    open_registration(v);fill(v)
    v['app'].state.verification_service.send(v['token'],PHONE,secrets.token_hex(16),'127.0.0.1')
    v['page'].locator('#reg-send').click();expect(v['page'].locator('#reg-sms-status')).to_contain_text('请求过于频繁')
    assert any(path=='/api/auth/sms/send' and status==429 for path,status in v['responses'])

def timeout(v):
    open_registration(v);fill(v)
    def stall(route):
        time.sleep(16)
        try:route.abort()
        except Exception:pass
    v['page'].route('**/api/auth/sms/send',stall);v['page'].locator('#reg-send').click()
    expect(v['page'].locator('#reg-sms-status')).to_contain_text('超时',timeout=20000)
    assert counts(v)['users']==0

def invitation_changed(v):
    open_registration(v);fill(v);send(v);s=v['store']
    with s.lock,s.db:s.db.execute('UPDATE invites SET used=1 WHERE token=?',(digest(v['token']),))
    v['page'].locator('#reg-submit').click();expect(v['page'].locator('#reg-error')).to_contain_text('失效')
    assert counts(v)['users']==0 and counts(v)['business_events']==0

def double_click(v):
    open_registration(v);fill(v);send(v)
    v['page'].locator('#reg-submit').evaluate('(b) => { b.click(); b.click(); }')
    expect(v['page'].locator('#app')).to_be_visible(timeout=15000)
    assert sum(req['path']=='/api/register' for req in v['requests'])==1
    assert counts(v)['users']==1 and counts(v)['invite_uses']==1

def drop_response(v,retry=False):
    open_registration(v);fill(v);send(v);ids=[]
    def drop(route):
        ids.append(route.request.post_data_json['request_id'])
        response=route.fetch();assert response.status==201;route.abort('failed')
    p=v['page'];p.route('**/api/register',drop);p.locator('#reg-submit').click()
    expect(p.locator('#reg-recovery')).to_be_visible(timeout=15000)
    assert counts(v)['users']==1 and counts(v)['invite_uses']==1
    expect(p.locator('#app')).to_be_hidden();expect(p.locator('#reg-username')).to_be_disabled()
    p.unroute('**/api/register',drop)
    if retry:
        p.on('request',lambda req:ids.append(req.post_data_json['request_id']) if req.url.endswith('/api/register') else None)
        p.locator('#reg-retry').click();expect(p.locator('#app')).to_be_visible(timeout=15000)
        assert len(ids)==2 and ids[0]==ids[1]
    else:
        p.locator('#reg-recover-login').click();expect(p.locator('#auth-hint')).to_contain_text('已经完成');login(v)
    assert counts(v)['users']==1 and counts(v)['business_events']==1

def disabled(v):
    open_registration(v);expect(v['page'].locator('#reg-invitation')).to_contain_text('暂不开放注册')
    expect(v['page'].locator('#reg-submit')).to_be_disabled()
    v['page'].locator('#reg-login').click();expect(v['page'].locator('#auth-form')).to_be_visible()

def old_login(v):
    v['store'].create_user('existing-user',PASSWORD,invite=v['store'].invite())
    v['page'].goto(v['url']);expect(v['page'].locator('#auth-form')).to_be_visible();login(v,'existing-user')
    expect(v['page'].locator('#registration')).to_be_hidden()

def permissions(v):
    open_registration(v);fill(v);send(v);registered(v)
    expect(v['page'].locator('#invite-button')).to_be_hidden()
    assert v['page'].evaluate("async()=>{const me=await(await fetch('/api/me')).json();return (await fetch('/api/admin/invites',{method:'POST',headers:{'X-CSRF-Token':me.csrf}})).status}")==403

def isolation(v):
    s=v['store'];old=s.create_user('other-user',PASSWORD,invite=s.invite());conversation=s.create_conversation(old);s.snapshot(old,conversation['id'],{'private.txt':b'other-user-private'})
    open_registration(v);fill(v);send(v);registered(v)
    status=v['page'].evaluate("async p=>(await fetch(p)).status",'/api/conversations/'+conversation['id'])
    assert status==404 and 'other-user' not in v['page'].locator('#app').inner_text()

def navigation(v):
    open_registration(v);fill(v);send(v);registered(v);p=v['page']
    p.locator('#new-chat').click();expect(p.locator('#conversation-list button')).to_have_count(1)
    p.locator('#files-toggle').click();expect(p.locator('#files-panel')).to_be_visible()
    p.locator('#model-settings-button').click();expect(p.locator('#model-dialog')).to_be_visible()
    assert v['faults']==[]

def responsive(v):
    open_registration(v);p=v['page'];expect(p.locator('#reg-username')).to_be_enabled()
    assert p.evaluate('document.documentElement.scrollWidth <= innerWidth')
    for id in ['reg-username','reg-password','reg-confirm','reg-organization','reg-phone','reg-code','reg-submit','reg-login']:
        box=p.locator('#'+id).bounding_box();assert box and box['x']>=0 and box['x']+box['width']<=390
    p.locator('#reg-username').focus();p.keyboard.type('keyboard-user');p.keyboard.press('Tab');expect(p.locator('#reg-password')).to_be_focused()
    p.locator('#reg-phone').fill('bad');p.locator('#reg-send').click();expect(p.locator('#reg-phone-error')).to_be_visible()
    assert 'reg-phone-error' in p.locator('#reg-phone').get_attribute('aria-describedby')
    snapshot(v,'mobile-error.png');fill(v);send(v);p.locator('#reg-code').fill('');snapshot(v,'mobile-registration.png')
    expect(p.locator('#reg-send')).to_be_disabled();p.locator('#reg-organization').fill('Keyboard University')
    expect(p.locator('#reg-send')).to_be_enabled(timeout=4500)

def session_failure(v):
    open_registration(v);fill(v);send(v);c=v['store'].db
    def deny(operation,a,b,db,trigger):return sqlite3.SQLITE_DENY if operation==sqlite3.SQLITE_INSERT and a=='auth' else sqlite3.SQLITE_OK
    c.set_authorizer(deny);v['page'].locator('#reg-submit').click()
    expect(v['page'].locator('#auth-hint')).to_contain_text('账号已创建',timeout=15000)
    c.set_authorizer(None);assert counts(v)['users']==1 and counts(v)['auth']==0;login(v)

def retry_invitation(v):
    p=v['page'];p.route('**/api/auth/invitations/validate',lambda route:route.abort())
    open_registration(v);expect(p.locator('#reg-invitation')).to_contain_text('网络连接失败')
    p.unroute('**/api/auth/invitations/validate');p.locator('#reg-invite-retry').click();expect(p.locator('#reg-invitation')).to_contain_text('邀请有效')

with sync_playwright() as playwright:
    browser=playwright.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
    version=browser.version
    run(browser,['E2E-%02d'%n for n in range(1,11)],success)
    for id,state in [('E2E-11','invalid'),('E2E-12','expired'),('E2E-13','used'),('EXTRA-revoked','revoked')]:run(browser,[id],lambda v,state=state:invalid_invite(v,state))
    for id,fn in [('E2E-14',invalid_phone),('E2E-15',missing),('E2E-16',mismatch),('E2E-17',username_conflict),('E2E-18',phone_conflict),('E2E-19',wrong_code),('E2E-20',expired_code),('E2E-21',sms_unavailable),('E2E-22',rate_limit),('E2E-23',timeout),('E2E-24',invitation_changed),('E2E-25',double_click),('E2E-26',drop_response)]:run(browser,[id],fn)
    run(browser,['E2E-27'],disabled,disabled=True)
    run(browser,['E2E-28','E2E-29'],old_login)
    run(browser,['E2E-30'],lambda v:(open_registration(v),fill(v),send(v),registered(v)))
    for id,fn in [('E2E-31',permissions),('E2E-32',isolation),('E2E-33',navigation),('EXTRA-session-failure',session_failure),('EXTRA-invite-network-retry',retry_invitation),('EXTRA-safe-registration-retry',lambda v:drop_response(v,True))]:run(browser,[id],fn)
    run(browser,['A11Y-mobile-keyboard-cooldown'],responsive,mobile=True)
    browser.close()
data={'browser':'Chromium','version':version,'actual_browser':True,'scenarios':results,'passed':sum(r['status']=='Pass' for r in results),'failed':sum(r['status']=='Fail' for r in results),'skipped':0,'mock_only':True,'real_sms_calls':0,'server_ports':sorted(ports),'binding':'private network namespace loopback only','no_fixture_http_endpoint':True,'screenshots':sorted(p.name for p in (E/'screenshots').glob('*.png'))}
(E/'browser-e2e.json').write_text(json.dumps(data,indent=2))
print(json.dumps({k:v for k,v in data.items() if k not in {'scenarios','server_ports'}}),flush=True)
raise SystemExit(1 if data['failed'] else 0)
