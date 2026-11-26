"""Actual profile UI on private ASGI/SQLite; Mock code is read only in Python."""
from contextlib import contextmanager,closing
from dataclasses import replace
from pathlib import Path
from threading import Thread
import json,os,secrets,socket,sqlite3,time,traceback
import uvicorn
from playwright.sync_api import sync_playwright,expect
from geological_agent.team import migrations
from geological_agent.team.server import create_app,COOKIE
from geological_agent.team.store import password_hash
from geological_agent.team.activity_store import ActivityStore
from geological_agent.team.verification_service import VerificationService
from geological_agent.team.verification_policy import Settings,KeyRing
from geological_agent.team.sms_provider import MockProvider,SendResult
from geological_agent.team.registration_service import RegistrationPolicy
from geological_agent.team.profile_service import ProfilePolicy

W=Path(os.environ['P12_WORKSPACE']);E=Path(os.environ['P23_EVIDENCE']);D=Path(os.environ['P23_BROWSER_DATA'])
PASSWORD=secrets.token_urlsafe(24);ENCODED=password_hash(PASSWORD);PHONE='+8613800138000';OTHER_PHONE='+8613900139000';results=[];ports=set()
class Runner:
    def stop(self,rid):pass
class Clock:
    def __init__(self):self.offset=0
    def __call__(self):return time.time()+self.offset

@contextmanager
def environment(browser,name,mobile=False,cooldown=2,reauth=300):
    root=D/name;root.mkdir(parents=True)
    with closing(sqlite3.connect(root/'team.sqlite3',isolation_level=None)) as c:
        c.execute('PRAGMA foreign_keys=ON');migrations.migrate(c)
    provider=MockProvider();clock=Clock();key=KeyRing('profile-browser',{'profile-browser':secrets.token_bytes(32)})
    def factory(s):return VerificationService(s,settings=Settings(mode='mock',environment='test',default_region='CN',cooldown=cooldown,edge_limit=200,ip_hour_limit=100),keys=key,provider=provider,clock=clock)
    app=create_app(root,runner=Runner(),verification_factory=factory,registration_policy=RegistrationPolicy(mode='invite_sms',environment='test'),profile_policy=ProfilePolicy(phone_binding_enabled=True,environment='test',reauth_seconds=reauth))
    s=app.state.store;ids={}
    with s.lock,migrations.transaction(s.db):
        for user in ['legacy-user','other-user']:ids[user]=s.create_user_in_transaction(s.db,user,ENCODED)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];ports.add(port)
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,access_log=False,log_level='critical',proxy_headers=False))
    thread=Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start();limit=time.monotonic()+10
    while not server.started and thread.is_alive() and time.monotonic()<limit:time.sleep(.02)
    assert server.started,'private ASGI startup'
    context=browser.new_context(viewport={'width':390,'height':844} if mobile else {'width':1440,'height':1000},locale='zh-CN')
    p=context.new_page();p.set_default_timeout(6500);url='http://127.0.0.1:'+str(port)
    v={'page':p,'context':context,'app':app,'store':s,'provider':provider,'clock':clock,'root':root,'url':url,'ids':ids,'requests':[],'responses':[],'errors':[],'console':[],'grant':None,'confirm':None,'checkpoint':'setup'}
    def request(req):
        v['requests'].append({'path':req.url.split('?')[0].removeprefix(url),'method':req.method,'csrf':bool(req.headers.get('x-csrf-token'))})
        if req.url.endswith('/api/profile/phone/confirm'):v['confirm']=req.post_data_json
    def response(r):
        v['responses'].append((r.url.split('?')[0].removeprefix(url),r.status))
        if r.url.endswith('/api/profile/phone/reauthenticate') and r.status==200:v['grant']=r.json()['authorization']
    p.on('request',request);p.on('response',response);p.on('pageerror',lambda e:v['errors'].append(type(e).__name__))
    p.on('console',lambda m:v['console'].append(m.text))
    try:yield v
    finally:
        context.close();server.should_exit=True;thread.join(8);sock.close();s.db.close();assert not thread.is_alive(),'private ASGI cleanup'

