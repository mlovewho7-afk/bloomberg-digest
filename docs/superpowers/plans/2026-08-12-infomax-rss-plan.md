# 연합인포맥스 RSS 연동 + 홈페이지 탭 재구성 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 연합인포맥스 채권/외환 RSS를 두 번째 뉴스 소스로 추가하고, 홈페이지(`index.html`)를
Bloomberg/연합인포맥스 탭으로 전환 가능한 구조로 재구성한다.

**Architecture:** 신규 독립 스크립트 `infomax.py`가 RSS를 파싱해 날짜별로 누적 저장하고
`index.html`의 별도 pane에 렌더링한다. 기존 `digest.py`는 최소한의 안전장치(마커 소실 시
FAIL-LOUD 예외, 원자적 쓰기, 파일 락)만 보강한다. 두 스크립트가 공유하는 락/원자적쓰기
유틸은 새 모듈 `homepage_io.py`로 뽑아낸다. 실 서비스 중인 `index.html`(266KB, 누적
데이터 포함)의 구조 변경은 전용 검증 스크립트(`migrate_homepage.py`)로 1회만 수행한다.

**Tech Stack:** Python 3(표준 라이브러리 `xml.etree.ElementTree`, `fcntl`, `os`, `json`),
`requests`(이미 설치됨). 새 패키지 설치 없음. 테스트는 이 프로젝트에 기존 테스트
프레임워크가 없으므로(pytest 미설치, 기존 `digest.py`도 무테스트) `assert` 기반의 독립
실행 스크립트로 작성한다(`.venv/bin/python test_xxx.py`로 직접 실행, `pytest` 도입하지
않음 — 기존 관례 준수).

## Global Constraints

- RSS는 `https://news.einfomax.co.kr/rss/S1N16.xml`(채권/외환) 하나만 사용한다.
- 인포맥스에는 태그 필터링을 적용하지 않는다 — 제목 검색만.
- 실행은 완전 수동이다. 자동 스케줄 코드를 추가하지 않는다.
- 새 의존성을 추가하지 않는다(`requests`, 표준 라이브러리만).
- id 네이밍은 기존 코드베이스 관례(camelCase: `topBar`, `searchBox` 등)를 따른다 —
  kebab-case를 섞지 않는다.
- `index.html`에서 마커(`<!-- SECTIONS -->`, `<!-- INFOMAX_SECTIONS -->`)를 찾지 못하면
  절대 템플릿으로 조용히 대체하지 않는다 — 예외를 던지고 아무것도 쓰지 않는다.
- `index.html`에 대한 모든 쓰기는 임시 파일 + `os.replace()`로 원자적으로 수행한다.
- `index.html`을 읽고-수정하고-쓰고-`git commit/push`하는 구간 전체는
  `homepage_io.homepage_lock()`으로 감싼다. git 관련 `subprocess.run` 호출에는
  `timeout=60`을 둔다.
- 커밋 메시지: 블룸버그는 `"update: {date} Bloomberg 기사"`(기존 유지), 인포맥스는
  `"update: {date} 인포맥스 기사"`.
- 인포맥스 섹션의 HTML은 `<section class="infomaxSection"><h2>{date}</h2>...`로 렌더링해
  블룸버그의 무클래스 `<section><h2>{date}</h2>`와 마커 문자열이 겹치지 않게 한다.

---

### Task 1: `homepage_io.py` — 공용 파일 락 + 원자적 쓰기

**Files:**
- Create: `homepage_io.py`
- Test: `test_homepage_io.py`

**Interfaces:**
- Consumes: 없음(최하위 유틸 모듈)
- Produces:
  - `homepage_lock() -> contextmanager` — `with homepage_io.homepage_lock():` 형태로 사용,
    `index.html` 갱신 구간 전체를 감싸는 블로킹 파일 락(`fcntl.flock`, `.git/.homepage.lock`
    대상). 이후 Task 2, Task 7에서 사용.
  - `write_atomic(path: Path, content: str) -> None` — 임시 파일에 쓴 뒤 `os.replace()`로
    교체하는 원자적 쓰기. 이후 Task 2, 6, 9에서 사용.

- [ ] **Step 1: 실패하는 테스트 작성**

`/Users/sunggeunmoon/bloomberg-digest/test_homepage_io.py`:

```python
"""homepage_io.py의 write_atomic/homepage_lock을 검증한다.
pytest 없이 assert 기반으로 직접 실행: .venv/bin/python test_homepage_io.py"""
import tempfile
import threading
import time
from pathlib import Path

from homepage_io import homepage_lock, write_atomic


def test_write_atomic_creates_file_and_leaves_no_tmp():
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "index.html"
        write_atomic(target, "<html>hello</html>")
        assert target.read_text(encoding="utf-8") == "<html>hello</html>"
        assert not (Path(d) / "index.html.tmp").exists()
    print("test_write_atomic_creates_file_and_leaves_no_tmp: OK")


def test_write_atomic_overwrites_existing_file():
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "index.html"
        target.write_text("old", encoding="utf-8")
        write_atomic(target, "new")
        assert target.read_text(encoding="utf-8") == "new"
    print("test_write_atomic_overwrites_existing_file: OK")


def test_homepage_lock_serializes_concurrent_critical_sections():
    order = []

    def worker(name):
        with homepage_lock():
            order.append(f"{name}-start")
            time.sleep(0.1)
            order.append(f"{name}-end")

    t1 = threading.Thread(target=worker, args=("A",))
    t2 = threading.Thread(target=worker, args=("B",))
    t1.start()
    time.sleep(0.02)
    t2.start()
    t1.join()
    t2.join()

    assert order in (
        ["A-start", "A-end", "B-start", "B-end"],
        ["B-start", "B-end", "A-start", "A-end"],
    ), f"두 임계구역이 겹쳤음(직렬화 실패): {order}"
    print("test_homepage_lock_serializes_concurrent_critical_sections: OK")


if __name__ == "__main__":
    test_write_atomic_creates_file_and_leaves_no_tmp()
    test_write_atomic_overwrites_existing_file()
    test_homepage_lock_serializes_concurrent_critical_sections()
    print("ALL TESTS PASSED")
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python test_homepage_io.py`
Expected: `ModuleNotFoundError: No module named 'homepage_io'`

- [ ] **Step 3: 최소 구현 작성**

`/Users/sunggeunmoon/bloomberg-digest/homepage_io.py`:

```python
"""index.html에 대한 동시 접근·부분 쓰기를 막는 공용 유틸.

digest.py와 infomax.py가 각자 따로 index.html을 읽고-수정하고-쓰고-커밋하므로, 두
스크립트가 근접 실행되면 무음으로 서로의 변경분을 덮어쓸 수 있다(2026-08-12 spec review
critical 발견). homepage_lock()으로 갱신 구간 전체를 직렬화하고, write_atomic()으로
쓰기 도중 프로세스가 죽어도 파일이 잘린 채 남지 않게 한다.
"""
import fcntl
import os
from contextlib import contextmanager
from pathlib import Path

LOCK_PATH = Path(__file__).parent / ".git" / ".homepage.lock"


@contextmanager
def homepage_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def write_atomic(path: Path, content: str) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python test_homepage_io.py`
Expected: `ALL TESTS PASSED`

- [ ] **Step 5: 커밋**

