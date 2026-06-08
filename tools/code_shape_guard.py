from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_PATHS = ("src/silentfrog", "tools")
BASELINE_PATH = Path("tools/code_shape_baseline.json")
MAX_FUNCTION_LINES = 80
MAX_NESTING_DEPTH = 4
MAX_BRANCHES = 12
MAX_BOOL_ARGS = 2
MAX_ELIFS = 2


@dataclass(frozen=True, slots=True)
class FunctionShape:
    path: str
    qualname: str
    line: int
    length: int
    max_depth: int
    branches: int
    bool_args: int
    elif_count: int

    @property
    def key(self) -> str:
        return f"{self.path}:{self.qualname}"


@dataclass(frozen=True, slots=True)
class ShapeViolation:
    key: str
    metric: str
    actual: int
    limit: int
    path: str
    qualname: str
    line: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class _FunctionAnalyzer(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self._path = path
        self._stack: list[str] = []
        self.functions: list[FunctionShape] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._stack.append(node.name)
        self.functions.append(
            FunctionShape(
                path=self._path.as_posix(),
                qualname=".".join(self._stack),
                line=node.lineno,
                length=_function_length(node),
                max_depth=_max_nesting_depth(node),
                branches=_branch_count(node),
                bool_args=_bool_arg_count(node),
                elif_count=_elif_count(node),
            )
        )
        self.generic_visit(node)
        self._stack.pop()


def _function_length(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    end_line = max(getattr(child, "lineno", node.lineno) for child in ast.walk(node))
    return end_line - node.lineno + 1


def _bool_arg_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    args = [*node.args.args, *node.args.kwonlyargs]
    count = 0
    for arg in args:
        annotation = arg.annotation
        if isinstance(annotation, ast.Name) and annotation.id == "bool":
            count += 1
    return count


def _branch_count(node: ast.AST) -> int:
    branch_nodes = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match)
    return sum(isinstance(child, branch_nodes) for child in ast.walk(node))


def _elif_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    return sum(_if_chain_elifs(child) for child in ast.walk(node) if isinstance(child, ast.If))


def _if_chain_elifs(node: ast.If) -> int:
    count = 0
    current = node
    while len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
        count += 1
        current = current.orelse[0]
    return count


def _max_nesting_depth(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    depth_nodes = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match, ast.With, ast.AsyncWith)

    def visit(current: ast.AST, depth: int) -> int:
        next_depth = depth + 1 if isinstance(current, depth_nodes) else depth
        child_depths = [visit(child, next_depth) for child in ast.iter_child_nodes(current)]
        return max([next_depth, *child_depths], default=next_depth)

    return max(0, visit(node, -1))


def collect_functions(paths: Iterable[Path]) -> list[FunctionShape]:
    functions: list[FunctionShape] = []
    for root in paths:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            analyzer = _FunctionAnalyzer(path)
            analyzer.visit(tree)
            functions.extend(analyzer.functions)
    return functions


def collect_violations(functions: Iterable[FunctionShape]) -> list[ShapeViolation]:
    violations: list[ShapeViolation] = []
    for item in functions:
        metrics = (
            ("length", item.length, MAX_FUNCTION_LINES),
            ("depth", item.max_depth, MAX_NESTING_DEPTH),
            ("branches", item.branches, MAX_BRANCHES),
            ("bool_args", item.bool_args, MAX_BOOL_ARGS),
            ("elifs", item.elif_count, MAX_ELIFS),
        )
        for metric, actual, limit in metrics:
            if actual <= limit:
                continue
            violations.append(
                ShapeViolation(
                    key=item.key,
                    metric=metric,
                    actual=actual,
                    limit=limit,
                    path=item.path,
                    qualname=item.qualname,
                    line=item.line,
                )
            )
    return violations


def load_baseline(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(item["id"]) for item in data.get("allowed", [])}


def write_baseline(path: Path, violations: Iterable[ShapeViolation]) -> None:
    unique = sorted({f"{item.key}|{item.metric}" for item in violations})
    payload = {"allowed": [{"id": item} for item in unique]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def unexpected_violations(violations: Iterable[ShapeViolation], baseline_ids: set[str]) -> list[ShapeViolation]:
    return [item for item in violations if f"{item.key}|{item.metric}" not in baseline_ids]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guard against hard-to-maintain Python code shapes.")
    parser.add_argument("paths", nargs="*", default=list(DEFAULT_PATHS), help="Directories to scan.")
    parser.add_argument("--baseline", default=str(BASELINE_PATH), help="JSON file of grandfathered violations.")
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Rewrite the baseline with the current violations instead of failing.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    scan_paths = [Path(path) for path in args.paths]
    baseline_path = Path(args.baseline)
    violations = collect_violations(collect_functions(scan_paths))
    if args.update_baseline:
        write_baseline(baseline_path, violations)
        print(f"[code-shape] Baseline updated: {baseline_path}")
        return 0

    baseline_ids = load_baseline(baseline_path)
    failures = unexpected_violations(violations, baseline_ids)
    if not failures:
        print("[code-shape] OK")
        return 0

    print("[code-shape] New code-shape violations found:", file=sys.stderr)
    for item in failures:
        print(
            f" - {item.path}:{item.line} {item.qualname} -> {item.metric} {item.actual} > {item.limit}",
            file=sys.stderr,
        )
    print(
        "[code-shape] Refactor the function or, for intentional legacy exceptions, update the baseline explicitly.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
