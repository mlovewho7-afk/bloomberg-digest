# 연합인포맥스 RSS 연동 + 홈페이지 탭 재구성

## 배경

`bloomberg-digest` 프로젝트는 지금까지 bloomberg.com/latest를 Playwright로 스크래핑해
번역 후 홈페이지(`index.html`)와 옵시디언에 반영해왔다. 여기에 연합인포맥스 채권/외환
RSS(`https://news.einfomax.co.kr/rss/S1N16.xml`)를 두 번째 소스로 추가하고, 홈페이지를
두 소스를 오갈 수 있는 구조로 재구성한다.

인포맥스 RSS는 블룸버그와 성격이 다르다: 이미 한글이라 번역이 필요 없고, 정적 XML이라
Playwright나 캡차 대응이 필요 없다. 이 차이 때문에 별도 스크립트로 분리한다.

## 범위

- RSS: `S1N16`(채권/외환) 하나만. 다른 카테고리는 이번 범위 밖.
- 태그 필터링(US/Fed/China 등)은 인포맥스에 적용하지 않는다. 시간순 목록 + 제목 검색만.
- 실행은 완전 수동. 자동 스케줄 없음 — digest.py와 동일 관례.
- **digest.py에도 최소 변경이 필요하다** (아래 "기존 코드에 대한 안전장치 보강" 참조) —
  당초 "digest.py는 손대지 않는다"고 가정했으나, 리뷰 과정에서 digest.py의 기존 마커
  폴백 로직 자체가 이번 마이그레이션의 실패 시 파급을 키우는 원인임이 확인되어 범위에
  포함시킨다. 이 변경은 인포맥스 기능과 무관한 리팩터가 아니라, 이번 작업이 만드는 위험을
  직접 제거하는 데 필요한 최소 변경이다.

## 아키텍처

### 0. 기존 코드에 대한 안전장치 보강 (신규 — regenerate로 추가됨)

`digest.py`의 `update_homepage()`(234~258줄)에는 다음 폴백이 있다:

```python
existing_start = html.find(marker)
if existing_start == -1:
    html = template          # 마커를 못 찾으면 전체를 빈 템플릿으로 갈아치움 — 조용히 발생
    existing_start = html.find(marker)
```

이 폴백은 2026-07-29 사고(마커 소실 → 누적 데이터 통삭제, `solved_problems.md` 기록)를
일으켰던 바로 그 경로이며, 지금도 아무 경고 없이 살아있다(`FAIL-LOUD` 위반). 이번 작업은
실 서비스 중인 `index.html`을 손으로 재구성하는 마이그레이션을 수반하므로, 마커가 실수로
손상될 위험이 평소보다 높다. 이 폴백을 그대로 둔 채 마이그레이션하면, 실수가 나도 다음
`digest.py` 실행이 아무 경고 없이 데이터를 지워버린다.

**변경**: `existing_start == -1`일 때 template으로 조용히 대체하는 대신, 예외를 던지고
아무것도 쓰지 않은 채 중단한다(`RuntimeError("SECTIONS 마커를 찾을 수 없음 — index.html이
손상되었을 수 있음, 수동 확인 필요")`). `infomax.py`의 `update_infomax_pane()`도 처음부터
동일한 원칙(마커 없으면 예외로 중단, 절대 템플릿으로 대체하지 않음)으로 설계한다.

### 1. `infomax.py` (신규, digest.py와 분리된 독립 스크립트)

