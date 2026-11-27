import { describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  DEFAULT_RESEARCH_PLAN,
  PLAN_TEXT_LIMITS,
  createApiClient,
  createDraftsStore,
  createRecoveryController,
  describeRecovery,
  installLegacyGlobals,
  latestRequest,
  renderPlanReceipt,
  validateResearchPlan,
} from '../src/main';
import type { AuthSession, ResearchPlan } from '../src/types/api';

describe('presentationState', () => {
  it('tracks only the latest monotonic token', () => {
    const guard = latestRequest();
    const first = guard.begin();
    expect(guard.current(first)).toBe(true);
    const second = guard.begin();
    expect(guard.current(first)).toBe(false);
    expect(guard.current(second)).toBe(true);
  });
});

describe('createDraftsStore', () => {
  it('scopes drafts by user identity and flushes debounced writes', () => {
    localStorage.clear();
    const drafts = createDraftsStore({ debounceMs: 50, bindPageHide: false, idbFactory: null });

    // Anonymous user writes are ignored
    drafts.save('conv-1', 'text', 'ignored');
    drafts.flush();
    expect(drafts.text('conv-1', 'text')).toBe('');

    drafts.identity('user-a');
    drafts.save('conv-1', 'text', 'porphyry copper prospectivity');
    drafts.flush();
    expect(drafts.text('conv-1', 'text')).toBe('porphyry copper prospectivity');

    // Switching identity isolates drafts
    drafts.identity('user-b');
    expect(drafts.text('conv-1', 'text')).toBe('');

    drafts.identity('user-a');
    expect(drafts.text('conv-1', 'text')).toBe('porphyry copper prospectivity');
    drafts.clear('conv-1');
    expect(drafts.text('conv-1', 'text')).toBe('');
  });
});

describe('researchPlan', () => {
  it('validates default limits matching backend _PLAN_TEXT_LIMITS', () => {
    const validPlan: ResearchPlan = {
      ...DEFAULT_RESEARCH_PLAN,
      objective: '评估东昆仑地区斑岩型铜矿成矿潜力',
    };
    expect(validateResearchPlan(validPlan)).toEqual({ valid: true });

    const missingObjective: ResearchPlan = { ...validPlan, objective: '   ' };
    expect(validateResearchPlan(missingObjective)).toMatchObject({
      valid: false,
      fieldId: 'plan-objective',
    });

    const tooLong: ResearchPlan = {
      ...validPlan,
      objective: 'x'.repeat(PLAN_TEXT_LIMITS.objective + 1),
    };
    expect(validateResearchPlan(tooLong)).toMatchObject({
      valid: false,
      fieldId: 'plan-objective',
    });

    const tooManyAcceptance: ResearchPlan = {
      ...validPlan,
      acceptance: ['1', '2', '3', '4', '5', '6'],
    };
    expect(validateResearchPlan(tooManyAcceptance)).toMatchObject({
      valid: false,
      fieldId: 'plan-acceptance',
    });
  });

  it('renders a structured DOM receipt for confirmed research plans', () => {
    const plan: ResearchPlan = {
      ...DEFAULT_RESEARCH_PLAN,
      objective: '解析化探异常',
    };
    const receipt = renderPlanReceipt(plan);
    expect(receipt).not.toBeNull();
    expect(receipt?.tagName).toBe('DETAILS');
    expect(receipt?.textContent).toContain('解析化探异常');
    expect(receipt?.querySelectorAll('ol > li').length).toBe(3);
  });
});

