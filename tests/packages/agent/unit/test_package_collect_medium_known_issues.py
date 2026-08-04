from __future__ import annotations

import re
from pathlib import Path

from earendil_works.pi_agent.package_manager.collect import collect_files


def test_collect_files_matches_symlink_entry_name(tmp_path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "readme.txt").write_text("readme", encoding="utf-8")
    (tmp_path / "README.md").symlink_to(Path("docs/readme.txt"))

    files = collect_files(tmp_path, re.compile(r"README\.md$"), boundary=tmp_path)

    assert files == [str((docs / "readme.txt").resolve())]
