import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
API_KEY_NAMES = (
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ZHIPUAI_API_KEY",
)


def _clean_environment():
    environment = os.environ.copy()
    for name in API_KEY_NAMES:
        environment.pop(name, None)
    environment["PYTHONPATH"] = str(ROOT)
    return environment


def _run_clean_python(source):
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=ROOT,
        env=_clean_environment(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_main_imports_without_provider_stubs_or_api_keys():
    result = _run_clean_python("import main")

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_real_graph_constructs_without_model_instantiation():
    result = _run_clean_python(
        "\n".join(
            [
                "from langgraph.checkpoint.memory import InMemorySaver",
                "from src.graph import create_graph",
                "graph = create_graph(checkpointer=InMemorySaver())",
                "assert graph is not None",
            ]
        )
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_src_packages_import_in_either_order():
    result_forward = _run_clean_python("import src.domain; import src.schemas")
    result_reverse = _run_clean_python("import src.schemas; import src.domain")

    assert result_forward.returncode == 0, result_forward.stderr
    assert result_reverse.returncode == 0, result_reverse.stderr
