from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harumi.db import (
    get_db_path,
    init_db,
    insert_root,
    list_roots,
    upsert_document,
    upsert_file_record,
    upsert_fts_document,
)
from harumi.search import find_documents


class SearchTests(unittest.TestCase):
    def test_find_documents_filters_rows_ignored_by_root_harumiignore(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            root = base / "workspace"
            root.mkdir()
            (root / ".harumiignore").write_text("vendor/\n", encoding="utf-8")
            keep = root / "notes.txt"
            keep.write_text("aws sso setup notes\n", encoding="utf-8")
            ignored = root / "vendor" / "bundle" / "gem.txt"
            ignored.parent.mkdir(parents=True)
            ignored.write_text("aws sso gem internals\n", encoding="utf-8")

            db_path = get_db_path(base / "app")
            init_db(db_path)
            insert_root(db_path, root)
            root_id = int(list_roots(db_path)[0]["id"])

            for path in (keep, ignored):
                status, file_id = upsert_file_record(
                    db_path,
                    root_id=root_id,
                    path=str(path),
                    parent_path=str(path.parent),
                    filename=path.name,
                    extension=path.suffix,
                    size_bytes=path.stat().st_size,
                    mtime=path.stat().st_mtime,
                )
                self.assertEqual(status, "indexed")
                text = path.read_text(encoding="utf-8")
                upsert_document(
                    db_path,
                    file_id=file_id,
                    normalized_text=text,
                    normalized_format="text",
                )
                upsert_fts_document(
                    db_path,
                    file_id=file_id,
                    path=str(path),
                    filename=path.name,
                    extension=path.suffix,
                    parent_path=str(path.parent),
                    normalized_text=text,
                    summary_short="",
                )

            results = find_documents(db_path, "aws sso", limit=10)

            self.assertEqual([row["path"] for row in results], [str(keep)])


if __name__ == "__main__":
    unittest.main()