def login(v,name='legacy-user'):
    v['checkpoint']='login';p=v['page'];p.goto(v['url']);p.locator('#username').fill(name);p.locator('#password').fill(PASSWORD);p.locator('#auth-submit').click()
    expect(p.locator('#app')).to_be_visible(timeout=15000);expect(p.locator('#account-name')).to_have_text(name)

def open_profile(v):
    v['checkpoint']='open-profile';p=v['page']
    if p.viewport_size['width']<=760:p.locator('#menu-button').click()
    p.locator('#profile-open').click();expect(p.locator('#profile-dialog')).to_be_visible()
    expect(p.locator('#profile-dialog')).to_have_attribute('data-state','loaded')

def unit(v,text):
    v['checkpoint']='save-unit';p=v['page'];p.locator('#profile-unit-edit').click();p.locator('#profile-unit').fill(text);p.locator('#profile-unit-save').click()
    expect(p.locator('#profile-unit-form')).to_be_hidden();expect(p.locator('#profile-unit-value')).to_have_text(text.strip() or '未填写')

def auth(v,phone=PHONE,password=None):
    v['checkpoint']='reauthenticate';p=v['page']
    if p.locator('#profile-bind-start').is_visible():p.locator('#profile-bind-start').click()
    p.locator('#profile-phone').fill(phone);p.locator('#profile-password').fill(password or PASSWORD);p.locator('#profile-reauth').click()
    expect(p.locator('#profile-target-row')).to_be_visible(timeout=15000)
    expect(p.locator('#profile-password')).to_have_value('');expect(p.locator('#profile-phone')).to_have_value('')
    expect(p.locator('#profile-target')).to_have_text('准备绑定：***'+phone[-4:])

def send(v):
    v['checkpoint']='send-code';p=v['page'];p.locator('#profile-send').click()
    expect(p.locator('#profile-bind-status')).to_contain_text('请求已受理')
    row=v['store'].db.execute("SELECT verification_id FROM sms_verifications WHERE purpose='phone_change' ORDER BY rowid DESC LIMIT 1").fetchone()
    code=v['provider'].captured_for_test(row[0])[1]
    assert code not in p.locator('body').inner_text()
    p.locator('#profile-code').fill(code);return code

def confirm(v):
    v['checkpoint']='confirm-binding';p=v['page'];p.locator('#profile-confirm').click();expect(p.locator('#profile-bound')).to_be_visible(timeout=15000)
    expect(p.locator('#profile-phone-value')).to_have_text('***8000')

def shot(v,name):
    p=v['page'];assert p.url.endswith('#profile')
    # Capture-only redaction compatible with the existing CSP and native top layer.
    # No input values leave the page or change; restore input types immediately.
    types=p.evaluate("() => ['profile-phone','reg-phone'].map(id=>{const el=document.getElementById(id);if(!el)return null;const type=el.type;el.type='password';return [id,type]}).filter(Boolean)")
    try:p.screenshot(path=str(E/'screenshots'/name),full_page=True,mask_color='#dfe5d9',mask=[p.locator('#'+n) for n in ['profile-phone','profile-password','profile-code','reg-phone','reg-password','reg-confirm','reg-code','password']])
    finally:p.evaluate("types=>types.forEach(([id,type])=>{document.getElementById(id).type=type})",types)


def counts(v):
    c=v['store'].db
    return {'profiles':c.execute('SELECT count(*) FROM user_profiles').fetchone()[0],'consumed':c.execute('SELECT count(*) FROM sms_verifications WHERE consumed_at IS NOT NULL').fetchone()[0],'phone_events':c.execute("SELECT count(*) FROM business_events WHERE kind='profile_updated' AND json_extract(metadata,'$.phone_verified')=1 AND json_extract(metadata,'$.changed_fields[0]')='phone_number'").fetchone()[0],'sessions':c.execute('SELECT count(*) FROM auth').fetchone()[0]}

