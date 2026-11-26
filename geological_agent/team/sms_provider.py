"""Transport boundary. No real SMS vendor is selected or invoked in P2.1."""
from dataclasses import dataclass, field
from threading import Lock
from typing import Protocol


@dataclass(frozen=True)
class SendContext:
    verification_id: str
    request_id: str
    timeout_seconds: int


@dataclass(frozen=True)
class SendResult:
    state: str  # accepted, rejected, unknown; accepted never means delivered
    provider_ref: str | None = None


class Provider(Protocol):
    mode: str
    def send_verification_code(self, phone, code, context: SendContext) -> SendResult: ...


class DisabledProvider:
    mode='disabled'
    def send_verification_code(self,phone,code,context):
        return SendResult('rejected')


class UnconfiguredProvider:
    mode='provider'
    def send_verification_code(self,phone,code,context):
        raise RuntimeError('SMS provider is not configured')


class MockProvider:
    """Fixture-only memory capture; never expose capture via HTTP, logs or repr."""
    mode='mock'
    def __init__(self):
        self._lock=Lock();self._captured={}

    def __repr__(self):
        return 'MockProvider(<fixture-only>)'

    def send_verification_code(self,phone,code,context):
        with self._lock:self._captured[context.verification_id]=(phone,code)
        return SendResult('accepted','mock-'+context.verification_id)

    def captured_for_test(self,verification_id):
        with self._lock:return self._captured[verification_id]

    def call_count_for_test(self):
        with self._lock:return len(self._captured)
