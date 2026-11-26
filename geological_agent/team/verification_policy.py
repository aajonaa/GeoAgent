"""Explicit development policies; no provider credentials or country guessing."""
from dataclasses import dataclass, field
from pathlib import Path
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re

from .activity_store import phone as canonical_phone


@dataclass(frozen=True)
class Settings:
    mode: str = 'disabled'
    environment: str = 'production'
    allowed_regions: tuple = ('CN',)
    default_region: str | None = None
    digits: int = 6
    ttl: int = 300
    cooldown: int = 60
    attempts: int = 5
    phone_hour_limit: int = 5
    ip_hour_limit: int = 20
    window: int = 3600
    provider_timeout: int = 10
    body_limit: int = 2048
    edge_limit: int = 30
    edge_window: int = 60
    edge_buckets: int = 2048
    trusted_proxy_cidrs: tuple = ()

    def __post_init__(self):
        if self.mode not in ('disabled', 'mock', 'provider') or self.environment not in ('test', 'development', 'production'):
            raise ValueError('Invalid verification configuration')
        if self.mode == 'mock' and self.environment == 'production':
            raise ValueError('Mock SMS is forbidden in production configuration')
        if not self.allowed_regions or set(self.allowed_regions) - {'CN', 'NANP'}:
            raise ValueError('Explicit supported regions are required')
        if self.default_region is not None and self.default_region not in self.allowed_regions:
            raise ValueError('Default region must be explicitly allowed')
        for name in ('digits','ttl','attempts','phone_hour_limit','ip_hour_limit','window','provider_timeout','body_limit','edge_limit','edge_window','edge_buckets'):
            if type(getattr(self,name)) is not int or getattr(self,name) <= 0:
                raise ValueError('Invalid verification policy value')
        if not 6 <= self.digits <= 8 or type(self.cooldown) is not int or self.cooldown < 0:
            raise ValueError('Invalid verification policy value')
        if self.cooldown>self.window:
            raise ValueError('Cooldown cannot exceed its persisted quota window')
        object.__setattr__(self,'allowed_regions',tuple(self.allowed_regions))
        object.__setattr__(self,'trusted_proxy_cidrs',tuple(self.trusted_proxy_cidrs))
        for value in self.trusted_proxy_cidrs:
            ipaddress.ip_network(value)


def normalize_phone(value, settings):
    """Validate the configured numbering-plan shape; SMS proves possession, not regex."""
    if not isinstance(value, str) or not 1 <= len(value) <= 80 or not re.fullmatch(r'[+0-9 ()-]+', value):
        raise ValueError('Invalid phone format')
    compact = re.sub(r'[ ()-]', '', value)
    # +1 is a shared numbering plan, not a proof that a number is in the USA.
    rules = {'CN': ('86', r'1[3-9][0-9]{9}'), 'NANP': ('1', r'[2-9][0-9]{2}[2-9][0-9]{6}')}
    if not compact.startswith('+'):
        if settings.default_region is None:
            raise ValueError('Explicit country prefix is required')
        compact = '+' + rules[settings.default_region][0] + compact
    for region in settings.allowed_regions:
        prefix, pattern = rules[region]
        if compact.startswith('+'+prefix) and re.fullmatch(pattern,compact[len(prefix)+1:]):
            return canonical_phone(compact)
    raise ValueError('Phone is outside the configured numbering policy')


@dataclass(frozen=True, repr=False)
class KeyRing:
    active: str
    keys: dict = field(repr=False)

    def __post_init__(self):
        if self.active not in self.keys or not self.keys or any(not re.fullmatch(r'[A-Za-z0-9_.-]{1,48}',k) or not isinstance(v,bytes) or len(v)<32 for k,v in self.keys.items()):
            raise ValueError('Invalid verification key configuration')
        object.__setattr__(self,'keys',dict(self.keys))

    def __repr__(self):
        return 'KeyRing(<private>)'

    def digest(self, key_id, domain, *values):
        payload=json.dumps([domain,*values],ensure_ascii=True,separators=(',',':')).encode()
        return hmac.digest(self.keys[key_id],payload,hashlib.sha256)

    @classmethod
    def from_file(cls,path):
        path=Path(path)
        if path.is_symlink() or not path.is_file():
            raise ValueError('Private verification key file is required')
        info=path.stat()
        if os.name!='nt' and (info.st_mode & 0o077 or info.st_uid!=os.getuid()):
            raise ValueError('Verification key file must be owner-only')
        try:
            d=json.loads(path.read_text(encoding='utf-8'))
            return cls(d['active'],{k:base64.b64decode(v,validate=True) for k,v in d['keys'].items()})
        except Exception:
            raise ValueError('Invalid private verification key file') from None


def client_ip(peer,forwarded,settings):
    """Requires ASGI server proxy_headers=False; default never trusts forwarded headers."""
    try:
        address=ipaddress.ip_address(peer)
        if any(address in ipaddress.ip_network(cidr) for cidr in settings.trusted_proxy_cidrs):
            # One explicitly replacing proxy, not an arbitrary caller-supplied chain.
            return str(ipaddress.ip_address(forwarded.strip())) if forwarded else str(address)
        return str(address)
    except (ValueError,TypeError):
        return 'unknown'