```
fetch_rss(url) -> list[dict]
  requests + xml.etree.ElementTree로 <item> 파싱
  각 item: {title, link, pubdate_kst}
  - pubDate는 관찰된 샘플상 "YYYY-MM-DD HH:MM:SS"(타임존 표기 없음)이며 KST로 가정한다.
    이 가정은 검증되지 않은 전제이므로, 첫 실행 시 가장 최신 item의 pubDate와 실행 시각
    (now_kst)의 차이가 2시간을 넘으면 경고 로그를 출력한다(조용히 틀린 시각을 쓰지 않도록).
  - title에는 이중 이스케이프된 HTML 엔티티(예: &amp;quot;)가 실제로 존재함을 확인함.
    ElementTree가 파싱 시 1차 언이스케이프(&amp;→&)를 하므로, 파싱 후 남은 텍스트에
    `html.unescape()`를 한 번 더 적용해야 `&quot;` 같은 리터럴이 그대로 노출되지 않는다.

collect_items() -> list[dict]
  RSS가 반환하는 모든 item을 그대로 사용(창(window) 필터링 없음 — RSS 자체가 최근
  항목만 제공한다는 전제이며, 이는 실행 로그로 매번 관찰 가능하다: 반환 건수와 가장
  과거 pubDate를 로그에 남겨 전제가 깨지면(예: 갑자기 과거 데이터까지 몰려옴) 눈에 띄게
  한다).

load_store() / save_store()
  data/infomax_items.json, digest.py의 collected_items.json과 동일한 날짜별 dict
  구조(링크 기준 dedup, 기존 항목 보존)

render_infomax_day_section_html()
  <section class="infomaxSection"><h2>{date}</h2>...
  class="infomaxSection"으로 블룸버그 섹션(class 없음)과 구분 — 같은 날짜의 day_marker
  탐색이 서로 다른 소스의 섹션과 충돌하지 않게 한다.

update_infomax_pane()
  index.html에서 <!-- INFOMAX_SECTIONS --> 마커를 찾아 같은 날짜 section 있으면 교체,
  없으면 위에 추가. **마커를 못 찾으면 (섹션 0의 원칙대로) 예외를 던지고 중단한다 —
  절대 템플릿으로 조용히 대체하지 않는다.**

push_homepage()
  git add/commit(메시지: "update: {date} 인포맥스 기사")/push.
  **파일 락(아래 "동시 실행 경합 방지" 참조)을 acquire한 상태에서만 index.html을 읽고,
  수정하고, 쓰고, 커밋한다.**

main()
  RSS 수집 → 날짜별 누적 병합 → 락 획득 → 홈페이지 갱신 → push → 락 해제
```

의존성: `requests`(설치 확인됨), `xml.etree.ElementTree`(표준 라이브러리). 새 패키지
설치 불필요.

### 2. 동시 실행 경합 방지 (신규 — regenerate로 추가됨)

`digest.py`와 `infomax.py`는 각각 독립적으로 같은 `index.html`을 읽어 메모리에서 수정한
뒤 통째로 다시 쓰고 커밋·푸시한다. 두 스크립트가 시간이 겹쳐 실행되면(예: 사용자가
"블룸버그랑 인포맥스 둘 다 업데이트해줘"라고 해서 근접 실행되는 경우), 나중에 쓰는 쪽이
먼저 쓴 쪽의 변경분을 인지하지 못한 채 통째로 덮어써 무음으로 데이터를 유실시킬 수 있다
(git 커밋 자체는 실패하지 않으므로 에러도 뜨지 않는다).

**대응**: `index.html`을 읽고 쓰고 커밋하는 구간을 파일 락으로 감싼다.
`fcntl.flock()`으로 `.git/.homepage.lock`(git이 관리하지 않는 디렉터리라 실수로 커밋될
위험이 없음)을 잠그고, 읽기→수정→쓰기→git add/commit/push까지 끝난 뒤 해제한다. 두
스크립트 모두 이 락을 사용하므로, 근접 실행되어도 한쪽이 끝날 때까지 다른 쪽이
대기하며(스핀락 아님, blocking lock), 순차 직렬화되어 덮어쓰기가 발생하지 않는다. 새
의존성 불필요(`fcntl`은 표준 라이브러리, macOS/Linux 지원).

