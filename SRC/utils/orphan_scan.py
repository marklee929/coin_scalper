import argparse
import ast
import os
from typing import Dict, Set, List


def _module_name(root: str, path: str) -> str:
    rel = os.path.relpath(path, root)
    rel = rel.replace(os.sep, ".")
    if rel.endswith(".py"):
        rel = rel[:-3]
    return rel


def _build_module_map(root: str) -> Dict[str, str]:
    module_map = {}
    for dirpath, dirnames, filenames in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            full = os.path.join(dirpath, fname)
            module = _module_name(root, full)
            module_map[module] = full
    return module_map


def _parse_imports(path: str, current_module: str) -> Set[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
    except Exception:
        return set()

    imports: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level and current_module:
                parts = current_module.split(".")
                if node.level <= len(parts):
                    base = ".".join(parts[:-node.level])
                    mod = f"{base}.{mod}" if base and mod else (base or mod)
            if mod:
                imports.add(mod)
            # from X import Y -> also consider X.Y
            for alias in node.names:
                if mod:
                    imports.add(f"{mod}.{alias.name}")
    return imports


def find_orphans(root: str, entry: str) -> List[str]:
    module_map = _build_module_map(root)
    entry_module = _module_name(root, entry)

    visited: Set[str] = set()
    queue: List[str] = [entry_module]

    while queue:
        module = queue.pop()
        if module in visited:
            continue
        visited.add(module)
        path = module_map.get(module)
        if not path:
            continue
        imports = _parse_imports(path, module)
        for imp in imports:
            if imp in module_map and imp not in visited:
                queue.append(imp)
            # allow importing package __init__
            if imp + ".__init__" in module_map and (imp + ".__init__") not in visited:
                queue.append(imp + ".__init__")

    orphans = [m for m in module_map.keys() if m not in visited]
    return sorted(orphans)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="project root (SRC)")
    parser.add_argument("--entry", default="main.py", help="entrypoint file")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    entry = args.entry
    if not os.path.isabs(entry):
        entry = os.path.join(root, entry)

    orphans = find_orphans(root, entry)
    print("Orphan candidates:")
    for m in orphans:
        print(m)


if __name__ == "__main__":
    main()
