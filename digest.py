"""bloomberg.com/latest가 내부적으로 쓰는 공개 API(lineup-next/api/stories)를 직접
호출해 관심 주제(미국/중국/일본/한국/유럽/중동리스크/매크로/채권/주식/원유/금/연준/
오피니언)로 필터링하고 한글로 번역해 옵시디언 노트 + 홈페이지(index.html)에 반영한다.

자동 스케줄 없음 — 사용자가 "지금 업데이트 해줘"라고 할 때만 수동 실행한다. 그때는 창을
고정 종료시각(예: 아침 7시)이 아니라 "지금(실행 시각)"까지로 잡는다 — 명시적으로 그렇게
하기로 확정됨(2026-07-23).

이 API는 로그인·브라우저 없이 plain HTTP로도 열람 가능하고(PerimeterX 안 걸림, 2026-07-23
확인) ISO 발행시각을 정확히 준다 — 그래서 이전의 Playwright 기반 DOM 스크래핑(위젯
"Load more" 버튼 클릭 방식, RSS 등)을 전부 버리고 이 API 하나로 통합했다.
"""
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from deep_translator import GoogleTranslator

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent
VAULT_DIR = Path(
    "/Users/sunggeunmoon/Library/Mobile Documents/iCloud~md~obsidian/Documents"
    "/Moon/02.Finance/000.블룸버그기사"
)
STORIES_API = "https://www.bloomberg.com/lineup-next/api/stories"
STORIES_API_QUERY = "types=ARTICLE,FEATURE,INTERACTIVE,LETTER,EXPLAINERS&locale=en&limit=25"
MAX_PAGES = 40
STORE_PATH = ROOT / "data" / "collected_items.json"

# "Won"은 "Won't"의 일부와 겹쳐 오탐이 났던 전례가 있어 뺐다(2026-07-23 확인).
KEYWORDS = {
    "US": [r"\bU\.S\.", r"\bUS\b", r"\bUnited States\b", r"\bTrump\b", r"\bFed\b",
           r"\bWashington\b", r"\bAmerica\b", r"\bUSMCA\b"],
    "Fed": [r"\bFed\b", r"\bFederal Reserve\b", r"\bFOMC\b", r"\bWarsh\b", r"\bPowell\b"],
    "China": [r"\bChina\b", r"\bChinese\b", r"\bBeijing\b", r"\bPBOC\b", r"\bYuan\b"],
    "Japan": [r"\bJapan\b", r"\bJapanese\b", r"\bBOJ\b", r"\bTokyo\b", r"\bYen\b"],
    "Korea": [r"\bKorea\b", r"\bKorean\b", r"\bBOK\b", r"\bSeoul\b"],
    "Europe": [r"\bEU\b", r"\bEurope\b", r"\bEuropean\b", r"\bECB\b", r"\bUK\b",
               r"\bBritain\b", r"\bBritish\b", r"\bGermany\b", r"\bFrance\b",
               r"\bEurozone\b", r"\bGilts?\b"],
    "MiddleEast": [r"\bIran\b", r"\bIranian\b", r"\bIsrael\b", r"\bIsraeli\b", r"\bGaza\b",
                   r"\bSaudi\b", r"\bOPEC\b", r"\bGulf\b", r"\bHormuz\b", r"\bHouthi\b",
                   r"\bYemen\b", r"\bIraq\b", r"\bSyria\b", r"\bQatar\b", r"\bUAE\b",
                   r"\bMiddle East\b"],
    "Macro": [r"\binflation\b", r"\bGDP\b", r"\bgrowth\b", r"\brecession\b",
              r"\bemployment\b", r"\bjobs?\b", r"\bunemployment\b", r"\brates?\b",
              r"\bcentral bank\b", r"\bmonetary policy\b",
              r"\btariffs?\b", r"\btrade\b"],
    "Bonds": [r"\bbonds?\b", r"\byields?\b", r"\bTreasury\b", r"\bTreasuries\b",
              r"\bdebt\b", r"\bauction\b", r"\bGilts?\b"],
    "Stocks": [r"\bstocks?\b", r"\bequit(y|ies)\b", r"\bshares?\b"],
    "Oil": [r"\bBrent\b", r"\bWTI\b", r"\bcrude\b", r"\boil\b", r"\bbarrels?\b",
            r"\btanker\b", r"\brefiner(y|ies)\b", r"\bOPEC\b"],
    "Gold": [r"\bgold\b", r"\bbullion\b", r"\bXAU\b"],
}
PATTERNS = {k: re.compile("|".join(v), re.IGNORECASE) for k, v in KEYWORDS.items()}


