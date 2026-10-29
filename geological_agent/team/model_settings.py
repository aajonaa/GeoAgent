"""Session or encrypted account profiles and credential-safe model transport."""
from dataclasses import dataclass, field, fields, is_dataclass, replace
import ipaddress
import json
import os
import socket
from threading import RLock
import time
import uuid
from urllib.parse import urlsplit

import httpx

from ..contracts import Message, ModelRequest, strict_json
from ..settings import Settings, DEFAULT_CONTEXT_WINDOW_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS
from ..context_budget import budget_description
from ..llm import LocalChatClient, missing_native_tool_message
from .store import digest
from .model_vault import ModelVault, ModelVaultError
from .protocol import scrub


@dataclass(frozen=True)
class ModelProfile:
    source: str
    base_url: str
    model: str
    api_token: str = field(default="", repr=False, compare=False)
    storage: str = field(default="login_session", compare=False)
    profile_id: str = field(default="", compare=False)
    name: str = field(default="", compare=False)
    revision: int = field(default=0, compare=False)
    context_window_tokens: int | None = DEFAULT_CONTEXT_WINDOW_TOKENS
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS

    def runtime_settings(self):
        return {"context_model": self.model,
                "context_window_tokens": self.context_window_tokens if self.context_window_tokens is not None else DEFAULT_CONTEXT_WINDOW_TOKENS,
                "max_output_tokens": self.max_output_tokens}

    def context_budget(self):
        return budget_description(Settings(**self.runtime_settings()))

    def identity(self):
        return {"source": self.source, "base_url": self.base_url, "model": self.model}

    def run_snapshot(self):
        """Credential-free parameters from the immutable profile used by this run."""
        settings = self.runtime_settings()
        return {**self.identity(), **{key: settings[key] for key in
                ("context_window_tokens", "max_output_tokens")}}

    def public(self):
        return {**self.identity(), "has_token": bool(self.api_token), "storage": self.storage,
                "profile_id": self.profile_id, "name": self.name, "revision": self.revision,
                "context_window_tokens": self.runtime_settings()["context_window_tokens"],
                "max_output_tokens": self.max_output_tokens, "context_budget": self.context_budget()}


def builtin_profile():
    return ModelProfile(
        "builtin",
        os.environ.get("GEOTOOL_MODEL_URL") or os.environ.get("WORKSPACE_MODEL_URL", "http://127.0.0.1:8000/v1"),
        os.environ.get("GEOTOOL_MODEL") or os.environ.get("WORKSPACE_MODEL", "GeoGPT-Research-Project/Qwen2.5-72B-GeoGPT"),
        os.environ.get("GEOTOOL_MODEL_KEY") or os.environ.get("WORKSPACE_MODEL_KEY", ""),
        # The existing GeoGPT service runs with a 32,768-token window.
        # Administrators can override both limits with the deployed service values.
        context_window_tokens=int(os.environ.get("GEOTOOL_MODEL_CONTEXT_TOKENS", "32768")),
        max_output_tokens=int(os.environ.get("GEOTOOL_MODEL_MAX_OUTPUT_TOKENS", "4096")),
    )


def trace_credentials(profile, environment=None):
    """Collect real credentials without treating a local no-auth sentinel as one.

    The historical local vLLM key 'none' is a placeholder, not a secret.
    A custom/remote endpoint's literal 'none' is still protected. Header/key
    masking remains independent of this known-value list.
    """
    env = os.environ if environment is None else environment
    local_hosts = {"localhost", "127.0.0.1", "::1"}

    def append(values, token, source, base_url):
        placeholder = (source == "builtin" and token == "none" and
                       urlsplit(base_url).hostname in local_hosts)
        if token and not placeholder:
            values.append(token)

    values = []
    builtin_url = env.get("GEOTOOL_MODEL_URL") or env.get("WORKSPACE_MODEL_URL", "http://127.0.0.1:8000/v1")
    append(values, env.get("GEOTOOL_MODEL_KEY", ""), "builtin", builtin_url)
    append(values, env.get("WORKSPACE_MODEL_KEY", ""), "builtin",
           env.get("WORKSPACE_MODEL_URL") or builtin_url)
    if env.get("LANGSMITH_API_KEY"):
        values.append(env["LANGSMITH_API_KEY"])
    append(values, profile.api_token, profile.source, profile.base_url)
    return tuple(dict.fromkeys(values))


