#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ソースから指定シンボルだけを取り出す（フルモジュール import を避ける）。"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, Iterable, Set


def load_module_functions(source_path: Path, names: Iterable[str]) -> Dict[str, Any]:
    """トップレベル関数のみを AST 抽出して exec する。"""
    wanted = set(names)
    src = source_path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    keep: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
            keep.append(node)
    found = {n.name for n in keep if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    missing = wanted - found
    if missing:
        raise LookupError(f"{source_path}: functions not found: {sorted(missing)}")
    module = ast.Module(body=keep, type_ignores=[])
    ast.fix_missing_locations(module)
    typing = __import__("typing")
    ns: Dict[str, Any] = {
        "__name__": "_isolated",
        "re": __import__("re"),
        "Optional": typing.Optional,
        "Dict": typing.Dict,
        "Any": typing.Any,
        "List": typing.List,
        "Tuple": typing.Tuple,
    }
    exec(compile(module, str(source_path), "exec"), ns)  # noqa: S102
    return {n: ns[n] for n in wanted}


def load_class_subset(source_path: Path, class_name: str, method_names: Iterable[str]) -> type:
    """クラス定義から指定メソッドだけを残して exec し、クラスオブジェクトを返す。"""
    wanted: Set[str] = set(method_names)
    src = source_path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    class_node = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            class_node = node
            break
    if class_node is None:
        raise LookupError(f"{source_path}: class {class_name} not found")

    new_body: list[ast.stmt] = []
    found: Set[str] = set()
    for node in class_node.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
            new_body.append(node)
            found.add(node.name)
    missing = wanted - found
    if missing:
        raise LookupError(f"{source_path}: methods not found on {class_name}: {sorted(missing)}")

    subset = ast.ClassDef(
        name=class_node.name,
        bases=[],
        keywords=[],
        body=new_body,
        decorator_list=[],
        type_params=getattr(class_node, "type_params", []),
    )
    module = ast.Module(body=[subset], type_ignores=[])
    ast.fix_missing_locations(module)
    ns: Dict[str, Any] = {
        "__name__": "_isolated",
        "Optional": __import__("typing").Optional,
        "Dict": __import__("typing").Dict,
        "Any": __import__("typing").Any,
        "List": __import__("typing").List,
    }
    exec(compile(module, str(source_path), "exec"), ns)  # noqa: S102
    return ns[class_name]
