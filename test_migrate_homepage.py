"""migrate_homepage.py의 migrate() 순수 함수를 작은 fixture HTML로 검증한다.
실제 index.html(266KB)에 대해서는 이 테스트 대신 Step 5에서 실제로 1회 실행하고
git diff로 사람이 확인한다. .venv/bin/python test_migrate_homepage.py 로 실행."""
from migrate_homepage import migrate

FIXTURE = """<!doctype html>
<html lang="ko">
<head><title>t</title></head>
<body>
<div id="topBar">
  <h1>Bloomberg 기사 요약</h1>
  <input type="text" id="searchBox" placeholder="제목 검색...">
  <div id="topTags"></div>
  <div id="filterBar">
    <span id="filterStatus">x</span>
    <button id="resetFilter" type="button">전체 보기</button>
  </div>
</div>
<!-- SECTIONS -->
<section><h2>2026-08-12</h2><ul><li><span class="stamp">08-12 08:00</span><a href="https://x">기사</a></li></ul></section>
<script>
var state = { tag: null, query: '' };
document.querySelectorAll('section').forEach(function (section) {
  section.style.display = '';
});
</script>
</body>
</html>"""


def test_migrate_preserves_existing_section_count_and_content():
    result = migrate(FIXTURE)
    assert result.count("<section>") == FIXTURE.count("<section>")
    assert "2026-08-12" in result and "기사" in result and 'href="https://x"' in result
    print("test_migrate_preserves_existing_section_count_and_content: OK")


def test_migrate_adds_required_markers_exactly_once():
    result = migrate(FIXTURE)
    for required in ("<!-- SECTIONS -->", "<!-- INFOMAX_SECTIONS -->",
                      'id="bloombergPane"', 'id="infomaxPane"', 'id="tabBar"'):
        assert result.count(required) == 1, f"{required}가 정확히 1개여야 함(실제 {result.count(required)}개)"
    print("test_migrate_adds_required_markers_exactly_once: OK")


def test_migrate_narrows_bloomberg_filter_selector():
    result = migrate(FIXTURE)
    assert "querySelectorAll('#bloombergPane section')" in result
    assert "querySelectorAll('section')" not in result.replace(
        "querySelectorAll('#bloombergPane section')", ""
    )
    print("test_migrate_narrows_bloomberg_filter_selector: OK")


def test_migrate_raises_when_sections_marker_absent():
    broken = FIXTURE.replace("<!-- SECTIONS -->", "")
    raised = False
    try:
        migrate(broken)
    except RuntimeError:
        raised = True
    assert raised
    print("test_migrate_raises_when_sections_marker_absent: OK")


def test_migrate_raises_when_already_migrated():
    once = migrate(FIXTURE)
    raised = False
    try:
        migrate(once)
    except RuntimeError:
        raised = True
    assert raised, "이미 마이그레이션된 파일에 재실행하면 중복 삽입 대신 예외를 던져야 함"
    print("test_migrate_raises_when_already_migrated: OK")


if __name__ == "__main__":
    test_migrate_preserves_existing_section_count_and_content()
    test_migrate_adds_required_markers_exactly_once()
    test_migrate_narrows_bloomberg_filter_selector()
    test_migrate_raises_when_sections_marker_absent()
    test_migrate_raises_when_already_migrated()
    print("ALL TESTS PASSED")
