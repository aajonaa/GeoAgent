'use strict';
// No credentials, remote origin, HTML injection or localStorage.
(() => {
  const dialog = $('account-settings-dialog');
  const section = element('section', undefined, 'memorax-settings');
  section.setAttribute('aria-labelledby', 'memorax-heading');
  const heading = element('h3', '长期记忆 · MemoraX'); heading.id = 'memorax-heading';
  const copy = element('p', '按账号隔离。召回内容只作为参考，不是执行证据。当前问题会用于记忆检索；召回内容会发给所选模型，并可能进入现有追踪记录。', 'account-settings-note');
  const toggleLabel = element('label', undefined, 'memorax-toggle');
  const enabled = element('input'); enabled.type = 'checkbox'; enabled.id = 'memorax-enabled';
  toggleLabel.append(enabled, element('span', '启用当前账号的长期记忆'));
  const autoLabel = element('label', undefined, 'memorax-toggle');
  const automatic = element('input'); automatic.type = 'checkbox'; automatic.id = 'memorax-automatic';
  autoLabel.append(automatic, element('span', '自动延续长对话，并记住新任务中的偏好和决定'));
  const autoCopy = element('p', '一次开启，无需逐条确认。仅处理此后启动的新任务：所选模型在后台整理本地摘要，只有能匹配你原话的少量信息会写入 MemoraX。不会回填旧对话、上传论文或文件；可能增加模型调用费用。关闭后不再发起新的写入，已发出的请求可能仍会完成。', 'account-settings-note');
  const projectLabel = element('label', '项目标识', 'memorax-label'); projectLabel.htmlFor = 'memorax-project';
  const project = element('input'); project.id = 'memorax-project'; project.maxLength = 64; project.pattern = '[a-z0-9][a-z0-9_-]{0,63}'; project.autocomplete = 'off';
  const scope = element('p', '账号相互隔离。项目标识支持小写字母、数字、短横线和下划线。对话首次使用记忆后绑定项目；修改这里仅影响尚未绑定的新对话。', 'account-settings-note');
  const save = element('button', '保存记忆设置', 'account-settings-save'); save.type = 'button';
  const separator = element('hr');
  const manual = element('details'); manual.append(element('summary', '手动补充记忆（可选）'));
  const noteLabel = element('label', '补充一条明确的偏好或决定', 'memorax-label'); noteLabel.htmlFor = 'memorax-note';
  const note = element('textarea'); note.id = 'memorax-note'; note.rows = 3; note.maxLength = 4000;
  note.placeholder = '例如：本项目地图使用中文标注。不要填写密码、Token、整段对话或论文正文。';
  const kindLabel = element('label', '内容类型', 'memorax-label'); kindLabel.htmlFor = 'memorax-kind';
  const kind = element('select'); kind.id = 'memorax-kind';
  for (const [value, label] of [['preference', '用户偏好'], ['decision', '已确认的任务决定']]) {
    const option = element('option', label); option.value = value; kind.append(option);
  }
  const approvalLabel = element('label', undefined, 'memorax-toggle');
  const approved = element('input'); approved.type = 'checkbox';
  approvalLabel.append(approved, element('span', '我确认仅将以上文字保存到当前对话所属项目'));
  const remember = element('button', '批准并保存这条记忆', 'account-settings-reset'); remember.type = 'button';
  const status = element('p', '', 'account-settings-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  manual.append(noteLabel, note, kindLabel, kind, approvalLabel, remember);
  section.append(heading, copy, toggleLabel, autoLabel, autoCopy, projectLabel, project, scope, save, separator, manual,
    element('p', '摘要不替代原始记录。保存结果未知时不会自动重发。关闭不会删除已有记忆；远端删除、导出及保留策略尚未接入。', 'account-settings-note'), status);
  dialog.querySelector('form').append(section);
  const style = element('link'); style.rel = 'stylesheet'; style.href = '/assets/memorax.css?v=20261024'; document.head.append(style);
  let current = null, epoch = 0, busy = false, approvalId = null;
  function waiting(value) {
    busy = value; section.setAttribute('aria-busy', String(value));
    for (const control of [enabled, automatic, project, save, note, kind, approved, remember]) control.disabled = value;
  }
  function resetApproval() { approvalId = null; approved.checked = false; }
  note.addEventListener('input', resetApproval); kind.addEventListener('change', resetApproval);
  async function load() {
    if (!state.me || busy) return;
    const version = ++epoch, uid = state.me.id;
    waiting(true); status.textContent = '';
    try {
      const value = await api('/api/settings/memory');
      if (epoch !== version || state.me?.id !== uid) return;
      current = value; enabled.checked = value.enabled; automatic.checked = value.automatic_enabled; project.value = value.project_id;
      status.textContent = value.configured ? '服务端配置已存在，尚不代表连接已通过测试。' : '服务端尚未配置 MemoraX 密钥，启用后也不会伪造召回。';
    } catch (error) { if (epoch === version && state.me?.id === uid) status.textContent = error.message; }
    finally { if (epoch === version) waiting(false); }
  }
  $('account-settings-button').addEventListener('click', load);
  save.addEventListener('click', async () => {
    if (busy || !current || !state.me) return;
    if (!project.value || !project.checkValidity()) { project.reportValidity(); return; }
    const uid = state.me.id, version = epoch; waiting(true);
    try {
      const value = await api('/api/settings/memory', {method: 'PUT', body: {
        enabled: enabled.checked, automatic_enabled: automatic.checked, project_id: project.value, revision: current.revision}});
      if (epoch !== version || state.me?.id !== uid) return;
      current = value; automatic.checked = value.automatic_enabled;
      status.textContent = value.automatic_enabled ? '自动记忆已开启，仅处理此后启动的新任务。没有回填历史记录。' : '记忆设置已保存。自动记忆已关闭，没有上传对话或文件。'; resetApproval();
    } catch (error) { if (epoch === version && state.me?.id === uid) status.textContent = error.message; }
    finally { if (epoch === version) waiting(false); }
  });
  remember.addEventListener('click', async () => {
    if (busy || !state.me || !current) return;
    if (!current.enabled || !state.cid || !note.value.trim() || !approved.checked) {
      status.textContent = '请先保存启用设置、打开对话，并勾选这条文字的明确授权。'; return;
    }
    const uid = state.me.id, cid = state.cid, version = epoch;
    approvalId ||= crypto.randomUUID(); waiting(true);
    try {
      const result = await api(`/api/conversations/${cid}/memory/approve`, {method: 'POST', body: {
        approved: true, approval_id: approvalId, kind: kind.value, text: note.value}});
      if (epoch !== version || state.me?.id !== uid || state.cid !== cid) return;
      if (result.status === 'completed') {
        note.value = ''; resetApproval(); status.textContent = '已确认保存到项目 ' + result.project_id + '。这不是科学执行证据。';
      } else {
        status.textContent = '保存状态：' + result.status + '。不会自动重复写入；请保留回执并由管理员核对。请求 ID：' + (result.request_id || result.approval_id);
      }
    } catch (error) {
      if (epoch === version && state.me?.id === uid) status.textContent = error.message + '；再次点击沿用同一授权 ID，不会自动重复写入。';
    } finally { if (epoch === version) waiting(false); }
  });
  const clearDefaults = window.GeoAgentDefaults.clear;
  window.GeoAgentDefaults.clear = () => {
    epoch++; current = null; approvalId = null; waiting(false);
    enabled.checked = false; automatic.checked = false; project.value = ''; note.value = ''; approved.checked = false; status.textContent = '';
    clearDefaults();
  };
})();
