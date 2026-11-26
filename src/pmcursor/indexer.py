from __future__ import annotations

import ast
from pathlib import Path

from pmcursor._multistack_indexer import (
    HTTP_METHODS,
    _extract_adr,
    _extract_graphql_contracts,
    _extract_nextjs_routes,
    _extract_openapi_contracts,
    _extract_prisma_models,
    _extract_sql_models,
    _extract_sql_telemetry,
    _extract_ts_telemetry,
    _extract_zod_models,
    _is_nextjs_route_file,
)
from pmcursor.models import (
    ADRContract,
    FieldContract,
    ModelContract,
    RepoMap,
    RouteContract,
    TelemetryContract,
)

MAX_INDEX_FILE_BYTES = 2_097_152

MODEL_BASE_NAMES: frozenset[str] = frozenset(
    {"BaseModel", "SQLModel", "Schema", "TypedDict"}
)
IGNORED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
    }
)


def _format_annotation(node: ast.expr | None) -> str:
    if node is None:
        return "Any"
    return ast.unparse(node).strip()


def _extract_base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _extract_base_name(node.value)
    return ast.unparse(node).strip()


def _is_contract_model(node: ast.ClassDef) -> tuple[bool, list[str]]:
    bases = [_extract_base_name(base) for base in node.bases]
    for base in bases:
        if base in MODEL_BASE_NAMES or base.endswith(("Model", "Schema", "Request", "Response")):
            return True, bases
    for dec in node.decorator_list:
        dec_name = _extract_base_name(dec.func if isinstance(dec, ast.Call) else dec)
        if dec_name == "dataclass":
            return True, ["dataclass", *bases]
    return False, bases


def _is_field_required(value: ast.expr | None) -> bool:
    if value is None:
        return True
    if isinstance(value, ast.Constant) and value.value is Ellipsis:
        return True
    if isinstance(value, ast.Call):
        func_name = _extract_base_name(value.func)
        if func_name == "Field":
            if (
                value.args
                and isinstance(value.args[0], ast.Constant)
                and value.args[0].value is Ellipsis
            ):
                return True
            for kw in value.keywords:
                if kw.arg in {"default", "default_factory"}:
                    return bool(
                        isinstance(kw.value, ast.Constant) and kw.value.value is Ellipsis
                    )
            return True
    return False


def _extract_models_from_tree(tree: ast.Module, rel_path: str) -> list[ModelContract]:
    models: list[ModelContract] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        is_model, bases = _is_contract_model(node)
        if not is_model:
            continue
        fields: list[FieldContract] = []
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                field_name = stmt.target.id
                if field_name.startswith("_") or field_name == "model_config":
                    continue
                fields.append(
                    FieldContract(
                        name=field_name,
                        type_annotation=_format_annotation(stmt.annotation),
                        required=_is_field_required(stmt.value),
                        line=stmt.lineno,
                    )
                )
        models.append(
            ModelContract(
                name=node.name,
                file_path=rel_path,
                line=node.lineno,
                base_classes=bases,
                fields=fields,
            )
        )
    return sorted(models, key=lambda m: (m.file_path, m.line))


def _extract_router_prefixes(tree: ast.Module) -> dict[str, str]:
    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func_name = _extract_base_name(node.value.func)
        if func_name not in {"APIRouter", "FastAPI"}:
            continue
        prefix = ""
        for kw in node.value.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) and isinstance(
                kw.value.value, str
            ):
                prefix = kw.value.value.rstrip("/")
        for target in node.targets:
            if isinstance(target, ast.Name):
                prefixes[target.id] = prefix
    return prefixes


