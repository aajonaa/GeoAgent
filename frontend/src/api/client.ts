import type { AuthSession } from '../types/api';

export interface ApiRequestOptions extends Omit<RequestInit, 'body' | 'headers'> {
  headers?: Record<string, string>;
  body?: BodyInit | Record<string, unknown> | null;
  timeoutMs?: number;
}

export interface ApiClientHooks {
  getSession: () => AuthSession | null;
  setSession: (session: AuthSession | null) => void;
  onUnauthorized?: (reason?: string) => void;
  onAccountChanged?: (message: string) => void;
  fetchImpl?: typeof fetch;
}

export class ApiError extends Error {
  status: number;
  code?: string;
  activeConversation: string | null;
  retryAfter: number | null;

  constructor(
    message: string,
    opts: {
      status: number;
      code?: string;
      activeConversation?: string | null;
      retryAfter?: number | null;
    },
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = opts.status;
    this.code = opts.code;
    this.activeConversation = opts.activeConversation ?? null;
    this.retryAfter = opts.retryAfter ?? null;
  }
}

const READ_ONLY_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

function isPlainJsonBody(body: ApiRequestOptions['body']): body is Record<string, unknown> {
  if (!body || typeof body !== 'object') return false;
  if (typeof File !== 'undefined' && body instanceof File) return false;
  if (typeof Blob !== 'undefined' && body instanceof Blob) return false;
  if (typeof FormData !== 'undefined' && body instanceof FormData) return false;
  if (body instanceof ArrayBuffer || ArrayBuffer.isView(body)) return false;
  if (typeof URLSearchParams !== 'undefined' && body instanceof URLSearchParams) return false;
  return true;
}

/**
 * Strongly-typed OreBOGAO HTTP client preserving same-origin cookie auth,
 * CSRF token injection, single automatic CSRF resync on cross-tab cookie rotation,
 * and account-change detection.
 */
export function createApiClient(hooks: ApiClientHooks) {
  const fetchFn = hooks.fetchImpl ?? globalThis.fetch.bind(globalThis);

  async function request<T = unknown>(path: string, options: ApiRequestOptions = {}): Promise<T> {
    const { timeoutMs, headers: inputHeaders, body: inputBody, ...rest } = options;
    const controller = timeoutMs ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;

    const headers: Record<string, string> = { ...(inputHeaders ?? {}) };
    const method = (rest.method ?? 'GET').toUpperCase();
    const isMutation = !READ_ONLY_METHODS.has(method);
    const currentSession = hooks.getSession();
    const identity = currentSession ? { id: currentSession.id, role: currentSession.role } : null;

    if (isMutation && currentSession) {
      headers['X-CSRF-Token'] = currentSession.csrf;
    }

    let serializedBody: BodyInit | null | undefined;
    if (isPlainJsonBody(inputBody)) {
      headers['Content-Type'] = 'application/json';
      serializedBody = JSON.stringify(inputBody);
    } else {
      serializedBody = inputBody;
    }

    let response!: Response;
    let payload: Record<string, unknown> = {};

    try {
      for (let attempt = 0; attempt < 2; attempt += 1) {
        response = await fetchFn(path, {
          ...rest,
          method,
          headers,
          body: serializedBody,
          signal: controller ? controller.signal : rest.signal,
          credentials: 'same-origin',
        });

        try {
          const parsed: unknown = await response.json();
          payload = parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : {};
        } catch (err) {
          if (err instanceof Error && err.name === 'AbortError') throw err;
          payload = {};
        }

        if (
          attempt !== 0 ||
          !isMutation ||
          !identity ||
          response.status !== 403 ||
          payload.detail !== 'CSRF validation failed'
        ) {
          break;
        }

        const refreshed = await request<AuthSession>('/api/me', {
          timeoutMs: Math.min(timeoutMs ?? 10_000, 10_000),
        });
        const live = hooks.getSession();
        if (
          !live ||
          live.id !== identity.id ||
          live.role !== identity.role ||
          refreshed.id !== identity.id ||
          refreshed.role !== identity.role
        ) {
          const msg = '登录账号或权限已在其他页面变化，请重新登录后操作。';
          hooks.onAccountChanged?.(msg);
          throw new ApiError(msg, { status: 409, code: 'account_changed' });
        }
        if (
          typeof refreshed.csrf !== 'string' ||
          !refreshed.csrf ||
          refreshed.csrf === headers['X-CSRF-Token']
        ) {
          break;
        }
        hooks.setSession(refreshed);
        headers['X-CSRF-Token'] = refreshed.csrf;
      }
    } finally {
      if (timer !== null) clearTimeout(timer);
    }

    if (!response.ok) {
      if (response.status === 401 && hooks.getSession()) {
        hooks.onUnauthorized?.('session_expired');
      }
      const detail = typeof payload.detail === 'string' ? payload.detail : '';
      const message =
        detail === 'CSRF validation failed'
          ? '登录校验未通过，请刷新页面后重试。'
          : detail || `HTTP ${response.status}`;
      const retryAfterHeader = response.headers.get('Retry-After');
      throw new ApiError(message, {
        status: response.status,
        code: typeof payload.code === 'string' ? payload.code : undefined,
        activeConversation: response.headers.get('X-Active-Conversation'),
        retryAfter: retryAfterHeader ? Number(retryAfterHeader) || null : null,
      });
    }

    return payload as T;
  }

  return { request };
}
