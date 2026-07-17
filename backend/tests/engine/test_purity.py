import ast
from pathlib import Path

FORBIDDEN_PREFIXES = ("httpx", "psycopg", "passage.db", "passage.weather", "passage.api")

ENGINE_DIR = Path(__file__).resolve().parent.parent.parent / "passage" / "engine"


def _imported_modules(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _is_forbidden(module: str) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES)


def test_engine_dir_exists_and_is_non_empty() -> None:
    assert ENGINE_DIR.is_dir()
    assert list(ENGINE_DIR.glob("*.py"))


def test_engine_modules_have_no_forbidden_imports() -> None:
    violations = {}
    for py_file in sorted(ENGINE_DIR.glob("*.py")):
        bad = {m for m in _imported_modules(py_file) if _is_forbidden(m)}
        if bad:
            violations[py_file.name] = bad
    assert not violations, f"engine modules import forbidden I/O packages: {violations}"