def matched_tags(title: str) -> list[str]:
    return [tag for tag, pat in PATTERNS.items() if pat.search(title)]


RETRY_WAITS_SECONDS = (10, 30, 60)


def fetch_stories_page(page_number: int) -> list[dict]:
    """이 API는 요청이 몰리면 403을 준다(직접 확인, 2026-07-23) — 사람이 잠깐 다시
    시도하면 보통 풀리는 수준이라 짧게 대기하며 재시도한다."""
    url = f"{STORIES_API}?{STORIES_API_QUERY}&pageNumber={page_number}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    last_error = None
    for attempt, wait_seconds in enumerate((0,) + RETRY_WAITS_SECONDS):
        if wait_seconds:
            print(f"[digest] API 403 — {wait_seconds}초 대기 후 재시도")
            time.sleep(wait_seconds)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code != 403:
                raise
            last_error = e
    raise last_error


def scrape_latest(window_start_kst: datetime) -> list[dict]:
    items = []
    for page_number in range(1, MAX_PAGES + 1):
        if page_number > 1:
            time.sleep(1.5)
        stories = fetch_stories_page(page_number)
        if not stories:
            break
        oldest_pubdate = None
        for s in stories:
            pubdate_kst = datetime.fromisoformat(s["publishedAt"].replace("Z", "+00:00")).astimezone(KST)
            oldest_pubdate = pubdate_kst if oldest_pubdate is None else min(oldest_pubdate, pubdate_kst)
            link = "https://www.bloomberg.com" + s["url"]
            items.append({
                "title": s["headline"], "link": link, "pubdate_kst": pubdate_kst,
                "is_opinion": "/opinion/" in s["url"],
            })
        if oldest_pubdate is not None and oldest_pubdate < window_start_kst:
            break
    return items


def collect_window(window_start_kst: datetime, window_end_kst: datetime) -> list[dict]:
    items = scrape_latest(window_start_kst)

    filtered = []
    for item in items:
        if not (window_start_kst <= item["pubdate_kst"] < window_end_kst):
            continue
        tags = matched_tags(item["title"])
        # Opinion은 주제 키워드 매칭 여부와 무관하게 항상 포함(사용자 명시 요청, 2026-07-23)
        if item["is_opinion"] and "Opinion" not in tags:
            tags = tags + ["Opinion"]
        if tags:
            filtered.append({**item, "tags": tags})

    filtered.sort(key=lambda x: x["pubdate_kst"])
    return filtered


def translate_items(items: list[dict]) -> None:
    translator = GoogleTranslator(source="auto", target="ko")
    for item in items:
        try:
            item["title_ko"] = translator.translate(item["title"])
        except Exception as e:
            print(f"[digest] 번역 실패, 원문 유지: {e!r}")
            item["title_ko"] = item["title"]


def render_obsidian_note(date_label: str, items: list[dict]) -> str:
    lines = [f"# {date_label} Bloomberg 기사", ""]
    for it in items:
        stamp = it["pubdate_kst"].strftime("%Y-%m-%d %H:%M")
        lines.append(f"- {stamp} [{','.join(it['tags'])}] — [{it['title_ko']}]({it['link']})")
    return "\n".join(lines) + "\n"


def save_to_obsidian(date_label: str, note: str) -> Path:
    VAULT_DIR.mkdir(exist_ok=True)
    out_path = VAULT_DIR / f"{date_label} Bloomberg 기사.md"
    out_path.write_text(note, encoding="utf-8")
    return out_path


