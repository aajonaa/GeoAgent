'use strict';
// Credentials and invitation context live only in this page's memory.
window.OreSageRegistration = (() => {
  const fragment = new URLSearchParams(location.hash.slice(1));
  const active = fragment.has('join') || fragment.has('register') || new URLSearchParams(location.search).get('view') === 'register';
  let invite = fragment.get('join') || '';
  if (active) history.replaceState(null, '', location.pathname + location.search);
  const $ = id => document.getElementById(id);
  let api, initialize, showLogin, config, valid = false, busy = false, sending = false, checking = false;
  let challenge = null, expires = 0, cooldown = 0, sendNonce = null, pending = null, uncertain = false;
  const nonce = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
  const fields = ['username', 'password', 'confirm', 'organization', 'phone', 'code'];
  const value = name => $('reg-' + name).value;
  const message = (id, text) => { $(id).textContent = text; };
  function error(name, text) {
    $('reg-' + name).setAttribute('aria-invalid', 'true');
    message('reg-' + name + '-error', text); $('reg-' + name).focus();
    return false;
  }
  function clearErrors() {
    fields.forEach(name => { $('reg-' + name).removeAttribute('aria-invalid'); message('reg-' + name + '-error', ''); });
    message('reg-error', '');
  }
  function phone() {
    const raw = value('phone');
    if (!raw || raw.length > 80 || !/^[+0-9 ()-]+$/.test(raw)) return null;
    let compact = raw.replace(/[ ()-]/g, '');
    const plans = {CN: ['86', /^1[3-9][0-9]{9}$/], NANP: ['1', /^[2-9][0-9]{2}[2-9][0-9]{6}$/]};
    if (!compact.startsWith('+')) {
      if (!config.default_region) return null;
      compact = '+' + plans[config.default_region][0] + compact;
    }
    return config.allowed_regions.some(region => compact.startsWith('+' + plans[region][0]) && plans[region][1].test(compact.slice(plans[region][0].length + 1))) ? compact : null;
  }
  function checkCode() {
    return new RegExp('^[0-9]{' + config.digits + '}$').test(value('code')) || error('code', '请输入 ' + config.digits + ' 位数字验证码。');
  }
  function checkForm() {
    clearErrors();
    if (!/^[A-Za-z0-9_.-]{3,40}$/.test(value('username').trim())) return error('username', '用户名需为 3–40 位英文字母、数字、点、下划线或连字符。');
    const length = Array.from(value('password')).length;
    if (length < 12 || length > 256) return error('password', '密码长度需为 12–256 个字符。');
    if (value('password') !== value('confirm')) return error('confirm', '两次输入的密码不一致。');
    const organization = value('organization').trim();
    if (!organization || Array.from(organization).length > 200 || /[\x00-\x1f\x7f]/.test(organization)) return error('organization', '请填写所属单位，最多 200 个字符，不含控制字符。');
    if (!phone()) return error('phone', '请输入受支持地区的手机号；无默认地区时请使用 +国家码。');
    if (!challenge) { message('reg-error', '请先请求短信验证码。'); $('reg-send').focus(); return false; }
    return checkCode();
  }
  function sync() {
    const wait = Math.max(0, Math.ceil((cooldown - Date.now()) / 1000));
    $('reg-fields').disabled = !valid || uncertain || busy;
    $('reg-submit').disabled = !valid || !challenge || busy || sending || checking || uncertain;
    $('reg-submit').textContent = busy ? '正在注册…' : '创建账号并登录';
    $('reg-send').disabled = !valid || sending || checking || busy || uncertain || wait > 0;
    $('reg-send').textContent = sending ? '正在请求…' : wait ? wait + ' 秒后可重试' : '请求验证码';
    $('reg-verify').disabled = !challenge || checking || sending || busy || uncertain;
    $('reg-verify').textContent = checking ? '正在检查…' : '检查验证码';
    $('reg-retry').disabled = busy;
    $('reg-invite').disabled = busy || uncertain;
    $('reg-invite-check').disabled = busy || uncertain || config.mode === 'disabled';
    $('reg-form').setAttribute('aria-busy', busy ? 'true' : 'false');
  }
  function safeError(exc, operation) {
    if (exc.status === 429) {
      const seconds = Math.max(1, exc.retryAfter || config.cooldown || 60);
      if (operation === 'send') cooldown = Date.now() + seconds * 1000;
      return '请求过于频繁，请等待 ' + seconds + ' 秒后重试。';
    }
    if (exc.code === 'registration_disabled') { valid = false; return '当前暂不开放注册。已有账号可直接登录。'; }
    if (exc.status === 409) return '账号资料或请求发生冲突，请核对资料；如可能已注册，请尝试登录。';
    if (exc.status === 403) return '邀请或验证码已失效。请检查验证码，必要时联系管理员获取新邀请。';
    if (exc.name === 'AbortError') return '请求超时，请稍后重试。';
    if (!exc.status) return '网络连接失败，请检查连接后重试。';
    return '服务暂时不可用，请稍后重试或联系管理员。';
  }
  function destroy() {
    invite = ''; pending = null; challenge = null; sendNonce = null; uncertain = false; valid = false;
    $('reg-invite').value = '';
    fields.forEach(name => { $('reg-' + name).value = ''; });
    $('registration').hidden = true;
  }
  function loginRecovery(text) {
    const username = value('username').trim(); destroy();
    $('auth-form').hidden = false; $('auth-title').textContent = '登录研究组';
    $('registration-open').hidden = false;
    const url = new URL(location.href); url.searchParams.delete('view'); url.hash = '';
    history.replaceState(null, '', url.pathname + url.search);
    $('auth-hint').textContent = text || '使用你的个人账号。新成员请向管理员索取邀请链接。';
    $('auth-error').textContent = ''; $('username').value = username; $('password').value = '';
    $('auth-screen').classList.remove('registering'); $('auth-form').reset(); $('username').value = username;
    $('username').focus();
  }
  function recover(text) {
    uncertain = true; message('reg-error', text);
    $('reg-recovery').hidden = false; $('reg-retry').hidden = !pending;
    sync(); $('reg-error').focus();
  }
  async function validateInvite() {
    valid = false; $('reg-invite-retry').disabled = true; sync();
    message('reg-invitation', '正在检查邀请…');
    if (config.mode === 'disabled') { message('reg-invitation', '注册需要填写所属单位、手机号并完成短信验证。短信服务尚未开通，暂时无法创建新账号；已有账号可直接登录。'); $('reg-invite-retry').hidden = true; return; }
    if (!/^[A-Za-z0-9_-]{43}$/.test(invite)) { message('reg-invitation', '请填写管理员提供的邀请链接或邀请码，再填写注册资料。'); $('reg-invite-retry').hidden = true; return; }
    const submittedInvite = invite;
    try {
      const result = await api('/api/auth/invitations/validate', {method: 'POST', body: {invite}, timeoutMs: 15000});
      if (invite !== submittedInvite) return;
      valid = result.valid === true;
      message('reg-invitation', valid ? '邀请有效 · 注册后获得普通成员权限' : '邀请无效、已过期、已使用或已撤销。请联系管理员获取新邀请。');
      $('reg-invite-retry').hidden = valid;
    } catch (exc) { message('reg-invitation', safeError(exc, 'invitation')); $('reg-invite-retry').hidden = false; }
    finally { $('reg-invite-retry').disabled = false; sync(); }
  }
  async function send() {
    if (sending || busy || uncertain || Date.now() < cooldown || !valid) return;
    clearErrors();
    if (!phone()) return error('phone', '请输入受支持地区的有效手机号，例如 +86 开头的手机号。');
    sending = true; sync(); sendNonce ||= nonce();
    const submittedPhone = phone();
    try {
      const result = await api('/api/auth/sms/send', {method: 'POST', body: {invite, phone: submittedPhone, request_id: sendNonce}, timeoutMs: 15000});
      if (phone() !== submittedPhone) return;
      challenge = result.verification_id; expires = result.expires_at * 1000;
      cooldown = Date.now() + config.cooldown * 1000; sendNonce = null;
      $('reg-code').value = '';
      message('reg-sms-status', '验证码请求已受理，不代表短信已送达。请查看手机短信；注册时会再次验证。');
    } catch (exc) { message('reg-sms-status', safeError(exc, 'send')); }
    finally { sending = false; sync(); }
  }
  async function verify() {
    if (!challenge || checking || busy || uncertain) return;
    clearErrors(); if (!checkCode()) return;
    checking = true; sync();
    const submitted = {invite, phone: phone(), verification_id: challenge, code: value('code')};
    try {
      const result = await api('/api/auth/sms/verify', {method: 'POST', body: submitted, timeoutMs: 15000});
      if (phone() !== submitted.phone || challenge !== submitted.verification_id || value('code') !== submitted.code) return;
      if (result.valid) message('reg-sms-status', '验证码预检查通过；尚未注册，提交时仍需最终验证。');
      else error('code', '验证码错误、过期或已失效，请核对或重新请求。');
    } catch (exc) { message('reg-sms-status', safeError(exc, 'verify')); }
    finally { checking = false; sync(); }
  }
  async function submit(event) {
    event?.preventDefault();
    if (busy || !valid || sending || checking) return;
    if (!uncertain) {
      if (!checkForm()) return;
      pending = {username: value('username').trim(), password: value('password'), organization: value('organization').trim(), phone: phone(), invite, verification_id: challenge, code: value('code'), request_id: nonce()};
    }
    if (!pending) return;
    busy = true; sync(); clearErrors();
    try {
      const result = await api('/api/register', {method: 'POST', body: pending, timeoutMs: 20000});
      if (result.registered !== true) { recover('未能确认注册结果。请先尝试登录，或安全重试本次注册。'); return; }
      if (result.authenticated !== true) { loginRecovery('账号已创建，请使用刚才的用户名和密码登录。'); return; }
      // Existing initialization fetches /api/me; no client-created identity.
      try { await initialize(); destroy(); }
      catch { showLogin(); recover('账号已创建，但未能确认页面登录状态。请前往登录恢复。'); }
    } catch (exc) {
      if (!exc.status || exc.status >= 500) recover('注册结果尚未确认，账号可能已经创建。请先尝试登录，或安全重试本次注册；不要重复创建新账号。');
      else { message('reg-error', safeError(exc, 'register')); if (uncertain) $('reg-recovery').hidden = false; else pending = null; }
    } finally { busy = false; sync(); }
  }
  function mount(dependencies) {
    api = dependencies.api; initialize = dependencies.initialize; showLogin = dependencies.showLogin;
    config = JSON.parse($('registration').dataset.config);
    $('auth-form').hidden = true; $('auth-screen').classList.add('registering'); $('registration').hidden = false;
    $('registration-open').hidden = true;
    $('auth-title').textContent = '注册研究组账号'; $('auth-hint').textContent = '注册时必须填写所属单位和手机号，完成手机验证后创建账号。邀请仅限使用一次。';
    if (invite) $('reg-invite').placeholder = '已从邀请链接读取，可粘贴新邀请替换';
    $('reg-invite').addEventListener('input', () => {
      if (busy || uncertain) return;
      valid = false; challenge = null; pending = null; sendNonce = null; expires = 0; invite = '';
      $('reg-code').value = ''; message('reg-sms-status', '验证邀请后填写单位和手机号。'); sync();
    });
    $('reg-invite-check').addEventListener('click', () => {
      if (busy || uncertain) return;
      const raw = $('reg-invite').value.trim();
      try { const link = new URL(raw); invite = link.origin === location.origin ? new URLSearchParams(link.hash.slice(1)).get('join') || '' : ''; }
      catch { invite = raw; }
      $('reg-invite').value = ''; validateInvite();
    });
    $('reg-code').maxLength = config.digits;
    $('reg-form').addEventListener('submit', submit);
    $('reg-send').addEventListener('click', send); $('reg-verify').addEventListener('click', verify);
    $('reg-invite-retry').addEventListener('click', validateInvite);
    $('reg-login').addEventListener('click', () => loginRecovery());
    $('reg-recover-login').addEventListener('click', () => loginRecovery('如果注册已经完成，请使用刚才的账号登录。'));
    $('reg-retry').addEventListener('click', submit);
    $('reg-phone').addEventListener('input', () => { challenge = null; sendNonce = null; pending = null; $('reg-code').value = ''; message('reg-sms-status', '手机号修改后需重新请求验证码。'); sync(); });
    fields.forEach(name => $('reg-' + name).addEventListener('input', () => { $('reg-' + name).removeAttribute('aria-invalid'); message('reg-' + name + '-error', ''); }));
    window.addEventListener('pagehide', destroy, {once: true});
    setInterval(() => { if (!active || $('registration').hidden) return; if (expires && Date.now() >= expires) message('reg-sms-status', '验证码可能已过期，请重新请求。最终有效性由服务器判断。'); sync(); }, 1000);
    validateInvite();
  }
  return {active, mount};
})();