def _extract_routes_from_tree(tree: ast.Module, rel_path: str) -> list[RouteContract]:
    prefixes = _extract_router_prefixes(tree)
    routes: list[RouteContract] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            method_lower = dec.func.attr.lower()
            if method_lower not in HTTP_METHODS:
                continue
            router_name = (
                dec.func.value.id if isinstance(dec.func.value, ast.Name) else ""
            )
            prefix = prefixes.get(router_name, "")
            raw_path = "/"
            if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(
                dec.args[0].value, str
            ):
                raw_path = dec.args[0].value
            else:
                for kw in dec.keywords:
                    if kw.arg == "path" and isinstance(kw.value, ast.Constant) and isinstance(
                        kw.value.value, str
                    ):
                        raw_path = kw.value.value
            full_path = f"{prefix}/{raw_path.lstrip('/')}".rstrip("/") or "/"
            if not full_path.startswith("/"):
                full_path = f"/{full_path}"

            response_model: str | None = None
            for kw in dec.keywords:
                if kw.arg == "response_model":
                    response_model = _format_annotation(kw.value)
            if response_model is None and node.returns is not None:
                ret_str = _format_annotation(node.returns)
                if ret_str not in {"None", "dict", "Any"}:
                    response_model = ret_str

            request_model: str | None = None
            for arg in node.args.args:
                if arg.arg in {"self", "cls", "request", "db", "session", "current_user"}:
                    continue
                if arg.annotation is not None:
                    ann = _format_annotation(arg.annotation)
                    if ann not in {"str", "int", "float", "bool", "UUID"}:
                        request_model = ann
                        break

            routes.append(
                RouteContract(
                    method=method_lower.upper(),
                    path=full_path,
                    function_name=node.name,
                    file_path=rel_path,
                    line=node.lineno,
                    request_model=request_model,
                    response_model=response_model,
                )
            )
    return sorted(routes, key=lambda r: (r.file_path, r.line))


def _dict_keys_from_ast(node: ast.expr | None) -> list[str]:
    if not isinstance(node, ast.Dict):
        return []
    keys: list[str] = []
    for key in node.keys:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            keys.append(key.value)
    return keys


