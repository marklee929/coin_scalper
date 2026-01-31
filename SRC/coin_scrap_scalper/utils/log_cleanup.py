import argparse
import os
import shutil
import time
from glob import glob
from typing import List


def _collect_files(logs_dir: str, patterns: List[str]) -> List[str]:
    files = []
    for pat in patterns:
        files.extend(glob(os.path.join(logs_dir, "**", pat), recursive=True))
    return [f for f in files if os.path.isfile(f)]


def _older_than(path: str, days: int) -> bool:
    if days <= 0:
        return True
    cutoff = time.time() - (days * 86400)
    return os.path.getmtime(path) < cutoff


def _human_size(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024.0:
            return f"{num:.1f}{unit}"
        num /= 1024.0
    return f"{num:.1f}TB"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs-dir", default="logs", help="log directory")
    parser.add_argument("--archive-dir", default="storage/archive/logs", help="archive directory")
    parser.add_argument("--days", type=int, default=0, help="only files older than N days (0=all)")
    parser.add_argument("--patterns", default="*.json,*.log", help="comma-separated patterns")
    parser.add_argument("--delete", action="store_true", help="delete instead of archive")
    parser.add_argument("--apply", action="store_true", help="apply changes (default: dry-run)")
    args = parser.parse_args()

    logs_dir = os.path.abspath(args.logs_dir)
    archive_dir = os.path.abspath(args.archive_dir)
    patterns = [p.strip() for p in args.patterns.split(",") if p.strip()]

    files = [f for f in _collect_files(logs_dir, patterns) if _older_than(f, args.days)]
    total_size = sum(os.path.getsize(f) for f in files)

    print(f"Found {len(files)} files, total { _human_size(total_size) }")
    if not files:
        return

    if not args.apply:
        print("Dry-run only. Use --apply to execute.")
        return

    if args.delete:
        for path in files:
            try:
                os.remove(path)
            except Exception as e:
                print(f"Failed to delete {path}: {e}")
        print("Delete complete.")
        return

    for path in files:
        rel = os.path.relpath(path, logs_dir)
        dst = os.path.join(archive_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            shutil.move(path, dst)
        except Exception as e:
            print(f"Failed to move {path}: {e}")
    print(f"Archive complete -> {archive_dir}")


if __name__ == "__main__":
    main()
