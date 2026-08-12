"""digest.py의 update_homepage() FAIL-LOUD 가드를 검증한다.
.venv/bin/python test_digest_safety.py 로 직접 실행."""
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import digest

KST = timezone(timedelta(hours=9))


def _sample_items():
    return [{
        "title": "Test", "title_ko": "테스트", "link": "https://example.com/a",
        "pubdate_kst": datetime(2026, 8, 12, 9, 0, tzinfo=KST), "tags": ["US"],
    }]


def test_update_homepage_raises_when_marker_missing_and_does_not_write():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        digest.ROOT = root
        (root / "index_template.html").write_text("<html></html>", encoding="utf-8")
        broken = "<html><body>no marker here</body></html>"
        (root / "index.html").write_text(broken, encoding="utf-8")

        raised = False
        try:
            digest.update_homepage("2026-08-12", _sample_items())
        except RuntimeError:
            raised = True

        assert raised, "마커 없을 때 RuntimeError가 발생해야 함"
        assert (root / "index.html").read_text(encoding="utf-8") == broken, \
            "예외 발생 시 파일이 변경되면 안 됨"
    print("test_update_homepage_raises_when_marker_missing_and_does_not_write: OK")


def test_update_homepage_bootstraps_from_template_when_file_absent():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        digest.ROOT = root
        (root / "index_template.html").write_text(
            "<html><body><!-- SECTIONS --></body></html>", encoding="utf-8"
        )
        digest.update_homepage("2026-08-12", _sample_items())
        result = (root / "index.html").read_text(encoding="utf-8")
        assert "<!-- SECTIONS -->" in result
        assert "테스트" in result
        assert not (root / "index.html.tmp").exists()
    print("test_update_homepage_bootstraps_from_template_when_file_absent: OK")


def test_update_homepage_raises_when_template_itself_lacks_marker():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        digest.ROOT = root
        (root / "index_template.html").write_text("<html><body>no marker</body></html>", encoding="utf-8")
        # index.html은 아예 없음 -> 템플릿 부트스트랩 분기를 타야 함
        raised = False
        try:
            digest.update_homepage("2026-08-12", _sample_items())
        except RuntimeError:
            raised = True
        assert raised, "템플릿 자체에 마커가 없어도 RuntimeError가 발생해야 함(조용한 no-op 금지)"
        assert not (root / "index.html").exists(), "예외 발생 시 index.html이 새로 생기면 안 됨"
    print("test_update_homepage_raises_when_template_itself_lacks_marker: OK")


def test_update_homepage_replaces_same_day_section_not_duplicates():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        digest.ROOT = root
        (root / "index_template.html").write_text(
            "<html><body><!-- SECTIONS --></body></html>", encoding="utf-8"
        )
        digest.update_homepage("2026-08-12", _sample_items())
        digest.update_homepage("2026-08-12", _sample_items())
        result = (root / "index.html").read_text(encoding="utf-8")
        assert result.count('<section><h2>2026-08-12</h2>') == 1, \
            "같은 날짜로 재실행하면 섹션이 교체돼야지 중복되면 안 됨"
    print("test_update_homepage_replaces_same_day_section_not_duplicates: OK")


if __name__ == "__main__":
    test_update_homepage_raises_when_marker_missing_and_does_not_write()
    test_update_homepage_bootstraps_from_template_when_file_absent()
    test_update_homepage_raises_when_template_itself_lacks_marker()
    test_update_homepage_replaces_same_day_section_not_duplicates()
    print("ALL TESTS PASSED")