이 태스크가 이 plan의 첫 커밋이다. `git status`로 미리 확인했을 때 이 작업과 무관한
untracked/수정 파일이 있다면(예: 이번 spec/plan 문서 자체가 아직 커밋 전이라면) 함께
커밋하지 말고 먼저 그 변경들의 성격을 파악해 별도로 커밋하거나 스태시한다 — Task 9(실
파일 마이그레이션)에서 "git status가 clean해야 한다"는 전제가 깨지지 않도록, 이 작업과
무관한 변경을 나중까지 미루지 않는다.

```bash
cd /Users/sunggeunmoon/bloomberg-digest
git add homepage_io.py test_homepage_io.py \
  docs/superpowers/specs/2026-08-12-infomax-rss-design.md \
  docs/superpowers/plans/2026-08-12-infomax-rss-plan.md
git commit -m "docs: 인포맥스 RSS 연동 spec/plan 추가; add: 파일 락 + 원자적 쓰기 유틸"
```

---

### Task 2: `digest.py` 안전장치 보강 — FAIL-LOUD 마커 가드 + 원자적 쓰기 + 락

**Files:**
- Modify: `digest.py:14-23`(import), `digest.py:234-258`(`update_homepage`),
  `digest.py:261-271`(`push_homepage`), `digest.py:325-326`(`main` 안의 호출부)
- Test: `test_digest_safety.py`

**Interfaces:**
- Consumes: Task 1의 `homepage_io.homepage_lock`, `homepage_io.write_atomic`
- Produces: `digest.update_homepage()`가 마커 못 찾으면 `RuntimeError`를 던짐(다른 태스크
  없음, digest.py는 이 plan의 다른 태스크가 의존하지 않는 종료 지점).

- [ ] **Step 1: 실패하는 테스트 작성**

`/Users/sunggeunmoon/bloomberg-digest/test_digest_safety.py`:

```python
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
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python test_digest_safety.py`
Expected: `AssertionError` (현재 코드는 마커 없으면 조용히 template으로 대체하므로
`raised`가 `False`) — 네 번째 테스트는 기존 로직으로도 통과할 수 있음(그건 정상, 회귀
방지용으로 같이 둔다).

- [ ] **Step 3: `digest.py` 수정**

`digest.py:14-23`의 import 블록 끝에 추가(23번째 줄 `from playwright.sync_api import
sync_playwright` 다음 줄):

```python
from homepage_io import homepage_lock, write_atomic
```

`digest.py:234-258`의 `update_homepage()` 전체를 다음으로 교체:

```python
def update_homepage(date_label: str, items: list[dict]) -> None:
    index_path = ROOT / "index.html"
    new_section = render_day_section_html(date_label, items)
    marker = "<!-- SECTIONS -->"

    if index_path.exists():
        html = index_path.read_text(encoding="utf-8")
        source_desc = "index.html"
    else:
        html = (ROOT / "index_template.html").read_text(encoding="utf-8")
        source_desc = "index_template.html"

    # 파일이 있든 없든(템플릿 부트스트랩이든) 마커 확인은 동일하게 적용한다 — 이전
    # 버전은 이 체크를 "파일이 이미 존재하는" 분기에만 걸어서, 템플릿 자체에 마커가
    # 없는 경우 template.replace()가 조용히 no-op으로 실패하는 구멍이 있었다
    # (2026-08-12 plan review에서 critical로 지적됨).
    existing_start = html.find(marker)
    if existing_start == -1:
        raise RuntimeError(
            f"{source_desc}에서 <!-- SECTIONS --> 마커를 찾을 수 없음 — 파일이 손상되었을 "
            "수 있으니 수동으로 확인할 것(템플릿으로 자동 대체하지 않음)"
        )

    # 같은 날짜 섹션이 이미 있으면 통째로 교체(재실행 시 중복 방지), 없으면 맨 위에 추가
    day_marker = f'<section><h2>{date_label}</h2>'
    if day_marker in html:
        start = html.find(day_marker)
        end = html.find("</section>", start) + len("</section>")
        html = html[:start] + new_section + html[end:]
    else:
        insert_at = existing_start + len(marker)
        html = html[:insert_at] + "\n" + new_section + html[insert_at:]

    write_atomic(index_path, html)
```

`digest.py:261-271`의 `push_homepage()` 전체를 다음으로 교체:

```python
def push_homepage(date_label: str) -> None:
    def run(cmd):
        subprocess.run(cmd, cwd=ROOT, check=True, timeout=60)

    run(["git", "add", "index.html"])
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT, timeout=60)
    if result.returncode == 0:
        print("[digest] 홈페이지 변경 없음 — 커밋 생략")
        return
    run(["git", "commit", "-m", f"update: {date_label} Bloomberg 기사"])
    run(["git", "push"])
```

`digest.py:325-326`(`main()` 안의 호출부, 원래:
```python
    update_homepage(date_label, all_items)
    push_homepage(date_label)
```
)을 다음으로 교체:

```python
    with homepage_lock():
        update_homepage(date_label, all_items)
        push_homepage(date_label)
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python test_digest_safety.py`
Expected: `ALL TESTS PASSED`

- [ ] **Step 5: 커밋**

```bash
cd /Users/sunggeunmoon/bloomberg-digest
git add digest.py test_digest_safety.py
git commit -m "fix: digest.py 마커 소실 시 조용한 템플릿 대체를 FAIL-LOUD 예외로 교체 + 원자적 쓰기/락 적용"
```

---

### Task 3: `infomax.py` — RSS 수집(fetch/parse)

**Files:**
- Create: `infomax.py`(이 태스크에서는 fetch/parse 부분만 작성, 이후 태스크에서 계속 추가)
- Test: `test_infomax.py`(이후 태스크에서 계속 추가)

**Interfaces:**
- Consumes: 없음
- Produces:
  - `KST` (timezone, UTC+9), `ROOT` (Path), `RSS_URL` (str) — 이후 태스크에서 사용.
  - `parse_rss_xml(xml_bytes: bytes) -> list[dict]` — 각 dict는
    `{"title": str, "link": str, "pubdate_kst": datetime}`. title은 이미 HTML
    언이스케이프 완료. Task 4, 5에서 사용.
  - `fetch_rss(url: str) -> list[dict]` — 네트워크 호출 후 `parse_rss_xml` 위임. Task 7의
    `main()`에서 사용.
  - `stale_pubdate_warning(items: list[dict], now_kst: datetime) -> str | None` — pubDate가
    KST가 아닐 수 있다는 의심이 들면(최신 항목과 현재 시각 차이 2시간 초과) 경고 문자열
    반환, 아니면 `None`. Task 7의 `main()`에서 사용.

- [ ] **Step 1: 실패하는 테스트 작성**

`/Users/sunggeunmoon/bloomberg-digest/test_infomax.py`:

