'use strict';
// Profile data comes from the Session-protected API; operation grants stay in memory.
window.OreSageProfile = (() => {
  const $ = id => document.getElementById(id);
  let api, identity, showLogin, config, profile = null, marker = null, epoch = 0;
  let busy = null, editing = false, loadState = 'closed', phase = 'idle', revision = 0;
  let authorization = null, authorizedUntil = 0, target = null, challenge = null, codeUntil = 0;
  let sendNonce = null, cooldownUntil = 0;
  const nonce = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), x => x.toString(16).padStart(2, '0')).join('');
  const text = (id, value = '') => { $(id).textContent = value; };
  const alive = e => e === epoch && $('profile-dialog').open;
  function phoneValue() {
    const raw = $('profile-phone').value;
    if (!raw || raw.length > 80 || !/^[+0-9 ()-]+$/.test(raw)) return null;
    let compact = raw.replace(/[ ()-]/g, '');
    const plans = {CN: ['86', /^1[3-9][0-9]{9}$/], NANP: ['1', /^[2-9][0-9]{2}[2-9][0-9]{6}$/]};
    if (!compact.startsWith('+')) {
      if (!config.default_region) return null;
      compact = '+' + plans[config.default_region][0] + compact;
    }
    return config.allowed_regions.some(region => compact.startsWith('+' + plans[region][0]) && plans[region][1].test(compact.slice(plans[region][0].length + 1))) ? compact : null;
  }
  function date(value) {
    return typeof value === 'number' && Number.isFinite(value) && value >= 0
      ? new Intl.DateTimeFormat('zh-CN', {dateStyle: 'medium', timeStyle: 'short'}).format(new Date(value * 1000)) : '未知';
  }
  function fieldError(id, message) {
    $(id).setAttribute('aria-invalid', 'true'); text(id + '-error', message); $(id).focus();
  }
  function clearErrors() {
    for (const id of ['profile-unit', 'profile-phone', 'profile-password', 'profile-code']) {
      $(id).removeAttribute('aria-invalid'); text(id + '-error');
    }
    text('profile-error');
  }
  function wipePhone() {
    revision++; authorization = null; authorizedUntil = 0; target = null;
    challenge = null; codeUntil = 0; sendNonce = null;
    for (const id of ['profile-phone', 'profile-password', 'profile-code']) $(id).value = '';
    text('profile-target'); text('profile-authorization');
  }
  function setPhase(next, message = '') { phase = next; text('profile-bind-status', message); sync(); }
  function clear() {
    epoch++; wipePhone(); profile = null; marker = null; busy = null; editing = false;
    loadState = 'closed'; phase = 'idle'; cooldownUntil = 0;
    $('profile-unit').value = '';
    for (const id of ['profile-username','profile-research-value','profile-gender-value','profile-age-value','profile-email-value','profile-unit-value','profile-phone-value','profile-registration-time','profile-verified-time','profile-completion','profile-status','profile-error','profile-bind-status']) text(id);
    clearErrors();
    if ($('profile-dialog').open) $('profile-dialog').close();
    if (location.hash === '#profile') history.replaceState(null, '', location.pathname + location.search);
    sync();
  }
  function loginRequired() { clear(); showLogin(); }
  function authFailure(exc) {
    if (exc.status === 401 || (exc.status === 403 && !exc.code)) { loginRequired(); return true; }
    return false;
  }
  function errorMessage(exc) {
    if (exc.status === 429) return '请求过于频繁，请等待 ' + Math.max(1, exc.retryAfter || config.cooldown || 60) + ' 秒后重试。';
    if (exc.status === 409) return '本次请求与此前操作不一致，请重新开始手机验证。';
    if (exc.code === 'reauthentication_required') return '身份确认已失效，请重新输入当前账号密码。';
    if (exc.code === 'phone_binding_rejected') return '验证码错误、过期或已失效，或绑定条件不满足。请核对后重试，必要时重新开始。';
    if (exc.status === 400) return '输入格式不符合要求，请检查后重试。';
    if (exc.name === 'AbortError') return '请求超时，请检查连接后重试。';
    if (!exc.status) return '网络连接失败，请稍后重试。';
    return '服务暂时不可用，请稍后重试或联系管理员。';
  }
  function apply(data) {
    if (!identity() || data.user_id !== identity().id) { loginRequired(); return false; }
    // Only the server's public profile fields are rendered; never a client-selected UID.
    profile = data; loadState = 'loaded';
    if (data.phone_verified === true) { wipePhone(); phase = 'bound'; }
    render(); return true;
  }
  function render() {
    if (!profile) { sync(); return; }
    text('profile-username', profile.username);
    text('profile-research-value', profile.research_area || '未填写');
    text('profile-gender-value', {male:'男',female:'女',other:'其他'}[profile.gender] || '未填写');
    text('profile-age-value', Number.isInteger(profile.age) ? String(profile.age) : '未填写');
    text('profile-email-value', profile.email_verified ? profile.email_masked : '未绑定邮箱；请使用旧账号密码登录');
    text('profile-unit-value', profile.organization || '未填写');
    text('profile-registration-time', date(profile.registration_time));
    text('profile-completion', {no_profile:'尚未补全', incomplete:'待完善', complete:'已完善'}[profile.profile_completion_status] || '未知');
    const verified = profile.phone_verified === true;
    text('profile-phone-value', verified ? (/^\*{3}[0-9]{0,4}$/.test(profile.phone_masked || '') ? profile.phone_masked : '已绑定') : '未绑定');
    text('profile-verified-time', verified ? date(profile.phone_verified_at) : '尚未验证');
    sync();
  }
  function sync() {
    const dialog = $('profile-dialog'); if (!dialog) return;
    dialog.dataset.state = loadState; dialog.dataset.bindingState = phase;
    dialog.setAttribute('aria-busy', busy ? 'true' : 'false');
    $('profile-content').hidden = !profile || loadState !== 'loaded';
    $('profile-retry').hidden = loadState !== 'error'; $('profile-refresh').disabled = Boolean(busy);
    $('profile-unit-form').hidden = !editing; $('profile-unit-display').hidden = editing;
    $('profile-unit-fields').disabled = Boolean(busy);
    $('profile-unit-edit').disabled = Boolean(busy); $('profile-unit-save').textContent = busy === 'organization' ? '正在保存…' : '保存';
    const bound = profile?.phone_verified === true;
    $('profile-bound').hidden = !bound; $('profile-bind-start').hidden = bound || phase !== 'idle' || config.phone_binding_enabled === false;
    $('profile-bind-start').disabled = Boolean(busy); $('profile-bind-form').hidden = bound || phase === 'idle';
    $('profile-phone-entry').hidden = Boolean(authorization);
    $('profile-target-row').hidden = !authorization;
    $('profile-phone').disabled = Boolean(busy); $('profile-password').disabled = Boolean(busy);
    $('profile-reauth').disabled = Boolean(busy);
    $('profile-reauth').textContent = busy === 'reauthenticate' ? '正在确认身份…' : '确认账号身份';
    $('profile-change-phone').disabled = Boolean(busy); $('profile-bind-restart').disabled = Boolean(busy);
    const wait = Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000));
    $('profile-send').hidden = !authorization;
    $('profile-send').disabled = Boolean(busy) || wait > 0;
    $('profile-send').textContent = busy === 'send' ? '正在请求…' : wait ? wait + ' 秒后可重试' : '请求验证码';
    $('profile-code-area').hidden = !challenge;
    $('profile-code').disabled = Boolean(busy);
    $('profile-confirm').disabled = Boolean(busy) || !authorization || !challenge;
    $('profile-confirm').textContent = busy === 'confirm' ? '正在确认绑定…' : phase === 'recovering' ? '安全重试确认' : '确认绑定';
    $('profile-check-result').hidden = phase !== 'recovering'; $('profile-check-result').disabled = Boolean(busy);
  }
  async function load() {
    if (!identity()) { loginRequired(); return false; }
    const e = epoch; busy = 'load'; loadState = 'loading'; text('profile-status', '正在读取个人资料…'); clearErrors(); sync();
    try {
      const data = await api('/api/profile', {timeoutMs:15000});
      if (!alive(e) || !apply(data)) return false;
      text('profile-status', data.profile_completion_status === 'no_profile' ? '尚未填写资料，不影响使用现有功能。' : '已读取服务器资料。');
      return true;
    } catch (exc) {
      if (!alive(e) || authFailure(exc)) return false;
      profile = null; loadState = 'error'; text('profile-status'); text('profile-error', errorMessage(exc));
      return false;
    } finally { if (alive(e)) { busy = null; sync(); } }
  }
  function open() {
    if (!identity()) { loginRequired(); return; }
    if ($('profile-dialog').open) return;
    epoch++; marker = identity().id + '|' + identity().csrf;
    history.replaceState(null, '', location.pathname + location.search + '#profile');
    $('sidebar').classList.remove('open'); $('profile-dialog').showModal(); $('profile-title').focus(); load();
  }
  function session(me) {
    const next = me.id + '|' + me.csrf;
    if (marker && marker !== next) clear();
    marker = next;
    if (location.hash === '#profile') open();
  }
  function beginUnit() {
    if (!profile || busy) return;
    editing = true; $('profile-unit').value = profile.organization || ''; clearErrors(); sync(); $('profile-unit').focus();
  }
  async function saveUnit(event) {
    event.preventDefault(); if (busy || !editing) return;
    clearErrors(); const normalized = $('profile-unit').value.trim();
    if (Array.from(normalized).length > 200 || /[\x00-\x1f\x7f]/.test(normalized)) { fieldError('profile-unit', '单位最多 200 个字符，不能包含控制字符。'); return; }
    const e = epoch; busy = 'organization'; text('profile-status', '正在保存所属单位…'); sync();
    try {
      const data = await api('/api/profile', {method:'PATCH', body:{organization: normalized || null}, timeoutMs:15000});
      if (!alive(e) || !apply(data)) return;
      editing = false; text('profile-status', '所属单位已保存。');
    } catch (exc) {
      if (!alive(e) || authFailure(exc)) return;
      if (!exc.status || exc.status >= 500) {
        // An interrupted response can follow a committed write. Read authority once.
        busy = null; const restored = await load();
        if (alive(e) && restored) {
          editing = false;
          text('profile-status', profile.organization === (normalized || null) ? '已从服务器确认单位资料。' : '暂未确认保存结果，已读取服务器当前资料。请稍后刷新核对。');
        }
      } else { text('profile-status'); text('profile-error', errorMessage(exc)); }
    } finally { if (alive(e)) { busy = null; sync(); } }
  }
  function beginPhone(message = '请输入准备绑定的手机号，并使用当前账号密码确认身份。') {
    if (!profile || profile.phone_verified || busy) return;
    wipePhone(); clearErrors(); setPhase('phone', message); $('profile-phone').focus();
  }
  function expire(message = '身份确认已过期，请重新输入当前账号密码。') {
    const previous = target; wipePhone();
    if (previous) $('profile-phone').value = previous;
    setPhase('expired', message); $('profile-password').focus();
  }
  async function reauthenticate(event) {
    event.preventDefault(); if (busy || profile?.phone_verified) return;
    clearErrors(); const phone = phoneValue();
    if (!phone) { fieldError('profile-phone', '请输入受支持地区的手机号；无默认地区时请包含 +国家码。'); return; }
    const password = $('profile-password').value; $('profile-password').value = '';
    if (Array.from(password).length < 12 || Array.from(password).length > 256) { fieldError('profile-password', '请输入当前账号密码，长度为 12–256 个字符。'); return; }
    const e = epoch, r = revision; busy = 'reauthenticate'; setPhase('reauthenticating', '正在确认账号身份…');
    try {
      const data = await api('/api/profile/phone/reauthenticate', {method:'POST', body:{phone,password}, timeoutMs:20000});
      if (!alive(e) || r !== revision) return;
      if (!data.authorization || !Number.isFinite(data.expires_at) || data.expires_at * 1000 <= Date.now()) { expire(); return; }
      authorization = data.authorization; authorizedUntil = data.expires_at * 1000; target = phone;
      $('profile-phone').value = ''; text('profile-target', '准备绑定：***' + phone.slice(-4));
      setPhase('authorized', '身份确认成功。现在可以请求短信验证码。'); $('profile-send').focus();
    } catch (exc) {
      if (!alive(e) || r !== revision || authFailure(exc)) return;
      wipePhone(); $('profile-phone').value = phone; setPhase('reauth_required', '需要确认当前账号身份。');
      fieldError('profile-password', exc.code === 'reauthentication_required' ? '密码验证未通过，请核对当前账号密码。' : errorMessage(exc));
    } finally { if (alive(e)) { busy = null; $('profile-password').value = ''; sync(); if (phase === 'authorized') $('profile-send').focus(); else if (['expired','reauth_required'].includes(phase)) $('profile-password').focus(); } }
  }
  async function sendCode() {
    if (busy || !authorization || !target || Date.now() < cooldownUntil) return;
    if (Date.now() >= authorizedUntil) { expire(); return; }
    const e = epoch, r = revision; clearErrors(); busy = 'send'; sendNonce ||= nonce(); setPhase('sending', '正在请求验证码…');
    try {
      const data = await api('/api/profile/phone/send', {method:'POST', body:{phone:target,authorization,request_id:sendNonce}, timeoutMs:15000});
      if (!alive(e) || r !== revision) return;
      if (Date.now() >= authorizedUntil) { expire(); return; }
      challenge = data.verification_id; codeUntil = data.expires_at * 1000; sendNonce = null;
      cooldownUntil = Date.now() + config.cooldown * 1000; $('profile-code').value = '';
      setPhase('awaiting_code', '验证码发送请求已受理，不代表实际送达。请查看手机短信。'); $('profile-code').focus();
    } catch (exc) {
      if (!alive(e) || r !== revision || authFailure(exc)) return;
      if (exc.code === 'reauthentication_required') expire(errorMessage(exc));
      else {
        if (exc.status === 429) cooldownUntil = Date.now() + Math.max(1, exc.retryAfter || config.cooldown || 60) * 1000;
        setPhase('failed', errorMessage(exc));
      }
    } finally { if (alive(e)) { busy = null; sync(); if (phase === 'awaiting_code') $('profile-code').focus(); else if (phase === 'expired') $('profile-password').focus(); } }
  }
  async function recoverBinding(e = epoch) {
    busy = 'recovery'; setPhase('recovering', '正在向服务器查询绑定结果…');
    try {
      const data = await api('/api/profile', {timeoutMs:15000});
      if (!alive(e) || !apply(data)) return;
      if (data.phone_verified === true) text('profile-bind-status', '已从服务器确认手机号绑定成功。');
      else if (authorization && Date.now() >= authorizedUntil) expire();
      else setPhase('recovering', '服务器暂未显示绑定成功。可稍后重新查询，或核对验证码后安全重试；不要反复发送。');
    } catch (exc) {
      if (!alive(e) || authFailure(exc)) return;
      setPhase('recovering', '暂时无法确认绑定结果，请重新查询资料，不要重复创建绑定。');
    } finally { if (alive(e)) { busy = null; sync(); } }
  }
  async function confirm() {
    if (busy || !authorization || !challenge || !target) return;
    if (Date.now() >= authorizedUntil) { expire(); return; }
    clearErrors(); const code = $('profile-code').value;
    if (!new RegExp('^[0-9]{' + config.digits + '}$').test(code)) { fieldError('profile-code', '请输入 ' + config.digits + ' 位数字验证码。'); return; }
    const e = epoch, r = revision; busy = 'confirm'; setPhase('confirming', '正在确认绑定…');
    try {
      await api('/api/profile/phone/confirm', {method:'POST', body:{phone:target,authorization,verification_id:challenge,code}, timeoutMs:20000});
      if (!alive(e) || r !== revision) return;
      // Even a successful confirm is followed by the authoritative read.
      await recoverBinding(e);
    } catch (exc) {
      if (!alive(e) || r !== revision || authFailure(exc)) return;
      if (!exc.status || exc.status >= 500) await recoverBinding(e);
      else if (exc.code === 'reauthentication_required') expire(errorMessage(exc));
      else { setPhase('failed', '绑定未确认。'); fieldError('profile-code', errorMessage(exc)); }
    } finally { if (alive(e)) { busy = null; sync(); } }
  }
  function mount(dependencies) {
    api = dependencies.api; identity = dependencies.identity; showLogin = dependencies.showLogin;
    config = JSON.parse($('registration').dataset.config);
    $('profile-code').maxLength = config.digits;
    $('profile-open').addEventListener('click', open);
    $('profile-close').addEventListener('click', () => { clear(); (matchMedia('(max-width:760px)').matches ? $('menu-button') : $('profile-open')).focus(); });
    $('profile-dialog').addEventListener('close', () => { if (!$('profile-dialog').open) clear(); });
    $('profile-refresh').addEventListener('click', () => { editing = false; load(); }); $('profile-retry').addEventListener('click', load);
    $('profile-unit-edit').addEventListener('click', beginUnit); $('profile-unit-form').addEventListener('submit', saveUnit);
    $('profile-unit-cancel').addEventListener('click', () => { editing = false; $('profile-unit').value = ''; clearErrors(); sync(); $('profile-unit-edit').focus(); });
    $('profile-unit-clear').addEventListener('click', () => { $('profile-unit').value = ''; text('profile-status', '已清空输入，保存后生效。'); $('profile-unit').focus(); });
    $('profile-bind-start').addEventListener('click', () => beginPhone());
    $('profile-bind-restart').addEventListener('click', () => beginPhone()); $('profile-change-phone').addEventListener('click', () => beginPhone('目标手机号已改变，请重新确认账号身份。'));
    $('profile-reauth-form').addEventListener('submit', reauthenticate);
    $('profile-phone').addEventListener('input', () => { if (authorization || target || challenge) { const entered = $('profile-phone').value; wipePhone(); $('profile-phone').value = entered; setPhase('phone', '目标手机号已改变，请重新确认账号身份。'); } });
    $('profile-send').addEventListener('click', sendCode); $('profile-confirm').addEventListener('click', confirm);
    $('profile-check-result').addEventListener('click', () => recoverBinding());
    for (const id of ['profile-unit','profile-phone','profile-password','profile-code']) $(id).addEventListener('input', () => { $(id).removeAttribute('aria-invalid'); text(id + '-error'); });
    window.addEventListener('hashchange', () => { if (location.hash === '#profile') open(); else if ($('profile-dialog').open) clear(); });
    window.addEventListener('pagehide', clear);
    setInterval(() => {
      if (!$('profile-dialog').open) return;
      if (authorization) {
        const remaining = Math.max(0, Math.ceil((authorizedUntil - Date.now()) / 1000));
        text('profile-authorization', remaining ? '身份确认剩余 ' + remaining + ' 秒；有效性仍由服务器判断。' : '授权已到期，等待当前请求结果。');
        if (!remaining && !busy) expire();
      }
      if (challenge && codeUntil <= Date.now() && !busy) text('profile-bind-status', '验证码可能已过期，请重新请求。最终有效性由服务器判断。');
      sync();
    }, 1000);
  }
  return {mount, open, clear, session};
})();