def browser_fetch(v,path,method='GET',body=None):
    return v['page'].evaluate("async args=>{const me=await(await fetch('/api/me')).json();const r=await fetch(args.path,{method:args.method,headers:{'Content-Type':'application/json','X-CSRF-Token':me.csrf||''},...(args.body?{body:JSON.stringify(args.body)}:{})});return {status:r.status,body:await r.json()}}",{'path':path,'method':method,'body':body})

def run(browser,ids,fn,**kwargs):
    name=ids[0].lower();v=None
    try:
        with environment(browser,name,**kwargs) as v:fn(v);assert v['errors']==[],'no page script exceptions'
        for id in ids:results.append({'id':id,'status':'Pass'})
    except Exception as exc:
        frames=[{'function':f.name,'line':f.lineno} for f in traceback.extract_tb(exc.__traceback__) if f.filename.endswith('profile_e2e.py')]
        data={'status':'Fail','error_type':type(exc).__name__,'test_frames':frames,'checkpoint':v.get('checkpoint') if v else 'startup'}
        for id in ids:results.append({'id':id,**data})
        print(json.dumps({'case':name,**data}),flush=True)
    (E/'progress.json').write_text(json.dumps({'scenarios':results,'completed':len(results)},indent=2))

def basic(v):
    login(v);open_profile(v);p=v['page']
    expect(p.locator('#profile-username')).to_have_text('legacy-user');expect(p.locator('#profile-completion')).to_have_text('尚未补全')
    expect(p.locator('#profile-unit-value')).to_have_text('未填写');expect(p.locator('#profile-phone-value')).to_have_text('未绑定');expect(p.locator('#profile-registration-time')).to_have_text('未知')
    assert counts(v)['profiles']==0;shot(v,'profile-desktop.png');shot(v,'phone-unbound.png')
    p.locator('#profile-bind-start').click();expect(p.locator('#profile-password')).to_be_visible();expect(p.locator('#profile-send')).to_be_hidden()
    assert p.locator('#profile-password').get_attribute('type')=='password'
    shot(v,'reauthentication.png')

def binding(v):
    login(v);open_profile(v);unit(v,'Browser University');cookie=v['context'].cookies()[0]['value'];sessions=counts(v)['sessions']
    auth(v);code=send(v);shot(v,'code-entry.png')
    before_get=sum(r['path']=='/api/profile' and r['method']=='GET' for r in v['requests'])
    v['page'].locator('#profile-confirm').evaluate('(b)=>{b.click();b.click()}')
    p=v['page'];expect(p.locator('#profile-bound')).to_be_visible(timeout=15000)
    assert sum(r['path']=='/api/profile/phone/confirm' for r in v['requests'])==1
    assert sum(r['path']=='/api/profile' and r['method']=='GET' for r in v['requests'])>before_get
    expect(p.locator('#profile-phone-value')).to_have_text('***8000');expect(p.locator('#profile-completion')).to_have_text('已完善');expect(p.locator('#profile-registration-time')).to_have_text('未知')
    assert counts(v)=={'profiles':1,'consumed':1,'phone_events':1,'sessions':sessions}
    assert v['context'].cookies()[0]['value']==cookie
    assert all(p.locator('#'+id).input_value()=='' for id in ['profile-phone','profile-password','profile-code'])
    assert p.evaluate('localStorage.length')==p.evaluate('sessionStorage.length')==0
    assert all(secret not in p.content() and all(secret not in entry for entry in v['console']) for secret in [PASSWORD,code,PHONE,v['grant']])
    shot(v,'binding-success.png')
    expect(p.locator('#profile-bind-start')).to_be_hidden();expect(p.locator('#profile-change-phone')).to_be_hidden()
    p.reload();expect(p.locator('#profile-bound')).to_be_visible();expect(p.locator('#profile-phone-value')).to_have_text('***8000')

