"""Safe online backup of the SQLite database (assist.db), with pruning.

Uses SQLite's own backup API, so it is consistent even while the server is
writing, and it needs no `sqlite3` command-line program on the server.

    PYTHONPATH=. python3 -m phase8.tools.backup_db \
        --src /var/lib/wakuflow/assist.db --dest /var/backups/wakuflow --keep 14

Exit code 0 = a verified backup file now exists; non-zero = it did not work.
Copy the backup folder off the server from time to time: a backup on the same
disk does not protect you from losing the whole server.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PREFIX, SUFFIX = "assist-", ".db"


class BackupError(Exception):
    pass


def backup(src: str | Path, dest_dir: str | Path, keep: int = 14, now: datetime | None = None) -> Path:
    src, dest_dir = Path(src), Path(dest_dir)
    if keep < 1:
        raise BackupError("--keep must be at least 1")
    if not src.is_file():
        # Never create an empty database by accident and call it a backup.
        raise BackupError("database not found: %s" % src)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    final = dest_dir / ("%s%s%s" % (PREFIX, stamp, SUFFIX))
    tmp = dest_dir / (final.name + ".partial")
    try:
        source = sqlite3.connect("file:%s?mode=ro" % src.resolve(), uri=True, timeout=30)
        target = sqlite3.connect(str(tmp))
        try:
            source.backup(target)
            result = target.execute("PRAGMA integrity_check").fetchone()
        finally:
            target.close()
            source.close()
        if not result or result[0] != "ok":
            raise BackupError("backup failed its integrity check: %r" % (result,))
        tmp.replace(final)
    except sqlite3.Error as exc:
        raise BackupError("sqlite error: %s" % exc) from exc
    finally:
        if tmp.exists():
            tmp.unlink()
    _prune(dest_dir, keep)
    return final


def _prune(dest_dir: Path, keep: int) -> list[Path]:
    files = sorted(p for p in dest_dir.glob("%s*%s" % (PREFIX, SUFFIX)) if p.is_file())
    old = files[:-keep] if len(files) > keep else []
    for p in old:
        p.unlink()
    return old


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default="data/assist.db", help="database file (default: data/assist.db)")
    ap.add_argument("--dest", required=True, help="folder for backup files")
    ap.add_argument("--keep", type=int, default=14, help="how many backups to keep (default 14)")
    args = ap.parse_args(argv)
    try:
        out = backup(args.src, args.dest, args.keep)
    except BackupError as exc:
        print("BACKUP FAILED: %s" % exc, file=sys.stderr)
        return 1
    print("backup ok: %s (%d bytes)" % (out, out.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
