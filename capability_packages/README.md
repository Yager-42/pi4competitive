# capability_packages/

Local-only capability package root for CompetitorLens (ADR 0004 + **ADR 0006**).

Aligned with upstream `coding-agent` **Package Structure** / **Package Filtering**
(local subset of `docs/packages.md`). **Install / npm / git / `~/.pi` / `pi install`
are not supported.**

## Layout

Each immediate child directory is one package:

```text
capability_packages/
  my_package/
    package.json          # optional; "pi" manifest
    register.py           # optional host-delta: package-root register(api)
    extensions/           # *.py modules with register(api) | TOOLS | create_tools()
    skills/               # SKILL.md folders and/or top-level *.md
    prompts/              # *.md prompt templates
```

### `package.json` → `pi` manifest (optional)

```json
{
  "name": "my-package",
  "pi": {
    "extensions": ["./extensions"],
    "skills": ["./skills"],
    "prompts": ["./prompts"]
  }
}
```

Paths are relative to the package root. Arrays may include globs and `!exclusions`.
Themes are omitted in this port.

### Convention directories (no manifest)

If `package.json` has no `pi` key:

| directory | resources |
|-----------|-----------|
| `extensions/` | `*.py` (not `__init__.py`); subdirs with `register.py` / `index.py` |
| `skills/` | recursive `SKILL.md` + top-level `*.md` |
| `prompts/` | recursive `*.md` |

Package-root `register.py` / `index.py` is also discovered (host delta).

### Extension registration (Python host delta)

```python
from earendil_works.pi_agent import AgentTool

async def _echo(tool_call_id, params, signal=None, on_update=None):
    text = str(params.get("text", ""))
    return {"content": [{"type": "text", "text": text}], "details": {"echoed": text}}

def register(api):
    api.registerTool(AgentTool(
        name="echo",
        description="Echo text",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        label="Echo",
        execute=_echo,
    ))
```


## Load API

```python
from earendil_works.pi_agent.package_manager import (
    load_capability_packages,
    apply_capability_report,
)

report = await load_capability_packages()  # defaults to ./capability_packages
apply_capability_report(agent, report)
```

Filters: `enabled=["echo_example"]`, `disabled=[...]`, `strict=True`.

## Security

Capability packages run with full process privileges. Review code before enabling
packages. No remote download path exists in this product.