def render_day_section_html(date_label: str, items: list[dict]) -> str:
    rows = []
    for it in items:
        stamp = it["pubdate_kst"].strftime("%m-%d %H:%M")
        tags = "".join(f'<span class="tag">{t}</span>' for t in it["tags"])
        rows.append(
            f'<li><span class="stamp">{stamp}</span>{tags}'
            f'<a href="{it["link"]}" target="_blank" rel="noopener">{it["title_ko"]}</a></li>'
        )
    return f'<section><h2>{date_label}</h2><ul>' + "\n".join(rows) + "</ul></section>"


def update_homepage(date_label: str, items: list[dict]) -> None:
    index_path = ROOT / "index.html"
    template = (ROOT / "index_template.html").read_text(encoding="utf-8")
    new_section = render_day_section_html(date_label, items)

    if index_path.exists():
        html = index_path.read_text(encoding="utf-8")
        marker = "<!-- SECTIONS -->"
        existing_start = html.find(marker)
        if existing_start == -1:
            html = template
            existing_start = html.find(marker)
        # 같은 날짜 섹션이 이미 있으면 통째로 교체(재실행 시 중복 방지), 없으면 맨 위에 추가
        day_marker = f'<section><h2>{date_label}</h2>'
        if day_marker in html:
            start = html.find(day_marker)
            end = html.find("</section>", start) + len("</section>")
            html = html[:start] + new_section + html[end:]
        else:
            insert_at = existing_start + len(marker)
            html = html[:insert_at] + "\n" + new_section + html[insert_at:]
    else:
        html = template.replace("<!-- SECTIONS -->", "<!-- SECTIONS -->\n" + new_section)

    index_path.write_text(html, encoding="utf-8")


def push_homepage(date_label: str) -> None:
    def run(cmd):
        subprocess.run(cmd, cwd=ROOT, check=True)

    run(["git", "add", "index.html"])
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if result.returncode == 0:
        print("[digest] 홈페이지 변경 없음 — 커밋 생략")
        return
    run(["git", "commit", "-m", f"update: {date_label} Bloomberg 기사"])
    run(["git", "push"])


def load_store() -> dict:
    if STORE_PATH.exists():
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    return {}


def save_store(store: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    """실행마다 새로 가져온 기사를 그날 누적분에 링크 기준으로 합친다(덮어쓰지 않음) —
    블룸버그 쪽 차단/요청제한으로 이번 조회가 이전보다 적게 잡혀도 예전에 이미 확보한
    기사가 사라지지 않는다(2026-07-23, 사용자 지적으로 도입)."""
    now_kst = datetime.now(KST)
    window_end_kst = now_kst
    window_start_kst = (now_kst - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
    date_label = now_kst.date().isoformat()

    print(f"[digest] 창: {window_start_kst} ~ {window_end_kst}")
    new_items = collect_window(window_start_kst, window_end_kst)
    print(f"[digest] 이번 조회 {len(new_items)}건")

    store = load_store()
    day_store = store.get(date_label, {})
    added = 0
    for item in new_items:
        if item["link"] not in day_store:
            day_store[item["link"]] = {**item, "pubdate_kst": item["pubdate_kst"].isoformat()}
            added += 1
    print(f"[digest] 신규 {added}건 추가, 누적 {len(day_store)}건")

    if not day_store:
        print("[digest] 누적 항목 없음 — 종료")
        return

    to_translate = [v for v in day_store.values() if "title_ko" not in v]
    if to_translate:
        translate_items(to_translate)

    store[date_label] = day_store
    save_store(store)

    all_items = [{**v, "pubdate_kst": datetime.fromisoformat(v["pubdate_kst"])} for v in day_store.values()]
    all_items.sort(key=lambda x: x["pubdate_kst"])

    note = render_obsidian_note(date_label, all_items)
    obsidian_path = save_to_obsidian(date_label, note)
    print(f"[digest] 옵시디언 저장: {obsidian_path}")

    update_homepage(date_label, all_items)
    push_homepage(date_label)
    print("[digest] 완료")


if __name__ == "__main__":
    main()
