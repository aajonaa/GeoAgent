'use strict';
// Account presets initialize new custom connections; they are not model metadata.
(() => {
  const style = document.createElement('link');
  style.rel = 'stylesheet'; style.href = '/assets/defaults.css?v=20261004-defaults1m';
  document.head.append(style);
  const button = element('button', '', 'account-settings-button');
  button.type = 'button'; button.id = 'account-settings-button';
  button.setAttribute('aria-haspopup', 'dialog'); button.setAttribute('aria-controls', 'account-settings-dialog');
  const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  icon.setAttribute('viewBox', '0 0 24 24'); icon.setAttribute('aria-hidden', 'true');
  const lines = document.createElementNS(icon.namespaceURI, 'path');
  lines.setAttribute('d', 'M4 7h16M4 17h16');
  const top = document.createElementNS(icon.namespaceURI, 'circle');
  top.setAttribute('cx', '9'); top.setAttribute('cy', '7'); top.setAttribute('r', '3');
  const bottom = document.createElementNS(icon.namespaceURI, 'circle');
  bottom.setAttribute('cx', '15'); bottom.setAttribute('cy', '17'); bottom.setAttribute('r', '3');
  icon.append(lines, top, bottom); button.append(icon, element('span', '设置'));
  $('model-settings-button').after(button);

  const dialog = element('dialog', undefined, 'account-settings-dialog');
  dialog.id = 'account-settings-dialog'; dialog.setAttribute('aria-labelledby', 'account-settings-title');
  const form = element('form', undefined, 'account-settings-form');
  const header = element('header', undefined, 'account-settings-header');
  const titles = element('div');
  titles.append(element('p', 'ACCOUNT SETTINGS', 'account-settings-eyebrow'));
  const title = element('h2', '设置'); title.id = 'account-settings-title';
  titles.append(title, element('p', '默认模型参数', 'account-settings-subtitle'));
  const close = element('button', '关闭', 'account-settings-close'); close.type = 'button';
  header.append(titles, close);
  const intro = element('p', '按账号保存，重启后仍保留。以下默认值仅初始化新 API 连接；已有连接、内置 GeoGPT 和进行中的任务不会自动改变。', 'account-settings-intro');
  const fields = element('div', undefined, 'account-settings-grid');
  const field = (id, labelText) => {
    const wrap = element('div', undefined, 'account-settings-field');
    const label = element('label', labelText); label.htmlFor = id;
    const input = element('input'); input.id = id; bindTokenInput(input);
    input.inputMode = 'numeric'; input.required = true; input.autocomplete = 'off';
    input.setAttribute('aria-describedby', 'account-defaults-budget');
    wrap.append(label, input); fields.append(wrap); return input;
  };
  const windowInput = field('account-default-context', '默认上下文窗口（Tokens）');
  const outputInput = field('account-default-output', '默认最大输出（Tokens）');
  const budget = element('p', '', 'account-settings-budget');
  budget.id = 'account-defaults-budget'; budget.setAttribute('role', 'status'); budget.setAttribute('aria-live', 'polite');
  const note = element('p', '这是框架预设，不代表供应商支持的容量。请核对所用 API 的限制。最大输出是每次模型响应的上限，不是整个任务的总输出；输入预算会扣除输出和安全余量。', 'account-settings-note');
  const status = element('p', '', 'account-settings-status');
  status.id = 'account-defaults-status'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  const footer = element('footer', undefined, 'account-settings-footer');
  const reset = element('button', '恢复框架预设', 'account-settings-reset'); reset.type = 'button';
  const save = element('button', '保存默认值', 'account-settings-save'); save.type = 'submit';
  footer.append(reset, save); form.append(header, intro, fields, budget, note, status, footer);
  dialog.append(form); document.body.append(dialog);
  let current = null, busy = false, epoch = 0;
  function waiting(value) {
    busy = value;
    for (const control of [windowInput, outputInput, close, reset, save]) control.disabled = value;
    form.setAttribute('aria-busy', String(value));
  }
  function validate() {
    const windowTokens = parseTokenValue(windowInput.value), outputTokens = parseTokenValue(outputInput.value);
    windowInput.setCustomValidity(''); outputInput.setCustomValidity('');
    if (!Number.isSafeInteger(outputTokens) || outputTokens < 1) {
      outputInput.setCustomValidity('最大输出须为正整数 Token 数。');
      budget.textContent = '请填写正整数 Token 数。'; return false;
    }
    const safety = Math.max(1024, Math.ceil(windowTokens / 20));
    const available = windowTokens - outputTokens - safety;
    if (!Number.isSafeInteger(windowTokens) || windowTokens < 1 || available <= 0) {
      windowInput.setCustomValidity('上下文窗口须大于最大输出与安全余量之和。');
      budget.textContent = '输入预算不足，请调整上下文窗口或最大输出。'; return false;
    }
    budget.textContent = '可用输入约 ' + available.toLocaleString('zh-CN') + ' Token · 输出预留 ' +
      outputTokens.toLocaleString('zh-CN') + ' · 安全余量 ' + safety.toLocaleString('zh-CN');
    return true;
  }
  function fill(values) {
    windowInput.value = formatTokenValue(values.context_window_tokens);
    outputInput.value = formatTokenValue(values.max_output_tokens);
    validate();
  }
  for (const input of [windowInput, outputInput]) input.addEventListener('input', () => {
    status.textContent = ''; validate();
  });
  button.addEventListener('click', async () => {
    if (busy || !state.me) return;
    const version = ++epoch, uid = state.me.id;
    waiting(true); status.textContent = '';
    try {
      const result = await api('/api/settings/model-defaults');
      if (version !== epoch || state.me?.id !== uid) return;
      current = result; fill(result); dialog.showModal(); windowInput.focus();
    } catch (error) { if (version === epoch && state.me) notice(error.message); }
    finally { if (version === epoch) waiting(false); }
  });
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  reset.addEventListener('click', () => {
    fill({context_window_tokens:1000000, max_output_tokens:128000});
    status.textContent = '已填入框架预设，点击“保存默认值”后生效。';
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !current || !state.me || !validate() || !form.reportValidity()) return;
    const version = epoch, uid = state.me.id;
    waiting(true); status.textContent = '';
    try {
      const result = await api('/api/settings/model-defaults', {method:'PUT', body:{
        context_window_tokens:parseTokenValue(windowInput.value), max_output_tokens:parseTokenValue(outputInput.value),
        revision:current.revision}});
      if (version !== epoch || state.me?.id !== uid) return;
      current = result; fill(result);
      status.textContent = '已保存到你的账号。新 API 连接将使用这些初始参数；已有配置未改变。';
      window.dispatchEvent(new CustomEvent('geoagent:defaults-updated'));
    } catch (error) { if (version === epoch && state.me) status.textContent = error.message; }
    finally { if (version === epoch) waiting(false); }
  });
  window.GeoAgentDefaults = {clear() {
    epoch++; current = null; waiting(false); dialog.close();
    windowInput.value = ''; outputInput.value = ''; budget.textContent = ''; status.textContent = '';
  }};
})();
