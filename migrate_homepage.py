"""index.html을 tabBar/bloombergPane/infomaxPane 구조로 1회 마이그레이션하는 스크립트.

기존 <!-- SECTIONS --> 마커와 그 안의 모든 <section> 콘텐츠(누적된 실제 기사 데이터)는
절대 건드리지 않고, 앞뒤로 새 wrapper만 '삽입'한다(치환 아님 — 2026-07-29 사고 재발 방지,
solved_problems.md 참조). 단, 예외가 하나 있다: 기존 Bloomberg 필터 스크립트의
`querySelectorAll('section')`을 `querySelectorAll('#bloombergPane section')`으로 바꾸는
5번째 치환은 콘텐츠가 아니라 JS 필터링 동작 자체를 바꾸는 진짜 치환(semantic
substitution)이다 — "삽입만 한다"는 안전성 원칙은 기사 데이터에만 적용되고 이 한 줄에는
적용되지 않는다는 점을 명시해둔다. 실행 전후 <section> 개수와 필수 마커 존재 여부를
스스로 검증하고, 어긋나면 아무것도 쓰지 않고 예외를 던진다. 1회성 도구이므로 이미
마이그레이션된 파일에 다시 실행하면 예외를 던진다(IDEMPOTENT: 중복 실행이 안전하게
거부됨).
"""
from pathlib import Path

from homepage_io import write_atomic

ROOT = Path(__file__).parent
INDEX_PATH = ROOT / "index.html"

TAB_BAR_HTML = (
    '<div id="tabBar">\n'
    '  <button id="tabBloomberg" class="tabBtn active" type="button">Bloomberg</button>\n'
    '  <button id="tabInfomax" class="tabBtn" type="button">연합인포맥스</button>\n'
    '</div>\n'
)

INFOMAX_PANE_HTML = (
    '<div id="infomaxPane" style="display:none">\n'
    '  <div id="infomaxTopBar">\n'
    '    <h1>연합인포맥스 채권/외환</h1>\n'
    '    <input type="text" id="infomaxSearchBox" placeholder="제목 검색...">\n'
    '  </div>\n'
    '  <!-- INFOMAX_SECTIONS -->\n'
    '</div>\n'
)

TAB_SCRIPT = """
var infomaxState = { query: '' };

function switchTab(tab) {
  document.getElementById('bloombergPane').style.display = tab === 'bloomberg' ? '' : 'none';
  document.getElementById('infomaxPane').style.display = tab === 'infomax' ? '' : 'none';
  document.getElementById('tabBloomberg').classList.toggle('active', tab === 'bloomberg');
  document.getElementById('tabInfomax').classList.toggle('active', tab === 'infomax');
  localStorage.setItem('activeTab', tab);
}

document.getElementById('tabBloomberg').addEventListener('click', function () { switchTab('bloomberg'); });
document.getElementById('tabInfomax').addEventListener('click', function () { switchTab('infomax'); });
switchTab(localStorage.getItem('activeTab') || 'bloomberg');

document.getElementById('infomaxSearchBox').addEventListener('input', function (e) {
  infomaxState.query = e.target.value.trim().toLowerCase();
  applyInfomaxFilter();
});

function applyInfomaxFilter() {
  document.querySelectorAll('#infomaxPane section').forEach(function (section) {
    var visibleCount = 0;
    section.querySelectorAll('li').forEach(function (li) {
      var titleText = (li.querySelector('a') || {}).textContent || '';
      var match = infomaxState.query === '' || titleText.toLowerCase().indexOf(infomaxState.query) !== -1;
      li.style.display = match ? '' : 'none';
      if (match) visibleCount++;
    });
    section.style.display = visibleCount > 0 ? '' : 'none';
  });
}
"""


def migrate(html_text: str) -> str:
    if "<!-- SECTIONS -->" not in html_text:
        raise RuntimeError("<!-- SECTIONS --> 마커가 없음 — 파일이 손상되었거나 대상이 아님")
    if 'id="bloombergPane"' in html_text:
        raise RuntimeError("이미 마이그레이션된 것으로 보임(bloombergPane 존재) — 중복 실행 방지")

    section_count_before = html_text.count("<section>")

    body_anchor = '<body>\n<div id="topBar">'
    if html_text.count(body_anchor) != 1:
        raise RuntimeError(
            f"<body> 직후 앵커를 정확히 1곳에서 못 찾음(발견 {html_text.count(body_anchor)}곳)"
        )
    html_text = html_text.replace(
        body_anchor,
        f'<body>\n{TAB_BAR_HTML}\n<div id="bloombergPane">\n<div id="topBar">',
        1,
    )

    script_anchor = "</section>\n<script>"
    if html_text.count(script_anchor) != 1:
        raise RuntimeError(
            f"</section> 다음 <script> 앵커를 정확히 1곳에서 못 찾음"
            f"(발견 {html_text.count(script_anchor)}곳)"
        )
    html_text = html_text.replace(
        script_anchor,
        f"</section>\n</div>\n\n{INFOMAX_PANE_HTML}\n<script>",
        1,
    )

    old_selector = "document.querySelectorAll('section').forEach(function (section) {"
    new_selector = "document.querySelectorAll('#bloombergPane section').forEach(function (section) {"
    if html_text.count(old_selector) != 1:
        raise RuntimeError(
            "Bloomberg 필터의 querySelectorAll('section') 앵커를 정확히 1곳에서 못 찾음"
        )
    html_text = html_text.replace(old_selector, new_selector, 1)

    if html_text.count("</script>\n</body>") != 1:
        raise RuntimeError("</script></body> 앵커를 정확히 1곳에서 못 찾음")
    html_text = html_text.replace(
        "</script>\n</body>", TAB_SCRIPT + "</script>\n</body>", 1
    )

    section_count_after = html_text.count("<section>")
    if section_count_after != section_count_before:
        raise RuntimeError(
            f"마이그레이션 후 <section> 개수가 달라짐"
            f"({section_count_before} -> {section_count_after}) — 콘텐츠 손상 의심, 파일을 쓰지 않음"
        )
    for required in ("<!-- SECTIONS -->", "<!-- INFOMAX_SECTIONS -->",
                      'id="bloombergPane"', 'id="infomaxPane"', 'id="tabBar"'):
        if html_text.count(required) != 1:
            raise RuntimeError(f"마이그레이션 후 '{required}'가 정확히 1개가 아님(검증 실패)")

    return html_text


def main() -> None:
    original = INDEX_PATH.read_text(encoding="utf-8")
    migrated = migrate(original)
    write_atomic(INDEX_PATH, migrated)
    print("[migrate_homepage] 완료 — index.html 마이그레이션됨")


if __name__ == "__main__":
    main()
