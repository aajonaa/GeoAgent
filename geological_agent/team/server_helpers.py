"""Shared concurrency leases, plan/recovery validators, and deadline receipt helpers for team server."""
import re
from threading import Lock
from urllib.parse import parse_qsl, quote, urlsplit

from fastapi import HTTPException


class _ModelSlotLease:
    """One request's ownership of the existing shared semaphore, never a new pool."""

    def __init__(self, semaphore):
        self._semaphore = semaphore
        self._lock = Lock()
        self._state = 'new'

    def acquire(self, *args, **kwargs):
        with self._lock:
            if self._state != 'new':
                raise RuntimeError('Model slot lease was already acquired')
        acquired = self._semaphore.acquire(*args, **kwargs)
        if acquired:
            with self._lock:
                self._state = 'reserved'
        return acquired

    def claim(self):
        with self._lock:
            if self._state != 'reserved':
                return False
            self._state = 'running'
            return True

    def _release(self, expected):
        with self._lock:
            if self._state != expected:
                return False
            self._semaphore.release()
            self._state = 'released'
            return True

    def abort_start(self):
        return self._release('reserved')

    def release(self):
        return self._release('running')


class _TaskStartup:
    """Per-run claim/abort fence; it does not count or allocate execution slots."""

    def __init__(self, uid, rid):
        self.uid, self.rid = uid, rid
        self._lock = Lock()
        self._state = 'reserved'

    def claim(self):
        with self._lock:
            if self._state != 'reserved':
                return False
            self._state = 'worker_owned'
            return True

    def _abort(self, expected):
        with self._lock:
            if self._state != expected:
                return False
            self._state = 'aborted'
            return True

    def abort_start(self):
        return self._abort('reserved')

    def fail_initialization(self):
        return self._abort('worker_owned')

    def is_aborted(self):
        with self._lock:
            return self._state == 'aborted'


class _TaskStartupError(HTTPException):
    """Readable legacy detail plus metadata for startup-failure reconciliation."""

    def __init__(self, code, rid, pending=None):
        messages = {
            'startup_reconciliation_pending': 'Task did not start; startup reconciliation is pending. Retry when storage is available.',
            'task_state_reconciliation_pending': 'The previous task has ended; its state is being reconciled.',
            'task_startup_failed': 'Task did not start; its startup failure was recorded.',
            'task_start_outcome_unknown': 'The startup response failed after worker ownership was handed off. Query this run before retrying.',
        }
        super().__init__(503, messages[code] + ' Run: ' + rid)
        self.payload = {'detail': self.detail, 'code': code, 'run_id': rid}
        if pending is not None:
            self.payload['reconciliation_pending'] = pending


_PLAN_TEXT_LIMITS = {'objective': 500, 'scope': 1000, 'materials': 1000, 'tools': 500, 'deliverables': 1000}