def origin(url):
    value = httpx.URL(url)
    return value.scheme, value.host, value.port or (443 if value.scheme == "https" else 80)


class EndpointPolicy:
    def __init__(self, builtin_url, allowed=()):
        self.allowed = {origin(builtin_url), *(origin(item.strip()) for item in allowed if item.strip())}

    def normalize(self, raw):
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 2048:
            raise ValueError("API Base URL must contain 1 to 2048 characters")
        raw = raw.strip()
        if any(ord(c) <= 32 or ord(c) == 127 for c in raw) or "\\" in raw:
            raise ValueError("API Base URL contains invalid characters")
        try:
            parts, url = urlsplit(raw), httpx.URL(raw)
            if (url.scheme not in ("http", "https") or not url.host or
                    parts.username is not None or parts.password is not None or parts.query or parts.fragment):
                raise ValueError()
            host_origin = origin(url)
        except (ValueError, httpx.InvalidURL):
            raise ValueError("Use an HTTP(S) API base URL without credentials, query parameters or fragments") from None
        if url.path.rstrip("/").endswith("/chat/completions"):
            raise ValueError("Enter the API base URL (usually ending in /v1), not /chat/completions")
        if host_origin not in self.allowed:
            if url.scheme != "https":
                raise ValueError("Custom public endpoints require HTTPS")
            try:
                address = ipaddress.ip_address(url.host)
            except ValueError:
                address = None
            if url.host.rstrip(".").lower() in ("localhost", "metadata.google.internal") or (
                    address is not None and not self.public_address(address)):
                raise ValueError("Private or reserved endpoints require an administrator allowlist")
        return str(url).rstrip("/")

    @staticmethod
    def public_address(value):
        address = ipaddress.ip_address(value)
        return address.is_global and not address.is_multicast and not (
            isinstance(address, ipaddress.IPv6Address) and
            (address.ipv4_mapped or address.sixtofour or address.teredo)
        )

    def transport(self, base_url):
        return PinnedTransport(base_url, self)


class PinnedTransport(httpx.BaseTransport):
    """Resolve, validate, then connect to that IP; preserve Host and TLS SNI.

    No redirect following or proxy/environment inheritance. Private origins
    must be explicitly trusted by the server administrator.
    """
    def __init__(self, base_url, policy, *, inner=None, resolver=None):
        self.base_url, self.policy = base_url, policy
        self.inner = inner or httpx.HTTPTransport(trust_env=False, retries=0)
        self.resolver = resolver or socket.getaddrinfo

    def handle_request(self, request):
        if str(request.url) != self.base_url.rstrip("/") + "/chat/completions" or request.method != "POST":
            raise ValueError("Model transport only permits its configured chat-completions endpoint")
        if origin(request.url) in self.policy.allowed:
            return self.inner.handle_request(request)
        try:
            addresses = [item[4][0] for item in self.resolver(request.url.host, request.url.port or 443,
                                                            type=socket.SOCK_STREAM)]
        except OSError:
            raise ValueError("Model endpoint DNS lookup failed") from None
        if not addresses or not all(self.policy.public_address(ip) for ip in addresses):
            raise ValueError("Model endpoint DNS resolves to a private or reserved address")
        headers = httpx.Headers(request.headers)
        headers["Host"] = request.url.netloc.decode("ascii")
        pinned = httpx.Request(request.method, request.url.copy_with(host=addresses[0]),
                               headers=headers, stream=request.stream,
                               extensions={**request.extensions, "sni_hostname": request.url.host})
        return self.inner.handle_request(pinned)

    def close(self):
        self.inner.close()


