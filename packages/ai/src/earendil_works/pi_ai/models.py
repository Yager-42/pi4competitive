"""Models collection — port of models.ts."""

from __future__ import annotations

import copy
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .api.lazy import lazy_stream
from .auth.context import default_auth_context
from .auth.credential_store import InMemoryCredentialStore
from .auth.resolve import ModelsError, resolve_provider_auth
from .models_store import InMemoryModelsStore
from .types import (
    Api,
    AssistantMessage,
    Context,
    Model,
    ModelThinkingLevel,
    ProviderHeaders,
    SimpleStreamOptions,
    StreamOptions,
    Usage,
    empty_cost,
)
from .utils.event_stream import AssistantMessageEventStream

EXTENDED_THINKING_LEVELS: list[ModelThinkingLevel] = [
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
]


def merge_headers(
    base: ProviderHeaders | None,
    override: ProviderHeaders | None,
) -> ProviderHeaders | None:
    if not base and not override:
        return None
    out: ProviderHeaders = {}
    if base:
        out.update(base)
    if override:
        for k, v in override.items():
            if v is None:
                out.pop(k, None)
            else:
                out[k] = v
    return out


class Provider:
    """Runtime provider unit (mirrors TS Provider interface)."""

    def __init__(
        self,
        *,
        id: str,
        name: str,
        auth: dict[str, Any],
        get_models: Callable[[], list[Model]],
        stream: Callable[..., AssistantMessageEventStream],
        stream_simple: Callable[..., AssistantMessageEventStream],
        base_url: str | None = None,
        headers: ProviderHeaders | None = None,
        refresh_models: Callable[..., Awaitable[None]] | None = None,
        filter_models: Callable[[list[Model], Any], list[Model]] | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.auth = auth
        self.baseUrl = base_url
        self.headers = headers
        self._get_models = get_models
        self._stream = stream
        self._stream_simple = stream_simple
        self.refreshModels = refresh_models
        self.filterModels = filter_models

    def getModels(self) -> list[Model]:
        return self._get_models()

    def stream(
        self,
        model: Model,
        context: Context,
        options: StreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        return self._stream(model, context, options)

    def streamSimple(
        self,
        model: Model,
        context: Context,
        options: SimpleStreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        return self._stream_simple(model, context, options)


class ModelsImpl:
    def __init__(self, options: dict[str, Any] | None = None) -> None:
        options = options or {}
        self._providers: dict[str, Provider] = {}
        self._credentials = options.get("credentials") or InMemoryCredentialStore()
        self._models_store = options.get("modelsStore") or InMemoryModelsStore()
        self._auth_context = options.get("authContext") or default_auth_context()

    def setProvider(self, provider: Provider) -> None:
        self._providers[provider.id] = provider

    def deleteProvider(self, id: str) -> None:
        self._providers.pop(id, None)

    def clearProviders(self) -> None:
        self._providers.clear()

    def getProviders(self) -> list[Provider]:
        return list(self._providers.values())

    def getProvider(self, id: str) -> Provider | None:
        return self._providers.get(id)

    def getModels(self, provider: str | None = None) -> list[Model]:
        if provider is not None:
            entry = self._providers.get(provider)
            if not entry:
                return []
            try:
                return list(entry.getModels())
            except Exception:
                return []
        models: list[Model] = []
        for entry in self._providers.values():
            try:
                models.extend(entry.getModels())
            except Exception:
                continue
        return models

    def getModel(self, provider: str, id: str) -> Model | None:
        for model in self.getModels(provider):
            if model.get("id") == id:
                return model
        return None

    async def refresh(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = options or {}
        allow_network = options.get("allowNetwork", True)
        signal = options.get("signal")
        errors: dict[str, Exception] = {}
        for provider in list(self._providers.values()):
            if not provider.refreshModels:
                continue
            if signal is not None and getattr(signal, "is_set", lambda: False)():
                break
            store = _ProviderStore(self._models_store, provider.id)
            try:
                stored = await self._credentials.read(provider.id)
                await provider.refreshModels(
                    {
                        "credential": stored,
                        "store": store,
                        "allowNetwork": allow_network,
                        "force": options.get("force"),
                        "signal": signal,
                    }
                )
            except Exception as exc:
                errors[provider.id] = exc
        return {
            "aborted": bool(signal is not None and getattr(signal, "is_set", lambda: False)()),
            "errors": errors,
        }

    async def checkAuth(self, provider_id: str) -> dict[str, Any] | None:
        provider = self._providers.get(provider_id)
        if not provider:
            return None
        resolution = await resolve_provider_auth(provider, self._credentials, self._auth_context)
        if not resolution:
            return None
        return {"source": resolution.get("source", ""), "type": "api_key"}

    async def getAvailable(self, provider_id: str | None = None) -> list[Model]:
        if provider_id is not None:
            provider = self._providers.get(provider_id)
            if provider is None:
                return []
            providers = [provider]
        else:
            providers = self.getProviders()
        out: list[Model] = []
        for provider in providers:
            auth = await self.checkAuth(provider.id)
            if not auth:
                continue
            models = provider.getModels()
            if provider.filterModels:
                stored = await self._credentials.read(provider.id)
                models = provider.filterModels(models, stored)
            out.extend(models)
        return out

    async def getAuth(
        self,
        provider_or_model: str | Model,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if isinstance(provider_or_model, str):
            provider_id = provider_or_model
            model = None
        else:
            provider_id = provider_or_model["provider"]
            model = provider_or_model
        provider = self._providers.get(provider_id)
        if not provider:
            return None
        result = await resolve_provider_auth(provider, self._credentials, self._auth_context, overrides)
        if not result or model is None or not model.get("headers"):
            return result
        auth = dict(result.get("auth") or {})
        auth["headers"] = merge_headers(auth.get("headers"), model.get("headers"))  # type: ignore[arg-type]
        return {**result, "auth": auth}

    async def login(self, provider_id: str, type: str, interaction: Any) -> Any:
        provider = self._providers.get(provider_id)
        if not provider:
            raise ModelsError("provider", f"Unknown provider: {provider_id}")
        method = provider.auth.get("oauth" if type == "oauth" else "apiKey")
        if not method or "login" not in method:
            raise ModelsError("auth", f"{provider.name} does not support {type} login")
        credential = await method["login"](interaction)

        async def _set(_c: Any) -> Any:
            return credential

        await self._credentials.modify(provider_id, _set)
        return credential

    async def logout(self, provider_id: str) -> None:
        await self._credentials.delete(provider_id)

    def _require_provider(self, model: Model) -> Provider:
        provider = self._providers.get(model["provider"])
        if not provider:
            raise ModelsError("provider", f"Unknown provider: {model['provider']}")
        return provider

    async def _apply_auth(
        self,
        model: Model,
        options: StreamOptions | None,
    ) -> tuple[Model, StreamOptions | None]:
        self._require_provider(model)
        resolution = await self.getAuth(
            model,
            {
                "apiKey": (options or {}).get("apiKey"),
                "env": (options or {}).get("env"),
            },
        )
        if not resolution:
            raise ModelsError("auth", f"Provider is not configured: {model['provider']}")
        auth = resolution.get("auth") or {}
        api_key = (options or {}).get("apiKey") or auth.get("apiKey")
        headers = merge_headers(auth.get("headers"), (options or {}).get("headers"))  # type: ignore[arg-type]
        transform = (options or {}).get("transformHeaders")  # type: ignore[assignment]
        if transform:
            headers = await transform(headers or {})
        env = None
        if resolution.get("env") or (options or {}).get("env"):
            env = {**(resolution.get("env") or {}), **((options or {}).get("env") or {})}
        request_model = copy.deepcopy(model)
        if auth.get("baseUrl"):
            request_model["baseUrl"] = auth["baseUrl"]  # type: ignore[index]
        request_options: StreamOptions = dict(options or {})  # type: ignore[assignment]
        if api_key is not None:
            request_options["apiKey"] = api_key  # type: ignore[typeddict-item]
        if headers is not None:
            request_options["headers"] = headers  # type: ignore[typeddict-item]
        if env is not None:
            request_options["env"] = env  # type: ignore[typeddict-item]
        request_options.pop("transformHeaders", None)  # type: ignore[arg-type]
        return request_model, request_options

    def stream(
        self,
        model: Model,
        context: Context,
        options: StreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        async def setup():
            provider = self._require_provider(model)
            request_model, request_options = await self._apply_auth(model, options)
            return provider.stream(request_model, context, request_options)

        return lazy_stream(model, setup)

    async def complete(
        self,
        model: Model,
        context: Context,
        options: StreamOptions | None = None,
    ) -> AssistantMessage:
        return await self.stream(model, context, options).result()

    def streamSimple(
        self,
        model: Model,
        context: Context,
        options: SimpleStreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        async def setup():
            provider = self._require_provider(model)
            request_model, request_options = await self._apply_auth(model, options)  # type: ignore[arg-type]
            return provider.streamSimple(request_model, context, request_options)  # type: ignore[arg-type]

        return lazy_stream(model, setup)

    async def completeSimple(
        self,
        model: Model,
        context: Context,
        options: SimpleStreamOptions | None = None,
    ) -> AssistantMessage:
        return await self.streamSimple(model, context, options).result()


class _ProviderStore:
    def __init__(self, store: Any, provider_id: str) -> None:
        self._store = store
        self._id = provider_id

    async def read(self):
        return await self._store.read(self._id)

    async def write(self, entry):
        return await self._store.write(self._id, entry)

    async def delete(self):
        return await self._store.delete(self._id)


def create_models(options: dict[str, Any] | None = None) -> ModelsImpl:
    return ModelsImpl(options)


def create_provider(input: dict[str, Any]) -> Provider:
    baseline: list[Model] = list(input.get("models") or [])
    dynamic: list[Model] = []
    fetch_models = input.get("fetchModels")
    inflight: list[Any] = [None]

    def current_models() -> list[Model]:
        merged = list(baseline)
        for model in dynamic:
            idx = next((i for i, e in enumerate(merged) if e.get("id") == model.get("id")), -1)
            if idx >= 0:
                merged[idx] = model
            else:
                merged.append(model)
        return merged

    api = input["api"]
    if isinstance(api, dict) and callable(api.get("stream")):
        single = api
        by_api = None
    elif callable(getattr(api, "stream", None)):
        single = {
            "stream": api.stream,
            "streamSimple": getattr(api, "streamSimple", None),
            "stream_simple": getattr(api, "stream_simple", None),
        }
        by_api = None
    else:
        single = None
        by_api = api if isinstance(api, dict) else None

    def api_for(model: Model) -> dict[str, Any] | None:
        if single is not None:
            return single
        assert by_api is not None
        return by_api.get(model.get("api"))

    def dispatch(model: Model, run: Callable[[dict[str, Any]], AssistantMessageEventStream]):
        streams = api_for(model)
        if not streams:
            async def fail():
                raise ModelsError("stream", f"Provider {input['id']} has no API implementation for \"{model.get('api')}\"")
            return lazy_stream(model, fail)
        return run(streams)

    async def refresh_models(context: dict[str, Any]) -> None:
        nonlocal dynamic
        if not fetch_models:
            return
        if inflight[0] is not None:
            await inflight[0]
            return

        async def work() -> None:
            nonlocal dynamic
            try:
                stored = await context["store"].read()
                if stored and stored.get("models"):
                    dynamic = [m for m in stored["models"] if m.get("provider") == input["id"]]
                if not context.get("allowNetwork"):
                    return
                refreshed = await fetch_models(context)
                dynamic = list(refreshed)
                await context["store"].write({"models": refreshed, "checkedAt": time.time() * 1000})
            finally:
                inflight[0] = None

        import asyncio
        inflight[0] = asyncio.create_task(work())
        await inflight[0]
    return Provider(
        id=input["id"],
        name=input.get("name") or input["id"],
        base_url=input.get("baseUrl"),
        headers=input.get("headers"),
        auth=input["auth"],
        get_models=current_models,
        refresh_models=refresh_models if fetch_models else None,
        filter_models=input.get("filterModels"),
        stream=lambda model, context, options=None: dispatch(
            model, lambda s: s["stream"](model, context, options)
        ),
        stream_simple=lambda model, context, options=None: dispatch(
            model, lambda s: (s.get("streamSimple") or s.get("stream_simple") or s["stream"])(model, context, options)
        ),
    )


def has_api(model: Model, api: Api) -> bool:
    return model.get("api") == api


def calculate_cost(model: Model, usage: Usage) -> Usage["cost"]:
    rates = model.get("cost") or {}
    cost = empty_cost()
    cost["input"] = (usage.get("input") or 0) * float(rates.get("input") or 0) / 1_000_000
    cost["output"] = (usage.get("output") or 0) * float(rates.get("output") or 0) / 1_000_000
    cost["cacheRead"] = (usage.get("cacheRead") or 0) * float(rates.get("cacheRead") or 0) / 1_000_000
    cost["cacheWrite"] = (usage.get("cacheWrite") or 0) * float(rates.get("cacheWrite") or 0) / 1_000_000
    cost["total"] = cost["input"] + cost["output"] + cost["cacheRead"] + cost["cacheWrite"]
    return cost


def get_supported_thinking_levels(model: Model) -> list[ModelThinkingLevel]:
    if not model.get("reasoning"):
        return ["off"]
    tmap = model.get("thinkingLevelMap") or {}
    levels: list[ModelThinkingLevel] = ["off"]
    for level in EXTENDED_THINKING_LEVELS[1:]:
        if level not in tmap or tmap[level] is not None:
            levels.append(level)
    return levels


def clamp_thinking_level(model: Model, level: ModelThinkingLevel) -> ModelThinkingLevel:
    supported = get_supported_thinking_levels(model)
    if level in supported:
        return level
    return supported[-1] if supported else "off"


def models_are_equal(a: Model | None, b: Model | None) -> bool:
    if not a or not b:
        return False
    return a.get("id") == b.get("id") and a.get("provider") == b.get("provider")
