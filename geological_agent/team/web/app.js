'use strict';
const $ = id => document.getElementById(id);
const AGENT_NAME = 'OreBOGAO';
const state = {me: null, cid: null, view: 0, runs: new Map(), sources: new Map(), busy: null, activeTasks: [], inputRequests: []};
function element(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
async function api(path, options = {}) {
  const {timeoutMs, ...fetchOptions} = options; options = fetchOptions;
  const controller = timeoutMs ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  if (controller) options.signal = controller.signal;
  const headers = {...options.headers};
  const mutation = options.method && !['GET', 'HEAD', 'OPTIONS'].includes(options.method.toUpperCase());
  const identity = state.me ? {id: state.me.id, role: state.me.role} : null;
  if (mutation && identity) headers['X-CSRF-Token'] = state.me.csrf;
  if (options.body && typeof options.body === 'object' && !(options.body instanceof File)) { headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(options.body); }
  let response, result;
  try {
    for (let attempt = 0; attempt < 2; attempt++) {
      response = await fetch(path, {...options, headers, credentials: 'same-origin'});
      try { result = await response.json(); } catch (error) { if (error.name === 'AbortError') throw error; result = {}; }
      if (attempt !== 0 || !mutation || !identity || response.status !== 403 || result.detail !== 'CSRF validation failed') break;
      // Another tab can replace the shared Cookie while this page retains its
      // old CSRF. The rejected request has not entered its mutation handler.
      const current = await api('/api/me', {timeoutMs: Math.min(timeoutMs || 10000, 10000)});
      if (!state.me || state.me.id !== identity.id || state.me.role !== identity.role || current.id !== identity.id || current.role !== identity.role) {
        const error = new Error('登录账号或权限已在其他页面变化，请重新登录后操作。');
        error.status = 409; error.code = 'account_changed';
        showLogin(); $('auth-error').textContent = error.message; throw error;
      }
      if (typeof current.csrf !== 'string' || !current.csrf || current.csrf === headers['X-CSRF-Token']) break;
      state.me = current; headers['X-CSRF-Token'] = current.csrf;
    }
  } finally { if (timer) clearTimeout(timer); }
  if (!response.ok) { if (response.status === 401 && state.me) showLogin(); const error = new Error(result.detail === 'CSRF validation failed' ? '登录校验未通过，请刷新页面后重试。' : result.detail || `HTTP ${response.status}`); error.status = response.status; error.code = result.code; error.activeConversation = response.headers.get('X-Active-Conversation'); error.retryAfter = Number(response.headers.get('Retry-After')) || null; throw error; }
  return result;
}
function showLogin() { $('admin-releases-dialog').close(); $('admin-releases-open').hidden = true; $('admin-releases-content').replaceChildren(); $('auth-submit').disabled = false; window.OreSageEmail?.showLogin(); window.OreSageProfile?.clear(); window.OreSagePassword?.clear(); window.OreSageAdminUsers?.clear(); window.OreSageAdminUsage?.clear(); window.OreSageSharedKnowledge?.clear(); window.GeoAgentCases?.clear(); window.GeoAgentDefaults?.clear(); window.GeoAgentImages?.clear(); window.OreSageDrafts?.reset(); stopRunElapsedClock(); submissionFeedback(); state.runs.clear(); state.activeTasks = []; state.inputRequests = []; renderGlobalTask(); window.GeoToolLibrary?.reset(); window.GeoToolHITL?.reset(); state.view++; state.cid = null; state.me = null; modelSettings = null; $('model-token').value = ''; $('model-dialog').close(); for (const source of state.sources.values()) source.close(); state.sources.clear(); $('app').hidden = true; $('auth-screen').hidden = false; }
function notice(message = '') { $('notice').textContent = message; }
function submissionFeedback(message = '', conversationId = '') {
  const box = $('submission-feedback'), label = $('submission-status'), open = $('active-task-open');
  box.hidden = !message;
  label.textContent = message;
  open.hidden = !/^[a-f0-9]{32}$/.test(conversationId);
  open.dataset.conversation = open.hidden ? '' : conversationId;
}
$('active-task-open').addEventListener('click', async () => {
  const cid = $('active-task-open').dataset.conversation;
  if (!cid) return;
  submissionFeedback();
  try {
    await openConversation(cid);
  } catch (error) {
    submissionFeedback('暂时无法打开正在执行的任务，请重试。', cid);
  }
});
function taskElapsed(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  if (value < 60) return value + ' 秒';
  if (value < 3600) return Math.floor(value / 60) + ' 分 ' + value % 60 + ' 秒';
  return Math.floor(value / 3600) + ' 小时 ' + Math.floor(value % 3600 / 60) + ' 分';
}
function renderGlobalTask() {
  const box = $('global-task'), task = state.activeTasks[0], request = state.inputRequests.find(item => item.state === 'pending');
  box.hidden = !task && !request;
  if (!task && !request) return;
  const pending = !task && request;
  $('global-task-title').textContent = pending ? '需要补充信息 · ' + (request.title || '当前任务') : (task.title || '任务正在执行');
  $('global-task-detail').textContent = pending ? request.question : task.query + ' · 已运行 ' + taskElapsed(task.elapsed_seconds);
  const open = $('global-task-open'), cid = pending ? request.cid : task.cid;
  open.textContent = pending ? '去回复' : '返回任务';
  open.dataset.conversation = cid;
  open.hidden = !pending && state.cid === cid && state.busy === task.id;
}
let activeTaskRequest = 0;
async function refreshActiveTasks() {
  const identity = state.me?.id;
  if (!identity) return;
  const request = ++activeTaskRequest;
  const result = await api('/api/active-tasks');
  if (state.me?.id !== identity || request !== activeTaskRequest) return;
  state.activeTasks = Array.isArray(result.tasks) ? result.tasks : [];
  state.inputRequests = Array.isArray(result.requests) ? result.requests : [];
  renderGlobalTask();
}
$('global-task-open').addEventListener('click', async () => {
  const cid = $('global-task-open').dataset.conversation;
  if (cid) await openConversation(cid).catch(error => notice(error.message));
});
function inline(node, text, assets = null, citations = null) {
  const pattern = /(`[^`]+`|!?\[[^\]\n]*\]\((?:[^()\n]|\([^()\n]*\))*\)|\[K[0-9a-f]{16,64}_[0-9]+\]|\*\*[^*]+\*\*|\$\$[^\n]+?\$\$|\\\[[^\n]+?\\\]|\$[^$\n]+\$|\\\([^\n]+?\\\))/g; let index = 0;
  for (const match of text.matchAll(pattern)) {
    node.append(document.createTextNode(text.slice(index, match.index)));
    const token = match[0];
    if (token.startsWith('`')) node.append(element('code', token.slice(1, -1)));
    else if (token.startsWith('**')) { const strong = element('strong'); inline(strong, token.slice(2, -2), assets, citations); node.append(strong); }
    else if (/^\[K[0-9a-f]{16,64}_[0-9]+\]$/.test(token) && citations) node.append(window.GeoAgentCitations.mark(token.slice(1, -1), citations));
    else if (token.startsWith('[') || token.startsWith('![')) node.append(window.GeoAgentArtifacts?.renderLink(token, assets) || document.createTextNode(token));
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
function markdown(target, text, assets = null) {
  const citations = target.classList.contains('answer') ? window.GeoAgentCitations?.context(assets) : null;
  const renderInline = (node, value) => inline(node, value, assets, citations);
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
        const block = element('div', undefined, 'math-block');
        if (window.katex) window.katex.render(math.join('\n').trim(), block, {output:'mathml', displayMode:true, throwOnError:false, trust:false});
        else block.textContent = lines.slice(i, cursor + 1).join('\n');
        target.append(block);
        if (suffix.trim()) { const p = element('p'); renderInline(p, suffix); target.append(p); }
        i = cursor + 1; continue;
      }
    }
    if (i + 1 < lines.length && line.includes('|') && /^\s*\|?\s*:?-+/.test(lines[i + 1]) && lines[i + 1].includes('|')) {
      const table = element('table'); const split = value => value.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(v => v.trim());
      const head = element('thead'), row = element('tr'); for (const value of split(line)) { const cell = element('th'); renderInline(cell, value); row.append(cell); } head.append(row); table.append(head); i += 2;
      const body = element('tbody'); while (i < lines.length && lines[i].includes('|') && lines[i].trim()) { const row = element('tr'); for (const value of split(lines[i++])) { const cell = element('td'); renderInline(cell, value); row.append(cell); } body.append(row); } table.append(body); const scroll = element('div', undefined, 'table-scroll'); scroll.append(table); target.append(scroll); continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line); if (heading) { const h = element('h' + heading[1].length); renderInline(h, heading[2]); target.append(h); i++; continue; }
    const listMarker = /^\s*(?:(\d{1,9})\.|[-*+])\s+/.exec(line);
    if (listMarker) {
      const ordered = listMarker[1] !== undefined;
      const list = element(ordered ? 'ol' : 'ul');
      if (ordered) list.start = Number(listMarker[1]);
      while (i < lines.length) {
        const marker = /^\s*(?:(\d{1,9})\.|[-*+])\s+/.exec(lines[i]);
        if (!marker || (marker[1] !== undefined) !== ordered) break;
        const item = element('li');
        renderInline(item, lines[i++].slice(marker[0].length));
        list.append(item);
      }
      target.append(list);
      continue;
    }
    const p = element('p'); renderInline(p, line); target.append(p); i++;
  }
  if (citations) window.GeoAgentCitations.finish(target, citations, String(text || ''));
}
async function initialize() {
  window.OreSagePassword?.clear();
  state.me = await api('/api/me'); window.OreSageDrafts?.identity(state.me.id); $('auth-screen').hidden = true; $('app').hidden = false;
  $('account-name').textContent = state.me.username; $('account-role').textContent = state.me.role === 'admin' ? '管理员' : '成员';
  $('invite-button').hidden = state.me.role !== 'admin';
  $('admin-releases-open').hidden = state.me.role !== 'admin';
  $('connection').title = [state.me.release, state.me.execution, state.me.execution_notice].filter(Boolean).join('\n');
  setComposerMode('ask');
  await loadModelSettings();
  await loadConversations();
  restoreComposerDraft();
  refreshActiveTasks().catch(() => {});
  window.OreSageProfile?.session(state.me);
  window.OreSageAdminUsers?.session(state.me);
  window.OreSageAdminUsage?.session(state.me);
  window.OreSageSharedKnowledge?.session(state.me);
  window.OreSageEmail?.authenticated();
}
$('auth-form').addEventListener('submit', async event => {
  event.preventDefault(); $('auth-error').textContent = ''; $('auth-submit').disabled = true;
  try { const credentials = {username: $('username').value.trim(), password: $('password').value};
    await api('/api/login', {method:'POST', body:credentials}); $('password').value = ''; await initialize();
  } catch (error) { $('auth-error').textContent = error.status===401?'用户名、邮箱或密码不正确。尚未设置密码可点击“首次设置密码”。':error.message; } finally { $('auth-submit').disabled = false; }
});
function composerDraftScope() { return 'composer:' + (state.cid || 'new'); }
function restoreComposerDraft() { $('prompt').value = window.OreSageDrafts?.text(composerDraftScope()) || ''; }
async function loadConversations() {
  const conversations = await api('/api/conversations'); $('conversation-list').replaceChildren();
  for (const conversation of conversations) { const button = element('button', conversation.title, conversation.id === state.cid ? 'selected' : ''); button.title = conversation.title; button.addEventListener('click', () => openConversation(conversation.id).catch(e => notice(e.message))); $('conversation-list').append(button); }
}
function closeStreams() { window.GeoAgentCitations?.clear(); stopRunElapsedClock(); for (const source of state.sources.values()) source.close(); state.sources.clear(); }
function busy(rid) { state.busy = rid; $('composer-mode').disabled = Boolean(rid); $('send').disabled = Boolean(rid); $('stop').hidden = !rid; $('attach').disabled = Boolean(rid); $('upload-button').disabled = Boolean(rid); window.GeoToolHITL?.syncComposer(); }
async function openConversation(cid) {
  window.GeoToolLibrary?.close({focus:false});
  if (state.cid && state.cid !== cid) window.GeoToolLibrary?.clearSelection();
  if (!submittingRun) submissionFeedback();
  window.OreSageDrafts?.flush(); window.GeoAgentImages?.clear(); closeStreams(); state.cid = cid; const view = ++state.view; state.runs.clear(); $('messages').replaceChildren(); notice(); busy(null); restoreComposerDraft();
  window.GeoToolHITL?.selectConversation(cid);
  const conversation = await api(`/api/conversations/${cid}`); if (state.cid !== cid || state.view !== view) return; $('chat-title').textContent = conversation.title;
  if (!conversation.runs.length) $('messages').append(welcome);
  for (const run of conversation.runs) { const ui = renderRun(run); if (runIsWorking(run.status)) { subscribe(run.id); busy(run.id); } else attachRunHistory(run.id, ui); }
  $('sidebar').classList.remove('open'); await Promise.all([loadConversations(), loadFiles()]); refreshActiveTasks().catch(() => {}); scrollEnd(); window.GeoAgentCases?.conversation(cid);
}
async function ensureConversation() { if (!state.cid) { const conversation = await api('/api/conversations', {method:'POST'}); await openConversation(conversation.id); } return state.cid; }
$('new-chat').addEventListener('click', async () => {
  setComposerMode('ask');
  try {
    const conversation = await api('/api/conversations', {method:'POST'});
    await openConversation(conversation.id);
    if (state.cid !== conversation.id) return;
    $('prompt').focus();
  } catch (error) { notice(error.message); }
});
function scrollEnd() { $('messages').scrollTop = $('messages').scrollHeight; }
// One clock for the visible conversation. Durations come from the server;
// performance.now() advances the display without relying on the browser's wall clock.
let runElapsedClock = null;
let submittingRun = false;
function runIsWorking(status) { return status === 'running' || status === 'stopping'; }
function stopRunElapsedClock() { if (runElapsedClock !== null) clearInterval(runElapsedClock); runElapsedClock = null; }
function elapsedSeconds(ui) {
  return ui.elapsedBase + (runIsWorking(ui.status) ? Math.max(0, performance.now() - ui.elapsedAnchor) / 1000 : 0);
}
function paintRunElapsed(ui) {
  window.GeoAgentTimeline?.tick(ui);
  ui.elapsed.hidden = !ui.elapsedKnown;
  if (!ui.elapsedKnown) return;
  const seconds = Math.max(0, Math.floor(elapsedSeconds(ui)));
  const duration = seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
  const text = `${runIsWorking(ui.status) ? '已用时' : '耗时'} ${duration}`;
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
  setRunMessageTimes(ui, run);
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
// Message timestamps use persisted server times, never page-load time.
function messageDate(value) {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    const date = new Date(value * 1000);
    return Number.isFinite(date.getTime()) ? date : null;
  }
  if (typeof value === 'string' && /^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(value)) {
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? date : null;
  }
  return null;
}
function messageDayKey(date) { return date.getFullYear() + '-' + date.getMonth() + '-' + date.getDate(); }
function shouldSeparateMessages(current, previous) {
  return Boolean(current && (!previous || messageDayKey(current) !== messageDayKey(previous)
    || current.getTime() - previous.getTime() >= 30 * 60 * 1000));
}
function messageTimeLabel(date, now = new Date()) {
  const clock = new Intl.DateTimeFormat('zh-CN', {hour:'2-digit', minute:'2-digit', hourCycle:'h23'}).format(date);
  if (messageDayKey(date) === messageDayKey(now)) return '今天 ' + clock;
  const yesterday = new Date(now); yesterday.setDate(yesterday.getDate() - 1);
  if (messageDayKey(date) === messageDayKey(yesterday)) return '昨天 ' + clock;
  return new Intl.DateTimeFormat('zh-CN', {year:'numeric', month:'long', day:'numeric'}).format(date) + ' ' + clock;
}
function messageTimeNode(kind) {
  const box = element('div', undefined, 'message-meta message-meta-' + kind);
  const time = element('time'); time.tabIndex = 0; box.append(time); box.hidden = true;
  return {box, time};
}
function setRunMessageTimes(ui, run) {
  const sent = messageDate(run.created), finished = messageDate(run.finished_at);
  if (sent) ui.sentAt = sent;
  if (finished) ui.finishedAt = finished;
  function paint(entry, date, label) {
    if (!date) return;
    entry.time.dateTime = date.toISOString();
    entry.time.textContent = messageTimeLabel(date);
    entry.time.title = label + '：' + new Intl.DateTimeFormat('zh-CN', {
      year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit',
      second:'2-digit', hourCycle:'h23', timeZoneName:'longOffset'
    }).format(date);
    entry.time.setAttribute('aria-label', entry.time.title); entry.box.hidden = false;
  }
  paint(ui.userTime, ui.sentAt, '发送时间');
  paint(ui.answerTime, ui.finishedAt, '本轮答复或暂停时间');
  let previous = null;
  for (const turn of state.runs.values()) {
    if (turn === ui) break;
    previous = turn.finishedAt || turn.sentAt || previous;
  }
  ui.timeSeparator.hidden = !shouldSeparateMessages(ui.sentAt, previous);
  if (!ui.timeSeparator.hidden) {
    ui.timeSeparator.firstChild.dateTime = ui.sentAt.toISOString();
    ui.timeSeparator.firstChild.textContent = messageTimeLabel(ui.sentAt);
  }
}
// End message timestamp helpers.