def organization(v):
    login(v);open_profile(v);p=v['page'];unit(v,'First University');unit(v,'Second University')
    p.locator('#profile-unit-edit').click();p.locator('#profile-unit').fill('Cancelled University');p.locator('#profile-unit-cancel').click()
    expect(p.locator('#profile-unit-value')).to_have_text('Second University')
    assert v['store'].db.execute("SELECT count(*) FROM business_events WHERE kind='profile_updated'").fetchone()[0]==2
    p.locator('#profile-unit-edit').click();p.locator('#profile-unit').fill('x'*201);p.locator('#profile-unit-save').click()
    expect(p.locator('#profile-unit-error')).to_contain_text('200');assert p.locator('#profile-unit').get_attribute('aria-invalid')=='true'
    p.locator('#profile-unit').fill('Final University');shot(v,'organization-edit.png')
    p.locator('#profile-unit-save').evaluate('(b)=>{b.click();b.click()}');expect(p.locator('#profile-unit-form')).to_be_hidden()
    assert v['store'].db.execute("SELECT count(*) FROM business_events WHERE kind='profile_updated'").fetchone()[0]==3
    p.reload();expect(p.locator('#profile-unit-value')).to_have_text('Final University')
    p.locator('#profile-unit-edit').click();p.locator('#profile-unit-clear').click();p.locator('#profile-unit-save').click();expect(p.locator('#profile-unit-value')).to_have_text('未填写')

def load_retry(v):
    login(v);p=v['page'];p.route('**/api/profile',lambda r:r.fulfill(status=503,json={'code':'profile_unavailable'}))
    p.locator('#profile-open').click();expect(p.locator('#profile-retry')).to_be_visible();expect(p.locator('#profile-content')).to_be_hidden()
    p.unroute('**/api/profile');p.locator('#profile-retry').click();expect(p.locator('#profile-username')).to_have_text('legacy-user')

def organization_loss(v):
    login(v);open_profile(v);p=v['page']
    def drop(route):
        if route.request.method=='PATCH':response=route.fetch();assert response.status==200;route.abort('failed')
        else:route.continue_()
    p.route('**/api/profile',drop);unit(v,'Recovered University');expect(p.locator('#profile-status')).to_contain_text('服务器确认')
    assert v['store'].db.execute("SELECT count(*) FROM business_events WHERE kind='profile_updated'").fetchone()[0]==1

def wrong_password(v):
    login(v);open_profile(v);p=v['page'];p.locator('#profile-bind-start').click();p.locator('#profile-phone').fill(PHONE);p.locator('#profile-password').fill('Incorrect-Synthetic-Password');p.locator('#profile-reauth').click()
    expect(p.locator('#profile-password-error')).to_contain_text('密码验证未通过');expect(p.locator('#profile-password')).to_have_value('');expect(p.locator('#profile-send')).to_be_hidden();shot(v,'error-example.png')

def expired_grant(v):
    login(v);open_profile(v);auth(v);v['clock'].offset=301;v['page'].locator('#profile-send').click()
    expect(v['page'].locator('#profile-bind-status')).to_contain_text('失效');expect(v['page'].locator('#profile-password')).to_be_visible();assert counts(v)['consumed']==0

def changed_phone(v):
    login(v);open_profile(v);auth(v);p=v['page'];p.locator('#profile-change-phone').click();expect(p.locator('#profile-send')).to_be_hidden()
    p.locator('#profile-phone').fill(OTHER_PHONE);p.locator('#profile-send').evaluate('(b)=>b.click()')
    assert not any(r['path']=='/api/profile/phone/send' for r in v['requests'])
    auth(v,OTHER_PHONE);p.locator('#profile-send').click();expect(p.locator('#profile-bind-status')).to_contain_text('请求已受理')
    assert v['store'].db.execute('SELECT phone_number FROM sms_verifications').fetchone()[0]==OTHER_PHONE

def logout_grant(v):
    login(v);open_profile(v);auth(v);grant=v['grant'];p=v['page'];p.locator('#profile-close').click();p.locator('#logout').click();expect(p.locator('#auth-form')).to_be_visible()
    response=p.evaluate("async data=>{const r=await fetch('/api/profile/phone/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});return r.status}",{'phone':PHONE,'authorization':grant,'request_id':secrets.token_hex(16)})
    assert response==401;login(v);open_profile(v);expect(p.locator('#profile-send')).to_be_hidden()
    result=browser_fetch(v,'/api/profile/phone/send','POST',{'phone':PHONE,'authorization':grant,'request_id':secrets.token_hex(16)});assert result['status']==403