```python
"""infomax.py를 검증한다. .venv/bin/python test_infomax.py 로 직접 실행."""
from datetime import datetime, timedelta, timezone

from infomax import KST, fetch_rss, parse_rss_xml, stale_pubdate_warning

SAMPLE_XML = """<?xml version="1.0" encoding="utf-8" ?>
<rss version="2.0"><channel>
<title>연합인포맥스 - 채권/외환</title>
<item>
<nsid>AKR1</nsid>
<title>짐 비앙코 &amp;quot;연준이 패닉해야&amp;quot;</title>
<link>https://news.einfomax.co.kr/news/articleView.html?idxno=1</link>
<description><![CDATA[본문]]></description>
<author><![CDATA[김성진 기자]]></author>
<pubDate>2026-08-12 05:42:32</pubDate>
</item>
<item>
<nsid>AKR2</nsid>
<title>미국 3년물 국채 입찰</title>
<link>https://news.einfomax.co.kr/news/articleView.html?idxno=2</link>
<description><![CDATA[본문2]]></description>
<author><![CDATA[김성진 기자]]></author>
<pubDate>2026-08-12 04:21:35</pubDate>
</item>
</channel></rss>""".encode("utf-8")


def test_parse_rss_xml_unescapes_double_encoded_entities():
    items = parse_rss_xml(SAMPLE_XML)
    assert len(items) == 2
    assert items[0]["title"] == '짐 비앙코 "연준이 패닉해야"', items[0]["title"]
    assert items[0]["link"] == "https://news.einfomax.co.kr/news/articleView.html?idxno=1"
    assert items[0]["pubdate_kst"] == datetime(2026, 8, 12, 5, 42, 32, tzinfo=KST)
    assert items[1]["title"] == "미국 3년물 국채 입찰"
    print("test_parse_rss_xml_unescapes_double_encoded_entities: OK")


def test_parse_rss_xml_empty_channel_returns_empty_list():
    empty = b'<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
    assert parse_rss_xml(empty) == []
    print("test_parse_rss_xml_empty_channel_returns_empty_list: OK")


def test_stale_pubdate_warning_none_when_recent():
    now = datetime(2026, 8, 12, 8, 0, tzinfo=KST)
    items = [{"pubdate_kst": datetime(2026, 8, 12, 7, 30, tzinfo=KST)}]
    assert stale_pubdate_warning(items, now) is None
    print("test_stale_pubdate_warning_none_when_recent: OK")


def test_stale_pubdate_warning_set_when_drift_over_2h():
    now = datetime(2026, 8, 12, 8, 0, tzinfo=KST)
    items = [{"pubdate_kst": datetime(2026, 8, 11, 20, 0, tzinfo=KST)}]  # 12시간 차이
    warning = stale_pubdate_warning(items, now)
    assert warning is not None and "경고" in warning
    print("test_stale_pubdate_warning_set_when_drift_over_2h: OK")


def test_stale_pubdate_warning_none_when_empty():
    now = datetime(2026, 8, 12, 8, 0, tzinfo=KST)
    assert stale_pubdate_warning([], now) is None
    print("test_stale_pubdate_warning_none_when_empty: OK")


if __name__ == "__main__":
    test_parse_rss_xml_unescapes_double_encoded_entities()
    test_parse_rss_xml_empty_channel_returns_empty_list()
    test_stale_pubdate_warning_none_when_recent()
    test_stale_pubdate_warning_set_when_drift_over_2h()
    test_stale_pubdate_warning_none_when_empty()
    print("ALL TESTS PASSED (Task 3)")
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python test_infomax.py`
Expected: `ModuleNotFoundError: No module named 'infomax'`

- [ ] **Step 3: 최소 구현 작성**

`/Users/sunggeunmoon/bloomberg-digest/infomax.py`:

```python
"""연합인포맥스 채권/외환 RSS(https://news.einfomax.co.kr/rss/S1N16.xml)를 수집해
날짜별로 누적하고 홈페이지(index.html)의 인포맥스 탭에 반영한다.

블룸버그(digest.py)와 달리 이미 한글이라 번역이 필요 없고, 정적 XML이라 Playwright나
캡차 대응이 필요 없다. 이 차이 때문에 별도 스크립트로 분리했다.

자동 스케줄 없음 — 사용자가 "인포맥스 업데이트해줘"라고 할 때만 수동 실행한다.
"""
import html
import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from homepage_io import homepage_lock, write_atomic

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent
RSS_URL = "https://news.einfomax.co.kr/rss/S1N16.xml"
STORE_PATH = ROOT / "data" / "infomax_items.json"
PUBDATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_rss_xml(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    for item_el in root.findall("./channel/item"):
        title_el = item_el.find("title")
        link_el = item_el.find("link")
        pubdate_el = item_el.find("pubDate")
        if title_el is None or link_el is None or pubdate_el is None:
            continue
        # ElementTree가 파싱 시 1차 언이스케이프(&amp;quot;->&quot;)를 하므로,
        # html.unescape()로 한 번 더 풀어야 &quot; 같은 리터럴이 안 남는다.
        title = html.unescape((title_el.text or "").strip())
        link = (link_el.text or "").strip()
        pubdate_kst = datetime.strptime(
            (pubdate_el.text or "").strip(), PUBDATE_FORMAT
        ).replace(tzinfo=KST)
        items.append({"title": title, "link": link, "pubdate_kst": pubdate_kst})
    return items


def fetch_rss(url: str) -> list[dict]:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return parse_rss_xml(resp.content)


def stale_pubdate_warning(items: list[dict], now_kst: datetime) -> str | None:
    """pubDate가 실제로 KST인지는 검증되지 않은 가정이다(spec review에서 지적됨).
    매 실행마다(최초 실행에 한정하지 않음) 최신 항목과 현재 시각의 차이가 2시간을 넘으면
    그 가정이 깨졌을 수 있다고 경고한다 — 매번 확인해도 비용이 거의 없고, 인포맥스 쪽
    RSS 형식이 나중에 바뀌는 경우까지 계속 감시할 수 있다."""
    if not items:
        return None
    newest = max(item["pubdate_kst"] for item in items)
    drift_hours = (now_kst - newest).total_seconds() / 3600
    if abs(drift_hours) > 2:
        return (
            f"경고: 최신 기사 시각({newest})이 현재 시각({now_kst})과 "
            f"{drift_hours:.1f}시간 차이남 — pubDate가 KST가 아닐 수 있음"
        )
    return None
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python test_infomax.py`
Expected: `ALL TESTS PASSED (Task 3)`

- [ ] **Step 5: 커밋**

```bash
cd /Users/sunggeunmoon/bloomberg-digest
git add infomax.py test_infomax.py
git commit -m "add: infomax.py RSS 수집·파싱(fetch_rss/parse_rss_xml)"
```

---

### Task 4: `infomax.py` — 날짜별 누적 저장소

**Files:**
- Modify: `infomax.py`(Task 3에서 만든 파일에 이어서 추가)
- Modify: `test_infomax.py`(이어서 추가)

**Interfaces:**
- Consumes: 없음(순수 함수, dict/list만 다룸)
- Produces:
  - `load_store() -> dict` — `data/infomax_items.json` 로드, 없으면 `{}`.
  - `save_store(store: dict) -> None`
  - `merge_items(store: dict, items: list[dict]) -> dict[str, int]` — items를 각자의
    `pubdate_kst` 날짜로 버킷팅해 store에 링크 기준 병합. 반환값은
    `{날짜라벨: 신규건수}`(신규가 없는 날짜는 키에 없음). Task 7의 `main()`에서 사용.

- [ ] **Step 1: 실패하는 테스트 작성**

`test_infomax.py`에 다음 함수들을 추가(파일 상단 import에 `import tempfile`과 `from
pathlib import Path` 추가, `from infomax import ...`에 `load_store, save_store,
merge_items` 추가):

