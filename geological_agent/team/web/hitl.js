/* Task-bound human input. No global questions, push permissions, or model polling. */
(() => {
  const drafts = new Map(), cards = new Map();
  let cid = null, version = 0, loading = false, inFlight = null, entries = [];
  let disposed = false, loadError = false;
  const ordinaryPlaceholder = $('prompt').placeholder;
  const hint = element('p', '', 'hitl-composer-hint');
  hint.hidden = true; hint.setAttribute('role', 'status'); $('composer').before(hint);

  function draftFor(id) {
    if (!drafts.has(id)) drafts.set(id, {text:'', option:'', files:[], sending:false});
    return drafts.get(id);
  }
  function pendingHere() { return entries.some(item => item.state === 'pending'); }
  function blocksComposer() { return loading || pendingHere(); }
  function syncComposer() {
    const blocked = blocksComposer(), active = Boolean(state.busy);
    $('prompt').disabled = blocked || active;
    $('send').disabled = blocked || active;
    $('attach').disabled = blocked || active;
    $('upload-button').disabled = blocked || active;
    $('prompt').placeholder = blocked ? '请在上方的补充信息卡片中回复；新问题请新建对话。' : ordinaryPlaceholder;
    hint.hidden = !blocked;
    hint.textContent = loadError ? '补充信息状态读取失败，请重新打开这段对话后回复。' : loading ? '正在读取这段对话的待回复问题…' : '当前任务已暂停。请在对应卡片中回复，不会另建任务。';
  }
  function validView(item, v) {
    return !disposed && state.me && state.cid === item.cid && cid === item.cid && version === v;
  }
  function selectConversation(next) {
    cid = next; version++; loading = Boolean(next); loadError = false; entries = [];
    for (const card of cards.values()) card.node.remove();
    cards.clear(); inFlight = null; syncComposer(); refresh();
  }
  function reset() {
    disposed = true; selectConversation(null); drafts.clear();
    disposed = false;
  }
  function button(label, className='outline') {
    const node = element('button', label, className); node.type = 'button'; return node;
  }
  function cardFor(item) {
    const history = item.state !== 'pending';
    const node = element(history ? 'details' : 'section', undefined, 'hitl-card' + (history ? ' hitl-resolved' : ''));
    node.dataset.inputRequestId = item.id; node.dataset.conversationId = item.cid; node.dataset.runId = item.rid;
    const title = element(history ? 'summary' : 'h3', history ?
      ({resuming:'已回复，任务继续中', answered:'已回复', cancelled:'已结束此任务', interrupted:'上次恢复已中断'}[item.state] || '问题已关闭') : '需要你补充信息');
    const titleId = 'hitl-title-' + item.id; title.id = titleId;
    node.setAttribute('aria-labelledby', titleId);
    const header = element('div', undefined, 'hitl-header');
    if (history) node.append(title);
    else { header.append(title, element('span', '任务已暂停', 'badge')); node.append(header); }
    node.append(element('p', item.question, 'hitl-question'));
    if (item.reason && item.reason !== item.question) node.append(element('p', item.reason, 'hitl-reason'));
    if (item.missing?.length) node.append(element('p', '需要补充：' + item.missing.join('；'), 'hitl-missing'));
    if (history) return {node, item};

    const draft = draftFor(item.id), v = version;
    const form = element('form', undefined, 'hitl-form');
    const options = element('div', undefined, 'hitl-options');
    options.setAttribute('role', 'group'); options.setAttribute('aria-label', '可选回应');
    const optionButtons = [];
    for (const value of item.options || []) {
      const choice = button(String(value), 'hitl-option');
      choice.setAttribute('aria-pressed', String(draft.option === value));
      choice.addEventListener('click', () => {
        draft.option = draft.option === value ? '' : value;
        for (const [control, option] of optionButtons) control.setAttribute('aria-pressed', String(draft.option === option));
      });
      optionButtons.push([choice, value]); options.append(choice);
    }
    if (optionButtons.length) form.append(options);
    const label = element('label', '补充说明（也可以不选选项，直接回答）');
    const input = element('textarea'); input.rows = 3; input.maxLength = 20000;
    input.id = 'hitl-text-' + item.id; label.htmlFor = input.id;
    input.placeholder = '输入你的回答，或添加所需材料…'; input.value = draft.text;
    input.addEventListener('input', () => { draft.text = input.value; });
    form.append(label, input);
    const files = element('div', undefined, 'hitl-files');
    files.setAttribute('aria-label', '本次补充的附件');
    const picker = element('input'); picker.type = 'file'; picker.multiple = true; picker.hidden = true;
    picker.setAttribute('aria-label', '为此问题添加附件');
    const error = element('p', '', 'error'); error.setAttribute('role', 'alert');
    const status = element('p', '', 'hitl-status'); status.setAttribute('role', 'status');
    const actions = element('div', undefined, 'hitl-actions');
    const add = button('添加附件'), cancel = button('结束此任务', 'quiet hitl-cancel');
    const submit = element('button', '提交并继续', 'primary'); submit.type = 'submit';
    actions.append(add, cancel, submit);
    const confirmation = element('div', undefined, 'hitl-confirm'); confirmation.hidden = true;
    const confirm = button('确认结束', 'outline'), back = button('返回', 'quiet');
    confirmation.append(element('p', '结束后不再恢复这个问题，已保存的文件会保留。'), back, confirm);
    form.append(files, picker, error, status, actions, confirmation);
    node.append(form, element('p', '回复只用于这条任务。暂停期间不会继续调用模型；提交后从保存的位置继续。', 'hitl-footnote'));

    function controls(disabled) {
      for (const control of form.querySelectorAll('button, textarea, input')) control.disabled = disabled;
    }
    function drawFiles() {
      files.replaceChildren();
      for (const record of draft.files) {
        const row = element('div', undefined, 'hitl-file');
        row.append(element('span', record.file.name + (record.uploaded ? ' · 已加入任务' : ' · 待上传')));
        if (!record.uploaded) {
          const remove = button('移除', 'quiet');
          remove.setAttribute('aria-label', '移除附件 ' + record.file.name);
          remove.disabled = draft.sending;
          remove.addEventListener('click', () => { draft.files = draft.files.filter(value => value !== record); drawFiles(); });
          row.append(remove);
        }
        files.append(row);
      }
    }
    add.addEventListener('click', () => picker.click());
    picker.addEventListener('change', () => {
      error.textContent = '';
      for (const file of picker.files) {
        if (file.size > 8 * 1024 * 1024) { error.textContent = '单个附件不能超过 8 MiB：' + file.name; continue; }
        if (draft.files.some(record => record.file.name === file.name)) {
          error.textContent = '已有同名附件，请先移除后再选择：' + file.name; continue;
        }
        draft.files.push({file, uploaded:false});
      }
      picker.value = ''; drawFiles();
    });
    cancel.addEventListener('click', () => { confirmation.hidden = false; confirm.focus(); });
    back.addEventListener('click', () => { confirmation.hidden = true; cancel.focus(); });
    confirm.addEventListener('click', async () => {
      if (draft.sending || !validView(item, v)) return;
      draft.sending = true; controls(true); error.textContent = ''; status.textContent = '正在结束此任务…';
      try {
        await api('/api/hitl/requests/' + encodeURIComponent(item.id) + '/cancel', {method:'POST'});
        drafts.delete(item.id);
        if (validView(item, v)) await openConversation(item.cid);
      } catch (e) { error.textContent = e.message; status.textContent = ''; }
      finally { draft.sending = false; controls(false); if (validView(item, v)) refresh(); }
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (draft.sending || !validView(item, v)) return;
      const answer = [draft.option, draft.text.trim()].filter(Boolean).join('\n');
      if (!answer && !draft.files.length) { error.textContent = '请选择一个选项、填写回答或添加附件。'; input.focus(); return; }
      const fileNote = draft.files.length ? '\n已补充附件：' + draft.files.map(record => record.file.name).join('、') : '';
      const text = (answer + fileNote).trim();
      if (text.length > 20000) { error.textContent = '回答及附件说明合计不能超过 20,000 字符。'; return; }
      draft.sending = true; controls(true); error.textContent = '';
      try {
        for (const record of draft.files) {
          if (record.uploaded) continue;
          status.textContent = '正在上传：' + record.file.name;
          const path = '/api/hitl/requests/' + encodeURIComponent(item.id) + '/upload?cid=' +
            encodeURIComponent(item.cid) + '&rid=' + encodeURIComponent(item.rid) + '&name=' + encodeURIComponent(record.file.name);
          await api(path, {method:'POST', body:record.file, headers:{'Content-Type':'application/octet-stream'}});
          record.uploaded = true; drawFiles();
        }
        status.textContent = '正在提交回复…';
        await api('/api/hitl/requests/' + encodeURIComponent(item.id) + '/reply',
          {method:'POST', body:{cid:item.cid, rid:item.rid, text}});
        status.textContent = '已回复，正在继续任务。'; drafts.delete(item.id);
        if (validView(item, v)) await openConversation(item.cid);
      } catch (e) {
        error.textContent = e.message + '。未发送的回答仍保留；如提交结果不确定，请刷新此对话查看状态。';
        status.textContent = '';
      } finally { draft.sending = false; controls(false); if (validView(item, v)) refresh(); }
    });
    drawFiles(); controls(draft.sending);
    return {node, item};
  }
  function attachCards() {
    for (const item of entries) {
      if (item.cid !== cid || state.cid !== cid) continue;
      const ui = state.runs.get(item.rid); if (!ui) continue;
      let card = cards.get(item.id);
      if (!card || JSON.stringify(card.item) !== JSON.stringify(item)) {
        if (card) card.node.remove();
        card = cardFor(item); cards.set(item.id, card);
      }
      if (card.node.parentNode !== ui.turn) ui.turn.append(card.node);
    }
    syncComposer();
  }
  async function refresh(suspendComposer = false) {
    if (suspendComposer === true) { loading = true; syncComposer(); }
    if (disposed || !state.me || !cid || state.cid !== cid || document.hidden) return;
    const selected = cid, v = version, uid = state.me.id || state.me.username;
    if (inFlight?.version === v) return;
    const ticket = {version:v}; inFlight = ticket;
    try {
      const result = await api('/api/hitl/requests?cid=' + encodeURIComponent(selected));
      if (version !== v || state.cid !== selected || (state.me?.id || state.me?.username) !== uid) return;
      entries = result.enabled ? [...(result.requests || []), ...(result.history || [])].filter(item => item.cid === selected) : [];
      const alive = new Set(entries.map(item => item.id));
      for (const [id, card] of cards) if (!alive.has(id)) { card.node.remove(); cards.delete(id); }
      loading = false; loadError = false; attachCards();
    } catch (e) {
      if (version === v && state.cid === selected) { loading = true; loadError = true; }
    } finally {
      if (inFlight === ticket) inFlight = null;
      if (version === v) syncComposer();
    }
  }
  window.GeoToolHITL = {selectConversation, attachCards, refresh, reset, syncComposer, blocksComposer};
  selectConversation(state.cid);
  setInterval(refresh, 5000);
  document.addEventListener('visibilitychange', refresh);
})();