describe('recovery', () => {
  it('maps cancelled to stopped and builds partial-state details', () => {
    expect(describeRecovery({ status: 'cancelled' })).toMatchObject({
      state: 'stopped',
      actions: [['resume', '从停止位置继续']],
    });
    expect(
      describeRecovery({
        status: 'incomplete',
        overview: {
          openItems: { hidden: false },
          openSummary: { textContent: '2 项待办' },
        },
      })?.detail,
    ).toContain('2 项待办');
  });

  it('attaches recovery actions and invokes hooks safely', async () => {
    const container = document.createElement('div');
    const reason = document.createElement('p');
    container.append(reason);
    const compose = vi.fn().mockResolvedValue(true);
    const inspect = vi.fn();
    const ctrl = createRecoveryController();

    ctrl.attach(
      'run-1',
      { status: 'completed', finished: true, reason },
      { blocked: () => false, inspect, compose },
    );

    const buttons = container.querySelectorAll<HTMLButtonElement>('button[data-action]');
    expect(buttons.length).toBe(2);
    buttons[0]?.click();
    await Promise.resolve();
    expect(compose).toHaveBeenCalledWith('run-1', 'follow_up');
  });
});

describe('createApiClient', () => {
  it('injects X-CSRF-Token on mutations and resyncs once on stale CSRF 403', async () => {
    let session: AuthSession | null = {
      id: 'u1',
      username: 'geo',
      role: 'member',
      csrf: 'old-csrf',
    };
    const calls: Array<{ url: string; csrf?: string }> = [];
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const headers = (init?.headers ?? {}) as Record<string, string>;
      calls.push({ url, csrf: headers['X-CSRF-Token'] });
      if (url === '/api/conversations' && headers['X-CSRF-Token'] === 'old-csrf') {
        return new Response(JSON.stringify({ detail: 'CSRF validation failed' }), {
          status: 403,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/me') {
        return new Response(
          JSON.stringify({ id: 'u1', username: 'geo', role: 'member', csrf: 'fresh-csrf' }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      return new Response(JSON.stringify({ id: 'cid-1' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    const client = createApiClient({
      getSession: () => session,
      setSession: (next) => {
        session = next;
      },
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    const created = await client.request<{ id: string }>('/api/conversations', {
      method: 'POST',
      body: { title: 'Test' },
    });

    expect(created).toEqual({ id: 'cid-1' });
    expect(session?.csrf).toBe('fresh-csrf');
    expect(calls).toEqual([
      { url: '/api/conversations', csrf: 'old-csrf' },
      { url: '/api/me', csrf: undefined },
      { url: '/api/conversations', csrf: 'fresh-csrf' },
    ]);
  });

  it('triggers onAccountChanged and throws 409 when another tab switched users', async () => {
    let session: AuthSession | null = { id: 'u1', username: 'geo', role: 'member', csrf: 'old' };
    const onAccountChanged = vi.fn();
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/me') {
        return new Response(
          JSON.stringify({ id: 'u2', username: 'other', role: 'member', csrf: 'new' }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      return new Response(JSON.stringify({ detail: 'CSRF validation failed' }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    const client = createApiClient({
      getSession: () => session,
      setSession: (next) => {
        session = next;
      },
      onAccountChanged,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    await expect(
      client.request('/api/conversations', { method: 'POST', body: {} }),
    ).rejects.toMatchObject({ name: 'ApiError', status: 409, code: 'account_changed' } satisfies Partial<ApiError>);
    expect(onAccountChanged).toHaveBeenCalledTimes(1);
  });

  it('installLegacyGlobals never overwrites pre-existing globals unless force=true', () => {
    const win = window as unknown as Record<string, unknown>;
    const sentinel = { latestRequest: () => ({ begin: () => 99, current: () => true }) };
    win.GeoPresentationState = sentinel;
    delete win.OreSageDrafts;
    delete win.GeoAgentRecovery;

    const installed = installLegacyGlobals();
    expect(win.GeoPresentationState).toBe(sentinel);
    expect(installed).toEqual(['OreSageDrafts', 'GeoAgentRecovery']);

    const forced = installLegacyGlobals({ force: true });
    expect(win.GeoPresentationState).not.toBe(sentinel);
    expect(forced).toEqual(['GeoPresentationState', 'OreSageDrafts', 'GeoAgentRecovery']);
  });
});
