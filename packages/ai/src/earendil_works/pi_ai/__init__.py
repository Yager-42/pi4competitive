"""earendil_works.pi_ai — Python isomorphic port of @earendil-works/pi-ai."""
from __future__ import annotations

from .auth import InMemoryCredentialStore, ModelsError, default_auth_context, env_api_key_auth
from .models import (
    Provider,
    calculate_cost,
    clamp_thinking_level,
    create_models,
    create_provider,
    get_supported_thinking_levels,
    has_api,
    models_are_equal,
)
from .models_store import InMemoryModelsStore
from .providers import (
    builtin_models,
    builtin_providers,
    faux_assistant_message,
    faux_provider,
    faux_text,
    faux_thinking,
    faux_tool_call,
    get_builtin_models,
    get_builtin_providers,
)
from .types import (
    AssistantMessage,
    Context,
    Model,
    Tool,
    Usage,
    empty_usage,
)
from .utils import (
    AssistantMessageEventStream,
    create_assistant_message_event_stream,
    parse_partial_json,
    uuidv7,
    validate_tool_arguments,
)
from .api import (
    build_anthropic_messages_payload,
    build_openai_completions_payload,
)

__all__ = [
    "AssistantMessage",
    "AssistantMessageEventStream",
    "Context",
    "InMemoryCredentialStore",
    "InMemoryModelsStore",
    "Model",
    "ModelsError",
    "Provider",
    "Tool",
    "Usage",
    "builtin_models",
    "builtin_providers",
    "build_anthropic_messages_payload",
    "build_openai_completions_payload",
    "calculate_cost",
    "clamp_thinking_level",
    "create_assistant_message_event_stream",
    "create_models",
    "create_provider",
    "default_auth_context",
    "empty_usage",
    "env_api_key_auth",
    "faux_assistant_message",
    "faux_provider",
    "faux_text",
    "faux_thinking",
    "faux_tool_call",
    "get_builtin_models",
    "get_builtin_providers",
    "get_supported_thinking_levels",
    "has_api",
    "models_are_equal",
    "parse_partial_json",
    "uuidv7",
    "validate_tool_arguments",
]

__version__ = "0.81.2"
