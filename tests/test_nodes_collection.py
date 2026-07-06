import builtins
import contextlib
import importlib.util
import io
from pathlib import Path


def test_test_nodes_module_is_inert_on_import():
    module_path = Path(__file__).with_name("test_nodes.py")
    spec = importlib.util.spec_from_file_location("isolated_test_nodes", module_path)
    assert spec and spec.loader

    stdout = io.StringIO()
    stderr = io.StringIO()
    imported_names = []
    real_import = builtins.__import__

    def tracking_import(name, globals=None, locals=None, fromlist=(), level=0):
        imported_names.append(name)
        return real_import(name, globals, locals, fromlist, level)

    module = importlib.util.module_from_spec(spec)

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        builtins.__import__ = tracking_import
        try:
            spec.loader.exec_module(module)
        finally:
            builtins.__import__ = real_import

    assert stdout.getvalue() == ""
    assert stderr.getvalue() == ""
    assert callable(module.main)
    assert not any(name == "src" or name.startswith("src.") for name in imported_names)
    assert not any(
        name == "langchain_core" or name.startswith("langchain_core.")
        for name in imported_names
    )
