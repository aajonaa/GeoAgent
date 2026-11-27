'use strict';
(() => {
  const views = new Map();
  const node = (tag, text, className) => {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    return item;
  };
  const specs = {
    completed: {
      state:'completed', title:'本轮已完成 · 可继续推进',
      detail:'可继续追问，或基于本轮答复和已保存成果生成新内容。',
      actions:[['follow_up','继续追问'],['derive','基于成果生成']]
    },
    stopped: {
      state:'stopped', title:'任务已停止 · 已有记录保留',
      detail:'续写会先核对执行详情和已保存文件，再处理未完成部分。',
      actions:[['resume','从停止位置继续']]
    },
    failed: {
      state:'failed', title:'执行失败 · 可保留上下文重试',
      detail:'失败原因保留在上方；重试会新建运行，不改写本次记录。',
      actions:[['retry','保留上下文重试']]
    },
    incomplete: {
      state:'partial', title:'部分完成 · 仍有未完成事项',
      detail:'', actions:[['inspect','查看未完成项'],['resume','继续未完成部分']]
    },
    budget_exhausted: {
      state:'partial', title:'预算已耗尽 · 尚未完整交付',
      detail:'', actions:[['inspect','查看未完成项'],['resume','继续未完成部分']]
    },
    interrupted: {
      state:'partial', title:'执行中断 · 保留已有进展',
      detail:'', actions:[['inspect','查看未完成项'],['resume','继续未完成部分']]
    }
  };
  function describe(ui) {
    const status = ui.status === 'cancelled' ? 'stopped' : ui.status;
    const spec = specs[status];
    if (!spec) return null;
    if (!spec.detail && ui.overview?.openItems?.hidden === false) {
      const count = ui.overview.openSummary?.textContent || '未完成事项';
      return {...spec, detail:'已加载记录中显示“' + count + '”；完整清单见执行详情。'};
    }
    return {...spec, detail:spec.detail || '具体未完成项见执行详情；尚未加载的记录不作推断。'};
  }
  function sync() {
    for (const view of views.values()) {
      const blocked = view.hooks.blocked();
      for (const button of view.buttons.values()) button.disabled = blocked || view.pending === button.dataset.action;
    }
  }
  function paint(view) {
    const {ui, hooks, box} = view, spec = describe(ui);
    box.hidden = !ui.finished || !spec;
    box.dataset.state = spec?.state || '';
    if (!spec) return;
    const signature = JSON.stringify([spec, ui.overview?.openItems?.hidden, ui.overview?.openSummary?.textContent]);
    if (view.signature === signature) { sync(); return; }
    view.signature = signature;
    const header = node('div', undefined, 'run-recovery-heading');
    header.append(node('strong', spec.title), node('p', spec.detail));
    const actions = node('div', undefined, 'run-recovery-actions');
    const status = node('span', '', 'run-recovery-status');
    status.setAttribute('role', 'status');
    view.buttons.clear();
    for (const [action, label] of spec.actions) {
      const button = node('button', label, action === 'inspect' ? 'quiet' : 'outline');
      button.type = 'button'; button.dataset.action = action;
      button.addEventListener('click', async () => {
        if (hooks.blocked() || view.pending) return;
        if (action === 'inspect') {
          hooks.inspect(ui);
          status.textContent = '未完成项已展开；记录较多时可继续加载。';
          return;
        }
        view.pending = action; button.disabled = true; status.textContent = '正在核对原运行并准备草稿…';
        try {
          const prepared = await hooks.compose(ui.runId, action);
          status.textContent = prepared === false ? '对话已切换，未填入草稿。' : '草稿已准备，请编辑后确认研究计划并发送。';
        } catch (error) {
          status.textContent = '准备失败：' + (error?.message || '请稍后重试。');
        } finally {
          view.pending = null; sync();
        }
      });
      actions.append(button); view.buttons.set(action, button);
    }
    actions.append(status);
    const note = node('p', '动作只准备输入；确认研究计划并发送后，将在同一对话新建运行。原运行和成果版本保留。', 'run-recovery-note');
    box.replaceChildren(header, actions, note);
    sync();
  }
  function attach(rid, ui, hooks) {
    if (ui.recovery) return;
    ui.runId = rid;
    const box = node('section', undefined, 'run-recovery');
    box.setAttribute('aria-label', '终态恢复与下一步动作');
    if (ui.replyActions) ui.replyActions.before(box);
    else ui.reason.after(box);
    const view = ui.recovery = {ui, hooks, box, buttons:new Map(), signature:'', pending:null};
    views.set(rid, view); paint(view);
  }
  function event(rid) {
    const view = views.get(rid);
    if (view) paint(view);
  }
  window.GeoAgentRecovery = {attach, event, sync, reset() { views.clear(); }};
})();