def switch_user(v):
    login(v);open_profile(v);unit(v,'Private A University');auth(v);p=v['page'];p.locator('#profile-close').click();p.locator('#logout').click();expect(p.locator('#auth-form')).to_be_visible()
    login(v,'other-user');open_profile(v);expect(p.locator('#profile-username')).to_have_text('other-user');expect(p.locator('#profile-unit-value')).to_have_text('未填写')
    assert 'Private A University' not in p.locator('#profile-dialog').inner_text();expect(p.locator('#profile-send')).to_be_hidden()
    assert all(p.locator('#'+id).input_value()=='' for id in ['profile-phone','profile-password','profile-code'])

def cooldown(v):
    login(v);open_profile(v);auth(v);send(v);p=v['page'];expect(p.locator('#profile-send')).to_be_disabled();p.reload();expect(p.locator('#profile-dialog')).to_have_attribute('data-state','loaded')
    auth(v);p.locator('#profile-send').click();expect(p.locator('#profile-bind-status')).to_contain_text('请求过于频繁');assert v['provider'].call_count_for_test()==1

def wrong_code(v):
    login(v);open_profile(v);auth(v);code=send(v);p=v['page'];p.locator('#profile-code').fill(('0' if code[0]!='0' else '1')+code[1:]);p.locator('#profile-confirm').click()
    expect(p.locator('#profile-code-error')).to_contain_text('验证码错误');expect(p.locator('#profile-bound')).to_be_hidden()
    assert v['store'].db.execute('SELECT attempt_count FROM sms_verifications').fetchone()[0]==1 and counts(v)['consumed']==0

def expired_code(v):
    login(v);open_profile(v);auth(v);send(v);v['clock'].offset=301;v['page'].locator('#profile-confirm').click()
    expect(v['page'].locator('#profile-code-error')).to_contain_text('过期');assert counts(v)['consumed']==0

def replay_code(v):
    login(v);open_profile(v);auth(v);send(v);confirm(v);before=counts(v)
    data={**v['confirm'],'phone':OTHER_PHONE};assert browser_fetch(v,'/api/profile/phone/confirm','POST',data)['status']==403
    v['page'].locator('#profile-confirm').evaluate('(b)=>b.click()');assert counts(v)==before

def binding_loss(v):
    login(v);open_profile(v);auth(v);send(v);p=v['page']
    def drop(route):response=route.fetch();assert response.status==200;route.abort('failed')
    p.route('**/api/profile/phone/confirm',drop);confirm(v);expect(p.locator('#profile-bind-status')).to_contain_text('服务器确认')
    assert counts(v)['consumed']==counts(v)['phone_events']==1

def sms_error(v):
    login(v);open_profile(v);auth(v);service=v['app'].state.verification_service;service.settings=replace(service.settings,mode='disabled')
    v['page'].locator('#profile-send').click();expect(v['page'].locator('#profile-bind-status')).to_contain_text('暂时不可用');assert v['provider'].call_count_for_test()==0

def anonymous(v):
    p=v['page'];p.goto(v['url']+'/#profile');expect(p.locator('#auth-form')).to_be_visible();expect(p.locator('#profile-dialog')).to_be_hidden()
    p.evaluate('window.OreSageProfile.open()');expect(p.locator('#profile-dialog')).to_be_hidden();assert browser_fetch(v,'/api/profile')['status']==401

def tamper_identity(v):
    login(v);v['page'].evaluate('(id)=>{state.me.id=id}',v['ids']['other-user']);v['page'].locator('#profile-open').click()
    expect(v['page'].locator('#auth-form')).to_be_visible();expect(v['page'].locator('#profile-dialog')).to_be_hidden()
    assert v['store'].db.execute('SELECT count(*) FROM user_profiles').fetchone()[0]==0

