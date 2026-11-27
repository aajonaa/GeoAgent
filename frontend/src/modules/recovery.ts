import type { RecoveryAction, RecoverySpec, RunStatus } from '../types/api';

/**
 * Typed terminal-state recovery module matching `window.GeoAgentRecovery`.
 */

export interface RecoveryRunUi {
  runId?: string;
  status: RunStatus | string;
  finished: boolean;
  replyActions?: Element | null;
  reason: Element;
  overview?: {
    openItems?: { hidden?: boolean } | null;
    openSummary?: { textContent?: string | null } | null;
  } | null;
  recovery?: RecoveryView;
}

export interface RecoveryHooks {
  blocked: () => boolean;
  inspect: (ui: RecoveryRunUi) => void;
  compose: (runId: string | undefined, action: RecoveryAction) => Promise<boolean | void>;
}

export interface RecoveryView {
  ui: RecoveryRunUi;
  hooks: RecoveryHooks;
  box: HTMLElement;
  buttons: Map<RecoveryAction, HTMLButtonElement>;
  signature: string;
  pending: RecoveryAction | null;
}

export interface RecoveryController {
  attach: (rid: string, ui: RecoveryRunUi, hooks: RecoveryHooks) => void;
  event: (rid: string) => void;
  sync: () => void;
  reset: () => void;
}

export const RECOVERY_SPECS: Record<string, RecoverySpec> = {
  completed: {
    state: 'completed',
    title: '本轮已完成 · 可继续推进',
    detail: '可继续追问，或基于本轮答复和已保存成果生成新内容。',
    actions: [
      ['follow_up', '继续追问'],
      ['derive', '基于成果生成'],
    ],
  },
  stopped: {
    state: 'stopped',
    title: '任务已停止 · 已有记录保留',
    detail: '续写会先核对执行详情和已保存文件，再处理未完成部分。',
    actions: [['resume', '从停止位置继续']],
  },
  failed: {
    state: 'failed',
    title: '执行失败 · 可保留上下文重试',
    detail: '失败原因保留在上方；重试会新建运行，不改写本次记录。',
    actions: [['retry', '保留上下文重试']],
  },
  incomplete: {
    state: 'partial',
    title: '部分完成 · 仍有未完成事项',
    detail: '',
    actions: [
      ['inspect', '查看未完成项'],
      ['resume', '继续未完成部分'],
    ],
  },
  budget_exhausted: {
    state: 'partial',
    title: '预算已耗尽 · 尚未完整交付',
    detail: '',
    actions: [
      ['inspect', '查看未完成项'],
      ['resume', '继续未完成部分'],
    ],
  },
  interrupted: {
    state: 'partial',
    title: '执行中断 · 保留已有进展',
    detail: '',
    actions: [
      ['inspect', '查看未完成项'],
      ['resume', '继续未完成部分'],
    ],
  },
};

export function describeRecovery(ui: Pick<RecoveryRunUi, 'status' | 'overview'>): RecoverySpec | null {
  const status = ui.status === 'cancelled' ? 'stopped' : ui.status;
  const spec = RECOVERY_SPECS[status];
  if (!spec) return null;
  if (!spec.detail && ui.overview?.openItems?.hidden === false) {
    const count = ui.overview.openSummary?.textContent || '未完成事项';
    return { ...spec, detail: `已加载记录中显示“${count}”；完整清单见执行详情。` };
  }
  return { ...spec, detail: spec.detail || '具体未完成项见执行详情；尚未加载的记录不作推断。' };
}

function createNode<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  text?: string,
  className?: string,
): HTMLElementTagNameMap[K] {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}

export function createRecoveryController(): RecoveryController {
  const views = new Map<string, RecoveryView>();

  function sync(): void {
    for (const view of views.values()) {
      const blocked = view.hooks.blocked();
      for (const button of view.buttons.values()) {
        button.disabled = blocked || view.pending === button.dataset.action;
      }
    }
  }

  function paint(view: RecoveryView): void {
    const { ui, hooks, box } = view;
    const spec = describeRecovery(ui);
    box.hidden = !ui.finished || !spec;
    box.dataset.state = spec?.state ?? '';
    if (!spec) return;

    const signature = JSON.stringify([
      spec,
      ui.overview?.openItems?.hidden,
      ui.overview?.openSummary?.textContent,
    ]);
    if (view.signature === signature) {
      sync();
      return;
    }
    view.signature = signature;

    const header = createNode('div', undefined, 'run-recovery-heading');
    header.append(createNode('strong', spec.title), createNode('p', spec.detail));

    const actions = createNode('div', undefined, 'run-recovery-actions');
    const status = createNode('span', '', 'run-recovery-status');
    status.setAttribute('role', 'status');
    view.buttons.clear();

    for (const [action, label] of spec.actions) {
      const button = createNode('button', label, action === 'inspect' ? 'quiet' : 'outline');
      button.type = 'button';
      button.dataset.action = action;
      button.addEventListener('click', async () => {
        if (hooks.blocked() || view.pending) return;
        if (action === 'inspect') {
          hooks.inspect(ui);
          status.textContent = '未完成项已展开；记录较多时可继续加载。';
          return;
        }
        view.pending = action;
        button.disabled = true;
        status.textContent = '正在核对原运行并准备草稿…';
        try {
          const prepared = await hooks.compose(ui.runId, action);
          status.textContent =
            prepared === false
              ? '对话已切换，未填入草稿。'
              : '草稿已准备，请编辑后确认研究计划并发送。';
        } catch (err) {
          const msg = err instanceof Error ? err.message : '';
          status.textContent = `准备失败：${msg || '请稍后重试。'}`;
        } finally {
          view.pending = null;
          sync();
        }
      });
      actions.append(button);
      view.buttons.set(action, button);
    }

    actions.append(status);
    const note = createNode(
      'p',
      '动作只准备输入；确认研究计划并发送后，将在同一对话新建运行。原运行和成果版本保留。',
      'run-recovery-note',
    );
    box.replaceChildren(header, actions, note);
    sync();
  }

  function attach(rid: string, ui: RecoveryRunUi, hooks: RecoveryHooks): void {
    if (ui.recovery) return;
    ui.runId = rid;
    const box = createNode('section', undefined, 'run-recovery');
    box.setAttribute('aria-label', '终态恢复与下一步动作');
    if (ui.replyActions) ui.replyActions.before(box);
    else ui.reason.after(box);

    const view: RecoveryView = {
      ui,
      hooks,
      box,
      buttons: new Map(),
      signature: '',
      pending: null,
    };
    ui.recovery = view;
    views.set(rid, view);
    paint(view);
  }

  function event(rid: string): void {
    const view = views.get(rid);
    if (view) paint(view);
  }

  function reset(): void {
    views.clear();
  }

  return { attach, event, sync, reset };
}