function replyActions(ui) {
  const box = element('div', undefined, 'reply-actions');
  const copy = element('button', '复制答复', 'quiet');
  copy.type = 'button';
  const feedback = element('span', '', 'reply-copy-feedback');
  feedback.setAttribute('role', 'status');
  copy.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(ui.answerText);
      feedback.textContent = '已复制';
    } catch {
      feedback.textContent = '无法复制，请选中正文后复制。';
    }
  });
  box.append(copy, feedback);
  box.hidden = !ui.finished || !ui.answerText.trim();
  return box;
}

function renderRun(run) {
  welcome.remove();
  const turn = element('article', undefined, 'turn'); turn.dataset.run = run.id;
  const user = element('div', run.query, 'user-message'); const label = element('div', AGENT_NAME, 'assistant-label');
  const activity = element('details', undefined, 'activity'); const summary = element('summary', '查看执行详情'); const list = element('div', undefined, 'tool-list'); activity.append(summary, list);
  const answer = element('div', undefined, 'answer'); markdown(answer, run.answer); const reason = element('div', run.reason || '', 'run-reason');
  const elapsed = element('div', undefined, 'run-elapsed');
  elapsed.setAttribute('role', 'timer'); elapsed.setAttribute('aria-live', 'off');
  elapsed.title = '包含模型、工具和审核耗时，不含等待用户回复的时间。';
  const userTime = messageTimeNode('user'), answerTime = messageTimeNode('assistant');
  const userGroup = element('div', undefined, 'message-user-group');
  const skillReceipt = element('div', undefined, 'run-skill'); skillReceipt.hidden = true;
  const modeReceipt = element('span', undefined, 'run-mode'); modeReceipt.hidden = true;
  const settingsReceipt = element('div', undefined, 'run-settings');
  settingsReceipt.append(modeReceipt, skillReceipt);
  userGroup.append(user, settingsReceipt, userTime.box);
  const timeSeparator = element('div', undefined, 'message-time-separator'); timeSeparator.append(element('time')); timeSeparator.hidden = true;
  turn.append(timeSeparator, userGroup, label, elapsed, activity, answer, reason, answerTime.box); $('messages').append(turn);
  const ui = {userTime, answerTime, timeSeparator, skillReceipt, modeReceipt, sentAt:null, finishedAt:null, mode:run.activity?.mode,
    hasExtendedProgress:Boolean(run.activity?.skill || run.activity?.tool_count || run.activity?.timing?.totals_seconds?.retrieval), elapsed, elapsedBase:0, elapsedAnchor:performance.now(), elapsedKnown:runIsWorking(run.status), status:run.status, turn, activity, summary, list, answer, answerText:run.answer || '', reason, tools:new Map(), finished:!['running','stopping'].includes(run.status)};
  ui.replyActions = replyActions(ui);
  reason.before(ui.replyActions);
  state.runs.set(run.id, ui); setRunElapsed(ui, run); window.GeoToolHITL?.attachCards(); window.GeoAgentExperience?.attach(run.id, ui); window.GeoAgentTimeline?.attach(run.id, ui); window.GeoAgentPresentation?.attach(run.id, ui);
  if (run.activity?.mode) handleEvent(run.id, {kind:'run_mode', mode:run.activity.mode}, null, true);
  if (run.activity?.skill) handleEvent(run.id, {kind:'skill_selected', skill:run.activity.skill}, null, true);
  for (const receipt of Object.values(run.activity?.loaded_skills || {})) window.GeoAgentTimeline?.event(run.id, receipt);
  if (run.activity?.profile) handleEvent(run.id, {kind:'model_config', profile:run.activity.profile}, null, true);
  if (run.activity?.timing) window.GeoAgentTimeline?.event(run.id, run.activity.timing);
  if (ui.finished && Number.isSafeInteger(run.activity?.tool_count)) { ui.summary.textContent = '执行过程 · ' + run.activity.tool_count + ' 次工具调用'; if (ui.overview) ui.overview.counts.textContent = run.activity.tool_count + ' 次工具调用 · 展开查看记录'; }
  return ui;
}
const statusText = {'Model is working':'模型正在处理','Starting an isolated task environment':'正在准备执行','GeoGPT is working':'GeoGPT 正在处理','Preparing answer':'正在整理答复','Checking the result':'正在检查结果','Correcting the result':'正在修正结果','Correcting a model response':'正在修正模型响应','Retrying the completion check':'正在重新检查完成情况'};
statusText['Running in the service account environment (OS isolation disabled)'] = '正在准备执行';
statusText['Compacting context'] = '正在压缩历史上下文';
const toolNames = {skill_find:'查找相关技能', skill_load:'读取技能说明', read_file:'读取文件', write_file:'写入文件', execute_python:'执行 Python', GeoMagnitudeToEnergy:'估算地震能量'};
function handleEvent(rid, data, eventId, historical = false) {
  const ui = state.runs.get(rid); if (!ui) return;
  const sequence = typeof eventId === 'string' && /^\d+$/.test(eventId) ? Number(eventId) : null;
  if (Number.isSafeInteger(sequence)) {
    if (sequence <= (ui.lastEventSequence ?? -1)) return;
    ui.lastEventSequence = sequence;
  }
  const wasNearEnd = $('messages').scrollHeight - $('messages').scrollTop - $('messages').clientHeight < 130;
  if (data.kind === 'run_mode' && ['ask','agent'].includes(data.mode)) {
    ui.mode = data.mode;
    ui.modeReceipt.textContent = data.mode === 'ask' ? '询问' : '执行';
    ui.modeReceipt.dataset.mode = data.mode;
    ui.modeReceipt.hidden = false;
  }
  if (data.kind === 'skill_selected' && data.skill) {
    const {name, id, revision, instructions_sha256: digest} = data.skill;
    ui.skillReceipt.textContent = '所选技能 · ' + name + ' · ' + revision;
    ui.skillReceipt.title = id + ' · SHA-256 ' + digest;
    ui.skillReceipt.hidden = false;
  }
  if (data.kind === 'model_config') { ui.turn.querySelector('.assistant-label').textContent = AGENT_NAME + ' · ' + data.profile.model; }
  if (data.kind === 'finished') {
    setRunMessageTimes(ui, data);
    for (const receipt of Object.values(data.activity?.loaded_skills || {})) window.GeoAgentTimeline?.event(rid, receipt);
  }
  const replacingDraft = data.kind === 'finished' && ui.overview?.preview.hidden === false;
  if (data.kind === 'finished' && !historical) {
    setRunElapsed(ui, data); ui.finished = true; ui.answerText = data.answer || ''; markdown(ui.answer, ui.answerText, ui.artifactContext); ui.summary.textContent = '查看执行详情'; ui.reason.textContent = data.reason || '';
    ui.replyActions.hidden = !ui.answerText.trim();
    const source = state.sources.get(rid); if (source) source.close(); state.sources.delete(rid); if (state.busy === rid) busy(null); window.GeoToolHITL?.refresh(data.status === 'needs_input'); refreshActiveTasks().catch(() => {}); loadFiles().catch(e => notice(e.message)); loadConversations().catch(e => notice(e.message));
  }
  window.GeoAgentExperience?.event(rid, data, eventId);
  if (!historical || data.kind !== 'stage_timing' || !ui.timing) window.GeoAgentTimeline?.event(rid, data, eventId);
  if (!historical) window.GeoAgentPresentation?.event(rid, data);
  if (wasNearEnd && !historical && !replacingDraft) scrollEnd();
}
function attachRunHistory(rid, ui) {
  if (ui.history) return;
  const pager = element('div', undefined, 'timeline-history-pager');
  const hint = element('p', '执行详情按需加载；完整原始记录保留。', 'timeline-note');
  const more = element('button', '加载执行详情', 'quiet');
  more.type = 'button'; pager.append(hint, more); ui.list.after(pager);
  const page = ui.history = {cursor:0, through:null, loading:false, done:false, pages:0};
  const cid = state.cid, view = state.view;
  const current = () => state.cid === cid && state.view === view && state.runs.get(rid) === ui;
  async function loadPage() {
    if (page.loading || page.done || !current()) return;
    page.loading = true; more.disabled = true; hint.textContent = '正在读取保存的记录…';
    try {
      const suffix = page.through === null ? '' : '&through=' + page.through;
      const result = await api('/api/runs/' + encodeURIComponent(rid) + '/history?after=' + page.cursor + '&limit=60' + suffix);
      if (!current()) return;
      if (result.run_id !== rid || !Array.isArray(result.events)) throw new Error('记录标识不一致');
      for (const receipt of result.loaded_skills || []) window.GeoAgentTimeline?.event(rid, receipt);
      for (const row of result.events) handleEvent(rid, row.data, String(row.id), true);
      page.cursor = result.next; page.through = result.through; page.done = !result.has_more; page.pages++;
      more.textContent = '加载更多记录'; more.hidden = page.done;
      hint.textContent = page.done ? '执行记录已全部加载。展开每一项查看详情。' : '已加载 ' + page.pages + ' 页；其余记录未省略，点击继续加载。';
      // Replaying a saved finish must not collapse a user-opened disclosure.
      ui.activity.open = true;
    } catch (error) { if (current()) { hint.textContent = '加载失败：' + error.message; more.textContent = '重试加载'; } }
    finally { page.loading = false; more.disabled = false; }
  }
  more.addEventListener('click', loadPage);
  ui.activity.addEventListener('toggle', () => { if (ui.activity.open && page.pages === 0) loadPage(); });
}
function subscribe(rid, after = 0) {
  const cid = state.cid, source = new EventSource(`/api/runs/${rid}/events?after=${after}`); state.sources.set(rid,source);
  // New submissions initially contain only an ID; recover authoritative timing
  // once, not by polling every second. Historical runs already include timing.
  const ui = state.runs.get(rid);
  if (ui && runIsWorking(ui.status)) api(`/api/runs/${rid}`).then(run => {
    if (state.cid !== cid || state.sources.get(rid) !== source || state.runs.get(rid) !== ui || ui.finished) return;
    if (!runIsWorking(run.status)) handleEvent(rid, {kind:'finished', ...run});
    else setRunElapsed(ui, run);
  }).catch(() => { /* The SSE reconnect path owns connection errors. */ });
  source.onmessage = event => { if (state.cid !== cid || state.sources.get(rid) !== source) return; try { handleEvent(rid,JSON.parse(event.data),event.lastEventId); $('connection').textContent = '已连接'; } catch { notice('事件显示失败，请重新打开这段对话。'); } };
  let checking = false;
  const active = () => state.cid === cid && state.sources.get(rid) === source;
  source.onopen = () => {
    if (!active()) return;
    $('connection').textContent = '已连接';
    if (ui?.overview?.connection) window.GeoAgentExperience?.event(rid, {kind:'connection_restored'});
  };
  source.onerror = async () => {
    if (!active()) return;
    $('connection').textContent = '正在重连';
    window.GeoAgentExperience?.event(rid, {kind:'connection_lost'});
    if (checking) return;
    checking = true;
    try {
      const run = await api(`/api/runs/${rid}`);
      if (!active()) return;
      // Let EventSource replay the missing events using Last-Event-ID.
      if (source.readyState === EventSource.CLOSED && !runIsWorking(run.status)) {
        handleEvent(rid, {kind:'finished', ...run});
        attachRunHistory(rid, ui);
      }
    } catch (error) {
      if (!active() || ![401, 403, 404].includes(error.status)) return;
      source.close();
      state.sources.delete(rid);
      window.GeoAgentExperience?.event(rid, {kind:'connection_failed'});
      notice(error.message);
    } finally {
      checking = false;
      if (active() && source.readyState === EventSource.CLOSED) {
        const after = ui?.lastEventSequence || 0;
        setTimeout(() => { if (active()) subscribe(rid, after); }, 1500);
      }
    }
  };
}
$('composer').addEventListener('submit', async event => {
  event.preventDefault();
  if (submittingRun || quickSwitching || state.busy || window.GeoToolHITL?.blocksComposer()) return;
  const prompt = $('prompt'), draft = prompt.value, query = draft.trim();
  if (!query) return;
  const mode = composerMode();
  const skillId = mode === 'agent' ? window.GeoToolLibrary?.selectedId() : null;
  const identity = state.me?.id, draftScope = composerDraftScope();
  let view = state.view, cid = state.cid;
  submittingRun = true;
  $('send').disabled = true;
  notice();
  submissionFeedback('正在提交任务…');
  try {
    if (!cid) {
      const conversation = await api('/api/conversations', {method:'POST'});
      if (state.view !== view || state.me?.id !== identity) return;
      const opening = openConversation(conversation.id);
      view = state.view;
      await opening;
      cid = conversation.id;
    }
    if (state.cid !== cid || state.view !== view || state.me?.id !== identity) return;
    const run = await api(`/api/conversations/${cid}/runs`, {method:'POST', body:{query, mode, ...(skillId ? {skill_id:skillId} : {})}});
    if (state.cid !== cid || state.view !== view || state.me?.id !== identity) return;
    if (prompt.value === draft) { prompt.value = ''; window.OreSageDrafts?.clear(composerDraftScope()); }
    if (draftScope !== composerDraftScope()) window.OreSageDrafts?.clear(draftScope);
    window.GeoToolLibrary?.clearSelection();
    renderRun({id:run.id,query,status:'running',answer:'',activity:{mode}});
    submissionFeedback();
    busy(run.id); subscribe(run.id); refreshActiveTasks().catch(() => {}); scrollEnd(); await loadConversations();
  } catch (error) {
    if (state.me?.id !== identity || state.view !== view) return;
    const active = error.status === 409 &&
      (error.activeConversation || error.message === 'You already have an active task; wait for it to finish');
    if (active) {
      submissionFeedback('此账号有任务正在执行。当前输入已保留。', error.activeConversation || '');
    } else {
      submissionFeedback();
      notice(error.message);
    }
  } finally {
    submittingRun = false;
    $('send').disabled = Boolean(state.busy || quickSwitching);
    window.GeoToolHITL?.syncComposer();
    if ($('submission-status').textContent === '正在提交任务…') submissionFeedback();
  }
});
window.GeoAgentCaseBridge = {
  api, notice, busy: () => Boolean(state.busy),
  load: async loaded => {
    await openConversation(loaded.conversation_id);
    if (state.cid !== loaded.conversation_id) return;
    setComposerMode('agent');
    $('prompt').value = loaded.prompt;
    $('prompt').dispatchEvent(new Event('input'));
    $('prompt').focus();
    notice(loaded.message);
  }
};
$('prompt').addEventListener('input', () => window.OreSageDrafts?.save(composerDraftScope(), 'text', $('prompt').value));
$('prompt').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('composer').requestSubmit(); } });
$('stop').addEventListener('click', async () => { if (!state.busy) return; try { await api(`/api/runs/${state.busy}/stop`,{method:'POST'}); notice('正在停止任务。最近已保存的文件会保留。'); } catch(e) { notice(e.message); } });
const welcome = $('welcome');
function composerMode() {
  return $('composer').elements.namedItem('mode').value;
}
function setComposerMode(mode) {
  $('composer').elements.namedItem('mode').value = mode;
  const ask = mode === 'ask';
  $('skill-picker-button').hidden = ask;
  if (ask) window.GeoToolLibrary?.clearSelection();
  $('execution-note').dataset.mode = mode;
  $('execution-note').textContent = ask ? '询问 · 只读问答，可检索资料'
    : '执行 · 可使用技能、运行工具并生成文件';
}
$('composer-mode').addEventListener('change', event => setComposerMode(event.target.value));
window.GeoAgentComposer = {mode: composerMode, useAgent: () => setComposerMode('agent')};
for (const button of welcome.querySelectorAll('[data-prompt]')) button.addEventListener('click', () => {
  setComposerMode(button.dataset.mode);
  $('prompt').value = button.dataset.prompt;
  $('prompt').dispatchEvent(new Event('input'));
  $('prompt').focus();
});
async function loadFiles() {
  $('files-list').replaceChildren(); if (!state.cid) { $('file-count').textContent='0'; return; }
  const cid=state.cid, result=await api(`/api/conversations/${cid}/files`); if (state.cid!==cid) return; $('file-count').textContent=String(result.files.length);
  const context = {...result, conversation_id:cid};
  for (const file of result.files) {
    const item = element('div', undefined, 'file-item artifact-file-item');
    const open = element('button', file.name, 'quiet artifact-file-name');
    open.type = 'button';
    open.addEventListener('click', () => window.GeoAgentArtifacts.openFile(context, file.name, open));
    const link = element('a', '下载');
    link.href = window.GeoAgentArtifacts.fileURL(context, file.name, 'download');
    link.download = file.name.split('/').pop();
    item.append(open, link, element('small', `${(file.bytes/1024).toFixed(1)} KiB · SHA-256 ${file.sha256.slice(0,12)}`));
    $('files-list').append(item);
  }
  if (!result.files.length) $('files-list').append(element('p','尚无文件。可添加材料，或让 Agent 生成文件。','muted'));
  window.GeoAgentImages?.render(result, cid);
}
for (const id of ['attach','upload-button']) $(id).addEventListener('click',()=>$('upload').click());
$('upload').addEventListener('change',async()=>{const file=$('upload').files[0]; if(!file)return; try{const cid=await ensureConversation();await api(`/api/conversations/${cid}/upload?name=${encodeURIComponent(file.name)}`,{method:'POST',body:file,headers:{'Content-Type':'application/octet-stream'}}); await loadFiles(); $('files-panel').hidden=false; notice('文件已加入当前对话。');}catch(e){notice(e.message);}finally{$('upload').value='';}});
$('files-toggle').addEventListener('click', () => {
  window.GeoAgentArtifacts.closePreview();
  $('files-panel').hidden = !$('files-panel').hidden;
});
$('files-close').addEventListener('click', () => { $('files-panel').hidden = true; });
$('menu-button').addEventListener('click',()=>$('sidebar').classList.toggle('open'));
$('logout').addEventListener('click',async()=>{window.OreSageProfile?.clear();try{await api('/api/logout',{method:'POST'});location.reload();}catch(e){notice(e.message);}});
let dialogAction=null;
function dialog(title){$('dialog-title').textContent=title;$('dialog-body').replaceChildren();$('dialog-error').textContent='';$('dialog-submit').hidden=false;$('account-dialog').showModal();}
$('dialog-close').addEventListener('click',()=>$('account-dialog').close());
function openCurrentPassword() {dialog('修改密码');for(const [id,label] of [['old-password','当前密码'],['new-password','新密码（至少 12 个字符）']]){const wrap=element('label',label),input=element('input');input.type='password';input.id=id;input.required=true;input.minLength=12;input.maxLength=256;input.autocomplete=id==='old-password'?'current-password':'new-password';wrap.append(input);$('dialog-body').append(wrap);}dialogAction=async()=>{await api('/api/password',{method:'POST',body:{old:$('old-password').value,new:$('new-password').value}});location.reload();};}
$('password-button').addEventListener('click',()=>window.OreSagePassword?.open());
window.OreSageInviteUIVersion = '20261110-csrf1';
$('admin-releases-open').addEventListener('click', async () => {
  if (state.me?.role !== 'admin') return;
  const dialog = $('admin-releases-dialog'), status = $('admin-releases-current');
  const content = $('admin-releases-content'), account = state.me.id;
  dialog.showModal();
  status.textContent = '正在读取版本记录…';
  content.replaceChildren();
  try {
    const {build, version, entries} = await api('/api/admin/releases');
    if (!dialog.open || state.me?.id !== account) return;
    status.textContent = (version ? '当前版本 ' + version : '当前构建尚未编号') + ' · ' + build;
    for (const entry of entries) {
      const card = element('article', undefined, 'admin-release-item');
      const heading = element('h3', entry.version || '历史部署');
      if (entry.build.slice(0, 12) === build) heading.append(element('span', '当前上线', 'admin-release-current'));
      const time = entry.deployed_at.length === 10 ? entry.deployed_at :
        new Date(entry.deployed_at).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false});
      const changes = element('ul');
      for (const change of entry.changes) changes.append(element('li', change));
      const metadata = element('details');
      metadata.append(element('summary', '构建与验收信息'), element('p', '构建 ' + entry.build));
      if (entry.previous_build) metadata.append(element('p', '前一构建 ' + entry.previous_build));
      if (entry.task) metadata.append(element('p', '任务 ' + entry.task));
      if (entry.verification) metadata.append(element('p', '验收 ' + entry.verification));
      card.append(heading, element('time', time), changes, metadata);
      content.append(card);
    }
    if (!entries.length) content.append(element('p', '暂无已核实的发布记录。'));
  } catch (error) {
    if (dialog.open && state.me?.id === account) status.textContent = '读取失败。关闭后可重新打开。';
  }
});
$('invite-button').addEventListener('click', async () => {
  dialog('邀请研究组成员'); dialogAction = null; $('dialog-submit').hidden = true;
  $('dialog-body').append(element('p', '每个邀请链接在 24 小时内有效，最多可注册 50 名普通成员。可将同一链接提供给多人，达到上限后需生成新链接。'));
  $('invite-button').disabled = true;
  try {
    const previous = state.me;
    const current = await api('/api/me', {timeoutMs:10000});
    if (!previous || current.id !== previous.id || current.role !== previous.role) {
      $('account-dialog').close(); location.reload(); return;
    }
    // A different tab may have rotated this account's Cookie/Session.
    // Refresh its CSRF before the write; never retry a mutation across identities.
    state.me = current;
    const result = await api('/api/admin/invites', {method:'POST'});
    $('dialog-body').append(element('p', '注册人数：' + result.used_count + ' / ' + result.max_uses + '，剩余 ' + result.remaining + ' 个名额。'));
    const input = element('input'); input.readOnly = true;
    input.value = location.origin + '/#join=' + result.token;
    input.setAttribute('aria-label', '邀请链接');
    input.addEventListener('click', () => input.select()); $('dialog-body').append(input);
  } catch (error) {
    if (error.status === 401) $('account-dialog').close();
    else $('dialog-error').textContent = error.message === 'CSRF validation failed'
      ? '登录状态已在其他页面更新，请重新点击生成邀请。' : error.message;
  } finally { $('invite-button').disabled = false; }
});
$('account-form').addEventListener('submit',async event=>{event.preventDefault();if(!dialogAction)return;try{await dialogAction();}catch(e){$('dialog-error').textContent=e.message;}});
// Grouped text fields retain exact integer payloads; invalid commas are not ignored.
function parseTokenValue(value) {
  const text = String(value).trim();
  if (!/^(?:\d+|[1-9]\d{0,2}(?:,\d{3})+)$/.test(text)) return NaN;
  const number = Number(text.replaceAll(',', ''));
  return Number.isSafeInteger(number) && number > 0 ? number : NaN;
}
function formatTokenValue(value) {
  const number = parseTokenValue(value);
  return Number.isNaN(number) ? String(value) : number.toLocaleString('en-US');
}
function bindTokenInput(input) {
  input.type = 'text'; input.inputMode = 'numeric'; input.maxLength = 21;
  input.addEventListener('blur', () => { input.value = formatTokenValue(input.value); });
}
for (const id of ['model-context-window', 'model-max-output']) bindTokenInput($(id));
let modelSettings = null, modelPending = false, modelEditing = null, modelSelection = '', modelDraftBaseline = '';
function modelDefaults() { return modelSettings?.defaults || {context_window_tokens:1000000, max_output_tokens:128000}; }
window.addEventListener('geoagent:defaults-updated', () => {
  if (state.me) loadModelSettings().catch(error => notice(error.message));
});
async function loadModelSettings() {
  modelSettings = await api('/api/model-settings');
  const label = modelSettings.source === 'builtin' ? (modelSettings.model === 'gpt-6.1-sol' ? 'ChatGPT 6.1 Sol' : modelSettings.model) : modelSettings.name || modelSettings.model;
  $('model-quick-label').textContent = label;
  $('model-quick-trigger').title = '选择模型 · ' + modelSettings.model;
  renderModelQuickOptions();
  window.GeoAgentExperience?.model(modelSettings);
  if (modelSettings.storage_error) notice('已保存的模型配置不可用，请恢复服务器密钥，或在模型配置中清除损坏的数据。');
}
// Keep the budget card visible for the read-only built-in service as well.
$('custom-model-fields').after($('model-context-window').closest('.model-context-settings'));
function modelSavedProfiles() { return modelSettings?.saved_profiles || []; }
function modelPayload() {
  if ($('model-source').value === 'builtin') return {source:'builtin'};
  const keep = $('model-keep-token').checked && !$('model-token').value;
  const payload = {source:'custom', name:$('model-profile-name').value.trim(),
    base_url:$('model-base-url').value.trim(), model:$('model-id').value.trim(),
    api_token:$('model-token').value, keep_token:keep, remember:$('model-remember').checked,
    context_window_tokens:$('model-context-window').value.trim() ? parseTokenValue($('model-context-window').value) : modelDefaults().context_window_tokens,
    max_output_tokens:$('model-max-output').value.trim() ? parseTokenValue($('model-max-output').value) : modelDefaults().max_output_tokens};
  if (modelEditing?.profile_id) { payload.profile_id = modelEditing.profile_id; payload.revision = modelEditing.revision; }
  return payload;
}
function modelContextHint() {
  const input = $('model-context-window'), outputInput = $('model-max-output');
  const windowTokens = input.value.trim() ? parseTokenValue(input.value) : modelDefaults().context_window_tokens;
  const outputTokens = outputInput.value.trim() ? parseTokenValue(outputInput.value) : modelDefaults().max_output_tokens;
  input.setCustomValidity(''); outputInput.setCustomValidity('');
  if (!Number.isSafeInteger(outputTokens) || outputTokens < 1) {
    outputInput.setCustomValidity('最大输出须为正整数 Token 数。');
    $('model-context-hint').textContent = '请填写有效的最大输出 Token 数。';
    return;
  }
  const safety = Math.max(1024, Math.ceil(windowTokens / 20));
  const available = windowTokens - outputTokens - safety;
  if (!Number.isSafeInteger(windowTokens) || windowTokens < 1 || available <= 0) {
    input.setCustomValidity('上下文窗口须为正整数，并大于最大输出与安全预留之和。');
    $('model-context-hint').textContent = '最大输出与安全预留不能占满上下文窗口，请调整两个参数。';
    return;
  }
  $('model-context-hint').textContent = '可用输入约 ' + available.toLocaleString('zh-CN') +
    ' Token；每次响应最多 ' + outputTokens.toLocaleString('zh-CN') + ' 输出 Token，另留 ' +
    safety.toLocaleString('zh-CN') + ' 安全余量。账号默认值可在「设置」中修改，只用于新连接的初始参数；这里可单独覆盖。请核对供应商容量，BPE、协议和图片计数仍为估算。';
}
function modelDirty() { return modelDraftBaseline && JSON.stringify(modelPayload()) !== modelDraftBaseline; }
function modelControls() {
  modelContextHint();
  const custom = $('model-source').value === 'custom';
  $('custom-model-fields').hidden = !custom;
  $('custom-model-fields').disabled = !custom || modelPending;
  $('model-context-window').disabled = !custom || modelPending;
  $('model-max-output').disabled = !custom || modelPending;
  document.querySelector('.model-context-source').textContent = custom ? '连接参数 · 可编辑' : '内置服务 · 只读';
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
  add('builtin', '默认 · ' + (modelSettings.builtin?.model || modelSettings.model));
  for (const profile of modelSavedProfiles()) add(profile.profile_id,
    profile.name + ' · ' + profile.model + (profile.profile_id === modelSettings.profile_id ? '（当前）' : ''));
  if (modelSettings.source === 'custom' && !modelSettings.profile_id) add('session', '本次登录的临时配置');
  add('new', '新增 API 配置…');
  $('model-profile-count').textContent = modelSavedProfiles().length + ' 份已保存连接';
  $('model-active-label').textContent = '当前使用：' + (modelSettings.source === 'builtin' ? '默认 · ' + modelSettings.model : modelSettings.name || modelSettings.model);
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
  $('model-context-window').value = formatTokenValue(profile.context_window_tokens ?? modelDefaults().context_window_tokens);
  $('model-max-output').value = formatTokenValue(profile.max_output_tokens ?? modelDefaults().max_output_tokens);
  $('model-context-window').placeholder = '账号默认 ' + formatTokenValue(modelDefaults().context_window_tokens);
  $('model-max-output').placeholder = '账号默认 ' + formatTokenValue(modelDefaults().max_output_tokens);
  $('model-keep-wrap').hidden = !profile.has_token;
  $('model-keep-token').checked = Boolean(profile.has_token);
  $('model-remember').checked = selection !== 'session';
  $('builtin-model-note').textContent = modelSettings.builtin.model + ' · 使用研究组已有服务；窗口与最大输出由服务配置控制。切换到这里不会删除已保存的 API 配置。';
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
      'model-token','model-context-window','model-max-output','model-keep-token','model-remember','model-clear','model-test','model-save','model-close']) $(id).disabled = wait;
  modelControls();
}
const quickModels = $('model-quick');
let quickSwitching = false;
function renderModelQuickOptions() {
  const target = $('model-quick-options');
  target.replaceChildren();
  const add = (id, title, detail, current) => {
    const option = element('button', undefined, 'model-quick-option');
    option.type = 'button';
    if (current) option.setAttribute('aria-current', 'true');
    const label = element('span');
    label.append(element('strong', title));
    if (detail && detail !== title) label.append(element('small', detail));
    option.append(label);
    if (current) option.append(element('span','✓','model-current-check'));
    option.addEventListener('click', () => {
      if (current) { quickModels.open = false; $('model-quick-trigger').focus(); }
      else switchQuickModel(id);
    });
    target.append(option);
  };
  const builtin = modelSettings.builtin?.model || modelSettings.model;
  add(null, '平台默认', builtin, modelSettings.source === 'builtin');
  for (const profile of modelSavedProfiles())
    add(profile.profile_id, profile.name || profile.model, profile.model, profile.profile_id === modelSettings.profile_id);
  const sessionOnly = modelSettings.source === 'custom' && !modelSettings.profile_id;
  if (sessionOnly) add(null, modelSettings.name || modelSettings.model, '本次登录', true);
  const note = $('model-quick-note');
  note.hidden = !sessionOnly;
  note.textContent = sessionOnly ? '切换后将结束当前临时连接。' : '';
}
async function switchQuickModel(id) {
  if (quickSwitching || submittingRun || !state.me) return;
  quickSwitching = true;
  const account = state.me.id;
  quickModels.open = false;
  $('model-quick-trigger').focus();
  try {
    await api('/api/model-settings/activate', {method:'POST',body:{profile_id:id}});
    if (state.me?.id === account) await loadModelSettings();
  } catch (error) {
    if (state.me?.id === account) notice(error.message);
  } finally { quickSwitching = false; }
}
document.addEventListener('pointerdown', event => {
  if (quickModels.open && !quickModels.contains(event.target)) quickModels.open = false;
});
quickModels.addEventListener('keydown', event => {
  if (quickModels.open && event.key === 'Escape') {
    event.preventDefault(); quickModels.open = false; $('model-quick-trigger').focus();
  }
});
$('model-settings-button').addEventListener('click', async () => {
  quickModels.open = false;
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
for (const id of ['model-id','model-profile-name','model-context-window','model-max-output','model-remember','model-keep-token']) {
  $(id).addEventListener(id === 'model-id' || id === 'model-profile-name' || id === 'model-context-window' || id === 'model-max-output' ? 'input' : 'change', () => {
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
window.OreSageProfile?.mount({api, identity: () => state.me, showLogin});
window.OreSageAdminUsers?.mount({api});
window.OreSageAdminUsage?.mount({api});
window.OreSageSharedKnowledge?.mount({api});
window.OreSagePassword?.mount({api, identity:()=>state.me, showLogin, openCurrentPassword});
window.OreSageEmail?.mount({api, initialize, showLogin});
if (window.OreSageEmail?.active) { $('auth-submit').disabled = false; }
else initialize().catch(()=>showLogin());
setInterval(() => { if (!document.hidden) refreshActiveTasks().catch(() => {}); }, 5000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshActiveTasks().catch(() => {}); });