def mass_assignment(v):
    login(v);open_profile(v);r=browser_fetch(v,'/api/profile','PATCH',{'organization':'Invalid Change','role':'admin','user_id':v['ids']['other-user']});assert r['status']==400
    assert browser_fetch(v,'/api/me')['body']['role']=='member' and counts(v)['profiles']==0

def session_expired(v):
    login(v);open_profile(v);auth(v);s=v['store']
    with s.lock,s.db:s.db.execute('UPDATE auth SET expires=?',(time.time()-1,))
    v['page'].locator('#profile-send').click();expect(v['page'].locator('#auth-form')).to_be_visible();expect(v['page'].locator('#profile-dialog')).to_be_hidden()
    assert all(v['page'].locator('#'+id).input_value()=='' for id in ['profile-phone','profile-password','profile-code'])

def csrf(v):
    login(v);open_profile(v);p=v['page'];p.locator('#profile-unit-edit').click();p.locator('#profile-unit').fill('No Write')
    p.evaluate("state.me.csrf='invalid-csrf'");p.locator('#profile-unit-save').click();expect(p.locator('#auth-form')).to_be_visible()
    assert counts(v)['profiles']==0

def registered_profile(v):
    p=v['page'];token=v['store'].invite();p.goto(v['url']+'/#join='+token);expect(p.locator('#reg-invitation')).to_contain_text('邀请有效')
    for key,value in [('username','registered-user'),('password',PASSWORD),('confirm',PASSWORD),('organization','New University'),('phone',PHONE)]:p.locator('#reg-'+key).fill(value)
    p.locator('#reg-send').click();expect(p.locator('#reg-sms-status')).to_contain_text('请求已受理');vid=v['store'].db.execute('SELECT verification_id FROM sms_verifications').fetchone()[0]
    p.locator('#reg-code').fill(v['provider'].captured_for_test(vid)[1]);p.locator('#reg-submit').click();expect(p.locator('#app')).to_be_visible(timeout=15000)
    open_profile(v);expect(p.locator('#profile-username')).to_have_text('registered-user');expect(p.locator('#profile-unit-value')).to_have_text('New University');expect(p.locator('#profile-bound')).to_be_visible()
    assert p.locator('#profile-registration-time').inner_text()!='未知'

def navigation(v):
    login(v);p=v['page'];p.locator('#new-chat').click();expect(p.locator('#conversation-list button')).to_have_count(1)
    file=v['root']/'sample.txt';file.write_text('Synthetic profile navigation proof')
    p.locator('#upload').set_input_files(str(file));expect(p.locator('#files-panel')).to_be_visible();expect(p.locator('#files-list')).to_contain_text('sample.txt')
    title=p.locator('#chat-title').inner_text();open_profile(v);p.locator('#profile-close').click();expect(p.locator('#chat-title')).to_have_text(title)
    expect(p.locator('#conversation-list button')).to_have_count(1);p.locator('#model-settings-button').click();expect(p.locator('#model-dialog')).to_be_visible()

def mobile(v):
    login(v);open_profile(v);p=v['page'];shot(v,'profile-mobile.png')
    assert p.evaluate('document.documentElement.scrollWidth <= innerWidth')
    p.locator('#profile-unit-edit').click();p.locator('#profile-unit').focus();p.keyboard.type('Mobile University');p.keyboard.press('Tab');p.keyboard.press('Tab');p.keyboard.press('Tab');p.keyboard.press('Enter')
    expect(p.locator('#profile-unit-value')).to_have_text('Mobile University')
    p.locator('#profile-bind-start').click();p.locator('#profile-phone').fill('bad');p.locator('#profile-password').fill(PASSWORD);p.locator('#profile-reauth').click();expect(p.locator('#profile-phone-error')).to_be_visible()
    assert 'profile-phone-error' in p.locator('#profile-phone').get_attribute('aria-describedby')
    for id in ['profile-phone','profile-password','profile-reauth','profile-close']:
        p.locator('#'+id).scroll_into_view_if_needed();box=p.locator('#'+id).bounding_box();assert box and box['x']>=0 and box['x']+box['width']<=390
    assert p.locator('label[for="profile-password"]').inner_text()=='当前账号密码' and p.locator('label[for="profile-code"]').inner_text()=='短信验证码'
    auth(v);send(v);expect(p.locator('#profile-send')).to_be_disabled();p.locator('#profile-code').focus();expect(p.locator('#profile-code')).to_be_focused()