```python
def test_load_store_returns_empty_dict_when_file_absent():
    with tempfile.TemporaryDirectory() as d:
        import infomax
        infomax.STORE_PATH = Path(d) / "infomax_items.json"
        assert load_store() == {}
    print("test_load_store_returns_empty_dict_when_file_absent: OK")


def test_save_and_load_store_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        import infomax
        infomax.STORE_PATH = Path(d) / "infomax_items.json"
        save_store({"2026-08-12": {"https://a": {"title": "a"}}})
        assert load_store() == {"2026-08-12": {"https://a": {"title": "a"}}}
    print("test_save_and_load_store_roundtrip: OK")


def test_merge_items_dedups_by_link_and_skips_unchanged():
    store = {}
    item = {"title": "a", "link": "https://a", "pubdate_kst": datetime(2026, 8, 12, 9, 0, tzinfo=KST)}
    added_first = merge_items(store, [item])
    added_second = merge_items(store, [item])
    assert added_first == {"2026-08-12": 1}
    assert added_second == {}, "이미 있는 링크는 다시 추가되면 안 됨"
    assert store["2026-08-12"]["https://a"]["title"] == "a"
    print("test_merge_items_dedups_by_link_and_skips_unchanged: OK")


def test_merge_items_buckets_by_own_pubdate_not_fixed_window():
    store = {}
    items = [
        {"title": "a", "link": "https://a", "pubdate_kst": datetime(2026, 8, 12, 9, 0, tzinfo=KST)},
        {"title": "b", "link": "https://b", "pubdate_kst": datetime(2026, 8, 11, 23, 0, tzinfo=KST)},
    ]
    added = merge_items(store, items)
    assert added == {"2026-08-12": 1, "2026-08-11": 1}
    assert "https://a" in store["2026-08-12"]
    assert "https://b" in store["2026-08-11"]
    print("test_merge_items_buckets_by_own_pubdate_not_fixed_window: OK")
```

`__main__` 블록의 실행 목록에도 이 4개를 추가.

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python test_infomax.py`
Expected: `ImportError: cannot import name 'load_store' from 'infomax'`

- [ ] **Step 3: 구현 추가**

`infomax.py` 끝에 추가:

```python
def load_store() -> dict:
    if STORE_PATH.exists():
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    return {}