**무기한 대기 방지**: `git push`를 포함한 락 보유 구간 전체를 `subprocess.run(..., timeout=
60)`으로 감싼다. 60초 안에 끝나지 않으면(네트워크 장애 등) 예외를 던지고 락을 해제한 뒤
중단한다 — 락이 push 실패로 무기한 걸려있는 상태를 막는다(FAIL-LOUD: 조용히 걸려있지
않고 즉시 에러로 드러남).

**쓰기 원자성**: `index.html`을 직접 덮어쓰지 않고, 임시 파일에 먼저 쓴 뒤
`os.replace()`로 교체한다(락과는 별개 문제 — 락은 동시 접근만 막고, 원자적 교체는 쓰기
도중 프로세스가 죽어도 파일이 잘린 상태로 남지 않게 한다).

이와 별개로 운영 규율로: 사용자가 "둘 다 업데이트해줘"라고 요청해도 에이전트는 두
스크립트를 병렬(백그라운드 동시)로 실행하지 않고 순차 실행한다(락이 있어도 안전하지만,
순차 실행이 더 예측 가능하고 로그 해석이 쉽다).

### 3. 홈페이지 구조 — 탭 전환

`index_template.html`과 실제 `index.html` 양쪽에 동일한 최종 구조를 만든다. 기존
코드베이스의 id 명명 관례(camelCase: `topBar`, `searchBox`, `topTags`, `filterBar`,
`resetFilter`)를 그대로 따른다(새로 kebab-case를 섞지 않는다).

```html
<body>
  <div id="tabBar">
    <button id="tabBloomberg" class="tabBtn active">Bloomberg</button>
    <button id="tabInfomax" class="tabBtn">연합인포맥스</button>
  </div>

  <div id="bloombergPane">
    <!-- 기존 topBar(검색+태그+필터상태) + <!-- SECTIONS --> + 누적 section들
         내용/구조 변경 없음, div로 감싸기만 함 -->
  </div>

  <div id="infomaxPane" style="display:none">
    <div id="infomaxTopBar">
      <input type="text" id="infomaxSearchBox" placeholder="제목 검색...">
    </div>
    <!-- INFOMAX_SECTIONS -->
  </div>

  <script>
    /* 기존 Bloomberg 필터 로직 유지, querySelectorAll('section')을
       '#bloombergPane section'으로 좁힘(Infomax pane과 격리) */

    /* 신규: 탭 전환 (localStorage로 마지막 탭 기억) */
    /* 신규: Infomax 검색 — 제목 텍스트 매칭만, 태그 없음 */
  </script>
</body>
```

### 4. 마이그레이션 방식 (기존 사고 재발 방지 — 절차 구체화됨)

`solved_problems.md`에 "마커를 콘텐츠로 치환해서 다음 실행용 삽입지점을 지워버린" 사고
기록이 있다. 이번에도 실제 운영 중인 `index.html`(약 266KB, 누적된 실제 기사 데이터
포함)을 손으로 재구성해야 한다.

**순서**:
1. **체크포인트 확인**: 마이그레이션 시작 전 `git status`로 작업 트리가 깨끗한지 확인한다
   (현재 확인됨: clean). 깨끗하지 않다면 먼저 커밋해 현재 HEAD를 안전한 롤백 지점으로
   만든다. 이렇게 하면 마이그레이션이 잘못돼도 `git checkout HEAD -- index.html`로 즉시
   되돌릴 수 있다.
2. **삽입만, 치환 금지**: 기존 `<!-- SECTIONS -->` 마커와 그 뒤에 붙은 모든 `<section>`은
   **내용을 전혀 건드리지 않는다.** 다음 지점에 새 요소를 *삽입*만 한다(문자열 치환 아님):
   - `<body>` 직후, `<div id="topBar">` 직전 → `<div id="tabBar">...</div>` 삽입
   - `<div id="topBar">` 직전 → `<div id="bloombergPane">` 여는 태그 삽입
   - 마지막 `</section>` 직후, `<script>` 직전(이 파일에서 이 경계는 유일하게 존재함 —
     확인됨) → `</div>` (bloombergPane 닫기) + `<div id="infomaxPane" style="display:
     none">...<!-- INFOMAX_SECTIONS --></div>`(빈 상태로) 삽입
   - `<script>` 블록 안에는 기존 코드를 지우지 않고, `querySelectorAll('section')` 한 줄만
     `'#bloombergPane section'`으로 좁히고, 탭 전환·인포맥스 검색 함수를 추가한다.