def parse_profile(data, builtin, previous, policy, defaults=None):
    defaults = defaults or {"context_window_tokens": DEFAULT_CONTEXT_WINDOW_TOKENS,
                            "max_output_tokens": DEFAULT_MAX_OUTPUT_TOKENS}
    if set(data) - {"source", "base_url", "model", "api_token", "keep_token", "context_window_tokens", "max_output_tokens"}:
        raise ValueError("Unknown model setting")
    if data.get("source") == "builtin":
        return builtin
    if data.get("source") != "custom":
        raise ValueError("Choose builtin or custom model")
    base_url = policy.normalize(data.get("base_url"))
    model = data.get("model")
    if not isinstance(model, str) or not 1 <= len(model.strip()) <= 256 or any(ord(c) < 32 for c in model):
        raise ValueError("Model ID must contain 1 to 256 printable characters")
    token, keep = data.get("api_token", ""), data.get("keep_token", False)
    if type(keep) is not bool or not isinstance(token, str) or len(token) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError("Invalid API Token or keep_token flag")
    if keep:
        if token or previous.source != "custom" or previous.base_url != base_url:
            raise ValueError("An existing token can only be kept for the same API endpoint")
        token = previous.api_token
    window = data.get("context_window_tokens", previous.context_window_tokens
                      if previous.base_url == base_url and previous.model == model.strip() else None)
    window = defaults["context_window_tokens"] if window is None else window
    same_model = previous.base_url == base_url and previous.model == model.strip()
    output = data.get("max_output_tokens", previous.max_output_tokens if same_model else defaults["max_output_tokens"])
    Settings(context_window_tokens=window, max_output_tokens=output, context_model=model.strip())
    return ModelProfile("custom", base_url, model.strip(), token, context_window_tokens=window, max_output_tokens=output)


