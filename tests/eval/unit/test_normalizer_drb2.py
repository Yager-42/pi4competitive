"""DRB II normalizer: report -> UTF-8 .md (D1 C2-wide, 只做编码/文件名规范化)."""

from __future__ import annotations

from pathlib import Path

from eval.normalizer.drb2 import build_report_path, normalize_report


def test_normalize_report_writes_md(tmp_path: Path):
    out = tmp_path / "reports" / "competitorlens_a2_drb2_22_0.md"
    normalize_report(
        report_md="# Title\n\nbody with 中文",
        instance_id="drb2_22",
        model_config_name="competitorlens_a2",
        trial_idx=0,
        out_path=out,
    )
    assert out.read_text(encoding="utf-8") == "# Title\n\nbody with 中文"


def test_normalize_report_empty_is_written(tmp_path: Path):
    out = tmp_path / "reports" / "competitorlens_a1_drb2_4_0.md"
    normalize_report(
        report_md="", instance_id="drb2_4",
        model_config_name="competitorlens_a1", trial_idx=0, out_path=out,
    )
    assert out.read_text(encoding="utf-8") == ""


def test_build_report_path_round_trips():
    p = build_report_path(
        reports_root="x/normalized", model_config_name="competitorlens_a2",
        instance_id="drb2_22", trial_idx=0,
    )
    assert p == Path("x/normalized") / "competitorlens_a2_drb2_22_0.md"
