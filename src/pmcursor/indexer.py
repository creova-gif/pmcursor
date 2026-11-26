from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from pmcursor.models import (
    ADRContract,
    FieldContract,
    ModelContract,
    RepoMap,
    RouteContract,
    TelemetryContract,
    TelemetrySourceKind,
)

MAX_INDEX_FILE_BYTES = 2_097_152

HTTP_METHODS: frozenset[str] = frozenset(
    {"get", "post", "put", "patch", "delete", "options", "head"}
)
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

ADR_HEADING_RE = re.compile(r"^#\s*(ADR-\d+)\s*:\s*(.+)$", re.IGNORECASE)
ADR_STATUS_RE = re.compile(r"^-\s*\*\*Status:\*\*\s*(.+)$", re.IGNORECASE)

ZOD_OBJECT_RE = re.compile(
    r"(?:export\s+)?const\s+([A-Za-z_]\w*)\s*=\s*z\.object\s*\(\s*\{"
)
TS_INTERFACE_RE = re.compile(
    r"(?:export\s+)?interface\s+([A-Za-z_]\w*)(?:\s+extends\s+[^{]+)?\s*\{"
)
ZOD_TYPE_MAP: dict[str, str] = {
    "string": "str",
    "number": "float",
    "boolean": "bool",
    "date": "datetime",
    "bigint": "int",
}
TS_TYPE_MAP: dict[str, str] = {
    "string": "str",
    "number": "float",
    "boolean": "bool",
    "Date": "datetime",
}

NEXTJS_ROUTE_FN_RE = re.compile(
    r"^\s*export\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE)\b",
    re.MULTILINE,
)

SQL_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:[`\"\[]?[A-Za-z_]\w*[`\"\]]?\.)?[`\"\[]?([A-Za-z_]\w*)[`\"\]]?\s*\(",
    re.IGNORECASE,
)
SQL_TYPE_MAP: dict[str, str] = {
    "TEXT": "str",
    "VARCHAR": "str",
    "CHAR": "str",
    "STRING": "str",
    "INT": "int",
    "INTEGER": "int",
    "BIGINT": "int",
    "SMALLINT": "int",
    "INT64": "int",
    "SERIAL": "int",
    "BIGSERIAL": "int",
    "BOOLEAN": "bool",
    "BOOL": "bool",
    "NUMERIC": "float",
    "DECIMAL": "float",
    "FLOAT": "float",
    "FLOAT64": "float",
    "DOUBLE": "float",
    "REAL": "float",
    "TIMESTAMP": "datetime",
    "TIMESTAMPTZ": "datetime",
    "DATETIME": "datetime",
    "DATE": "datetime",
}
SQL_CONSTRAINT_PREFIXES: tuple[str, ...] = (
    "PRIMARY KEY",
    "FOREIGN KEY",
    "CONSTRAINT",
    "UNIQUE",
    "CHECK",
    "INDEX",
    "KEY",
)

OPENAPI_TYPE_MAP: dict[str, str] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "object": "dict[str, Any]",
    "array": "list[Any]",
}

TS_TELEMETRY_RE = re.compile(
    r"(?:(posthog\.capture)|(?<![.\w])(track_event)|(?<![.\w])(track))\s*\(\s*"
    r"([\"'`])([^\"'`]+)\4(?:\s*,\s*\{)?"
)