def _confirmed_research_plan(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {*_PLAN_TEXT_LIMITS, 'acceptance'}:
        raise HTTPException(400, 'Invalid confirmed research plan')
    plan = {}
    for field, limit in _PLAN_TEXT_LIMITS.items():
        text = value[field]
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > limit:
            raise HTTPException(400, 'Invalid confirmed research plan')
        plan[field] = text.strip()
    acceptance = value['acceptance']
    if not isinstance(acceptance, list) or not 1 <= len(acceptance) <= 5:
        raise HTTPException(400, 'Invalid confirmed acceptance criteria')
    plan['acceptance'] = []
    for item in acceptance:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 300:
            raise HTTPException(400, 'Invalid confirmed acceptance criteria')
        plan['acceptance'].append(item.strip())
    return plan


_RECOVERY_ACTIONS = {
    'follow_up': ({'completed'}, '请基于上一轮答复和已保存成果，进一步说明关键结论、支持依据、局限和仍待研究的问题。'),
    'derive': ({'completed'}, '请基于本轮已保存的答复和成果，整理一份新的研究内容，包含目标、方法、结果、证据和局限。引用已有文件名，不要删除或改写原成果；新增文件使用新名称。'),
    'resume': ({'stopped', 'cancelled', 'incomplete', 'budget_exhausted', 'interrupted'},
               '请先读取同一对话中上一轮运行的执行详情和已保存文件，核对已完成与未完成步骤，再从中断位置继续。不要重复已确认完成的工具调用，不要删除或改写原成果；新增文件使用新名称。'),
    'retry': ({'failed'},
              '请保留同一对话中的原始问题、执行上下文和已保存文件，重试上次失败的任务。先判断哪些结果可以复用，避免重复已完成工作；不要删除或改写原成果，新增文件使用新名称。'),
}


def _terminal_recovery_prompt(run, action):
    spec = _RECOVERY_ACTIONS.get(action) if isinstance(action, str) else None
    if spec is None:
        raise HTTPException(400, 'Invalid terminal recovery action')
    statuses, prompt = spec
    if run['status'] not in statuses:
        raise HTTPException(409, 'This recovery action does not match the run status')
    return prompt


_RECOVERY_CONTEXT_LIMIT = 12000
_RECOVERY_EVENT_FIELDS = {
    'status': ('message', 'phase', 'turn'),
    'tool_start': ('name', 'arguments'),
    'tool_result': ('name', 'result'),
    'knowledge_sources': ('sources',),
    'plan_confirmed': ('plan',),
    'skill_selected': ('skill',),
    'finished': ('status', 'reason', 'answer'),
}

_LEGACY_DEADLINE_REASON = 'TimeoutError: Managed task execution deadline exceeded'
_MANAGED_DEADLINE_REASON = '任务已达到执行时限。完整调研报告未完成。'


def _public_receipt_url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or re.search(r'[\s\\\x00-\x1f\x7f]', value):
        return ''
    try:
        url = urlsplit(value)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            return ''
        fields = parse_qsl(url.query, max_num_fields=60, keep_blank_values=True)
        if any(re.search(r'token|key|secret|password|signature|authorization|credential|^sig$', key, re.I)
               for key, _ in fields):
            return ''
        return quote(url._replace(fragment='').geturl(), safe="/:?&=%+#@,;!$'*~_-")
    except ValueError:
        return ''


def _receipt_label(value, default):
    if not isinstance(value, str):
        return default
    return ' '.join(re.sub(r'[\[\]<>]', ' ', value).split())[:180] or default


def _deadline_evidence(events):
    candidates, fetched, knowledge = {}, {}, {}
    for event in events:
        if event.get('kind') == 'knowledge_sources':
            for ref in event.get('references') or ():
                if isinstance(ref, dict) and re.fullmatch(r'K[0-9a-f]{16,64}_[0-9]+', str(ref.get('citation_id', ''))):
                    knowledge[ref['citation_id']] = _receipt_label(ref.get('title'), '知识库原文片段')
            continue
        receipt = event.get('result')
        if not isinstance(receipt, dict) or receipt.get('status') != 'ok':
            continue
        data = receipt.get('data')
        if not isinstance(data, dict):
            continue
        name = receipt.get('name') or event.get('name')
        if name == 'web_fetch' and isinstance(data.get('content'), str) and data['content'].strip():
            url = _public_receipt_url(data.get('url'))
            if url:
                fetched.setdefault(url, _receipt_label(data.get('title'), ''))
        if name == 'web_search':
            for item in data.get('results') or ():
                if isinstance(item, dict) and (url := _public_receipt_url(item.get('url'))):
                    candidates.setdefault(url, _receipt_label(item.get('title'), urlsplit(url).hostname))

    sections = []
    if fetched:
        links = [f"- [{title or candidates.get(url) or urlsplit(url).hostname}]({url})"
                 for url, title in list(fetched.items())[:8]]
        sections.append('### 已读取的网页\n\n' + '\n'.join(links))
    if knowledge:
        links = [f'- {title} [{cid}]' for cid, title in list(knowledge.items())[:8]]
        sections.append('### 已召回的知识库片段\n\n' + '\n'.join(links))
    leads = [(url, title) for url, title in candidates.items() if url not in fetched][:8]
    if leads:
        sections.append('### 检索候选（尚未核对）\n\n' + '\n'.join(f'- [{title}]({url})' for url, title in leads))
    if not sections:
        return ''
    intro = '## 超时前已保存的资料\n\n以下资料来自本轮已保存的回执，尚未形成经审核的调研结论。'
    return intro + '\n\n' + '\n\n'.join(sections)