def _string_const(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _extract_telemetry_from_tree(tree: ast.Module, rel_path: str) -> list[TelemetryContract]:
    events: list[TelemetryContract] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                dec_name = _extract_base_name(dec.func if isinstance(dec, ast.Call) else dec)
                if dec_name != "observe":
                    continue
                obs_name = node.name
                if isinstance(dec, ast.Call):
                    for kw in dec.keywords:
                        if kw.arg == "name":
                            kw_val = _string_const(kw.value)
                            if kw_val is not None:
                                obs_name = kw_val
                events.append(
                    TelemetryContract(
                        event_name=obs_name,
                        source_kind="langfuse",
                        properties=[],
                        file_path=rel_path,
                        line=dec.lineno,
                    )
                )
            continue

        if not isinstance(node, ast.Call):
            continue

        if isinstance(node.func, ast.Name) and node.func.id == "track_event":
            te_name: str | None = _string_const(node.args[0]) if node.args else None
            te_props = _dict_keys_from_ast(node.args[1]) if len(node.args) > 1 else []
            for kw in node.keywords:
                if kw.arg in {"event_name", "name"} and te_name is None:
                    te_name = _string_const(kw.value)
                elif kw.arg in {"properties", "props"} and not te_props:
                    te_props = _dict_keys_from_ast(kw.value)
            if te_name is not None:
                events.append(
                    TelemetryContract(
                        event_name=te_name,
                        source_kind="track_event",
                        properties=te_props,
                        file_path=rel_path,
                        line=node.lineno,
                    )
                )
            continue

        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            receiver = node.func.value.id
            method = node.func.attr
            if receiver == "posthog" and method == "capture":
                ph_name: str | None = None
                ph_props: list[str] = []
                if len(node.args) >= 2:
                    first_str = _string_const(node.args[0])
                    second_str = _string_const(node.args[1])
                    if first_str is not None and isinstance(node.args[1], ast.Dict):
                        ph_name = first_str
                        ph_props = _dict_keys_from_ast(node.args[1])
                    elif second_str is not None:
                        ph_name = second_str
                        if len(node.args) > 2:
                            ph_props = _dict_keys_from_ast(node.args[2])
                    elif first_str is not None:
                        ph_name = first_str
                elif len(node.args) == 1:
                    ph_name = _string_const(node.args[0])

                for kw in node.keywords:
                    if kw.arg == "event" and ph_name is None:
                        ph_name = _string_const(kw.value)
                    elif kw.arg == "properties" and not ph_props:
                        ph_props = _dict_keys_from_ast(kw.value)

                if ph_name is not None:
                    events.append(
                        TelemetryContract(
                            event_name=ph_name,
                            source_kind="posthog",
                            properties=ph_props,
                            file_path=rel_path,
                            line=node.lineno,
                        )
                    )
            elif receiver in {"langfuse", "langfuse_context"}:
                lf_name: str | None = _string_const(node.args[0]) if node.args else None
                lf_props: list[str] = []
                for kw in node.keywords:
                    if kw.arg == "name" and lf_name is None:
                        lf_name = _string_const(kw.value)
                    elif kw.arg in {"metadata", "input"} and not lf_props:
                        lf_props = _dict_keys_from_ast(kw.value)
                if lf_name is not None:
                    events.append(
                        TelemetryContract(
                            event_name=lf_name,
                            source_kind="langfuse",
                            properties=lf_props,
                            file_path=rel_path,
                            line=node.lineno,
                        )
                    )

    return sorted(events, key=lambda t: (t.file_path, t.line))


def index_repository(repo_root: Path) -> RepoMap:
    """Walk a repository and extract models, routes, telemetry, and ADRs."""
    resolved_root = repo_root.resolve()
    models: list[ModelContract] = []
    routes: list[RouteContract] = []
    telemetry: list[TelemetryContract] = []
    adrs: list[ADRContract] = []
    indexed_files: list[str] = []

    for path in sorted(resolved_root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            if not path.resolve().is_relative_to(resolved_root):
                continue
        except OSError:
            continue
        rel_parts = path.relative_to(resolved_root).parts
        if any(part in IGNORED_DIRS or part.startswith(".") for part in rel_parts[:-1]):
            continue
        try:
            if path.stat().st_size > MAX_INDEX_FILE_BYTES:
                continue
        except OSError:
            continue

        rel_path = path.relative_to(resolved_root).as_posix()
        indexed_files.append(rel_path)
        name_lower = path.name.lower()

        if path.suffix == ".py":
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=rel_path)
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue
            models.extend(_extract_models_from_tree(tree, rel_path))
            routes.extend(_extract_routes_from_tree(tree, rel_path))
            telemetry.extend(_extract_telemetry_from_tree(tree, rel_path))
        elif path.suffix in {".ts", ".tsx"}:
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            models.extend(_extract_zod_models(source, rel_path))
            if _is_nextjs_route_file(rel_path):
                routes.extend(_extract_nextjs_routes(source, rel_path))
            telemetry.extend(_extract_ts_telemetry(source, rel_path))
        elif name_lower.endswith(("openapi.json", "openapi.yaml", "openapi.yml")):
            oa_models, oa_routes = _extract_openapi_contracts(path, rel_path)
            models.extend(oa_models)
            routes.extend(oa_routes)
        elif path.suffix == ".sql":
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            models.extend(_extract_sql_models(source, rel_path))
            telemetry.extend(_extract_sql_telemetry(source, rel_path))
        elif path.suffix == ".prisma":
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            models.extend(_extract_prisma_models(source, rel_path))
        elif path.suffix in {".graphql", ".gql"}:
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            gql_models, gql_routes = _extract_graphql_contracts(source, rel_path)
            models.extend(gql_models)
            routes.extend(gql_routes)
        elif (
            path.suffix == ".md"
            and len(rel_parts) >= 2
            and rel_parts[0] == "docs"
            and rel_parts[1] == "adr"
        ):
            adr = _extract_adr(path, rel_path)
            if adr is not None:
                adrs.append(adr)

    return RepoMap(
        repo_root=str(resolved_root),
        models=models,
        routes=routes,
        telemetry=telemetry,
        adrs=adrs,
        indexed_files=sorted(indexed_files),
    )
