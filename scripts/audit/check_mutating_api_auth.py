"""Audit mutating FastAPI routes for explicit auth classification.

The scanner is read-only: it parses ``backend/app/api/*.py`` with ``ast`` and
does not import application modules. Routes with ``Depends(verify_admin_token)``
are classified from code; mutating routes without that dependency must be
listed in ``mutating_api_auth_classification.json``.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_API_DIR = REPO_ROOT / "backend" / "app" / "api"
DEFAULT_CLASSIFICATION = REPO_ROOT / "scripts" / "audit" / "mutating_api_auth_classification.json"
MUTATING_METHODS = frozenset({"post", "put", "delete", "patch"})
ALLOWED_CLASSIFICATIONS = frozenset(
    {
        "admin_gate_backlog",
        "decision_required",
        "inbound_secret_required",
        "low_risk_local_state",
        "public_bootstrap",
    }
)


@dataclass(frozen=True)
class Route:
    """A mutating FastAPI route discovered by AST scan."""

    key: str
    file: str
    method: str
    path: str
    function: str
    line: int
    admin_gated: bool


@dataclass(frozen=True)
class AuditResult:
    """Route-auth audit result."""

    total_mutating: int
    admin_gated: int
    no_admin_dependency: int
    missing: list[str]
    stale: list[str]
    invalid: list[str]
    routes: list[Route]

    @property
    def ok(self) -> bool:
        """Return whether the classification baseline covers current routes."""

        return not self.missing and not self.stale and not self.invalid


def _repo_rel(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _string_constant(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _router_prefix(tree: ast.Module) -> str:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "router" for target in node.targets
        ):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if not isinstance(func, ast.Name) or func.id != "APIRouter":
            continue
        for keyword in node.value.keywords:
            if keyword.arg == "prefix":
                return _string_constant(keyword.value) or ""
    return ""


def _route_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if not isinstance(func, ast.Attribute) or func.attr not in MUTATING_METHODS:
            continue
        route_path = ""
        if decorator.args:
            route_path = _string_constant(decorator.args[0]) or ""
        routes.append((func.attr.upper(), route_path))
    return routes


def _call_name(expr: ast.AST) -> str:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return ""


def _is_verify_admin_token(expr: ast.AST) -> bool:
    return "verify_admin_token" in _call_name(expr)


def _depends_on_admin(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for subnode in ast.walk(node):
        if not isinstance(subnode, ast.Call):
            continue
        if _call_name(subnode.func) != "Depends":
            continue
        for arg in subnode.args:
            if _is_verify_admin_token(arg):
                return True
        for keyword in subnode.keywords:
            if keyword.value and _is_verify_admin_token(keyword.value):
                return True
    return False


def _join_paths(prefix: str, route_path: str) -> str:
    if not prefix:
        return route_path or "/"
    if not route_path:
        return prefix
    return f"{prefix.rstrip('/')}/{route_path.lstrip('/')}"


def scan_routes(api_dir: Path = DEFAULT_API_DIR, repo_root: Path = REPO_ROOT) -> list[Route]:
    """Scan mutating FastAPI routes under the API directory."""

    routes: list[Route] = []
    if not api_dir.exists():
        raise FileNotFoundError(f"API directory not found: {api_dir}")

    for path in sorted(api_dir.glob("*.py")):
        rel = _repo_rel(path, repo_root)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        prefix = _router_prefix(tree)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            route_decorators = _route_decorators(node)
            if not route_decorators:
                continue
            admin_gated = _depends_on_admin(node)
            for method, route_path in route_decorators:
                full_path = _join_paths(prefix, route_path)
                key = f"{rel}|{method}|{full_path}|{node.name}"
                routes.append(
                    Route(
                        key=key,
                        file=rel,
                        method=method,
                        path=full_path,
                        function=node.name,
                        line=node.lineno,
                        admin_gated=admin_gated,
                    )
                )
    return routes


def load_classifications(path: Path = DEFAULT_CLASSIFICATION) -> dict[str, dict[str, Any]]:
    """Load no-admin route classifications."""

    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "entries" in payload:
        entries = payload["entries"]
    else:
        entries = payload
    if not isinstance(entries, dict):
        raise ValueError("classification file must be a JSON object or contain an entries object")
    return entries


def _invalid_classifications(entries: dict[str, dict[str, Any]]) -> list[str]:
    invalid: list[str] = []
    for key, value in sorted(entries.items()):
        if not isinstance(value, dict):
            invalid.append(f"{key}: entry must be an object")
            continue
        classification = value.get("classification")
        priority = value.get("priority")
        reason = value.get("reason")
        if classification not in ALLOWED_CLASSIFICATIONS:
            invalid.append(f"{key}: invalid classification {classification!r}")
        if not isinstance(priority, str) or not priority:
            invalid.append(f"{key}: missing priority")
        if not isinstance(reason, str) or not reason:
            invalid.append(f"{key}: missing reason")
    return invalid


def audit_repo(
    repo_root: Path = REPO_ROOT,
    classification_path: Path | None = None,
) -> AuditResult:
    """Audit current mutating API routes against the classification baseline."""

    api_dir = repo_root / "backend" / "app" / "api"
    classifications = load_classifications(
        classification_path or repo_root / DEFAULT_CLASSIFICATION.relative_to(REPO_ROOT)
    )
    routes = scan_routes(api_dir=api_dir, repo_root=repo_root)
    no_admin_keys = {route.key for route in routes if not route.admin_gated}
    classified_keys = set(classifications)
    missing = sorted(no_admin_keys - classified_keys)
    stale = sorted(classified_keys - no_admin_keys)
    invalid = _invalid_classifications(classifications)
    admin_gated = sum(1 for route in routes if route.admin_gated)

    return AuditResult(
        total_mutating=len(routes),
        admin_gated=admin_gated,
        no_admin_dependency=len(routes) - admin_gated,
        missing=missing,
        stale=stale,
        invalid=invalid,
        routes=routes,
    )


def _format_route(route: Route) -> str:
    auth = "admin" if route.admin_gated else "classified"
    return f"{route.file}:{route.line} {route.method} {route.path} {route.function} [{auth}]"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(description="Check mutating API auth classification coverage.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT), help="repository root")
    parser.add_argument("--classification", default=None, help="classification JSON path")
    parser.add_argument("--json", action="store_true", help="emit JSON output")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root)
    classification = Path(args.classification) if args.classification else None
    try:
        result = audit_repo(repo_root, classification)
    except Exception as exc:  # noqa: BLE001 - top-level audit script fail-loud
        print(f"FATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "total_mutating": result.total_mutating,
                    "admin_gated": result.admin_gated,
                    "no_admin_dependency": result.no_admin_dependency,
                    "missing": result.missing,
                    "stale": result.stale,
                    "invalid": result.invalid,
                    "routes": [asdict(route) for route in result.routes],
                },
                indent=2,
            )
        )
    elif result.ok:
        print(
            "[mutating-api-auth] PASS: "
            f"{result.total_mutating} mutating routes, "
            f"{result.admin_gated} admin-gated, "
            f"{result.no_admin_dependency} classified no-admin routes."
        )
    else:
        print("[mutating-api-auth] BLOCK: mutating route auth classification drift.")
        if result.missing:
            print("Missing classification:")
            route_by_key = {route.key: route for route in result.routes}
            for key in result.missing:
                route = route_by_key[key]
                print(f"  {key} ({_format_route(route)})")
        if result.stale:
            print("Stale classification:")
            for key in result.stale:
                print(f"  {key}")
        if result.invalid:
            print("Invalid classification:")
            for item in result.invalid:
                print(f"  {item}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