def _line_number_at(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _find_matching_delimiter(
    source: str, open_idx: int, open_ch: str, close_ch: str
) -> int | None:
    depth = 0
    in_quote: str | None = None
    escaped = False
    for idx in range(open_idx, len(source)):
        ch = source[idx]
        if escaped:
            escaped = False
            continue
        if in_quote is not None:
            if ch == "\\":
                escaped = True
            elif ch == in_quote:
                in_quote = None
            continue
        if ch in {"'", '"', "`"}:
            in_quote = ch
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return idx
    return None


def _split_top_level_with_offsets(
    text: str, base_offset: int, separators: frozenset[str]
) -> list[tuple[str, int]]:
    items: list[tuple[str, int]] = []
    depth = 0
    in_quote: str | None = None
    escaped = False
    chunk_start = 0

    for idx, ch in enumerate(text):
        if escaped:
            escaped = False
            continue
        if in_quote is not None:
            if ch == "\\":
                escaped = True
            elif ch == in_quote:
                in_quote = None
            continue
        if ch in {"'", '"', "`"}:
            in_quote = ch
            continue
        if ch in {"(", "{", "["}:
            depth += 1
        elif ch in {")", "}", "]"} and depth > 0:
            depth -= 1
        elif depth == 0 and ch in separators:
            chunk = text[chunk_start:idx]
            if chunk.strip():
                leading_ws = len(chunk) - len(chunk.lstrip())
                items.append((chunk.strip(), base_offset + chunk_start + leading_ws))
            chunk_start = idx + 1

    tail = text[chunk_start:]
    if tail.strip():
        leading_ws = len(tail) - len(tail.lstrip())
        items.append((tail.strip(), base_offset + chunk_start + leading_ws))
    return items


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


def _map_zod_type(expr: str) -> str:
    match = re.search(r"z\.([A-Za-z_]\w*)\s*\(", expr)
    if not match:
        return "Any"
    zod_kind = match.group(1)
    if zod_kind == "array":
        inner_start = match.end() - 1
        inner_end = _find_matching_delimiter(expr, inner_start, "(", ")")
        if inner_end is not None:
            inner_type = _map_zod_type(expr[inner_start + 1 : inner_end])
            return f"list[{inner_type}]"
        return "list[Any]"
    return ZOD_TYPE_MAP.get(zod_kind, zod_kind)


def _extract_zod_models(source: str, rel_path: str) -> list[ModelContract]:
    models: list[ModelContract] = []

    for match in ZOD_OBJECT_RE.finditer(source):
        model_name = match.group(1)
        open_brace = match.end() - 1
        close_brace = _find_matching_delimiter(source, open_brace, "{", "}")
        if close_brace is None:
            continue
        body = source[open_brace + 1 : close_brace]
        fields: list[FieldContract] = []
        for chunk, offset in _split_top_level_with_offsets(body, open_brace + 1, frozenset({","})):
            if ":" not in chunk:
                continue
            field_raw, expr_raw = chunk.split(":", 1)
            field_name = field_raw.strip()
            if not re.fullmatch(r"[A-Za-z_]\w*", field_name):
                continue
            expr = expr_raw.strip()
            fields.append(
                FieldContract(
                    name=field_name,
                    type_annotation=_map_zod_type(expr),
                    required=".optional()" not in expr,
                    line=_line_number_at(source, offset),
                )
            )
        models.append(
            ModelContract(
                name=model_name,
                file_path=rel_path,
                line=_line_number_at(source, match.start()),
                base_classes=["ZodObject"],
                fields=fields,
            )
        )

    for match in TS_INTERFACE_RE.finditer(source):
        model_name = match.group(1)
        open_brace = match.end() - 1
        close_brace = _find_matching_delimiter(source, open_brace, "{", "}")
        if close_brace is None:
            continue
        body = source[open_brace + 1 : close_brace]
        fields = []
        for chunk, offset in _split_top_level_with_offsets(
            body, open_brace + 1, frozenset({";", "\n"})
        ):
            cleaned = chunk.strip().rstrip(",;")
            if not cleaned or cleaned.startswith("//") or ":" not in cleaned:
                continue
            field_raw, type_raw = cleaned.split(":", 1)
            field_part = re.sub(r"^readonly\s+", "", field_raw.strip())
            optional = field_part.endswith("?")
            field_name = field_part.rstrip("?").strip()
            if not re.fullmatch(r"[A-Za-z_]\w*", field_name):
                continue
            ts_type = type_raw.strip()
            mapped_type = TS_TYPE_MAP.get(ts_type, ts_type)
            fields.append(
                FieldContract(
                    name=field_name,
                    type_annotation=mapped_type,
                    required=not optional,
                    line=_line_number_at(source, offset),
                )
            )
        models.append(
            ModelContract(
                name=model_name,
                file_path=rel_path,
                line=_line_number_at(source, match.start()),
                base_classes=["interface"],
                fields=fields,
            )
        )

    return sorted(models, key=lambda m: (m.file_path, m.line))


def _is_nextjs_route_file(rel_path: str) -> bool:
    parts = Path(rel_path).parts
    if not parts or parts[-1] != "route.ts":
        return False
    return parts[0] == "app" or (len(parts) >= 2 and parts[0] == "src" and parts[1] == "app")


def _derive_nextjs_route_path(rel_path: str) -> str:
    parts = list(Path(rel_path).parts)
    app_idx = parts.index("app")
    route_segments = parts[app_idx + 1 : -1]
    normalized: list[str] = []
    for segment in route_segments:
        if segment.startswith("(") and segment.endswith(")"):
            continue
        converted = re.sub(r"\[(?:\.\.\.)?([^\]]+)\]", r"{\1}", segment)
        normalized.append(converted)
    return "/" + "/".join(normalized) if normalized else "/"


def _extract_nextjs_routes(source: str, rel_path: str) -> list[RouteContract]:
    route_path = _derive_nextjs_route_path(rel_path)
    routes: list[RouteContract] = []
    for match in NEXTJS_ROUTE_FN_RE.finditer(source):
        method = match.group(1)
        routes.append(
            RouteContract(
                method=method,
                path=route_path,
                function_name=method,
                file_path=rel_path,
                line=_line_number_at(source, match.start()),
            )
        )
    return sorted(routes, key=lambda r: (r.file_path, r.line))


def _extract_ts_telemetry(source: str, rel_path: str) -> list[TelemetryContract]:
    events: list[TelemetryContract] = []
    for match in TS_TELEMETRY_RE.finditer(source):
        if match.group(1):
            source_kind: TelemetrySourceKind = "posthog"
        elif match.group(2):
            source_kind = "track_event"
        else:
            source_kind = "vercel_analytics"
        event_name = match.group(5)
        props: list[str] = []
        if match.group(0).endswith("{"):
            open_brace = match.end() - 1
            close_brace = _find_matching_delimiter(source, open_brace, "{", "}")
            if close_brace is not None:
                body = source[open_brace + 1 : close_brace]
                for chunk, _ in _split_top_level_with_offsets(
                    body, open_brace + 1, frozenset({","})
                ):
                    key_part = chunk.split(":", 1)[0].strip().strip("\"'")
                    if re.fullmatch(r"[A-Za-z_]\w*", key_part):
                        props.append(key_part)
        events.append(
            TelemetryContract(
                event_name=event_name,
                source_kind=source_kind,
                properties=props,
                file_path=rel_path,
                line=_line_number_at(source, match.start()),
            )
        )
    return sorted(events, key=lambda t: (t.file_path, t.line))


def _unquote_yaml_scalar(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def _strip_yaml_comment(line: str) -> str:
    in_quote: str | None = None
    for idx, ch in enumerate(line):
        if in_quote is not None:
            if ch == in_quote:
                in_quote = None
            continue
        if ch in {"'", '"'}:
            in_quote = ch
        elif ch == "#" and (idx == 0 or line[idx - 1].isspace()):
            return line[:idx]
    return line


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any] | list[Any]]] = [(-1, root)]
    raw_lines = text.splitlines()

    parsed_lines: list[tuple[int, str]] = []
    for raw in raw_lines:
        no_comment = _strip_yaml_comment(raw).rstrip()
        if not no_comment.strip() or no_comment.strip() in {"---", "..."}:
            continue
        indent = len(no_comment) - len(no_comment.lstrip(" "))
        parsed_lines.append((indent, no_comment.strip()))

    for idx, (indent, content) in enumerate(parsed_lines):
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]

        if content.startswith("- "):
            item_val = _unquote_yaml_scalar(content[2:])
            if isinstance(parent, list):
                parent.append(item_val)
            continue

        if ":" not in content:
            continue
        key_raw, val_raw = content.split(":", 1)
        key = _unquote_yaml_scalar(key_raw)
        val_str = val_raw.strip()

        if val_str:
            if isinstance(parent, dict):
                if val_str.startswith("[") and val_str.endswith("]"):
                    inner = val_str[1:-1].strip()
                    parent[key] = (
                        [_unquote_yaml_scalar(v) for v in inner.split(",") if v.strip()]
                        if inner
                        else []
                    )
                else:
                    parent[key] = _unquote_yaml_scalar(val_str)
            continue

        next_is_list = (
            idx + 1 < len(parsed_lines)
            and parsed_lines[idx + 1][0] > indent
            and parsed_lines[idx + 1][1].startswith("- ")
        )
        container: dict[str, Any] | list[Any] = [] if next_is_list else {}
        if isinstance(parent, dict):
            parent[key] = container
        stack.append((indent, container))

    return root


