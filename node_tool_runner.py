import shutil
import subprocess
import sys
from pathlib import Path


def node_executable():
    found = shutil.which("node") or shutil.which("node.exe")
    if found:
        return found
    bundled = (Path.home() / ".cache" / "codex-runtimes" /
               "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe")
    if bundled.is_file():
        return str(bundled)
    raise FileNotFoundError("Node.js不可用，无法执行翻后验证器")


def main(argv=None):
    arguments = list(argv if argv is not None else sys.argv[1:])
    if not arguments:
        raise ValueError("缺少Node脚本路径")
    return subprocess.run([node_executable(), *arguments], check=False).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, OSError, ValueError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(2)