class SessionModels:
    """Named, encrypted account connections with optional session overrides."""
    def __init__(self, store, builtin, policy):
        self.store, self.builtin, self.policy = store, builtin, policy
        self.lock, self.profiles = RLock(), {}
        self.vault = ModelVault(store)

    @staticmethod
    def _name(value):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 96 or any(ord(c) < 32 for c in value):
            raise ValueError("Connection name must contain 1 to 96 printable characters")
        return value.strip()

    @staticmethod
    def _defaults(collection):
        values = collection.get("defaults", {
            "context_window_tokens": DEFAULT_CONTEXT_WINDOW_TOKENS,
            "max_output_tokens": DEFAULT_MAX_OUTPUT_TOKENS})
        if not isinstance(values, dict) or set(values) != {"context_window_tokens", "max_output_tokens"}:
            raise ValueError("Default settings require context window and maximum output")
        if type(values["context_window_tokens"]) is not int or values["context_window_tokens"] < 1:
            raise ValueError("Default context window must be a positive whole number of tokens")
        Settings(**values)
        return dict(values)

    @classmethod
    def _public_defaults(cls, collection):
        values = cls._defaults(collection)
        window, output = values["context_window_tokens"], values["max_output_tokens"]
        safety = max(1024, (window + 19) // 20)
        return {**values, "revision": collection.get("defaults_revision", 0),
                "input_budget_tokens": window - output - safety,
                "safety_reserve_tokens": safety,
                "scope": "new_custom_connections",
                "stored": "defaults" in collection}

    def get_defaults(self, token):
        with self.lock:
            uid = self.store.authenticate(token)["id"]
            return self._public_defaults(self._collection(uid, self.vault.get(uid)))

    def save_defaults(self, token, data):
        if not isinstance(data, dict) or set(data) != {"context_window_tokens", "max_output_tokens", "revision"}:
            raise ValueError("Supply both default limits and their revision")
        revision = data["revision"]
        if type(revision) is not int or revision < 0:
            raise ValueError("Invalid defaults revision")
        values = self._defaults({"defaults": {key: data[key] for key in
                                 ("context_window_tokens", "max_output_tokens")}})
        selected = []
        with self.lock:
            uid = self.store.authenticate(token)["id"]
            def change(raw):
                collection = self._collection(uid, raw)
                if revision != collection.get("defaults_revision", 0):
                    raise ValueError("Default settings changed in another window. Reopen settings before saving.")
                collection["defaults"] = values
                collection["defaults_revision"] = revision + 1
                selected.append(self._public_defaults(collection))
                return collection
            self.vault.mutate(uid, change)
        return selected[0]

    def _record_profile(self, item):
        profile = parse_profile({**{key: item[key] for key in ("source", "base_url", "model", "api_token")},
                                 "context_window_tokens": item.get("context_window_tokens"),
                                 "max_output_tokens": item.get("max_output_tokens", 4096)},
                                self.builtin, self.builtin, self.policy)
        if (profile.source != "custom" or not isinstance(item["id"], str) or
                not item["id"] or len(item["id"]) > 64 or
                type(item["revision"]) is not int or item["revision"] < 1):
            raise ValueError("Invalid saved connection")
        return replace(profile, storage="account_encrypted", profile_id=item["id"],
                       name=self._name(item["name"]), revision=item["revision"])

    def _collection(self, uid, raw):
        if raw is None:
            return {"format": "connections-v1", "active_id": None, "items": []}
        try:
            if raw.get("source") == "custom" and "format" not in raw:
                # A stable ID makes legacy reads read-only until the first mutation.
                identifier = uuid.uuid5(uuid.NAMESPACE_URL, "geotoolagent:legacy:" + uid).hex
                item = {**raw, "id": identifier, "name": raw["model"][:96], "revision": 1}
                raw = {"format": "connections-v1", "active_id": identifier, "items": [item]}
            if raw.get("format") != "connections-v1" or not isinstance(raw["items"], list):
                raise ValueError()
            self._defaults(raw)
            revision = raw.get("defaults_revision", 0)
            if type(revision) is not int or revision < 0:
                raise ValueError("Invalid defaults revision")
            ids = []
            for item in raw["items"]:
                ids.append(self._record_profile(item).profile_id)
            if len(ids) != len(set(ids)) or (raw["active_id"] is not None and raw["active_id"] not in ids):
                raise ValueError()
            return raw
        except (KeyError, ValueError, TypeError, AttributeError):
            raise ModelVaultError() from None

    @staticmethod
    def _find(collection, identifier):
        for item in collection["items"]:
            if item["id"] == identifier:
                return item
        raise KeyError("Saved connection not found")

    def _active(self, collection):
        if collection["active_id"] is None:
            return self.builtin
        return self._record_profile(self._find(collection, collection["active_id"]))

    def prune(self):
        with self.store.lock:
            active = {row[0] for row in self.store.db.execute(
                "SELECT token FROM auth JOIN users ON users.id=auth.uid WHERE expires>? AND disabled=0", (time.time(),))}
        with self.lock:
            for key in list(self.profiles):
                if key not in active:
                    del self.profiles[key]

    def get(self, token):
        self.prune()
        with self.lock:
            uid = self.store.authenticate(token)["id"]
            if digest(token) in self.profiles:
                return self.profiles[digest(token)]
            return self._active(self._collection(uid, self.vault.get(uid)))

    def public(self, token):
        with self.lock:
            uid = self.store.authenticate(token)["id"]
            profile = self.get(token)
            collection = self._collection(uid, self.vault.get(uid))
            return {**profile.public(), "saved_profiles": [
                self._record_profile(item).public() for item in collection["items"]
            ], "account_active_id": collection["active_id"],
                "defaults": self._public_defaults(collection)}

    def _details(self, data):
        clean = dict(data)
        remember = clean.pop("remember", False)
        identifier = clean.pop("profile_id", "")
        revision = clean.pop("revision", None)
        name = clean.pop("name", None)
        if type(remember) is not bool:
            raise ValueError("remember must be a boolean")
        if not isinstance(identifier, str) or len(identifier) > 64:
            raise ValueError("Invalid saved connection ID")
        if revision is not None and (type(revision) is not int or revision < 1):
            raise ValueError("Invalid connection revision")
        if name is not None:
            name = self._name(name)
        return clean, remember, identifier, revision, name

    def _parse(self, token, uid, clean, identifier, revision, name, collection=None):
        collection = collection if collection is not None else self._collection(uid, self.vault.get(uid))
        previous = self.builtin
        if identifier:
            collection = collection if collection is not None else self._collection(uid, self.vault.get(uid))
            item = self._find(collection, identifier)
            if revision != item["revision"]:
                raise ValueError("This connection changed in another window. Reopen model settings before editing.")
            previous = self._record_profile(item)
        elif clean.get("keep_token"):
            previous = self.get(token)
        profile = parse_profile(clean, self.builtin, previous, self.policy, self._defaults(collection))
        if profile.source == "builtin":
            return profile
        return replace(profile, name=name or previous.name or profile.model[:96])

    def parse(self, token, data):
        with self.lock:
            uid = self.store.authenticate(token)["id"]
            clean, _, identifier, revision, name = self._details(data)
            return self._parse(token, uid, clean, identifier, revision, name)

    def _forget_account_sessions(self, uid):
        with self.store.lock:
            tokens = [row[0] for row in self.store.db.execute("SELECT token FROM auth WHERE uid=?", (uid,))]
        for hashed in tokens:
            self.profiles.pop(hashed, None)

    def save(self, token, data):
        with self.lock:
            uid = self.store.authenticate(token)["id"]
            clean, remember, identifier, revision, name = self._details(data)
            if clean.get("source") == "builtin":
                # Validate all request fields before changing the active selection.
                self._parse(token, uid, clean, identifier, revision, name)
                return self.activate(token, None)
            if not remember:
                profile = self._parse(token, uid, clean, identifier, revision, name)
                # Temporary use must never erase saved account connections.
                self.profiles[digest(token)] = profile
                return profile

            selected = []
            def change(raw):
                collection = self._collection(uid, raw)
                profile = self._parse(token, uid, clean, identifier, revision, name, collection)
                target_id = identifier or uuid.uuid4().hex
                item = {**profile.identity(), "api_token": profile.api_token,
                        "context_window_tokens": profile.context_window_tokens,
                        "max_output_tokens": profile.max_output_tokens,
                        "id": target_id, "name": profile.name,
                        "revision": self._find(collection, identifier)["revision"] + 1 if identifier else 1}
                if identifier:
                    collection["items"] = [item if old["id"] == identifier else old for old in collection["items"]]
                else:
                    collection["items"].append(item)
                collection["active_id"] = target_id
                selected.append(self._record_profile(item))
                return collection

            self.vault.mutate(uid, change)
            self._forget_account_sessions(uid)
            return selected[0]

    def activate(self, token, identifier):
        with self.lock:
            uid = self.store.authenticate(token)["id"]
            if identifier is not None and (not isinstance(identifier, str) or not identifier):
                raise ValueError("Choose a saved connection or builtin")
            selected = []
            def change(raw):
                collection = self._collection(uid, raw)
                if identifier is not None:
                    self._find(collection, identifier)
                collection["active_id"] = identifier
                selected.append(self._active(collection))
                return collection if collection["items"] or "defaults" in collection else None
            self.vault.mutate(uid, change)
            self._forget_account_sessions(uid)
            return selected[0]

    def remove(self, token, identifier, revision):
        with self.lock:
            uid = self.store.authenticate(token)["id"]
            was_active = []
            def change(raw):
                collection = self._collection(uid, raw)
                item = self._find(collection, identifier)
                if type(revision) is not int or revision != item["revision"]:
                    raise ValueError("This connection changed. Reopen model settings before deleting.")
                was_active.append(collection["active_id"] == identifier)
                collection["items"] = [item for item in collection["items"] if item["id"] != identifier]
                if was_active[0]:
                    collection["active_id"] = None
                return collection if collection["items"] or "defaults" in collection else None
            self.vault.mutate(uid, change)
            if was_active[0]:
                self._forget_account_sessions(uid)
            return self.get(token)

    def delete(self, token):
        # Explicit recovery/clear-all operation only; switching never calls it.
        with self.lock:
            uid = self.store.authenticate(token)["id"]
            self.vault.delete(uid)
            self._forget_account_sessions(uid)
            return self.builtin

    def forget(self, token):
        with self.lock:
            self.profiles.pop(digest(token), None)

    def clear(self):
        with self.lock:
            self.profiles.clear()

def redact(value, secrets):
    """Preserve model contract dataclasses while masking credentials."""
    if is_dataclass(value) and not isinstance(value, type):
        return replace(value, **{f.name: redact(getattr(value, f.name), secrets) for f in fields(value)})
    if isinstance(value, dict):
        return {key: "[REDACTED]" if str(key).lower() in (
            "api_token", "api_key", "authorization", "password", "access_token",
            "session_token", "refresh_token", "cookie"
        ) else redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item, secrets) for item in value)
    if isinstance(value, str):
        for secret in sorted(filter(None, secrets), key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
    return value


def provider_error_details(exc, secrets=()):
    """Publish whitelisted upstream diagnostics, never headers or raw bodies."""
    details = {"error": type(exc).__name__}
    if isinstance(exc, httpx.HTTPStatusError):
        details["http_status"] = exc.response.status_code
        try:
            payload = exc.response.json()
        except (ValueError, UnicodeError, httpx.ResponseNotRead):
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error", payload)
            if isinstance(error, str):
                details["message"] = error
            elif isinstance(error, dict):
                for key in ("message", "type", "code", "param"):
                    value = error.get(key)
                    if isinstance(value, (str, int)) and not isinstance(value, bool):
                        details[key] = value
    elif not isinstance(exc, httpx.HTTPError):
        details["message"] = str(exc)
    return scrub(redact(details, secrets), secrets)


def model_endpoint_error(exc, secrets=()):
    details = provider_error_details(exc, secrets)
    code = details.get("http_status", details["error"])
    message = f"Model endpoint request failed ({code}); check your model settings"
    parts = [f"{key}={details[key]}" for key in ("type", "code", "param", "message") if key in details]
    return message + (". Provider: " + "; ".join(parts) if parts else "")


def profile_client(profile, policy, *, probe=False):
    return LocalChatClient(profile.base_url, profile.model, profile.api_token,
                           timeout=httpx.Timeout(90 if probe else 180, connect=10),
                           max_tokens=min(256, profile.max_output_tokens) if probe else profile.max_output_tokens,
                           thinking_enabled=not probe,
                           required_streaming=profile.source == "custom",
                           transport=policy.transport(profile.base_url) if profile.source == "custom" else None)


@dataclass(frozen=True)
class ProbeTool:
    name: str = "connection_probe"
    description: str = "Confirm a synthetic connection test; it has no side effects."
    when_to_use: str = "Only when asked to confirm the connection."
    input_schema: dict = field(default_factory=lambda: {
        "type": "object", "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"], "additionalProperties": False,
    })