def save_store(store: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_items(store: dict, items: list[dict]) -> dict[str, int]:
    """items를 각자의 pubdate_kst 날짜로 버킷팅해 store에 링크 기준으로 병합한다.
    digest.py의 day_store 병합과 동일한 원칙(기존 항목 보존, 링크 기준 dedup)이되,
    RSS에는 고정 시간창이 없으므로 각 item 자신의 날짜로 버킷을 나눈다."""
    added_by_date: dict[str, int] = {}
    for item in items:
        date_label = item["pubdate_kst"].date().isoformat()
        day_store = store.setdefault(date_label, {})
        if item["link"] not in day_store:
            day_store[item["link"]] = {**item, "pubdate_kst": item["pubdate_kst"].isoformat()}
            added_by_date[date_label] = added_by_date.get(date_label, 0) + 1
    return added_by_date
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python test_infomax.py`
Expected: `ALL TESTS PASSED (Task 3)` 뒤에 4개 테스트 OK 라인 추가 확인(마지막
`print`문을 "ALL TESTS PASSED (Task 4)"로 갱신했다면 그 문구 확인)

- [ ] **Step 5: 커밋**

```bash
cd /Users/sunggeunmoon/bloomberg-digest
git add infomax.py test_infomax.py
git commit -m "add: infomax.py 날짜별 누적 저장소(load_store/save_store/merge_items)"
```

---

### Task 5: `infomax.py` — 날짜 섹션 HTML 렌더링

**Files:**
- Modify: `infomax.py`
- Modify: `test_infomax.py`

**Interfaces:**
- Consumes: Task 4의 `merge_items`가 만드는 item 형태(단, 렌더링 시점엔 `pubdate_kst`가
  다시 `datetime`으로 변환된 상태여야 함 — Task 7의 `main()`에서 변환 후 전달)
- Produces: `render_infomax_day_section_html(date_label: str, items: list[dict]) -> str` —
  Task 6의 `update_infomax_pane()`에서 사용.

- [ ] **Step 1: 실패하는 테스트 작성**

`test_infomax.py`에 추가(import에 `render_infomax_day_section_html` 추가):

```python
def test_render_infomax_day_section_html_newest_first():
    items = [
        {"title": "오래된 기사", "link": "https://a", "pubdate_kst": datetime(2026, 8, 12, 7, 0, tzinfo=KST)},
        {"title": "최신 기사", "link": "https://b", "pubdate_kst": datetime(2026, 8, 12, 9, 0, tzinfo=KST)},
    ]
    html_out = render_infomax_day_section_html("2026-08-12", items)
    assert html_out.startswith('<section class="infomaxSection"><h2>2026-08-12</h2><ul>')
    assert html_out.index("최신 기사") < html_out.index("오래된 기사"), "최신이 위에 와야 함"
    assert 'href="https://b"' in html_out
    assert html_out.endswith("</ul></section>")
    print("test_render_infomax_day_section_html_newest_first: OK")


def test_render_infomax_day_section_html_empty_items():
    html_out = render_infomax_day_section_html("2026-08-12", [])
    assert html_out == '<section class="infomaxSection"><h2>2026-08-12</h2><ul></ul></section>'
    print("test_render_infomax_day_section_html_empty_items: OK")
```

`__main__` 블록에 두 함수 호출 추가.

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python test_infomax.py`
Expected: `ImportError: cannot import name 'render_infomax_day_section_html'`

- [ ] **Step 3: 구현 추가**

`infomax.py` 끝에 추가:

```python
def render_infomax_day_section_html(date_label: str, items: list[dict]) -> str:
    rows = []
    for it in reversed(items):  # 최신 기사가 맨 위(블룸버그와 동일 관례)
        stamp = it["pubdate_kst"].strftime("%m-%d %H:%M")
        rows.append(
            f'<li><span class="stamp">{stamp}</span>'
            f'<a href="{it["link"]}" target="_blank" rel="noopener">{it["title"]}</a></li>'
        )
    return f'<section class="infomaxSection"><h2>{date_label}</h2><ul>' + "\n".join(rows) + "</ul></section>"
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python test_infomax.py`
Expected: 모든 테스트 OK, 마지막 `ALL TESTS PASSED (Task 5)`

- [ ] **Step 5: 커밋**

```bash
cd /Users/sunggeunmoon/bloomberg-digest
git add infomax.py test_infomax.py
git commit -m "add: infomax.py 날짜 섹션 HTML 렌더링(render_infomax_day_section_html)"
```

---

### Task 6: `infomax.py` — `update_infomax_pane()` (마커 기반 삽입/교체, FAIL-LOUD)

**Files:**
- Modify: `infomax.py`
- Modify: `test_infomax.py`

**Interfaces:**
- Consumes: Task 1의 `write_atomic`, Task 5의 `render_infomax_day_section_html`
- Produces: `update_infomax_pane(date_label: str, items: list[dict]) -> None` — Task 7의
  `main()`에서 사용. `index.html`에 `<!-- INFOMAX_SECTIONS -->` 마커가 없으면
  `RuntimeError`.

- [ ] **Step 1: 실패하는 테스트 작성**

`test_infomax.py`에 추가(import에 `update_infomax_pane` 추가):

```python
def _one_item(title="a", link="https://a", hour=9):
    return [{"title": title, "link": link, "pubdate_kst": datetime(2026, 8, 12, hour, 0, tzinfo=KST)}]


def test_update_infomax_pane_bootstraps_from_template_when_file_absent():
    with tempfile.TemporaryDirectory() as d:
        import infomax
        infomax.ROOT = Path(d)
        (Path(d) / "index_template.html").write_text(
            "<html><body><!-- INFOMAX_SECTIONS --></body></html>", encoding="utf-8"
        )
        update_infomax_pane("2026-08-12", _one_item())
        result = (Path(d) / "index.html").read_text(encoding="utf-8")
        assert "<!-- INFOMAX_SECTIONS -->" in result
        assert "infomaxSection" in result
    print("test_update_infomax_pane_bootstraps_from_template_when_file_absent: OK")


def test_update_infomax_pane_inserts_new_date_above_existing():
    with tempfile.TemporaryDirectory() as d:
        import infomax
        infomax.ROOT = Path(d)
        (Path(d) / "index_template.html").write_text(
            "<html><body><!-- INFOMAX_SECTIONS --></body></html>", encoding="utf-8"
        )
        update_infomax_pane("2026-08-11", _one_item(link="https://old"))
        update_infomax_pane("2026-08-12", _one_item(link="https://new"))
        result = (Path(d) / "index.html").read_text(encoding="utf-8")
        assert result.index("2026-08-12") < result.index("2026-08-11"), "새 날짜가 위에 와야 함"
        assert "https://old" in result, "과거 날짜 섹션이 사라지면 안 됨"
    print("test_update_infomax_pane_inserts_new_date_above_existing: OK")


def test_update_infomax_pane_replaces_same_day_not_duplicates():
    with tempfile.TemporaryDirectory() as d:
        import infomax
        infomax.ROOT = Path(d)
        (Path(d) / "index_template.html").write_text(
            "<html><body><!-- INFOMAX_SECTIONS --></body></html>", encoding="utf-8"
        )
        update_infomax_pane("2026-08-12", _one_item(link="https://first"))
        update_infomax_pane("2026-08-12", _one_item(link="https://second"))
        result = (Path(d) / "index.html").read_text(encoding="utf-8")
        assert result.count('<section class="infomaxSection"><h2>2026-08-12</h2>') == 1
        assert "https://first" not in result, "재실행 시 이전 내용이 아니라 최신 내용으로 교체돼야 함"
        assert "https://second" in result
    print("test_update_infomax_pane_replaces_same_day_not_duplicates: OK")


def test_update_infomax_pane_raises_when_marker_missing_and_does_not_write():
    with tempfile.TemporaryDirectory() as d:
        import infomax
        infomax.ROOT = Path(d)
        (Path(d) / "index_template.html").write_text("<html></html>", encoding="utf-8")
        broken = "<html><body>no marker</body></html>"
        (Path(d) / "index.html").write_text(broken, encoding="utf-8")

        raised = False
        try:
            update_infomax_pane("2026-08-12", _one_item())
        except RuntimeError:
            raised = True

        assert raised
        assert (Path(d) / "index.html").read_text(encoding="utf-8") == broken
    print("test_update_infomax_pane_raises_when_marker_missing_and_does_not_write: OK")


def test_update_infomax_pane_raises_when_template_itself_lacks_marker():
    with tempfile.TemporaryDirectory() as d:
        import infomax
        infomax.ROOT = Path(d)
        (Path(d) / "index_template.html").write_text("<html><body>no marker</body></html>", encoding="utf-8")
        # index.html은 아예 없음 -> 템플릿 부트스트랩 분기를 타야 함

        raised = False
        try:
            update_infomax_pane("2026-08-12", _one_item())
        except RuntimeError:
            raised = True

        assert raised, "템플릿 자체에 마커가 없어도 RuntimeError가 발생해야 함(잘못된 위치 삽입 금지)"
        assert not (Path(d) / "index.html").exists(), "예외 발생 시 index.html이 새로 생기면 안 됨"
    print("test_update_infomax_pane_raises_when_template_itself_lacks_marker: OK")
```

`__main__` 블록에 5개 함수 호출 추가.

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python test_infomax.py`
Expected: `ImportError: cannot import name 'update_infomax_pane'`

- [ ] **Step 3: 구현 추가**

`infomax.py` 끝에 추가:

```python
def update_infomax_pane(date_label: str, items: list[dict]) -> None:
    index_path = ROOT / "index.html"
    new_section = render_infomax_day_section_html(date_label, items)
    marker = "<!-- INFOMAX_SECTIONS -->"

    if index_path.exists():
        html_text = index_path.read_text(encoding="utf-8")
        source_desc = "index.html"
    else:
        html_text = (ROOT / "index_template.html").read_text(encoding="utf-8")
        source_desc = "index_template.html"

    # 파일이 있든 없든(템플릿 부트스트랩이든) 마커 확인은 동일하게 적용한다 — 이전
    # 버전은 이 체크를 "파일이 이미 존재하는" 분기에만 걸어서, 템플릿 자체에 마커가
    # 없으면 existing_start=-1인 채로 insert_at 계산에 그대로 쓰여 파일 임의
    # 위치(바이트 오프셋 음수+len(marker))에 조용히 잘못 삽입되는 실제 버그가 있었다
    # (2026-08-12 plan review에서 critical로 지적됨).
    existing_start = html_text.find(marker)
    if existing_start == -1:
        raise RuntimeError(
            f"{source_desc}에서 <!-- INFOMAX_SECTIONS --> 마커를 찾을 수 없음 — 파일이 "
            "손상됐거나 마이그레이션이 안 된 상태일 수 있으니 수동으로 확인할 것"
        )

    day_marker = f'<section class="infomaxSection"><h2>{date_label}</h2>'
    if day_marker in html_text:
        start = html_text.find(day_marker)
        end = html_text.find("</section>", start) + len("</section>")
        html_text = html_text[:start] + new_section + html_text[end:]
    else:
        insert_at = existing_start + len(marker)
        html_text = html_text[:insert_at] + "\n" + new_section + html_text[insert_at:]

    write_atomic(index_path, html_text)
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python test_infomax.py`
Expected: 모든 테스트 OK, `ALL TESTS PASSED (Task 6)`

- [ ] **Step 5: 커밋**

```bash
cd /Users/sunggeunmoon/bloomberg-digest
git add infomax.py test_infomax.py
git commit -m "add: infomax.py update_infomax_pane (마커 삽입/교체, FAIL-LOUD 가드)"
```

---

### Task 7: `infomax.py` — `push_homepage()` + `main()` 조립

**Files:**
- Modify: `infomax.py`

**Interfaces:**
- Consumes: Task 1(`homepage_lock`), Task 3(`fetch_rss`, `stale_pubdate_warning`, `RSS_URL`,
  `KST`), Task 4(`load_store`, `save_store`, `merge_items`), Task 6(`update_infomax_pane`)
- Produces: `main()` — CLI 진입점. 이 태스크 이후로는 다른 태스크가 의존하지 않는다
  (파이프라인의 끝).

이 태스크는 git/네트워크 부작용이 있는 glue 코드라 프로젝트의 기존 관례(digest.py의
`push_homepage`/`main`도 무테스트, 실제 실행으로만 검증)를 따라 자동 테스트를 새로
만들지 않는다 — 실제 검증은 Task 10(End-to-End)에서 진행한다.

- [ ] **Step 1: 구현 추가**

`infomax.py` 끝에 추가:

```python
def push_homepage(date_label: str) -> None:
    def run(cmd):
        subprocess.run(cmd, cwd=ROOT, check=True, timeout=60)

    run(["git", "add", "index.html"])
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT, timeout=60)
    if result.returncode == 0:
        print("[infomax] 홈페이지 변경 없음 — 커밋 생략")
        return
    run(["git", "commit", "-m", f"update: {date_label} 인포맥스 기사"])
    run(["git", "push"])