def _find_key_line(text: str, key: str, start_line: int = 1) -> int:
    lines = text.splitlines()
    pattern = re.compile(rf"^\s*[\"']?{re.escape(key)}[\"']?\s*:")
    for line_no in range(start_line, len(lines) + 1):
        if pattern.match(lines[line_no - 1]):
            return line_no
    return start_line


def _extract_ref_name(schema_obj: Any) -> str | None:
    if not isinstance(schema_obj, dict):
        return None
    ref = schema_obj.get("$ref")
    if isinstance(ref, str) and "/" in ref:
        return ref.rsplit("/", 1)[-1]
    return None


def _resolve_openapi_type(schema_obj: Any) -> str:
    if not isinstance(schema_obj, dict):
        return "Any"
    ref_name = _extract_ref_name(schema_obj)
    if ref_name is not None:
        return ref_name
    oa_type = str(schema_obj.get("type", "Any"))
    if oa_type == "array":
        items = schema_obj.get("items")
        inner = _resolve_openapi_type(items)
        return f"list[{inner}]"
    return OPENAPI_TYPE_MAP.get(oa_type, oa_type)


def _extract_openapi_contracts(
    path: Path, rel_path: str
) -> tuple[list[ModelContract], list[RouteContract]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [], []

    spec: dict[str, Any] | None = None
    if path.suffix.lower() == ".json":
        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                spec = loaded
        except json.JSONDecodeError:
            return [], []
    else:
        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                spec = loaded
        except json.JSONDecodeError:
            spec = _parse_simple_yaml(text)

    if not isinstance(spec, dict):
        return [], []

    models: list[ModelContract] = []
    components = spec.get("components")
    if isinstance(components, dict):
        schemas = components.get("schemas")
        if isinstance(schemas, dict):
            for schema_name, schema_obj in schemas.items():
                if not isinstance(schema_obj, dict):
                    continue
                schema_line = _find_key_line(text, str(schema_name))
                required_raw = schema_obj.get("required")
                required_fields = (
                    {str(item) for item in required_raw}
                    if isinstance(required_raw, list)
                    else set()
                )
                fields: list[FieldContract] = []
                props = schema_obj.get("properties")
                if isinstance(props, dict):
                    for prop_name, prop_obj in props.items():
                        prop_key = str(prop_name)
                        fields.append(
                            FieldContract(
                                name=prop_key,
                                type_annotation=_resolve_openapi_type(prop_obj),
                                required=prop_key in required_fields,
                                line=_find_key_line(text, prop_key, schema_line),
                            )
                        )
                models.append(
                    ModelContract(
                        name=str(schema_name),
                        file_path=rel_path,
                        line=schema_line,
                        base_classes=["OpenAPISchema"],
                        fields=fields,
                    )
                )

    routes: list[RouteContract] = []
    paths = spec.get("paths")
    if isinstance(paths, dict):
        for route_path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            path_str = str(route_path)
            path_line = _find_key_line(text, path_str)
            for method_key, operation in path_item.items():
                method_lower = str(method_key).lower()
                if method_lower not in HTTP_METHODS or not isinstance(operation, dict):
                    continue
                op_id = operation.get("operationId")
                function_name = str(op_id) if isinstance(op_id, str) and op_id else method_lower

                request_model: str | None = None
                req_body = operation.get("requestBody")
                if isinstance(req_body, dict):
                    content = req_body.get("content")
                    if isinstance(content, dict):
                        app_json = content.get("application/json")
                        if isinstance(app_json, dict):
                            request_model = _extract_ref_name(app_json.get("schema"))

                response_model: str | None = None
                responses = operation.get("responses")
                if isinstance(responses, dict):
                    for status_code in ("200", "201"):
                        resp_obj = responses.get(status_code)
                        if isinstance(resp_obj, dict):
                            content = resp_obj.get("content")
                            if isinstance(content, dict):
                                app_json = content.get("application/json")
                                if isinstance(app_json, dict):
                                    response_model = _extract_ref_name(app_json.get("schema"))
                                    if response_model is not None:
                                        break

                routes.append(
                    RouteContract(
                        method=method_lower.upper(),
                        path=path_str,
                        function_name=function_name,
                        file_path=rel_path,
                        line=_find_key_line(text, str(method_key), path_line),
                        request_model=request_model,
                        response_model=response_model,
                    )
                )

    return (
        sorted(models, key=lambda m: (m.file_path, m.line)),
        sorted(routes, key=lambda r: (r.file_path, r.line)),
    )


def _strip_sql_comments(chunk: str) -> str:
    lines = [re.sub(r"--.*$", "", line) for line in chunk.splitlines()]
    return " ".join(lines).strip()


def _extract_sql_columns(
    source: str, open_paren: int, close_paren: int
) -> list[FieldContract]:
    body = source[open_paren + 1 : close_paren]
    fields: list[FieldContract] = []
    for raw_chunk, offset in _split_top_level_with_offsets(
        body, open_paren + 1, frozenset({","})
    ):
        cleaned = _strip_sql_comments(raw_chunk)
        if not cleaned:
            continue
        upper = cleaned.upper()
        if upper.startswith(SQL_CONSTRAINT_PREFIXES):
            continue
        col_match = re.match(
            r"^[`\"\[]?([A-Za-z_]\w*)[`\"\]]?\s+([A-Za-z_]\w*(?:\s*\([^)]*\))?)(.*)$",
            cleaned,
        )
        if not col_match:
            continue
        col_name = col_match.group(1)
        raw_type = re.sub(r"\([^)]*\)", "", col_match.group(2)).strip().upper()
        rest = col_match.group(3).upper()
        mapped_type = SQL_TYPE_MAP.get(raw_type, raw_type)
        fields.append(
            FieldContract(
                name=col_name,
                type_annotation=mapped_type,
                required="NOT NULL" in rest,
                line=_line_number_at(source, offset),
            )
        )
    return fields


def _extract_sql_models(source: str, rel_path: str) -> list[ModelContract]:
    models: list[ModelContract] = []
    for match in SQL_CREATE_TABLE_RE.finditer(source):
        table_name = match.group(1)
        open_paren = match.end() - 1
        close_paren = _find_matching_delimiter(source, open_paren, "(", ")")
        if close_paren is None:
            continue
        fields = _extract_sql_columns(source, open_paren, close_paren)
        models.append(
            ModelContract(
                name=table_name,
                file_path=rel_path,
                line=_line_number_at(source, match.start()),
                base_classes=["SQLTable"],
                fields=fields,
            )
        )
    return sorted(models, key=lambda m: (m.file_path, m.line))


def _extract_sql_telemetry(source: str, rel_path: str) -> list[TelemetryContract]:
    events: list[TelemetryContract] = []
    for match in SQL_CREATE_TABLE_RE.finditer(source):
        table_name = match.group(1)
        lower_name = table_name.lower()
        if lower_name.startswith("telemetry_"):
            event_name = table_name[len("telemetry_") :]
        elif lower_name.startswith("events_"):
            event_name = table_name[len("events_") :]
        else:
            continue
        if not event_name:
            continue
        open_paren = match.end() - 1
        close_paren = _find_matching_delimiter(source, open_paren, "(", ")")
        if close_paren is None:
            continue
        columns = _extract_sql_columns(source, open_paren, close_paren)
        events.append(
            TelemetryContract(
                event_name=event_name,
                source_kind="bigquery",
                properties=[col.name for col in columns],
                file_path=rel_path,
                line=_line_number_at(source, match.start()),
            )
        )
    return sorted(events, key=lambda t: (t.file_path, t.line))


def _extract_adr(file_path: Path, rel_path: str) -> ADRContract | None:
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    adr_id = file_path.stem.upper()
    title = file_path.stem
    heading_line = 1
    status = "Unknown"

    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        heading_match = ADR_HEADING_RE.match(line)
        if heading_match:
            adr_id = heading_match.group(1).upper()
            title = heading_match.group(2).strip()
            heading_line = idx
        status_match = ADR_STATUS_RE.match(line)
        if status_match:
            status = status_match.group(1).strip()

    if "000-template" in rel_path.lower():
        return None

    return ADRContract(
        adr_id=adr_id,
        title=title,
        status=status,
        file_path=rel_path,
        line=heading_line,
    )


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
