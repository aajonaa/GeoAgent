'use strict';
const $ = id => document.getElementById(id);
const state = {me: null, cid: null, view: 0, runs: new Map(), sources: new Map(), busy: null};
let invitation = new URLSearchParams(location.hash.slice(1)).get('join');
if (invitation) {
  history.replaceState(null, '', location.pathname);
  $('auth-title').textContent = '加入研究组'; $('auth-hint').textContent = '创建你的个人账号。邀请仅限使用一次，注册后为普通成员。';
  $('auth-submit').textContent = '创建账号'; $('password').autocomplete = 'new-password';
}
function element(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
async function api(path, options = {}) {
  const headers = {...options.headers};
  if (options.method && options.method !== 'GET' && state.me) headers['X-CSRF-Token'] = state.me.csrf;
  if (options.body && typeof options.body === 'object' && !(options.body instanceof File)) { headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(options.body); }
  const response = await fetch(path, {...options, headers, credentials: 'same-origin'});
  let result; try { result = await response.json(); } catch { result = {}; }
  if (!response.ok) { if (response.status === 401 && state.me) showLogin(); throw new Error(result.detail || `HTTP ${response.status}`); }
  return result;
}
function showLogin() { window.GeoAgentImages?.clear(); stopRunElapsedClock(); state.runs.clear(); window.GeoToolLibrary?.reset(); window.GeoToolHITL?.reset(); state.view++; state.cid = null; state.me = null; modelSettings = null; $('model-token').value = ''; $('model-dialog').close(); for (const source of state.sources.values()) source.close(); state.sources.clear(); $('app').hidden = true; $('auth-screen').hidden = false; }
function notice(message = '') { $('notice').textContent = message; }
function inline(node, text) {
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\$\$[^\n]+?\$\$|\\\[[^\n]+?\\\]|\$[^$\n]+\$|\\\([^\n]+?\\\))/g; let index = 0;
  for (const match of text.matchAll(pattern)) {
    node.append(document.createTextNode(text.slice(index, match.index)));
    const token = match[0];
    if (token.startsWith('`')) node.append(element('code', token.slice(1, -1)));
    else if (token.startsWith('**')) node.append(element('strong', token.slice(2, -2)));
    else {
      const span = element('span');
      const display = token.startsWith('$$') || token.startsWith('\\[');
      const math = token.startsWith('$') && !display ? token.slice(1, -1) : token.slice(2, -2);
      if (window.katex) window.katex.render(math, span, {output:'mathml', displayMode:display, throwOnError:false, trust:false});
      else span.textContent = token;
      node.append(span);
    }
    index = match.index + token.length;
  }
  node.append(document.createTextNode(text.slice(index)));
}
function markdown(target, text) {
  target.replaceChildren(); const lines = String(text || '').split('\n'); let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (line.trim().startsWith('```')) { const code = []; i++; while (i < lines.length && !lines[i].trim().startsWith('```')) code.push(lines[i++]); const pre = element('pre'); pre.append(element('code', code.join('\n'))); target.append(pre); i++; continue; }
    const trimmed = line.trim(), opening = trimmed.startsWith('$$') ? '$$' : trimmed.startsWith('\\[') ? '\\[' : null;
    if (opening) {
      const closing = opening === '$$' ? '$$' : '\\]', math = []; let cursor = i, rest = trimmed.slice(opening.length), closed = false, suffix = '';
      while (cursor < lines.length) {
        const at = rest.indexOf(closing);
        if (at >= 0) { math.push(rest.slice(0, at)); suffix = rest.slice(at + closing.length); closed = true; break; }
        math.push(rest); cursor++; rest = lines[cursor] || '';
      }
      if (closed) {
        const block = element('div');
        if (window.katex) window.katex.render(math.join('\n').trim(), block, {output:'mathml', displayMode:true, throwOnError:false, trust:false});
        else block.textContent = lines.slice(i, cursor + 1).join('\n');
        target.append(block);
        if (suffix.trim()) { const p = element('p'); inline(p, suffix); target.append(p); }
        i = cursor + 1; continue;
      }
    }
    if (i + 1 < lines.length && line.includes('|') && /^\s*\|?\s*:?-+/.test(lines[i + 1]) && lines[i + 1].includes('|')) {
      const table = element('table'); const split = value => value.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(v => v.trim());
      const head = element('thead'), row = element('tr'); for (const value of split(line)) { const cell = element('th'); inline(cell, value); row.append(cell); } head.append(row); table.append(head); i += 2;
      const body = element('tbody'); while (i < lines.length && lines[i].includes('|') && lines[i].trim()) { const row = element('tr'); for (const value of split(lines[i++])) { const cell = element('td'); inline(cell, value); row.append(cell); } body.append(row); } table.append(body); const scroll = element('div', undefined, 'table-scroll'); scroll.append(table); target.append(scroll); continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line); if (heading) { const h = element('h' + heading[1].length); inline(h, heading[2]); target.append(h); i++; continue; }
    if (/^\s*(?:[-*]|\d+\.)\s+/.test(line)) { const list = element(/^\s*\d+\./.test(line) ? 'ol' : 'ul'); while (i < lines.length && /^\s*(?:[-*]|\d+\.)\s+/.test(lines[i])) { const li = element('li'); inline(li, lines[i++].replace(/^\s*(?:[-*]|\d+\.)\s+/, '')); list.append(li); } target.append(list); continue; }
    const p = element('p'); inline(p, line); target.append(p); i++;
  }
}
async function initialize() {
  state.me = await api('/api/me'); $('auth-screen').hidden = true; $('app').hidden = false;
  $('account-name').textContent = state.me.username; $('account-role').textContent = state.me.role === 'admin' ? '管理员' : '成员';
  $('invite-button').hidden = state.me.role !== 'admin';
  $('connection').title = `${state.me.release}\n${state.me.execution}`;
  $('execution-note').textContent = state.me.isolated ? '系统沙箱已启用。' : '受信任研究组模式：未启用系统沙箱。生成代码使用服务账号权限执行，请勿向不可信成员开放。';
  await loadModelSettings();
  await loadConversations();
}
$('auth-form').addEventListener('submit', async event => {
  event.preventDefault(); $('auth-error').textContent = ''; $('auth-submit').disabled = true;
  try { const credentials = {username: $('username').value.trim(), password: $('password').value};
    if (invitation) { await api('/api/register', {method:'POST', body:{...credentials, invite:invitation}}); invitation = null; }
    await api('/api/login', {method:'POST', body:credentials}); $('password').value = ''; await initialize();
  } catch (error) { $('auth-error').textContent = error.message; } finally { $('auth-submit').disabled = false; }
});
async function loadConversations() {
  const conversations = await api('/api/conversations'); $('conversation-list').replaceChildren();
  for (const conversation of conversations) { const button = element('button', conversation.title, conversation.id === state.cid ? 'selected' : ''); button.title = conversation.title; button.addEventListener('click', () => openConversation(conversation.id).catch(e => notice(e.message))); $('conversation-list').append(button); }
}
function closeStreams() { stopRunElapsedClock(); for (const source of state.sources.values()) source.close(); state.sources.clear(); }
function busy(rid) { state.busy = rid; $('send').disabled = Boolean(rid); $('stop').hidden = !rid; $('attach').disabled = Boolean(rid); $('upload-button').disabled = Boolean(rid); window.GeoToolHITL?.syncComposer(); }
async function openConversation(cid) {
  window.GeoToolLibrary?.close({focus:false});
  window.GeoAgentImages?.clear(); closeStreams(); state.cid = cid; const view = ++state.view; state.runs.clear(); $('messages').replaceChildren(); notice(); busy(null);
  window.GeoToolHITL?.selectConversation(cid);
  const conversation = await api(`/api/conversations/${cid}`); if (state.cid !== cid || state.view !== view) return; $('chat-title').textContent = conversation.title;
  for (const run of conversation.runs) { renderRun(run); subscribe(run.id); if (['running','stopping'].includes(run.status)) busy(run.id); }
  $('sidebar').classList.remove('open'); await Promise.all([loadConversations(), loadFiles()]); scrollEnd();
}
async function ensureConversation() { if (!state.cid) { const conversation = await api('/api/conversations', {method:'POST'}); await openConversation(conversation.id); } return state.cid; }
$('new-chat').addEventListener('click', async () => { try { const conversation = await api('/api/conversations', {method:'POST'}); await openConversation(conversation.id); $('prompt').focus(); } catch (e) { notice(e.message); } });
function scrollEnd() { $('messages').scrollTop = $('messages').scrollHeight; }
// One clock for the visible conversation. Durations come from the server;
// performance.now() advances the display without relying on the browser's wall clock.
let runElapsedClock = null;
function runIsWorking(status) { return status === 'running' || status === 'stopping'; }
function stopRunElapsedClock() { if (runElapsedClock !== null) clearInterval(runElapsedClock); runElapsedClock = null; }
function elapsedSeconds(ui) {
  return ui.elapsedBase + (runIsWorking(ui.status) ? Math.max(0, performance.now() - ui.elapsedAnchor) / 1000 : 0);
}
function paintRunElapsed(ui) {
  ui.elapsed.hidden = !ui.elapsedKnown;
  if (!ui.elapsedKnown) return;
  const seconds = Math.max(0, Math.floor(elapsedSeconds(ui)));
  const prefix = runIsWorking(ui.status) ? 'Working for' : ui.status === 'completed' ? 'Worked for'
    : ui.status === 'needs_input' ? 'Paused after' : ui.status === 'stopped' ? 'Stopped after' : 'Ended after';
  const text = `${prefix} ${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  if (ui.elapsed.textContent !== text) ui.elapsed.textContent = text;
  ui.elapsed.dataset.state = runIsWorking(ui.status) ? 'working' : 'finished';
}
function syncRunElapsedClock() {
  const working = [...state.runs.values()].some(ui => runIsWorking(ui.status));
  if (!working) { stopRunElapsedClock(); return; }
  if (runElapsedClock === null) runElapsedClock = setInterval(() => {
    for (const ui of state.runs.values()) if (runIsWorking(ui.status)) paintRunElapsed(ui);
  }, 1000);
}
function setRunElapsed(ui, run) {
  const measured = typeof run.elapsed_seconds === 'number' && Number.isFinite(run.elapsed_seconds);
  const elapsed = measured ? Math.max(0, run.elapsed_seconds) : elapsedSeconds(ui);
  ui.status = run.status || ui.status;
  ui.elapsedBase = elapsed;
  ui.elapsedAnchor = performance.now();
  ui.elapsedKnown = ui.elapsedKnown || measured;
  paintRunElapsed(ui);
  syncRunElapsedClock();
}
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) for (const ui of state.runs.values()) paintRunElapsed(ui);
});
function renderRun(run) {
  const turn = element('article', undefined, 'turn'); turn.dataset.run = run.id;
  const user = element('div', run.query, 'user-message'); const label = element('div', 'GeoAgent', 'assistant-label');
  const activity = element('details', undefined, 'activity'); const summary = element('summary', run.status === 'running' ? '任务启动中…' : '查看执行记录'); const list = element('div', undefined, 'tool-list'); activity.append(summary, list);
  const answer = element('div', undefined, 'answer'); markdown(answer, run.answer); const reason = element('div', run.reason || '', 'run-reason');
  const elapsed = element('div', undefined, 'run-elapsed');
  elapsed.setAttribute('role', 'timer'); elapsed.setAttribute('aria-live', 'off');
  elapsed.title = 'Elapsed time for this run, including model, tool and review time. Waiting for a human reply is excluded.';
  turn.append(user, label, elapsed, activity, answer, reason); $('messages').append(turn);
  const ui = {elapsed, elapsedBase:0, elapsedAnchor:performance.now(), elapsedKnown:runIsWorking(run.status), status:run.status, turn, activity, summary, list, answer, reason, tools:new Map(), finished:!['running','stopping'].includes(run.status)}; state.runs.set(run.id, ui); setRunElapsed(ui, run); window.GeoToolHITL?.attachCards(); return ui;
}
const statusText = {'Model is working':'模型正在处理','Starting an isolated task environment':'正在启动独立任务环境','GeoGPT is working':'GeoGPT 正在处理','Preparing answer':'正在整理答复','Checking the result':'正在检查结果','Correcting the result':'正在修正结果','Correcting a model response':'正在修正模型响应','Retrying the completion check':'正在重新检查完成情况'};
statusText['Running in the service account environment (OS isolation disabled)'] = '正在服务账号环境中运行（未启用系统沙箱）';
statusText['Compacting context'] = '正在压缩历史上下文';
const toolNames = {skill_find:'查找相关技能', skill_load:'读取技能说明', read_file:'读取文件', write_file:'写入文件', execute_python:'执行 Python', GeoMagnitudeToEnergy:'估算地震能量'};
function handleEvent(rid, data) {
  const ui = state.runs.get(rid); if (!ui) return;
  const wasNearEnd = $('messages').scrollHeight - $('messages').scrollTop - $('messages').clientHeight < 130;
  if (data.kind === 'model_config') { ui.turn.querySelector('.assistant-label').textContent = 'GeoAgent · ' + data.profile.model; }
  if (data.kind === 'status' && !ui.finished) ui.summary.textContent = (statusText[data.message] || data.message) + (data.turn ? ` · 第 ${data.turn} 次模型调用` : '');
  if (data.kind === 'context_compacted') {
    const line = element('div', `上下文已压缩：${data.before_chars.toLocaleString()} → ${data.after_chars.toLocaleString()} 字符；原始记录和工具证据保留`, 'tool-status');
    ui.list.append(line);
  }
  if (data.kind === 'tool_start') {
    let card = ui.tools.get(data.id); if (!card) { const details = element('details', undefined, 'tool-card'), summary = element('summary'), title = element('span', toolNames[data.name] || data.name), status = element('span', '执行中', 'tool-status'), input = element('pre'); summary.append(title, status); details.append(summary, input); ui.list.append(details); card = {details,status,input}; ui.tools.set(data.id,card); }
    card.input.textContent = JSON.stringify({tool:data.name, arguments:data.arguments}, null, 2);
  }
  if (data.kind === 'tool_result') {
    const card = ui.tools.get(data.id); if (card) { card.status.textContent = data.result.status === 'ok' ? '已完成' : '发生错误'; if (!card.output) { card.output = element('pre'); card.details.append(card.output); } card.output.textContent = JSON.stringify(data.result, null, 2); }
  }
  if (data.kind === 'finished') {
    setRunElapsed(ui, data); ui.finished = true; markdown(ui.answer, data.answer); ui.summary.textContent = `${data.status === 'completed' ? '已完成' : data.status === 'needs_input' ? '需要补充信息' : data.status === 'stopped' ? '已停止' : '未完成'} · ${ui.tools.size} 次工具调用${data.turns ? ` · ${data.turns} 次模型调用` : ''}`; ui.reason.textContent = data.reason || '';
    const source = state.sources.get(rid); if (source) source.close(); state.sources.delete(rid); if (state.busy === rid) busy(null); window.GeoToolHITL?.refresh(data.status === 'needs_input'); loadFiles().catch(e => notice(e.message)); loadConversations().catch(e => notice(e.message));
  }
  if (wasNearEnd) scrollEnd();
}
function subscribe(rid) {
  const cid = state.cid, source = new EventSource(`/api/runs/${rid}/events`); state.sources.set(rid,source);
  // New submissions initially contain only an ID; recover authoritative timing
  // once, not by polling every second. Historical runs already include timing.
  const ui = state.runs.get(rid);
  if (ui && runIsWorking(ui.status)) api(`/api/runs/${rid}`).then(run => {
    if (state.cid !== cid || state.sources.get(rid) !== source || state.runs.get(rid) !== ui || ui.finished) return;
    if (!runIsWorking(run.status)) handleEvent(rid, {kind:'finished', ...run});
    else setRunElapsed(ui, run);
  }).catch(() => { /* The SSE reconnect path owns connection errors. */ });
  source.onmessage = event => { if (state.cid !== cid || state.sources.get(rid) !== source) return; try { handleEvent(rid,JSON.parse(event.data)); $('connection').textContent = '已连接'; } catch { notice('事件显示失败，请重新打开这段对话。'); } };
  source.onerror = async () => { if (state.cid !== cid || state.sources.get(rid) !== source) return; $('connection').textContent = '正在重连'; try { const run = await api(`/api/runs/${rid}`); if (state.cid !== cid || state.sources.get(rid) !== source) return; if (!['running','stopping'].includes(run.status)) { handleEvent(rid,{kind:'finished',...run}); } } catch (e) { source.close(); state.sources.delete(rid); notice(e.message); } };
}
$('composer').addEventListener('submit', async event => {
  event.preventDefault(); if (state.busy || window.GeoToolHITL?.blocksComposer()) return; const query = $('prompt').value.trim(); if (!query) return; $('send').disabled = true; notice();
  try { const cid = await ensureConversation(); const run = await api(`/api/conversations/${cid}/runs`, {method:'POST',body:{query}}); $('prompt').value=''; renderRun({id:run.id,query,status:'running',answer:''}); busy(run.id); subscribe(run.id); await loadConversations(); scrollEnd(); } catch (e) { notice(e.message); $('send').disabled = false; }
});
$('prompt').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('composer').requestSubmit(); } });
$('stop').addEventListener('click', async () => { if (!state.busy) return; try { await api(`/api/runs/${state.busy}/stop`,{method:'POST'}); notice('正在停止任务。最近已保存的文件会保留。'); } catch(e) { notice(e.message); } });
for (const button of document.querySelectorAll('[data-prompt]')) button.addEventListener('click', () => { $('prompt').value=button.dataset.prompt; $('prompt').focus(); });
async function loadFiles() {
  $('files-list').replaceChildren(); if (!state.cid) { $('file-count').textContent='0'; return; }
  const cid=state.cid, result=await api(`/api/conversations/${cid}/files`); if (state.cid!==cid) return; $('file-count').textContent=String(result.files.length);
  for (const file of result.files) { const item=element('div',undefined,'file-item'), link=element('a',file.name); link.href=`/api/conversations/${cid}/download?name=${encodeURIComponent(file.name)}&generation=${encodeURIComponent(result.generation)}`; link.setAttribute('download',file.name.split('/').pop()); item.append(link,element('small',`${(file.bytes/1024).toFixed(1)} KiB · SHA-256 ${file.sha256.slice(0,12)}`)); $('files-list').append(item); }
  if (!result.files.length) $('files-list').append(element('p','尚无文件。可添加材料，或让 Agent 生成文件。','muted'));
  window.GeoAgentImages?.render(result, cid);
}
for (const id of ['attach','upload-button']) $(id).addEventListener('click',()=>$('upload').click());
$('upload').addEventListener('change',async()=>{const file=$('upload').files[0]; if(!file)return; try{const cid=await ensureConversation();await api(`/api/conversations/${cid}/upload?name=${encodeURIComponent(file.name)}`,{method:'POST',body:file,headers:{'Content-Type':'application/octet-stream'}}); await loadFiles(); $('files-panel').hidden=false; notice('文件已加入当前对话。');}catch(e){notice(e.message);}finally{$('upload').value='';}});
$('files-toggle').addEventListener('click',()=>{$('files-panel').hidden=!$('files-panel').hidden;}); $('files-close').addEventListener('click',()=>{$('files-panel').hidden=true;});
$('menu-button').addEventListener('click',()=>$('sidebar').classList.toggle('open'));
$('logout').addEventListener('click',async()=>{try{await api('/api/logout',{method:'POST'});location.reload();}catch(e){notice(e.message);}});
let dialogAction=null;
function dialog(title){$('dialog-title').textContent=title;$('dialog-body').replaceChildren();$('dialog-error').textContent='';$('dialog-submit').hidden=false;$('account-dialog').showModal();}
$('dialog-close').addEventListener('click',()=>$('account-dialog').close());
$('password-button').addEventListener('click',()=>{dialog('修改密码');for(const [id,label] of [['old-password','当前密码'],['new-password','新密码（至少 12 个字符）']]){const wrap=element('label',label),input=element('input');input.type='password';input.id=id;input.required=true;input.minLength=12;input.maxLength=256;input.autocomplete=id==='old-password'?'current-password':'new-password';wrap.append(input);$('dialog-body').append(wrap);}dialogAction=async()=>{await api('/api/password',{method:'POST',body:{old:$('old-password').value,new:$('new-password').value}});location.reload();};});
$('invite-button').addEventListener('click',async()=>{dialog('邀请研究组成员');$('dialog-submit').hidden=true;$('dialog-body').append(element('p','邀请 24 小时内有效，仅可使用一次。新成员自动获得普通用户权限。'));try{const result=await api('/api/admin/invites',{method:'POST'}),input=element('input');input.readOnly=true;input.value=location.origin+'/#join='+result.token;input.setAttribute('aria-label','邀请链接');input.addEventListener('click',()=>input.select());$('dialog-body').append(input);dialogAction=null;}catch(e){$('dialog-error').textContent=e.message;}});
$('account-form').addEventListener('submit',async event=>{event.preventDefault();if(!dialogAction)return;try{await dialogAction();}catch(e){$('dialog-error').textContent=e.message;}});
let modelSettings = null, modelPending = false, modelEditing = null, modelSelection = '', modelDraftBaseline = '';
async function loadModelSettings() {
  modelSettings = await api('/api/model-settings');
  const label = modelSettings.source === 'builtin' ? 'GeoGPT' : modelSettings.name || modelSettings.model;
  $('model-settings-button').textContent = '模型：' + label;
  $('model-settings-button').title = modelSettings.model + '\n' + modelSettings.base_url;
  if (modelSettings.storage_error) notice('已保存的模型配置不可用，请恢复服务器密钥，或在模型配置中清除损坏的数据。');
}
function modelSavedProfiles() { return modelSettings?.saved_profiles || []; }
function modelPayload() {
  if ($('model-source').value === 'builtin') return {source:'builtin'};
  const keep = $('model-keep-token').checked && !$('model-token').value;
  const payload = {source:'custom', name:$('model-profile-name').value.trim(),
    base_url:$('model-base-url').value.trim(), model:$('model-id').value.trim(),
    api_token:$('model-token').value, keep_token:keep, remember:$('model-remember').checked};
  if (modelEditing?.profile_id) { payload.profile_id = modelEditing.profile_id; payload.revision = modelEditing.revision; }
  return payload;
}
function modelDirty() { return modelDraftBaseline && JSON.stringify(modelPayload()) !== modelDraftBaseline; }
function modelControls() {
  const custom = $('model-source').value === 'custom';
  $('custom-model-fields').hidden = !custom;
  $('custom-model-fields').disabled = !custom || modelPending;
  for (const id of ['model-base-url','model-id','model-profile-name']) $(id).required = custom;
  $('builtin-model-note').hidden = custom;
  $('model-clear').hidden = !modelEditing?.profile_id && !modelSettings?.storage_error;
  $('model-clear').textContent = modelSettings?.storage_error ? '清除损坏的全部配置' : '删除这份配置';
  $('model-save').textContent = !custom || (modelEditing?.profile_id && !modelDirty()) ? '使用此配置' : '保存并使用';
}
function modelOptions() {
  const select = $('model-profile-select');
  select.replaceChildren();
  const add = (value, label) => { const option = element('option', label); option.value = value; select.append(option); };
  add('builtin', '内置 GeoGPT');
  for (const profile of modelSavedProfiles()) add(profile.profile_id,
    profile.name + ' · ' + profile.model + (profile.profile_id === modelSettings.profile_id ? '（当前）' : ''));
  if (modelSettings.source === 'custom' && !modelSettings.profile_id) add('session', '本次登录的临时配置');
  add('new', '新增 API 配置…');
  $('model-profile-count').textContent = modelSavedProfiles().length + ' 份已保存连接';
  $('model-active-label').textContent = '当前使用：' + (modelSettings.source === 'builtin' ? '内置 GeoGPT' : modelSettings.name || modelSettings.model);
}
function modelFill(selection) {
  let profile;
  if (selection === 'builtin') profile = {...modelSettings.builtin, source:'builtin'};
  else if (selection === 'new') profile = {source:'custom', base_url:'', model:'', name:'', has_token:false};
  else if (selection === 'session') profile = modelSettings;
  else profile = modelSavedProfiles().find(item => item.profile_id === selection);
  if (!profile) throw new Error('这份配置已不存在，请重新打开模型配置。');
  modelEditing = profile; modelSelection = selection; $('model-profile-select').value = selection;
  $('model-source').value = profile.source;
  $('model-profile-name').value = profile.name || '';
  $('model-base-url').value = profile.source === 'custom' ? profile.base_url : '';
  $('model-id').value = profile.source === 'custom' ? profile.model : '';
  $('model-token').value = '';
  $('model-keep-wrap').hidden = !profile.has_token;
  $('model-keep-token').checked = Boolean(profile.has_token);
  $('model-remember').checked = selection !== 'session';
  $('builtin-model-note').textContent = modelSettings.builtin.model + ' · 使用研究组已有服务。切换到这里不会删除已保存的 API 配置。';
  $('model-storage-status').textContent = modelSettings.storage_error
    ? '保存的数据无法安全解密。请恢复服务器密钥；清除全部配置仅用于无法恢复时的显式重置。'
    : selection === 'new' ? '新增会保留已有连接。选择一个容易辨认的名称，例如“供应商 A · 日常”。'
    : selection === 'session' ? '这份配置仅在本次登录有效。勾选记住配置可另存到账号。'
    : profile.profile_id ? '编辑只更新这一份配置；切换、重启和重新登录都不会删除其他连接。'
    : '使用内置模型时，其他已保存连接仍可随时切换回来。';
  $('model-error').textContent = ''; $('model-test-result').textContent = '';
  modelDraftBaseline = JSON.stringify(modelPayload()); modelControls();
}
function modelChoose(selection) {
  if (modelDirty() && !window.confirm('当前表单的修改尚未保存。放弃这些草稿修改并切换？已保存的连接不会被删除。')) {
    $('model-profile-select').value = modelSelection; return;
  }
  modelFill(selection);
  if (selection === 'new') $('model-profile-name').focus();
}
function modelWaiting(wait) {
  modelPending = wait;
  for (const id of ['model-profile-select','model-new','model-profile-name','model-source','model-base-url','model-id',
      'model-token','model-keep-token','model-remember','model-clear','model-test','model-save','model-close']) $(id).disabled = wait;
  modelControls();
}
$('model-settings-button').addEventListener('click', async () => {
  try {
    await loadModelSettings(); modelOptions();
    modelFill(modelSettings.source === 'builtin' ? 'builtin' : modelSettings.profile_id || 'session');
    $('model-dialog').showModal();
  } catch (error) { notice(error.message); }
});
$('model-profile-select').addEventListener('change', () => modelChoose($('model-profile-select').value));
$('model-new').addEventListener('click', () => modelChoose('new'));
$('model-base-url').addEventListener('input', () => {
  if ($('model-base-url').value.trim().replace(/\/+$/, '') !== modelEditing?.base_url) $('model-keep-token').checked = false;
  $('model-test-result').textContent = ''; modelControls();
});
$('model-token').addEventListener('input', () => {
  if ($('model-token').value) $('model-keep-token').checked = false;
  $('model-test-result').textContent = ''; modelControls();
});
for (const id of ['model-id','model-profile-name','model-remember','model-keep-token']) {
  $(id).addEventListener(id === 'model-id' || id === 'model-profile-name' ? 'input' : 'change', () => {
    $('model-test-result').textContent = ''; modelControls();
  });
}
$('model-close').addEventListener('click', () => $('model-dialog').close());
$('model-dialog').addEventListener('cancel', event => { if (modelPending) event.preventDefault(); });
$('model-dialog').addEventListener('close', () => {
  $('model-token').value = ''; $('model-keep-token').checked = false;
  modelEditing = null; modelDraftBaseline = '';
});
$('model-form').addEventListener('submit', async event => {
  event.preventDefault(); if (modelPending) return;
  const data = modelPayload(), activateOnly = data.source === 'builtin' || (modelEditing?.profile_id && !modelDirty());
  modelWaiting(true); $('model-error').textContent = '';
  try {
    if (activateOnly) await api('/api/model-settings/activate', {method:'POST', body:{profile_id:data.source === 'builtin' ? null : modelEditing.profile_id}});
    else await api('/api/model-settings', {method:'PUT', body:data});
    await loadModelSettings(); $('model-dialog').close();
    notice((activateOnly ? '已切换模型。' : modelSettings.storage === 'account_encrypted'
      ? '这份连接已按账号加密保存。' : '已应用临时配置，仅用于本次登录。') +
      ' 其他已保存连接未删除；正在运行的任务保持原配置。');
  } catch (error) { $('model-error').textContent = error.message; }
  finally { modelWaiting(false); }
});
$('model-clear').addEventListener('click', async () => {
  if (modelPending) return;
  const broken = Boolean(modelSettings.storage_error), profile = modelEditing;
  if (!broken && !profile?.profile_id) return;
  const question = broken ? '无法解密的全部账号模型配置将被清除，之后需要重新输入。确认重置？'
    : '删除“' + profile.name + '”及其保存的 Token？其他配置不会被删除；正在运行的任务不受影响。';
  if (!window.confirm(question)) return;
  modelWaiting(true); $('model-error').textContent = '';
  try {
    if (broken) await api('/api/model-settings', {method:'DELETE'});
    else await api('/api/model-settings/profiles/' + encodeURIComponent(profile.profile_id),
      {method:'DELETE', body:{revision:profile.revision}});
    await loadModelSettings(); modelOptions();
    modelFill(modelSettings.source === 'builtin' ? 'builtin' : modelSettings.profile_id || 'session');
    $('model-storage-status').textContent = broken ? '已清除损坏配置。' : '已删除所选连接，其他配置已保留。';
  } catch (error) { $('model-error').textContent = error.message; }
  finally { modelWaiting(false); }
});
$('model-test').addEventListener('click', async () => {
  if (modelPending || !$('model-form').reportValidity()) return;
  const data = modelPayload(); modelWaiting(true); $('model-error').textContent = '';
  $('model-test-result').textContent = '正在检查基础原生调用，以及模型是否读取工具回传值…';
  try {
    const response = await fetch('/api/model-settings/test', {method:'POST', credentials:'same-origin',
      headers:{'Content-Type':'application/json','X-CSRF-Token':state.me.csrf}, body:JSON.stringify(data)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || result.detail || '连接测试失败');
    $('model-test-result').textContent = '基础协议测试通过（非流式）：原生调用、JSON 参数及随机回传值均通过。尚未验收真实多工具任务或流式调用，不代表完整 Agent 兼容。测试不会保存或切换配置。';
  } catch (error) { $('model-test-result').textContent = ''; $('model-error').textContent = error.message; }
  finally { modelWaiting(false); }
});
if (!invitation) initialize().catch(()=>showLogin());
