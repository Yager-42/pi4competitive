"""MODELS aggregate — port of models.generated.ts using JSON catalogs."""
from __future__ import annotations
from .model_catalog import load_provider_catalog

_PROVIDERS = [
    "amazon-bedrock","ant-ling","anthropic","azure-openai-responses","cerebras",
    "cloudflare-ai-gateway","cloudflare-workers-ai","deepseek","fireworks","github-copilot",
    "google","google-vertex","groq","huggingface","kimi-coding","minimax","minimax-cn",
    "mistral","moonshotai","moonshotai-cn","nvidia","openai","openai-codex","opencode",
    "opencode-go","openrouter","qwen-token-plan","qwen-token-plan-cn","together",
    "vercel-ai-gateway","xai","xiaomi","xiaomi-token-plan-ams","xiaomi-token-plan-cn",
    "xiaomi-token-plan-sgp","zai","zai-coding-cn",
]

MODELS = {p: load_provider_catalog(p) for p in _PROVIDERS}