def main() -> None:
    now_kst = datetime.now(KST)
    print(f"[infomax] RSS 수집 시작: {RSS_URL}")
    items = fetch_rss(RSS_URL)
    oldest = min((i["pubdate_kst"] for i in items), default=None)
    print(f"[infomax] RSS {len(items)}건 수신, 가장 과거 pubDate: {oldest}")

    warning = stale_pubdate_warning(items, now_kst)
    if warning:
        print(f"[infomax] {warning}")

    store = load_store()
    added_by_date = merge_items(store, items)
    total_added = sum(added_by_date.values())
    print(f"[infomax] 신규 {total_added}건 추가 ({added_by_date})")

    if not added_by_date:
        print("[infomax] 신규 항목 없음 — 종료")
        return

    save_store(store)

    with homepage_lock():
        for date_label in added_by_date:
            day_items = [
                {**v, "pubdate_kst": datetime.fromisoformat(v["pubdate_kst"])}
                for v in store[date_label].values()
            ]
            day_items.sort(key=lambda x: x["pubdate_kst"])
            update_infomax_pane(date_label, day_items)
        push_homepage(now_kst.date().isoformat())
    print("[infomax] 완료")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 문법 확인(임포트만 되는지)**

Run: `cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python -c "import infomax"`
Expected: 에러 없이 종료(아직 index.html에 INFOMAX_SECTIONS 마커가 없어 실제 `main()` 실행은
Task 9 마이그레이션 이후에 한다 — 이 스텝은 import 시점 문법/순환참조 오류만 잡는다)

- [ ] **Step 3: 커밋**

```bash
cd /Users/sunggeunmoon/bloomberg-digest
git add infomax.py
git commit -m "add: infomax.py push_homepage + main() 조립"
```

---

### Task 8: `index_template.html` — 탭 구조로 전면 개정

**Files:**
- Modify: `index_template.html`(전체 교체)

**Interfaces:**
- Consumes: 없음(정적 HTML)
- Produces: `index_template.html`이 이후 `index.html`이 완전히 사라지는 극단적 상황의
  폴백으로도, Task 6의 `update_infomax_pane()`이 "파일 없을 때" 경로에서 참조하는
  파일로도 쓰인다. `id="bloombergPane"`, `id="infomaxPane"`,
  `<!-- INFOMAX_SECTIONS -->` 마커가 반드시 있어야 함(Task 9의 실제 마이그레이션 결과와
  동일한 구조).

- [ ] **Step 1: 파일 전체 교체**

