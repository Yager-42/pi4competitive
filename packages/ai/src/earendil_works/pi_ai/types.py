"""Core types — isomorphic to packages/ai/src/types.ts."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

# ---------------------------------------------------------------------------
# API / provider ids
# ---------------------------------------------------------------------------

KnownApi = Literal[
    "openai-completions",
    "mistral-conversations",
    "openai-responses",
    "azure-openai-responses",
    "openai-codex-responses",
    "anthropic-messages",
    "bedrock-converse-stream",
    "google-generative-ai",
    "google-vertex",
    "pi-messages",
]
Api = str  # KnownApi | custom

KnownImagesApi = Literal["openrouter-images"]
ImagesApi = str

KnownProvider = Literal[
    "amazon-bedrock",
    "ant-ling",
    "anthropic",
    "google",
    "google-vertex",
    "openai",
    "azure-openai-responses",
    "openai-codex",
    "radius",
    "nvidia",
    "deepseek",
    "github-copilot",
    "xai",
    "groq",
    "cerebras",
    "openrouter",
    "vercel-ai-gateway",
    "zai",
    "zai-coding-cn",
    "mistral",
    "minimax",
    "minimax-cn",
    "moonshotai",
    "moonshotai-cn",
    "huggingface",
    "fireworks",
    "together",
    "opencode",
    "opencode-go",
    "kimi-coding",
    "cloudflare-workers-ai",
    "cloudflare-ai-gateway",
    "qwen-token-plan",
    "qwen-token-plan-cn",
    "xiaomi",
    "xiaomi-token-plan-cn",
    "xiaomi-token-plan-ams",
    "xiaomi-token-plan-sgp",
]
ProviderId = str

ThinkingLevel = Literal["minimal", "low", "medium", "high", "xhigh", "max"]
ModelThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]
ThinkingLevelMap = dict[str, str | None]

CacheRetention = Literal["none", "short", "long"]
Transport = Literal["sse", "websocket", "websocket-cached", "auto"]
ProviderEnv = dict[str, str]
ProviderHeaders = dict[str, str | None]
SessionAffinityFormat = Literal["openai", "openai-nosession", "openrouter"]
StopReason = Literal["stop", "length", "toolUse", "error", "aborted"]
ImagesStopReason = Literal["stop", "error", "aborted"]


class ProviderResponse(TypedDict):
    status: int
    headers: dict[str, str]


class CostBreakdown(TypedDict):
    input: float
    output: float
    cacheRead: float
    cacheWrite: float
    total: float


class Usage(TypedDict):
    input: int
    output: int
    cacheRead: int
    cacheWrite: int
    totalTokens: int
    cost: CostBreakdown
    cacheWrite1h: NotRequired[int]
    reasoning: NotRequired[int]


class TextContent(TypedDict):
    type: Literal["text"]
    text: str
    textSignature: NotRequired[str]


class ThinkingContent(TypedDict):
    type: Literal["thinking"]
    thinking: str
    thinkingSignature: NotRequired[str]
    redacted: NotRequired[bool]


class ImageContent(TypedDict):
    type: Literal["image"]
    data: str
    mimeType: str


class ToolCall(TypedDict):
    type: Literal["toolCall"]
    id: str
    name: str
    arguments: dict[str, Any]
    thoughtSignature: NotRequired[str]


class UserMessage(TypedDict):
    role: Literal["user"]
    content: str | list[TextContent | ImageContent]
    timestamp: int


class ErrorInfo(TypedDict):
    """Structured error classification (ADR 0015, pi4 deviation from upstream).

    Present on AssistantMessage only when ``stopReason == "error"``.
    ``statusCode`` exists only when ``type == "http_error"``.
    """

    statusCode: NotRequired[int]
    type: Literal["timeout", "connection", "http_error", "parse", "aborted", "other"]
    message: str


class AssistantMessage(TypedDict):
    role: Literal["assistant"]
    content: list[TextContent | ThinkingContent | ToolCall]
    api: Api
    provider: ProviderId
    model: str
    usage: Usage
    stopReason: StopReason
    timestamp: int
    responseModel: NotRequired[str]
    responseId: NotRequired[str]
    errorMessage: NotRequired[str]
    error: NotRequired[ErrorInfo]


class ToolResultMessage(TypedDict):
    role: Literal["toolResult"]
    toolCallId: str
    toolName: str
    content: list[TextContent | ImageContent]
    isError: bool
    timestamp: int
    details: NotRequired[Any]
    usage: NotRequired[Usage]
    addedToolNames: NotRequired[list[str]]


Message = UserMessage | AssistantMessage | ToolResultMessage


class Tool(TypedDict):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema (TypeBox → plain schema)


class Context(TypedDict):
    messages: list[Message]
    systemPrompt: NotRequired[str]
    tools: NotRequired[list[Tool]]


class ImagesContext(TypedDict):
    input: list[TextContent | ImageContent]


class AssistantImages(TypedDict):
    api: ImagesApi
    provider: str
    model: str
    output: list[TextContent | ImageContent]
    stopReason: ImagesStopReason
    timestamp: int
    responseId: NotRequired[str]
    usage: NotRequired[Usage]
    errorMessage: NotRequired[str]


class ModelCostRates(TypedDict):
    input: float
    output: float
    cacheRead: float
    cacheWrite: float


class ModelCost(ModelCostRates):
    pass


class Model(TypedDict):
    id: str
    name: str
    api: Api
    provider: ProviderId
    baseUrl: str
    reasoning: bool
    input: list[Literal["text", "image"]]
    cost: ModelCost
    contextWindow: int
    maxTokens: int
    thinkingLevelMap: NotRequired[ThinkingLevelMap]
    headers: NotRequired[dict[str, str]]
    compat: NotRequired[dict[str, Any]]


class ImagesModel(TypedDict):
    id: str
    name: str
    api: ImagesApi
    provider: str
    baseUrl: str
    input: list[Literal["text", "image"]]
    output: list[Literal["text", "image"]]
    cost: ModelCost
    headers: NotRequired[dict[str, str]]


# Stream events
class AssistantMessageEventStart(TypedDict):
    type: Literal["start"]
    partial: AssistantMessage


class AssistantMessageEventTextStart(TypedDict):
    type: Literal["text_start"]
    contentIndex: int
    partial: AssistantMessage


class AssistantMessageEventTextDelta(TypedDict):
    type: Literal["text_delta"]
    contentIndex: int
    delta: str
    partial: AssistantMessage


class AssistantMessageEventTextEnd(TypedDict):
    type: Literal["text_end"]
    contentIndex: int
    content: str
    partial: AssistantMessage


class AssistantMessageEventThinkingStart(TypedDict):
    type: Literal["thinking_start"]
    contentIndex: int
    partial: AssistantMessage


class AssistantMessageEventThinkingDelta(TypedDict):
    type: Literal["thinking_delta"]
    contentIndex: int
    delta: str
    partial: AssistantMessage


class AssistantMessageEventThinkingEnd(TypedDict):
    type: Literal["thinking_end"]
    contentIndex: int
    content: str
    partial: AssistantMessage


class AssistantMessageEventToolcallStart(TypedDict):
    type: Literal["toolcall_start"]
    contentIndex: int
    partial: AssistantMessage


class AssistantMessageEventToolcallDelta(TypedDict):
    type: Literal["toolcall_delta"]
    contentIndex: int
    delta: str
    partial: AssistantMessage


class AssistantMessageEventToolcallEnd(TypedDict):
    type: Literal["toolcall_end"]
    contentIndex: int
    toolCall: ToolCall
    partial: AssistantMessage


class AssistantMessageEventDone(TypedDict):
    type: Literal["done"]
    reason: Literal["stop", "length", "toolUse"]
    message: AssistantMessage


class AssistantMessageEventError(TypedDict):
    type: Literal["error"]
    reason: Literal["aborted", "error"]
    error: AssistantMessage


AssistantMessageEvent = (
    AssistantMessageEventStart
    | AssistantMessageEventTextStart
    | AssistantMessageEventTextDelta
    | AssistantMessageEventTextEnd
    | AssistantMessageEventThinkingStart
    | AssistantMessageEventThinkingDelta
    | AssistantMessageEventThinkingEnd
    | AssistantMessageEventToolcallStart
    | AssistantMessageEventToolcallDelta
    | AssistantMessageEventToolcallEnd
    | AssistantMessageEventDone
    | AssistantMessageEventError
)


class StreamOptions(TypedDict, total=False):
    temperature: float
    maxTokens: int
    signal: Any  # asyncio.Event or AbortSignal-like
    apiKey: str
    transport: Transport
    cacheRetention: CacheRetention
    sessionId: str
    onPayload: Any
    onResponse: Any
    headers: ProviderHeaders
    timeoutMs: int
    websocketConnectTimeoutMs: int
    maxRetries: int
    maxRetryDelayMs: int
    metadata: dict[str, Any]
    env: ProviderEnv


class SimpleStreamOptions(StreamOptions, total=False):
    reasoning: ModelThinkingLevel
    thinkingBudgets: dict[str, int]


def empty_usage() -> Usage:
    return {
        "input": 0,
        "output": 0,
        "cacheRead": 0,
        "cacheWrite": 0,
        "totalTokens": 0,
        "cost": {"input": 0.0, "output": 0.0, "cacheRead": 0.0, "cacheWrite": 0.0, "total": 0.0},
    }


def empty_cost() -> CostBreakdown:
    return {"input": 0.0, "output": 0.0, "cacheRead": 0.0, "cacheWrite": 0.0, "total": 0.0}