def probe_model(client):
    request = ModelRequest(
        (Message("user", "Connection test: call connection_probe with ok=true. Do not write an explanation."),),
        (ProbeTool(),), "required")
    first = client.invoke(request)
    # vLLM 0.8.x required-tool responses can finish with 'stop' while
    # carrying a complete native call. Truncation and incomplete calls
    # remain rejected; the exact function and JSON arguments are checked below.
    if len(first.tool_calls) != 1 or first.finish_reason not in ("tool_calls", "stop"):
        if not first.tool_calls:
            raise ValueError(missing_native_tool_message(first))
        raise ValueError("Endpoint did not return a complete native tool call")
    call = first.tool_calls[0]
    args = strict_json(call.arguments) if isinstance(call.arguments, str) else call.arguments
    if not call.id or call.name != "connection_probe" or not isinstance(args, dict) or set(args) != {"ok"} or args["ok"] is not True:
        raise ValueError("Endpoint returned invalid native tool arguments")
    receipt = uuid.uuid4().hex
    second = client.invoke(ModelRequest((*request.messages,
        Message("assistant", first.content, first.tool_calls, reasoning_content=first.reasoning_content),
        Message("tool", json.dumps({"ok": True, "receipt": receipt}), tool_call_id=call.id),
        Message("user", "Return exactly the receipt value from the tool result, with no "
                        "other text and no further calls. This verifies result consumption."),
    ), (ProbeTool(),), "auto"))
    if second.tool_calls or not second.content.strip() or second.finish_reason != "stop":
        raise ValueError("Endpoint did not complete the native tool-result round trip")
    if second.content.strip() != receipt:
        raise ValueError("Endpoint did not return the actual tool-result receipt; a generic answer is not a round-trip pass")
    return {"ok": True, "checks": ["native_required_tool_call", "json_arguments",
                                  "tool_result_to_auto_answer", "tool_result_receipt"],
            "scope": "synthetic_nonstreaming_round_trip", "agent_compatibility": "not_evaluated",
            "message": "Basic non-streaming native call and exact tool-result receipt passed. "
                       "Real agent contexts, multiple tools and streaming are not evaluated. "
                       "This result does not certify full agent compatibility."}
