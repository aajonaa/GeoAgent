"""Explicit configuration factory; never loaded automatically on app startup."""
from pathlib import Path
import json

from .verification_policy import Settings,KeyRing
from .verification_service import VerificationService
from .sms_provider import MockProvider,DisabledProvider,UnconfiguredProvider


def configured_factory(path):
    """Caller must opt in: create_app(..., verification_factory=...).

    JSON has {settings: {...}, keys_file?: private JSON path}. Default is disabled.
    A provider SDK/transport must be supplied in a future separately tested task.
    """
    try:
        content=json.loads(Path(path).read_text(encoding='utf-8'))
        if set(content)-{'settings','keys_file'}:raise ValueError()
        settings=Settings(**content.get('settings',{}))
        keys=KeyRing.from_file(content['keys_file']) if settings.mode!='disabled' else None
    except Exception:
        raise ValueError('Invalid verification configuration') from None
    def factory(store):
        provider={'disabled':DisabledProvider,'mock':MockProvider,'provider':UnconfiguredProvider}[settings.mode]()
        return VerificationService(store,settings=settings,keys=keys,provider=provider)
    return factory
