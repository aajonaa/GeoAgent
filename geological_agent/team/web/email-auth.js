'use strict';
window.OreSageEmail = (() => {
  const $ = id => document.getElementById(id);
  const fragment = new URLSearchParams(location.hash.slice(1));
  window.addEventListener('hashchange', () => {
    if (new URLSearchParams(location.hash.slice(1)).has('join')) location.reload();
  });
  const active = fragment.has('join') || new URLSearchParams(location.search).get('view') === 'register';
  let invite = fragment.get('join') || '';
  if (fragment.has('join')) history.replaceState(null, '', location.pathname + location.search);
  let api, initialize, loginScreen, enabled = false, busy = false, booting = false, pending = '';
  const flows = {login:{}, register:{}};
  const nonce = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), v => v.toString(16).padStart(2,'0')).join('');
  const text = (id, value='') => { $(id).textContent = value; };
  const address = purpose => $('email-'+purpose+'-address').value.trim().toLowerCase();
  const status = (purpose, value) => text('email-'+purpose+'-status',value);
  function clearError(purpose) {
    if (purpose==='register') text('email-register-error');
    $('email-'+purpose+'-status').classList.remove('error');
  }
  function fail(purpose,message,input=null) {
    status(purpose,'');
    const box=$(purpose==='register'?'email-register-error':'email-login-status');
    box.textContent=message;box.classList.add('error');box.setAttribute('role','alert');box.tabIndex=-1;
    if (input) {
      input.setAttribute('aria-invalid','true');input.setCustomValidity(message);
      input.reportValidity();
    } else {box.focus({preventScroll:true});box.scrollIntoView({block:'center'});}
    return false;
  }
  function validRegistration() {
    const rules=[
      ['username',v=>/^[A-Za-z0-9_.-]{3,40}$/.test(v),'用户名需为 3–40 位英文字母、数字、点、下划线或连字符，暂不支持中文用户名。'],
      ['organization',v=>v.length>0 && Array.from(v).length<=200,'请填写所属单位，最多 200 个字符。'],
      ['research-area',v=>v.length>0 && Array.from(v).length<=200,'请填写研究领域，最多 200 个字符。'],
      ['gender',v=>['male','female'].includes(v),'请选择性别：男或女。'],
      ['age',v=>v.length>0 && Number.isInteger(Number(v)) && Number(v)>=1 && Number(v)<=120,'年龄需为 1–120 的整数。'],
      ['password',v=>Array.from(v).length>=12 && Array.from(v).length<=256,'密码需为 12–256 个字符。'],
      ['confirm-password',v=>v===$('email-register-password').value,'两次输入的密码不一致。']
    ];
    for (const [suffix,valid,message] of rules) {
      const input=$('email-register-'+suffix);
      if (!valid(suffix.includes('password')?input.value:input.value.trim())) return fail('register',message,input);
    }
    return readInvite();
  }
  function wipe() {
    for (const purpose of ['login','register']) {
      flows[purpose]={};
      for (const suffix of ['address','code']) $('email-'+purpose+'-'+suffix).value='';
      status(purpose,'');
    }
    for (const suffix of ['invite','username','organization','research-area','gender','age','password','confirm-password']) $('email-register-'+suffix).value='';
    invite='';text('email-register-error');text('auth-error');
    for(const input of document.querySelectorAll('#email-register-form input,#email-register-form select,#email-login-form input')) {input.setCustomValidity('');input.removeAttribute('aria-invalid');}
  }
  function sync() {
    $('email-register-fields').disabled=booting || busy || !enabled;
    for (const purpose of ['login','register']) {
      const wait=Math.max(0,Math.ceil(((flows[purpose].cooldown||0)-Date.now())/1000));
      $('email-'+purpose+'-send').disabled=booting || busy || !enabled || wait>0;
      $('email-'+purpose+'-send').textContent=wait ? wait+' 秒后可重发' : '发送验证码';
      $('email-'+purpose+'-submit').disabled=booting || busy || !enabled;
      $('email-'+purpose+'-submit').textContent=busy ? (pending==='send'?'正在发送验证码…':purpose==='register'?'正在验证并创建账号…':'正在验证登录…') : purpose==='register'?'验证邮箱并创建账号':'验证并登录';
      $('email-'+purpose+'-form').setAttribute('aria-busy',String(busy));
      $('email-'+purpose+'-code').disabled=booting || busy || !enabled;
      $('email-'+purpose+'-address').disabled=booting || busy || !enabled;
    }
    for (const id of ['email-mode','password-mode','email-register-back']) $(id).disabled=booting || busy;
  }
  function showLogin(initializing=false,method='password') {
    if (!$('email-login-form')) return;
    wipe();busy=false;booting=initializing===true;
    $('registration').hidden=true;$('auth-form').hidden=method!=='password';$('email-login-form').hidden=method!=='email';$('forgot-password').hidden=false;
    $('auth-methods').hidden=false;$('registration-open').hidden=false;$('auth-screen').classList.remove('registering');
    text('auth-title',method==='email'?'邮箱验证码登录':'账号密码登录');text('auth-hint',method==='email'?'使用已验证邮箱获取验证码登录；也可切换回账号密码登录。':'支持用户名或已验证邮箱和密码。尚未设置密码或忘记密码，可通过邮箱验证设置。');
    const url=new URL(location.href);url.searchParams.delete('view');if (url.hash.startsWith('#join=')) url.hash='';history.replaceState(null,'',url.pathname+url.search+url.hash);
    if (!enabled) status('login','邮箱验证码服务尚未开启。旧账号可使用密码登录。');
    sync();
  }
  function showRegister() {
    $('email-login-form').hidden=true;$('auth-form').hidden=true;$('registration').hidden=false;
    $('auth-methods').hidden=true;$('registration-open').hidden=true;$('forgot-password').hidden=true;$('auth-screen').classList.add('registering');
    text('auth-title','受邀注册 OreBOGAO');text('auth-hint','注册时填写邮箱、单位、研究领域、性别和年龄。验证邮箱并设置密码，之后可用用户名或邮箱和密码登录。');
    if (!enabled) text('email-registration-notice','邮箱验证码注册尚未开启，请联系管理员。已有账号可继续密码登录。');
    sync();
  }
  function errorMessage(error) {
    if (error.status===429) return '请求过于频繁，请等待 '+Math.max(1,error.retryAfter||60)+' 秒后重试。';
    const messages={invalid_password:'密码需为 12–256 个字符。',password_mismatch:'两次输入的密码不一致。',invalid_email:'请填写有效邮箱。',organization_required:'请填写所属单位。',invitation_rejected:'邀请无效、已过期或已撤销，请联系管理员获取新邀请。',invitation_full:'此邀请已达到 50 人注册上限，请联系管理员获取新邀请。',research_area_required:'请填写研究领域。',gender_required:'请选择性别。',invalid_age:'年龄需为 1–120 的整数。',verification_rejected:'验证码错误、已过期或已使用，请核对或重新发送。',registration_conflict:'用户名或邮箱已注册，请直接登录或更换用户名。',request_conflict:'请求发生冲突，请重新开始。',send_unavailable:'邮件发送结果未确认，请等待后重试；请勿连续点击发送。',invalid_request:'请检查注册资料、密码和验证码；旧页面请刷新后重试。'};
    return messages[error.code] || '暂时无法完成请求，请稍后重试；如可能已创建账号，请改用邮箱验证码登录。';
  }
  function validEmail(purpose) {
    const input=$('email-'+purpose+'-address');
    if (!input.value.trim() || !input.checkValidity()) return fail(purpose,'请填写有效邮箱。',input);
    return true;
  }
  function readInvite() {
    const raw=$('email-register-invite').value.trim();
    if (raw) {
      try { const url=new URL(raw);invite=url.origin===location.origin ? new URLSearchParams(url.hash.slice(1)).get('join')||'' : ''; }
      catch { invite=raw; }
      $('email-register-invite').value='';
    }
    if (!/^[A-Za-z0-9_-]{43}$/.test(invite)) return fail('register','请提供管理员发出的邀请链接或邀请码。',$('email-register-invite'));
    return true;
  }
  async function send(purpose) {
    if (busy || !enabled || Date.now()<(flows[purpose].cooldown||0) || !validEmail(purpose)) return;
    clearError(purpose);
    if (purpose==='register' && !validRegistration()) return;
    const target=address(purpose);busy=true;pending='send';flows[purpose].cooldown=Date.now()+60000;sync();
    status(purpose,'正在发送验证码…');
    try {
      const data={email:target,purpose,request_id:nonce(),...(purpose==='register'?{invite}:{})};
      const response=await api('/api/auth/email/send',{method:'POST',body:data,timeoutMs:20000});
      flows[purpose].challenge=response.verification_id;flows[purpose].email=target;
      status(purpose,purpose==='login'?'如该邮箱已注册，将收到验证码。请查收邮箱及垃圾邮件，验证码五分钟内有效。':'验证码发送请求已受理，请查收邮箱及垃圾邮件，验证码五分钟内有效。');
    } catch(error) {
      if (error.status===429) flows[purpose].cooldown=Date.now()+Math.max(1,error.retryAfter||60)*1000;
      fail(purpose,errorMessage(error));
    } finally { busy=false;sync(); }
  }
  async function submit(event,purpose) {
    event.preventDefault();
    if (busy) return;
    clearError(purpose);
    if (!enabled) return fail(purpose,'邮箱验证码服务暂不可用，请稍后重试或联系管理员。');
    if (!validEmail(purpose)) return;
    text('auth-error');text('email-register-error');
    const code=$('email-'+purpose+'-code').value;
    if (purpose==='register' && !validRegistration()) return;
    if (!flows[purpose].challenge || flows[purpose].email!==address(purpose)) {fail(purpose,'请先为当前邮箱发送验证码；修改邮箱后需要重新发送。');return;}
    if (!/^[0-9]{6}$/.test(code)) {fail(purpose,'请输入六位数字验证码。',$('email-'+purpose+'-code'));return;}
    const data={email:address(purpose),verification_id:flows[purpose].challenge,code};
    if (purpose==='register') Object.assign(data,{username:$('email-register-username').value.trim(),organization:$('email-register-organization').value.trim(),research_area:$('email-register-research-area').value.trim(),gender:$('email-register-gender').value,age:Number($('email-register-age').value),password:$('email-register-password').value,confirm_password:$('email-register-confirm-password').value,invite,request_id:flows[purpose].registrationId ||= nonce()});
    busy=true;pending='submit';sync();status(purpose,'正在验证…');
    try {
      const result=await api('/api/auth/email/'+purpose,{method:'POST',body:data,timeoutMs:20000});
      if (purpose==='register' && result.authenticated!==true) {loginScreen();status('login','账号已创建。请获取新的邮箱验证码登录。');return;}
      await initialize();
    } catch(error) {fail(purpose,errorMessage(error));}
    finally {busy=false;sync();}
  }
  function authenticated() {wipe();busy=false;booting=false;const url=new URL(location.href);url.searchParams.delete('view');history.replaceState(null,'',url.pathname+url.search+url.hash);sync();}
  function mount(dependencies) {
    ({api,initialize}=dependencies);loginScreen=dependencies.showLogin;
    enabled=JSON.parse($('registration').dataset.config).email_enabled===true;
    $('email-mode').addEventListener('click',()=>showLogin(false,'email'));
    $('password-mode').addEventListener('click',()=>{showLogin();$('email-login-form').hidden=true;$('auth-form').hidden=false;text('auth-title','账号密码登录');$('username').focus();});
    $('email-register-back').addEventListener('click',loginScreen);
    for (const purpose of ['login','register']) {
      $('email-'+purpose+'-send').addEventListener('click',()=>send(purpose));
      $('email-'+purpose+'-form').addEventListener('submit',e=>{submit(e,purpose).catch(()=>{busy=false;sync();fail(purpose,'页面提交遇到错误，请重试；仍失败时请刷新页面后重新发送验证码。');});});
      $('email-'+purpose+'-address').addEventListener('input',()=>{if(flows[purpose].email!==address(purpose)){flows[purpose].challenge=null;flows[purpose].registrationId=null;$('email-'+purpose+'-code').value='';}});
    }
    for(const input of document.querySelectorAll('#email-register-form input,#email-register-form select,#email-login-form input')) {for(const event of ['input','change']) input.addEventListener(event,()=>{input.setCustomValidity('');input.removeAttribute('aria-invalid');clearError(input.closest('#email-register-form')?'register':'login');});}
    $('email-register-organization').addEventListener('input',()=>$('email-register-organization').removeAttribute('aria-invalid'));
    $('email-register-invite').addEventListener('input',()=>{invite='';flows.register.challenge=null;flows.register.registrationId=null;});
    window.addEventListener('pagehide',wipe,{once:true});setInterval(sync,1000);
    if (active) showRegister();else showLogin(true);
  }
  return {active,mount,showLogin,authenticated};
})();
