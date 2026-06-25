"""The package imports cleanly and exposes a version."""

import siro


def test_version():
    assert isinstance(siro.__version__, str)
    assert siro.__version__


def test_core_modules_import():
    # Importing the package surface must not require network or a model server.
    from siro import (  # noqa: F401
        archive,
        backends,
        controller,
        evaluator,
        memory,
        model_client,
        orchestrator,
        prompts,
        safety,
        sandbox,
        scale,
        schemas,
        tools,
    )
    from siro.agents import build_agents  # noqa: F401