def short_grant(v):
    login(v);open_profile(v);auth(v)
    p=v['page'];expect(p.locator('#profile-password')).to_be_visible(timeout=6500)
    expect(p.locator('#profile-dialog')).to_have_attribute('data-binding-state','expired')
    expect(p.locator('#profile-code')).to_have_value('');expect(p.locator('#profile-send')).to_be_hidden()

def exhausted_code(v):
    login(v);open_profile(v);service=v['app'].state.verification_service;service.settings=replace(service.settings,attempts=1)
    auth(v);code=send(v);p=v['page'];bad='000000' if code!='000000' else '111111'
    p.locator('#profile-code').fill(bad);p.locator('#profile-confirm').click();expect(p.locator('#profile-code-error')).to_contain_text('验证码错误')
    p.locator('#profile-code').fill(code);p.locator('#profile-confirm').click();expect(p.locator('#profile-code-error')).to_contain_text('验证码错误')
    assert counts(v)['consumed']==counts(v)['phone_events']==0 and browser_fetch(v,'/api/profile')['body']['phone_verified'] is False

def occupied_phone(v):
    repo=v['app'].state.profile_service.repo;s=v['store']
    with s.lock,migrations.transaction(s.db):repo.create_profile(v['ids']['other-user'],now=v['clock'](),phone_number=PHONE,phone_verified_at=v['clock']())
    login(v);open_profile(v);auth(v);p=v['page'];p.locator('#profile-send').click()
    expect(p.locator('#profile-bind-status')).to_contain_text('请求已受理');assert v['provider'].call_count_for_test()==0
    p.locator('#profile-code').fill('000000');p.locator('#profile-confirm').click();expect(p.locator('#profile-code-error')).to_contain_text('绑定条件不满足')
    assert browser_fetch(v,'/api/profile')['body']['phone_verified'] is False and counts(v)['consumed']==0

def database_retry(v):
    login(v);open_profile(v);unit(v,'Database Retry University');auth(v);send(v);s=v['store'];p=v['page']
    def deny(op,a,b,db,trigger):return sqlite3.SQLITE_DENY if op in (sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE) and a=='user_profiles' else sqlite3.SQLITE_OK
    s.db.set_authorizer(deny)
    try:
        p.locator('#profile-confirm').click();expect(p.locator('#profile-check-result')).to_be_visible()
        expect(p.locator('#profile-bind-status')).to_contain_text('暂未显示绑定成功');assert counts(v)['consumed']==counts(v)['phone_events']==0
    finally:s.db.set_authorizer(None)
    p.locator('#profile-confirm').click();expect(p.locator('#profile-bound')).to_be_visible();assert counts(v)['consumed']==counts(v)['phone_events']==1

def rejected_provider(v):
    original=v['provider'].send_verification_code
    def reject(phone,code,context):original(phone,code,context);return SendResult('rejected')
    v['provider'].send_verification_code=reject
    login(v);open_profile(v);auth(v);send(v);p=v['page'];p.locator('#profile-confirm').click()
    expect(p.locator('#profile-code-error')).to_contain_text('验证码错误');assert counts(v)['consumed']==counts(v)['phone_events']==0

def send_timeout(v):
    login(v);open_profile(v);auth(v);p=v['page'];held=[];p.clock.install()
    p.route('**/api/profile/phone/send',lambda route:held.append(route));p.locator('#profile-send').click()
    expect(p.locator('#profile-dialog')).to_have_attribute('data-binding-state','sending');assert held
    p.clock.fast_forward(16000);expect(p.locator('#profile-bind-status')).to_contain_text('请求超时')
    expect(p.locator('#profile-send')).to_be_enabled();assert v['provider'].call_count_for_test()==0

