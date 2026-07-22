from __future__ import annotations

from pathlib import Path

import earendil_works.pi_ai as pi_ai
from earendil_works.pi_ai.providers import builtin_models, builtin_providers, get_builtin_providers
from earendil_works.pi_ai.providers.faux import faux_provider

ROOT = Path(__file__).resolve().parents[4]
EXPECTED_PROVIDERS = (ROOT / "tests/packages/ai/contract/expected_providers.txt").read_text().split()
EXPECTED_APIS = (ROOT / "tests/packages/ai/contract/expected_apis.txt").read_text().split()


def test_public_symbols_minimum_set() -> None:
    for name in [
        "Context",
        "Tool",
        "Model",
        "Usage",
        "AssistantMessageEventStream",
        "create_models",
        "create_provider",
        "builtin_models",
        "faux_provider",
        "faux_assistant_message",
        "empty_usage",
    ]:
        assert hasattr(pi_ai, name), name


def test_provider_modules_exist() -> None:
    # every expected catalog provider has a module
    from importlib import import_module

    for pid in EXPECTED_PROVIDERS:
        if pid == "radius":
            mod = import_module("earendil_works.pi_ai.providers.radius")
            assert hasattr(mod, "radius_provider")
            continue
        mod_name = "earendil_works.pi_ai.providers." + pid.replace("-", "_")
        mod = import_module(mod_name)
        assert hasattr(mod, pid.replace("-", "_") + "_provider")


def test_api_modules_exist() -> None:
    from importlib import import_module

    for api in EXPECTED_APIS:
        mod = import_module("earendil_works.pi_ai.api." + api.replace("-", "_"))
        assert mod is not None


def test_subpath_imports() -> None:
    from earendil_works.pi_ai.providers import faux
    from earendil_works.pi_ai.providers import all as providers_all
    from earendil_works.pi_ai.api import openai_completions

    assert faux.faux_provider is not None
    assert providers_all.builtin_models is not None
    assert openai_completions.open_ai_completions_api is not None


def test_builtin_providers_register() -> None:
    ids = set(get_builtin_providers())
    for pid in EXPECTED_PROVIDERS:
        assert pid in ids, pid


def test_builtin_models_no_competitive_app_import() -> None:
    models = builtin_models()
    assert models.getProviders()
    # structural: faux still works alongside builtins
    f = faux_provider()
    models.setProvider(f["provider"])
    assert models.getModel("faux", "faux-1") is not None


def test_ai_package_does_not_import_competitive_app() -> None:
    import ast
    from pathlib import Path

    ai = Path(__file__).resolve().parents[4] / "packages/ai/src/earendil_works/pi_ai"
    for path in ai.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "competitive_app" in node.module:
                raise AssertionError(path)
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert "competitive_app" not in a.name


def test_ai_package_does_not_import_capability_packages() -> None:
    import ast
    from pathlib import Path

    ai = Path(__file__).resolve().parents[4] / "packages/ai/src/earendil_works/pi_ai"
    for path in ai.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "capability_packages" in node.module:
                raise AssertionError(path)