3. **검증**: 마이그레이션 직후 `<!-- SECTIONS -->` 마커가 여전히 존재하는지, `<section>`
   개수가 마이그레이션 전후 동일한지 스크립트로 대조한다(사람 눈이 아니라 코드로).
4. `index_template.html`도 동일한 최종 구조(빈 `infomaxPane` 포함)로 갱신한다.

## 검증 계획

1. 마이그레이션 직후: `<!-- SECTIONS -->` 마커 존재 여부와 `<section>` 개수를
   마이그레이션 전/후 diff로 대조 — 블룸버그 데이터 유실 없음을 증명. `index.html`과
   `index_template.html` 양쪽 모두 동일한 wrapper 구조(tabBar/bloombergPane/infomaxPane
   id와 마커)를 갖는지 확인.
2. `infomax.py`를 실제로 **2회** 수동 실행한다 — 1회차는 신규 수집·섹션 생성 확인, 2회차는
   같은 날짜 섹션이 (중복 추가가 아니라) 교체되는 경로를 확인한다(digest.py의 동일 로직과
   같은 방식으로 검증).
3. `digest.py`도 1회 재실행해 새 구조(bloombergPane으로 감싸진 상태) 아래에서 기존
   업데이트 로직이 그대로 동작하는지 확인.
4. git 커밋/푸시가 의도한 메시지 포맷으로 실제로 만들어지는지 확인.
5. 브라우저로 실제 페이지를 열어: (a) 탭 전환 및 새로고침 후에도 마지막 탭이 유지되는지
   (localStorage), (b) **블룸버그 탭에서 태그 필터를 클릭한 뒤 인포맥스 탭으로 전환 —
   인포맥스 항목이 전부 정상적으로 보이는지**(교차 오염 없음 확인, `#bloombergPane`
   스코프 수정이 실제로 격리를 만드는지의 핵심 테스트), (c) 인포맥스 탭에서 검색이
   제목 기준으로 정상 동작하는지.
6. **FAIL-LOUD 가드 확인**: `<!-- SECTIONS -->` 마커를 임시로 지운 복사본에 대해
   `update_homepage()`/`update_infomax_pane()`을 실행해 정말로 예외가 던져지고 원본
   `index.html`이 변경되지 않는지 확인한다(실제 운영 파일이 아닌 사본으로 테스트).
7. **락 직렬화 확인**: `digest.py`와 `infomax.py`를 의도적으로 거의 동시에(둘 다
   백그라운드로) 실행해, 두 실행이 겹치지 않고 순차적으로 처리되며 양쪽 변경분이 모두
   최종 `index.html`에 반영되는지 확인한다(한쪽이 다른 쪽을 덮어쓰지 않음).

## 범위 밖 (YAGNI)

- 인포맥스 다른 카테고리 RSS 통합 — `fetch_rss(url)`이 URL을 인자로 받는 것 자체로 이미
  충분히 확장 가능하다(이 이상의 별도 골격을 지금 만들지 않는다 — 예: 다중 URL 순회 로직,
  카테고리별 저장 스키마 분리 등은 실제 두 번째 카테고리가 필요해질 때 설계한다).
- 인포맥스 태그 필터링 — 사용자가 명시적으로 안 하기로 결정.
- 자동 스케줄 — 블룸버그와 동일하게 완전 수동 유지.
- 파일 락 이상의 동시성 제어(예: 큐, 원격 락 서비스) — 로컬 단일 사용자 환경이라
  `fcntl.flock` 수준이면 충분하다.

<!-- spec-review: passed lenses=3 date=2026-08-12 -->