`/Users/sunggeunmoon/bloomberg-digest/index_template.html`을 다음 내용으로 전체 교체:

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bloomberg / 연합인포맥스 기사 요약</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    background: #0b0e14;
    color: #e6e6e6;
    font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif;
    max-width: 760px;
    margin: 0 auto;
    padding: 24px 16px 60px;
  }
  h1 { font-size: 1.3rem; border-bottom: 1px solid #2a2f3a; padding-bottom: 12px; }
  h2 { font-size: 1rem; color: #8ab4f8; margin-top: 32px; }
  ul { list-style: none; padding: 0; margin: 8px 0 0; }
  li {
    padding: 10px 0;
    border-bottom: 1px solid #1c212b;
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 8px;
  }
  .stamp { color: #6b7280; font-size: 0.8rem; font-variant-numeric: tabular-nums; }
  .tag {
    background: #1c2536;
    color: #8ab4f8;
    font-size: 0.7rem;
    padding: 2px 6px;
    border-radius: 4px;
    cursor: pointer;
  }
  .tag:hover { background: #2a3550; }
  .tag.active { background: #8ab4f8; color: #0b0e14; }
  a { color: #e6e6e6; text-decoration: none; flex: 1 1 auto; }
  a:hover { text-decoration: underline; color: #8ab4f8; }

  #tabBar {
    display: flex;
    gap: 8px;
    padding-top: 4px;
    margin-bottom: 12px;
  }
  .tabBtn {
    background: #12161f;
    border: 1px solid #2a2f3a;
    color: #8ab4f8;
    font-size: 0.9rem;
    padding: 8px 16px;
    border-radius: 6px;
    cursor: pointer;
    font-family: inherit;
  }
  .tabBtn.active { background: #8ab4f8; color: #0b0e14; border-color: #8ab4f8; }

  #topBar, #infomaxTopBar {
    position: sticky;
    top: 0;
    background: #0b0e14;
    padding-top: 14px;
    margin-bottom: 4px;
    z-index: 10;
  }
  #searchBox, #infomaxSearchBox {
    width: 100%;
    background: #12161f;
    border: 1px solid #2a2f3a;
    color: #e6e6e6;
    font-size: 0.9rem;
    padding: 8px 12px;
    border-radius: 6px;
    font-family: inherit;
  }
  #searchBox:focus, #infomaxSearchBox:focus { outline: none; border-color: #8ab4f8; }
  #topTags {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 10px;
  }
  #filterBar {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 10px;
    font-size: 0.85rem;
    color: #6b7280;
    min-height: 1.2em;
  }
  #resetFilter {
    display: none;
    background: none;
    border: 1px solid #2a2f3a;
    color: #8ab4f8;
    font-size: 0.8rem;
    padding: 3px 10px;
    border-radius: 4px;
    cursor: pointer;
    font-family: inherit;
  }
  #resetFilter:hover { border-color: #8ab4f8; }
</style>
</head>
<body>
<div id="tabBar">
  <button id="tabBloomberg" class="tabBtn active" type="button">Bloomberg</button>
  <button id="tabInfomax" class="tabBtn" type="button">연합인포맥스</button>
</div>

<div id="bloombergPane">
<div id="topBar">
  <h1>Bloomberg 기사 요약</h1>
  <input type="text" id="searchBox" placeholder="제목 검색...">
  <div id="topTags"></div>
  <div id="filterBar">
    <span id="filterStatus">태그를 클릭하거나 검색하면 걸러 볼 수 있습니다.</span>
    <button id="resetFilter" type="button">전체 보기</button>
  </div>
</div>
<!-- SECTIONS -->
</div>

<div id="infomaxPane" style="display:none">
  <div id="infomaxTopBar">
    <h1>연합인포맥스 채권/외환</h1>
    <input type="text" id="infomaxSearchBox" placeholder="제목 검색...">
  </div>
  <!-- INFOMAX_SECTIONS -->
</div>

<script>
var state = { tag: null, query: '' };

document.addEventListener('DOMContentLoaded', function () {
  var tagOrder = ['US', 'Macro', 'Fed', 'Bonds', 'Stocks', 'Oil', 'MiddleEast', 'Gold',
                   'Japan', 'China', 'Korea', 'Opinion'];
  var tagNames = new Set();
  document.querySelectorAll('li .tag').forEach(function (t) { tagNames.add(t.textContent); });
  var sortedTags = Array.from(tagNames).sort(function (a, b) {
    var ia = tagOrder.indexOf(a), ib = tagOrder.indexOf(b);
    if (ia === -1 && ib === -1) return a.localeCompare(b);
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });
  var topTags = document.getElementById('topTags');
  sortedTags.forEach(function (name) {
    var btn = document.createElement('button');
    btn.className = 'tag topTagBtn';
    btn.textContent = name;
    topTags.appendChild(btn);
  });
});

document.addEventListener('click', function (e) {
  var tag = e.target.closest('.tag');
  if (tag) {
    state.tag = (state.tag === tag.textContent) ? null : tag.textContent;
    applyFilters();
    return;
  }
  if (e.target.closest('#resetFilter')) {
    state.tag = null;
    state.query = '';
    document.getElementById('searchBox').value = '';
    applyFilters();
  }
});

document.getElementById('searchBox').addEventListener('input', function (e) {
  state.query = e.target.value.trim().toLowerCase();
  applyFilters();
});

function applyFilters() {
  document.querySelectorAll('.tag').forEach(function (t) {
    t.classList.toggle('active', state.tag !== null && t.textContent === state.tag);
  });

  document.querySelectorAll('#bloombergPane section').forEach(function (section) {
    var visibleCount = 0;
    section.querySelectorAll('li').forEach(function (li) {
      var tags = Array.from(li.querySelectorAll('.tag')).map(function (t) { return t.textContent; });
      var tagMatch = state.tag === null || tags.indexOf(state.tag) !== -1;
      var titleText = (li.querySelector('a') || {}).textContent || '';
      var queryMatch = state.query === '' || titleText.toLowerCase().indexOf(state.query) !== -1;
      var match = tagMatch && queryMatch;
      li.style.display = match ? '' : 'none';
      if (match) visibleCount++;
    });
    section.style.display = visibleCount > 0 ? '' : 'none';
  });

  var active = state.tag !== null || state.query !== '';
  var parts = [];
  if (state.tag !== null) parts.push('태그 "' + state.tag + '"');
  if (state.query !== '') parts.push('검색어 "' + state.query + '"');
  document.getElementById('filterStatus').textContent = active
    ? parts.join(' + ') + '로 걸러보는 중'
    : '태그를 클릭하거나 검색하면 걸러 볼 수 있습니다.';
  document.getElementById('resetFilter').style.display = active ? 'inline-block' : 'none';
}

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
</script>
</body>
</html>
```

- [ ] **Step 2: 빈 데이터 상태로 브라우저에서 열어 확인**

Run: `open /Users/sunggeunmoon/bloomberg-digest/index_template.html`
Expected: 탭 2개("Bloomberg"/"연합인포맥스")가 보이고, 각 탭 클릭 시 전환되며, 새로고침해도
마지막 탭이 유지됨(둘 다 빈 목록이라도 레이아웃 확인 목적). 콘솔에 JS 에러 없음.

- [ ] **Step 3: 커밋**

```bash
cd /Users/sunggeunmoon/bloomberg-digest
git add index_template.html
git commit -m "restructure: index_template.html에 Bloomberg/연합인포맥스 탭 구조 추가"
```

---

### Task 9: 실 서비스 `index.html` 1회 마이그레이션 (최고 위험 태스크)

**Files:**
- Create: `migrate_homepage.py`
- Test: `test_migrate_homepage.py`
- Modify: `index.html`(스크립트 실행으로 변경, 손으로 편집하지 않음)

**Interfaces:**
- Consumes: Task 1의 `write_atomic`
- Produces: 마이그레이션된 `index.html`(Task 6의 `update_infomax_pane()`이 요구하는
  `<!-- INFOMAX_SECTIONS -->` 마커, `id="bloombergPane"`, `id="infomaxPane"`를 갖춤).
  `migrate()` 함수 자체는 순수 함수로, 이 태스크 밖에서는 재사용되지 않는다(1회성 도구).

- [ ] **Step 1: 실패하는 테스트 작성(작은 fixture로 앵커 삽입 로직 검증)**

`/Users/sunggeunmoon/bloomberg-digest/test_migrate_homepage.py`:

```python
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
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python test_migrate_homepage.py`
Expected: `ModuleNotFoundError: No module named 'migrate_homepage'`

- [ ] **Step 3: 구현 작성**

`/Users/sunggeunmoon/bloomberg-digest/migrate_homepage.py`:

```python
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
```

- [ ] **Step 4: 테스트 실행해 통과 확인 (fixture 기준)**

Run: `cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python test_migrate_homepage.py`
Expected: `ALL TESTS PASSED`

- [ ] **Step 5: 체크포인트 확인 후 실제 `index.html`에 1회 실행**

```bash
cd /Users/sunggeunmoon/bloomberg-digest
git status   # clean이어야 함(아니라면 먼저 커밋)
.venv/bin/python migrate_homepage.py
```

Expected: `[migrate_homepage] 완료 — index.html 마이그레이션됨` (마커/개수 검증 실패 시
`RuntimeError`가 뜨고 파일이 바뀌지 않음 — 이 경우 앵커 문자열이 실제 파일과 다른 것이니
`grep -c` 등으로 실제 텍스트를 재확인 후 `migrate_homepage.py`의 앵커 상수를 수정한다).

- [ ] **Step 6: 마이그레이션 결과를 diff로 검증(삭제 없이 삽입만 있었는지)**

```bash
git diff --stat index.html
git diff index.html | grep '^-' | grep -v '^---'
```

Expected: 두 번째 명령 출력이 **비어있어야 함**(삭제 라인이 하나도 없어야 함 — 있다면
기존 콘텐츠가 손상된 것이므로 `git checkout -- index.html`로 되돌리고 원인을 조사한다).

- [ ] **Step 6b: `index.html`과 `index_template.html`의 구조 마커가 동일한지 대조**

```bash
cd /Users/sunggeunmoon/bloomberg-digest
for id in tabBar bloombergPane infomaxPane; do
  echo "$id: index.html=$(grep -c "id=\"$id\"" index.html) template=$(grep -c "id=\"$id\"" index_template.html)"
done
for marker in "<!-- SECTIONS -->" "<!-- INFOMAX_SECTIONS -->"; do
  echo "$marker: index.html=$(grep -Fc -- "$marker" index.html) template=$(grep -Fc -- "$marker" index_template.html)"
done
```

Expected: 모든 줄에서 `index.html=1 template=1` — 두 파일이 같은 wrapper 구조를 가짐을
확인(spec 검증 계획 1번).

- [ ] **Step 7: 커밋**

```bash
cd /Users/sunggeunmoon/bloomberg-digest
git add migrate_homepage.py test_migrate_homepage.py index.html
git commit -m "restructure: index.html에 Bloomberg/연합인포맥스 탭 구조 1회 마이그레이션"
```

---

### Task 10: End-to-End 검증

**Files:** 없음(코드 변경 없음, 실행 검증만)

**Interfaces:** 없음(최종 태스크)

- [ ] **Step 1: FAIL-LOUD 가드 회귀 확인 (fixture 단위 테스트)**

Run: `cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python test_digest_safety.py &&
.venv/bin/python test_infomax.py && .venv/bin/python test_homepage_io.py &&
.venv/bin/python test_migrate_homepage.py`
Expected: 네 스크립트 모두 `ALL TESTS PASSED` 출력.

- [ ] **Step 1b: FAIL-LOUD 가드를 실제 규모(266KB) 파일 사본으로 재확인**

Step 1의 테스트는 모두 작은 합성 fixture로 검증한다. spec 검증 계획 6번은 "실제 운영
파일이 아닌 사본"으로 실물 규모에서도 확인하라고 명시했으므로, Task 9 마이그레이션이
끝난 실제 `index.html`의 사본을 만들어 마커를 지우고 확인한다:

```bash
cd /Users/sunggeunmoon/bloomberg-digest
.venv/bin/python -c "
import tempfile, shutil
from pathlib import Path
import digest

with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    real = Path('index.html').read_text(encoding='utf-8')
    broken = real.replace('<!-- SECTIONS -->', '')  # 마커만 제거, 나머지 실제 데이터는 그대로
    (root / 'index.html').write_text(broken, encoding='utf-8')
    (root / 'index_template.html').write_text(Path('index_template.html').read_text(encoding='utf-8'), encoding='utf-8')
    digest.ROOT = root
    try:
        digest.update_homepage('2026-08-12', [])
        print('FAIL: 예외가 발생하지 않음')
    except RuntimeError as e:
        print(f'OK: RuntimeError 발생 — {e}')
    assert (root / 'index.html').read_text(encoding='utf-8') == broken, 'FAIL: 예외에도 파일이 변경됨'
"
```

Expected: `OK: RuntimeError 발생 — ...` — 실제 파일 규모에서도 마커 소실 시 조용히
넘어가지 않고 예외가 발생함을 확인.

- [ ] **Step 2: `infomax.py`를 실제로 2회 연속 실행 — 신규 수집 + 교체 경로 확인**

```bash
cd /Users/sunggeunmoon/bloomberg-digest
.venv/bin/python infomax.py
.venv/bin/python infomax.py
```

Expected: 1회차는 `신규 N건 추가`(N>0, RSS에 실제로 최근 기사가 있는 한), 2회차는 `신규
0건 추가` 및 `홈페이지 변경 없음 — 커밋 생략`(멱등성 확인 — 같은 RSS를 다시 읽어도 중복
추가나 중복 커밋이 없어야 함).

- [ ] **Step 3: `digest.py` 재실행해 새 구조에서도 정상 동작하는지 확인**

```bash
cd /Users/sunggeunmoon/bloomberg-digest && .venv/bin/python digest.py
```

Expected: 기존과 동일하게 동작(캡차가 뜨면 프로젝트 관례대로 사용자에게 직접 해결
요청). 완료 후 `git log -1`로 커밋 메시지가 `"update: {date} Bloomberg 기사"` 형식인지
확인. Step 2에서 실제로 인포맥스 신규 항목이 있었다면(1회차), 그때의 커밋도
`git log --oneline -10`으로 찾아 메시지가 `"update: {date} 인포맥스 기사"` 형식인지 함께
확인한다(두 커밋 메시지 포맷을 모두 확인 — 인포맥스 쪽만 빠뜨리기 쉬움).

- [ ] **Step 4: 락 직렬화 확인 — 결정론적 2단계 확인**

`digest.py`는 헤디드 Playwright 스크래핑을 포함해 실행 시간이 들쭉날쭉하고 캡차가 뜨면
사람 개입이 필요하므로, `digest.py`와 `infomax.py`를 그냥 백그라운드로 동시에 띄우는
것만으로는 락이 실제로 직렬화를 강제하는지 신뢰성 있게 확인할 수 없다(우연히 순차
실행돼 "통과"처럼 보일 수 있음). 두 단계로 나눠 확인한다.

**4a. 결정론적 확인 — 두 개의 짧은 프로세스가 실제로 겹치지 않는지 검증:**

```bash
cd /Users/sunggeunmoon/bloomberg-digest
rm -f /tmp/lock_order.log
.venv/bin/python -c "
import time
from homepage_io import homepage_lock
with homepage_lock():
    with open('/tmp/lock_order.log', 'a') as f: f.write('P1-start\n')
    time.sleep(2)
    with open('/tmp/lock_order.log', 'a') as f: f.write('P1-end\n')
" &
sleep 0.3
.venv/bin/python -c "
import time
from homepage_io import homepage_lock
with homepage_lock():
    with open('/tmp/lock_order.log', 'a') as f: f.write('P2-start\n')
    time.sleep(2)
    with open('/tmp/lock_order.log', 'a') as f: f.write('P2-end\n')
" &
wait
cat /tmp/lock_order.log
```

Expected: `P1-start / P1-end / P2-start / P2-end` 순서(P1이 끝난 뒤에야 P2가 시작) — 두
독립 프로세스 사이에서도 `fcntl.flock`이 직렬화를 강제함을 증명. `P1-start / P2-start /
...`처럼 섞여 나오면 락이 동작하지 않는 것이므로 `homepage_io.py`의 `LOCK_PATH`나
`fcntl.flock` 사용법을 재점검한다.

**4b. 실전 감각 확인(참고용 — 캡차가 뜨면 오래 걸리거나 사용자 개입이 필요할 수 있음을
감안하고 진행):**

```bash
cd /Users/sunggeunmoon/bloomberg-digest
.venv/bin/python digest.py &
.venv/bin/python infomax.py &
wait
```

Expected: 둘 다 에러 없이 끝나고, `git log --oneline -5`에 두 스크립트의 커밋이 모두
보이며(한쪽이 없으면 덮어써진 것 — 실패), `index.html`을 열어 블룸버그 최신 섹션과
인포맥스 최신 섹션이 둘 다 반영돼 있는지 확인. digest.py가 캡차 대기로 오래 멈추면
프로젝트 관례대로 사용자에게 해결을 요청하고 기다린다(무기한 대기 자체는 정상 — 4a에서
락 메커니즘 자체는 이미 검증됐으므로, 이 스텝은 통합 동작 확인 목적이다).

- [ ] **Step 5: 브라우저 수동 확인**

```bash
open /Users/sunggeunmoon/bloomberg-digest/index.html
```

확인 항목:
- 탭 전환이 되는지, 새로고침 후에도 마지막 탭이 유지되는지(localStorage).
- **블룸버그 탭에서 아무 태그나 클릭해 필터를 건 다음 연합인포맥스 탭으로 전환** —
  인포맥스 기사가 전부 정상적으로 보이는지(교차 오염 없음 — 이게 이번 스펙 리뷰에서
  나온 핵심 회귀 시나리오).
- 인포맥스 탭에서 검색창에 아무 단어나 입력해 제목 기준 필터링이 되는지.
- 블룸버그 탭에서 기존 태그 필터/검색이 마이그레이션 전과 동일하게 동작하는지.

- [ ] **Step 6: 최종 상태 확인**

```bash
cd /Users/sunggeunmoon/bloomberg-digest && git status
```

Expected: `nothing to commit, working tree clean`(모든 변경이 이미 태스크별로 커밋됨).

<!-- spec-review: passed lenses=3 date=2026-08-12 -->