def deferred_login(v):
    v['checkpoint']='login-script-not-ready';p=v['page'];held=[]
    p.route('**/assets/app.js*',lambda route:held.append(route))
    p.goto(v['url'],wait_until='commit');expect(p.locator('#auth-form')).to_be_visible()
    p.locator('#username').fill('legacy-user');p.locator('#password').fill(PASSWORD)
    expect(p.locator('#auth-submit')).to_be_disabled();p.locator('#password').press('Enter');p.wait_for_timeout(250)
    from urllib.parse import urlsplit
    assert not urlsplit(p.url).query and not any(r['method']=='POST' for r in v['requests'])
    assert held;held[0].continue_();p.unroute('**/assets/app.js*')
    expect(p.locator('#auth-submit')).to_be_enabled();p.locator('#auth-submit').click()
    expect(p.locator('#app')).to_be_visible(timeout=15000);assert not urlsplit(p.url).query

with sync_playwright() as playwright:
    browser=playwright.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage']);version=browser.version
    if os.environ.get('PROFILE_E2E_SMOKE')=='1':
        run(browser,['SMOKE-display'],basic);run(browser,['SMOKE-binding'],binding)
    else:
        run(browser,['E2E-01','E2E-02','E2E-04','E2E-05','E2E-07','E2E-17','E2E-43'],basic)
        run(browser,['E2E-03','E2E-44','E2E-45'],registered_profile)
        run(browser,['E2E-09','E2E-10','E2E-11','E2E-12','E2E-13','E2E-14','E2E-15'],organization)
        run(browser,['E2E-06','E2E-18','E2E-24','E2E-25','E2E-27','E2E-28','E2E-29','E2E-33','E2E-35'],binding)
        for id,fn in [('E2E-08',load_retry),('E2E-16',organization_loss),('E2E-19',wrong_password),('E2E-20',expired_grant),('E2E-21',changed_phone),('E2E-22',logout_grant),('E2E-30',wrong_code),('E2E-32',replay_code),('E2E-34',binding_loss),('E2E-36',sms_error),('E2E-37',anonymous),('E2E-39',tamper_identity),('E2E-40',mass_assignment),('E2E-41',session_expired),('E2E-42',csrf)]:run(browser,[id],fn)
        run(browser,['E2E-23','E2E-38','E2E-46'],switch_user)
        run(browser,['E2E-26'],cooldown,cooldown=60)
        run(browser,['E2E-31'],expired_code,reauth=600)
        run(browser,['E2E-47','E2E-48','E2E-49'],navigation)
        run(browser,['A11Y-mobile-keyboard'],mobile,mobile=True)
        run(browser,['SEC-deferred-login-ready'],deferred_login)
        run(browser,['SEC-short-server-grant'],short_grant,reauth=2)
        for id,fn in [('ERR-code-exhaustion',exhausted_code),('ERR-occupied-phone',occupied_phone),('ERR-database-retry',database_retry),('ERR-provider-rejection',rejected_provider),('ERR-send-timeout',send_timeout)]:run(browser,[id],fn)
    browser.close()
data={'scope':'smoke' if os.environ.get('PROFILE_E2E_SMOKE')=='1' else 'profile frontend full','browser':'Chromium','version':version,'actual_browser':True,'scenarios':results,'passed':sum(r['status']=='Pass' for r in results),'failed':sum(r['status']=='Fail' for r in results),'skipped':0,'server_ports':sorted(ports),'real_sms_calls':0,'binding':'private namespace loopback','no_public_mock_code_endpoint':True,'screenshot_capture_policy':'Capture-only password rendering of phone inputs plus locator masks; original CSP retained','screenshots':sorted(p.name for p in (E/'screenshots').glob('*.png'))}
(E/'profile-browser-e2e.json').write_text(json.dumps(data,indent=2));print(json.dumps({k:v for k,v in data.items() if k not in {'scenarios','server_ports'}}),flush=True)
raise SystemExit(1 if data['failed'] else 0)
