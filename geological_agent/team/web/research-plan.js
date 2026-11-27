'use strict';
(() => {
  const byId = id => document.getElementById(id);
  const dialog = byId('plan-dialog'), form = byId('plan-form'), error = byId('plan-error');
  const definitions = [
    ['objective', '研究目标'], ['scope', '研究范围'], ['materials', '资料与数据'],
    ['tools', '工具与技能'], ['deliverables', '预期成果']
  ];
  const defaults = {
    objective: '', scope: '围绕研究问题确定；无额外限制',
    materials: '可使用已上传文件、知识库与公开资料', tools: '由 Agent 按需选择技能与工具',
    deliverables: '给出结论、关键证据与结果文件（如适用）',
    acceptance: ['结论回应研究问题', '关键判断引用可追溯来源', '说明数据或方法局限']
  };
  let scope = 'plan:new', pending = null, opening = null, objectiveEdited = false;

  function node(tag, text, className) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    return item;
  }
  function nextScope(cid) { return 'plan:' + (cid || 'new'); }
  function readDraft() {
    try {
      const value = JSON.parse(window.OreSageDrafts?.text(scope, 'plan') || 'null');
      return value && typeof value === 'object' && value.plan && typeof value.plan === 'object' ? value : null;
    } catch (_) { return null; }
  }
  function clearDraft(target) { if (target) window.OreSageDrafts?.clear(target); }
  function fill(plan) {
    for (const [field] of definitions) byId('plan-' + field).value = typeof plan[field] === 'string' ? plan[field] : '';
    byId('plan-acceptance').value = Array.isArray(plan.acceptance) ? plan.acceptance.join('\n') : '';
  }
  function collect() {
    const plan = {};
    for (const [field] of definitions) plan[field] = byId('plan-' + field).value.trim();
    plan.acceptance = byId('plan-acceptance').value.split('\n').map(value => value.trim()).filter(Boolean);
    return plan;
  }
  function persist() {
    const plan = collect();
    window.OreSageDrafts?.save(scope, 'plan', JSON.stringify({query:opening?.query || '', objectiveEdited, plan}));
  }
  function invalid(message, id) {
    error.textContent = message;
    byId(id).focus();
    return false;
  }
  function validate(plan) {
    const limits = {objective:500, scope:1000, materials:1000, tools:500, deliverables:1000};
    for (const [field, label] of definitions) {
      if (!plan[field]) return invalid('请填写' + label + '后再确认。', 'plan-' + field);
      if (plan[field].length > limits[field]) return invalid(label + '不能超过 ' + limits[field] + ' 个字符。', 'plan-' + field);
    }
    if (!plan.acceptance.length) return invalid('请至少填写一条验收标准。', 'plan-acceptance');
    if (plan.acceptance.length > 5) return invalid('验收标准请控制在 5 条以内。', 'plan-acceptance');
    if (plan.acceptance.some(item => item.length > 300)) return invalid('每条验收标准不能超过 300 个字符。', 'plan-acceptance');
    return true;
  }
  function open(query, skillId) {
    if (dialog.open) return true;
    opening = {query, skillId:skillId || null};
    const saved = readDraft();
    objectiveEdited = saved?.objectiveEdited === true;
    const plan = saved?.plan || {...defaults};
    fill(plan);
    if (!objectiveEdited) byId('plan-objective').value = query;
    if (!saved?.plan && skillId) byId('plan-tools').value = '已选技能：' + skillId + '；可按需使用其他工具';
    error.textContent = '';
    dialog.showModal();
    byId('plan-objective').focus();
    return true;
  }
  function consume(query, skillId) {
    if (!pending) return null;
    if (pending.query !== query || pending.skillId !== (skillId || null)) { pending = null; return null; }
    return pending.plan;
  }
  function committed() {
    clearDraft(pending?.scope);
    clearDraft(scope);
    pending = null;
  }
  function receipt(plan) {
    if (!plan || typeof plan !== 'object' || !Array.isArray(plan.acceptance)) return null;
    const box = node('details', undefined, 'run-plan');
    box.dataset.planReceipt = '';
    const summary = node('summary', undefined, 'run-plan-summary');
    summary.append(node('span', '研究计划与验收标准 · 已确认'), node('small', '验收 ' + plan.acceptance.length + ' 项'));
    const body = node('div', undefined, 'run-plan-body'), list = node('dl');
    for (const [field, label] of definitions) {
      if (typeof plan[field] !== 'string' || !plan[field]) continue;
      const row = node('div', undefined, 'run-plan-field');
      row.append(node('dt', label), node('dd', plan[field]));
      list.append(row);
    }
    body.append(list, node('h3', '验收标准 · 随结果核对'));
    const acceptance = node('ol');
    for (const item of plan.acceptance) if (typeof item === 'string' && item) acceptance.append(node('li', item));
    body.append(acceptance);
    box.append(summary, body);
    return box;
  }

  for (const [field] of definitions) byId('plan-' + field).addEventListener('input', () => {
    if (field === 'objective') objectiveEdited = true;
    error.textContent = '';
    persist();
  });
  byId('plan-acceptance').addEventListener('input', () => { error.textContent = ''; persist(); });
  byId('plan-cancel').addEventListener('click', () => dialog.close());
  form.addEventListener('submit', event => {
    event.preventDefault();
    const plan = collect();
    if (!validate(plan)) return;
    pending = {...opening, plan, scope};
    persist();
    dialog.close();
    byId('composer').requestSubmit();
  });

  window.GeoAgentPlan = {
    open, consume, committed, receipt,
    selectConversation(cid) {
      if (dialog.open) dialog.close();
      const next = nextScope(cid);
      if (pending && pending.scope !== 'plan:new' && pending.scope !== next) pending = null;
      scope = next;
    },
    reset() { if (dialog.open) dialog.close(); pending = null; opening = null; scope = 'plan:new'; }
  };
})();
