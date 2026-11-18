"""Offline syntax, file-boundary and conservative credential-pattern checks."""
import ast
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
FORBIDDEN_SUFFIXES = {".mp4", ".mov", ".png", ".jpg", ".onnx", ".joblib", ".pkl", ".exe", ".dll", ".jsonl"}
SECRET = re.compile(r"sk-[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}")


def main():
    files = [p for p in ROOT.rglob("*") if p.is_file() and not (set(p.relative_to(ROOT).parts) & EXCLUDED_PARTS)]
    failures = []
    python_count = js_count = 0
    for path in sorted(files):
        relative = path.relative_to(ROOT).as_posix()
        allowed_reference = relative == "docs/images/training-workspace-reference.png"
        if (path.suffix in FORBIDDEN_SUFFIXES and not allowed_reference) or path.name == ".env":
            failures.append({"file": relative, "reason": "unexpected private/binary artifact"})
        if path.suffix not in {".py", ".js", ".html", ".css", ".json", ".md", ".txt", ".yml"}:
            continue
        source = path.read_text(encoding="utf-8-sig")
        if SECRET.search(source):
            failures.append({"file": relative, "reason": "credential pattern; value omitted"})
        if path.suffix == ".py":
            python_count += 1
            try:
                ast.parse(source)
            except SyntaxError as error:
                failures.append({"file": relative, "reason": f"syntax error at line {error.lineno}"})
        if path.suffix == ".js":
            js_count += 1
            result = subprocess.run(["node", "--check", str(path)], capture_output=True, timeout=30)
            if result.returncode:
                failures.append({"file": relative, "reason": "JavaScript syntax error"})
    # Resolve the same runtime code graph from the copied snapshot.
    missing = []
    import sys
    for path in files:
        if path.suffix != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            modules = ([n.name for n in node.names] if isinstance(node, ast.Import)
                       else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for module in modules:
                top = module.split(".")[0]
                if top in sys.stdlib_module_names or top in {"PIL", "cv2", "joblib", "numpy", "rapidocr_onnxruntime", "webview"}:
                    continue
                target = ROOT.joinpath(*module.split("."))
                if not target.with_suffix(".py").is_file() and not (target / "__init__.py").is_file():
                    missing.append({"file": path.relative_to(ROOT).as_posix(), "module": module})
    report = {"pythonSyntaxFiles": python_count, "javascriptSyntaxFiles": js_count,
              "filesChecked": len(files), "failures": failures, "unresolvedLocalImports": missing,
              "scope": "Static checks only; no desktop, OCR, solver or clean-environment acceptance."}
    (ROOT / "docs" / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"python": python_count, "javascript": js_count, "failures": len(failures), "unresolvedImports": len(missing)}))
    return int(bool(failures or missing))


if __name__ == "__main__":
    raise SystemExit(main())
