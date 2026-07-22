# P1 Module Map

| upstream path | python path | status | notes |
|---------------|-------------|--------|-------|
| `src/types.ts` | `packages/ai/src/earendil_works/pi_ai/types.py` | done |  |
| `src/models.ts` | `packages/ai/src/earendil_works/pi_ai/models.py` | done |  |
| `src/models-store.ts` | `packages/ai/src/earendil_works/pi_ai/models_store.py` | done |  |
| `src/model-catalog.ts` | `packages/ai/src/earendil_works/pi_ai/model_catalog.py` | done |  |
| `src/models.generated.ts` | `packages/ai/src/earendil_works/pi_ai/models_generated.py` | done | JSON catalogs from npm 0.81.1 |
| `src/utils/event-stream.ts` | `packages/ai/src/earendil_works/pi_ai/utils/event_stream.py` | done |  |
| `src/utils/validation.ts` | `packages/ai/src/earendil_works/pi_ai/utils/validation.py` | done |  |
| `src/utils/uuid.ts` | `packages/ai/src/earendil_works/pi_ai/utils/uuid.py` | done |  |
| `src/utils/json-parse.ts` | `packages/ai/src/earendil_works/pi_ai/utils/json_parse.py` | done |  |
| `src/utils/text.ts` | `packages/ai/src/earendil_works/pi_ai/utils/text.py` | done |  |
| `src/utils/retry.ts` | `packages/ai/src/earendil_works/pi_ai/utils/retry.py` | done |  |
| `src/utils/provider-env.ts` | `packages/ai/src/earendil_works/pi_ai/utils/provider_env.py` | done |  |
| `src/utils/typebox-helpers.ts` | `packages/ai/src/earendil_works/pi_ai/utils/pydantic_helpers.py` | done | TypeBox→Pydantic host delta |
| `src/auth/*` | `packages/ai/src/earendil_works/pi_ai/auth/` | done |  |
| `src/api/lazy.ts` | `packages/ai/src/earendil_works/pi_ai/api/lazy.py` | done |  |
| `src/api/transform-messages.ts` | `packages/ai/src/earendil_works/pi_ai/api/transform_messages.py` | done |  |
| `src/api/openai-completions.ts` | `packages/ai/src/earendil_works/pi_ai/api/openai_completions.py` | done | httpx SSE |
| `src/api/openai-responses.ts` | `packages/ai/src/earendil_works/pi_ai/api/openai_responses.py` | done | surface; chat-compat streaming path |
| `src/api/anthropic-messages.ts` | `packages/ai/src/earendil_works/pi_ai/api/anthropic_messages.py` | done | httpx SSE |
| `src/api/google-generative-ai.ts` | `packages/ai/src/earendil_works/pi_ai/api/google_generative_ai.py` | done | structural; shared http path |
| `src/api/google-vertex.ts` | `packages/ai/src/earendil_works/pi_ai/api/google_vertex.py` | done |  |
| `src/api/bedrock-converse-stream.ts` | `packages/ai/src/earendil_works/pi_ai/api/bedrock_converse_stream.py` | done | structural |
| `src/api/mistral-conversations.ts` | `packages/ai/src/earendil_works/pi_ai/api/mistral_conversations.py` | done |  |
| `src/api/azure-openai-responses.ts` | `packages/ai/src/earendil_works/pi_ai/api/azure_openai_responses.py` | done |  |
| `src/api/openai-codex-responses.ts` | `packages/ai/src/earendil_works/pi_ai/api/openai_codex_responses.py` | done |  |
| `src/api/pi-messages.ts` | `packages/ai/src/earendil_works/pi_ai/api/pi_messages.py` | done |  |
| `src/api/openrouter-images.ts` | `packages/ai/src/earendil_works/pi_ai/api/openrouter_images.py` | done |  |
| `src/providers/faux.ts` | `packages/ai/src/earendil_works/pi_ai/providers/faux.py` | done |  |
| `src/providers/all.ts` | `packages/ai/src/earendil_works/pi_ai/providers/all.py` | done |  |
| `src/providers/data/*.json` | `packages/ai/src/earendil_works/pi_ai/providers/data/` | done | from @earendil-works/pi-ai@0.81.1 |
| `src/providers/<id>.ts` | `packages/ai/src/earendil_works/pi_ai/providers/<id>.py` | done | 37 catalog providers + radius |
| `src/compat/**` | `packages/ai/src/earendil_works/pi_ai/compat/` | done |  |
| `src/images*.ts` | `packages/ai/src/earendil_works/pi_ai/images*.py` | done | structural |
| `src/oauth.ts / bun-oauth.ts` | `packages/ai/src/earendil_works/pi_ai/oauth.py + auth/oauth/` | host-delta | No Bun; stub loaders |
| `src/cli.ts` | `packages/ai/src/earendil_works/pi_ai/cli.py` | done | minimal host CLI |

Upstream SHA: see `docs/plans/UPSTREAM_SHA.txt`

