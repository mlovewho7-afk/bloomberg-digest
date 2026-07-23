"""Bloomberg Economics+Markets RSS를 받아 관심 주제(미국/중국/일본/한국/유럽/중동리스크/
매크로/채권/주식)로 필터링하고 한글로 번역해 옵시디언 노트 + 홈페이지(index.html)에 반영한다.

자동 스케줄 없음 — 사용자가 "지금 업데이트 해줘"라고 할 때만 수동 실행한다. 그때는 창을
고정 종료시각(예: 아침 7시)이 아니라 "지금(실행 시각)"까지로 잡는다 — 명시적으로 그렇게
하기로 확정됨(2026-07-23).
"""
import html
import re
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from playwright.sync_api import sync_playwright

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent
VAULT_DIR = Path(
    "/Users/sunggeunmoon/Library/Mobile Documents/iCloud~md~obsidian/Documents"
    "/Moon/02.Finance/000.블룸버그기사"
)
FEEDS = {
    # scrape_economics_widget()이 opinion/newsletter까지 더 폭넓게 잡지만, 위젯 자체가
    # "Load more"로 되돌아갈 수 있는 과거 범위가 RSS보다 짧아서(직접 확인, 2026-07-23)
    # Economics RSS를 빼면 오히려 이른 시간대 기사가 통째로 누락된다. 그래서 스크래핑은
    # 추가 소스로만 쓰고 RSS 둘 다 유지 — 링크 기준으로 중복 제거.
    "Economics": "https://feeds.bloomberg.com/economics/news.rss",
    "Markets": "https://feeds.bloomberg.com/markets/news.rss",
}
ECONOMICS_URL = "https://www.bloomberg.com/economics"
BROWSER_PROFILE_DIR = ROOT / "data" / "browser_profile"
RELATIVE_TIME_RE = re.compile(r"(\d+)\s*(min|mins|minute|minutes|hr|hrs|hour|hours)\s*ago", re.IGNORECASE)
MAX_LOAD_MORE_CLICKS = 15
STALL_LIMIT = 3

# "Won"은 "Won't"의 일부와 겹쳐 오탐이 났던 전례가 있어 뺐다(2026-07-23 확인).
KEYWORDS = {
    "US": [r"\bU\.S\.", r"\bUS\b", r"\bUnited States\b", r"\bTrump\b", r"\bFed\b",
           r"\bWashington\b", r"\bAmerica\b", r"\bUSMCA\b", r"\bWarsh\b", r"\bPowell\b"],
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
}
PATTERNS = {k: re.compile("|".join(v), re.IGNORECASE) for k, v in KEYWORDS.items()}


def matched_tags(title: str) -> list[str]:
    return [tag for tag, pat in PATTERNS.items() if pat.search(title)]


def fetch_feed(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def load_rss_items(xml_bytes: bytes, source_name: str) -> list[dict]:
    tree = ET.fromstring(xml_bytes)
    out = []
    for it in tree.findall(".//item"):
        title = it.find("title").text
        link = it.find("link").text
        pubdate_kst = parsedate_to_datetime(it.find("pubDate").text).astimezone(KST)
        desc_el = it.find("description")
        summary = (desc_el.text or "").strip() if desc_el is not None else ""
        out.append({"title": title, "link": link, "pubdate_kst": pubdate_kst,
                     "source": source_name, "is_opinion": False, "summary": summary})
    return out


def parse_relative_time(text: str, scraped_at: datetime) -> datetime | None:
    text = text.strip()
    if text.lower() in ("just now", "now"):
        return scraped_at
    m = RELATIVE_TIME_RE.search(text)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    delta = timedelta(hours=n) if unit.startswith(("hr", "hour")) else timedelta(minutes=n)
    return scraped_at - delta


def scrape_economics_widget(window_start_kst: datetime) -> list[dict]:
    """bloomberg.com/economics의 "More Economics News" 위젯을 실제 브라우저로 긁는다.
    headless로는 PerimeterX(봇 차단, "px-captcha")에 막히지만 headed(화면 있는) 크롬은
    통과하는 것을 확인했다(2026-07-23) — 그래서 headless=False로 고정한다. 이 위젯은
    RSS에는 없는 newsletter/opinion/feature 콘텐츠까지 포함해 더 완전하다."""
    BROWSER_PROFILE_DIR.parent.mkdir(parents=True, exist_ok=True)
    items = []
    seen_hrefs = set()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(BROWSER_PROFILE_DIR),
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        page = ctx.new_page()
        page.goto(ECONOMICS_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        stall = 0
        for _ in range(MAX_LOAD_MORE_CLICKS):
            scraped_at = datetime.now(KST)
            soup = BeautifulSoup(page.content(), "html.parser")
            section = soup.find("section", class_="LineupContentArchive_LineupContentArchive__6yp9k")
            if section is None:
                print("[digest] More Economics News 위젯을 못 찾음 — 스크래핑 중단")
                break

            new_count = 0
            oldest_pubdate = None
            for c in section.find_all("div", class_="styles_itemContainer__t2ZQc"):
                a = c.find("a", class_="styles_itemLink__VgyXJ")
                time_el = c.find("time")
                if a is None or time_el is None:
                    continue
                href = urllib.parse.urljoin(ECONOMICS_URL, a["href"])
                pubdate_kst = parse_relative_time(time_el.get_text(strip=True), scraped_at)
                if pubdate_kst is None:
                    continue
                oldest_pubdate = pubdate_kst if oldest_pubdate is None else min(oldest_pubdate, pubdate_kst)
                if href in seen_hrefs:
                    continue
                seen_hrefs.add(href)
                headline_el = a.find(attrs={"data-testid": "headline"})
                title = headline_el.get_text(strip=True) if headline_el else a.get_text(strip=True)
                eyebrow = a.find("div", class_=lambda cls: cls and "optionalEyebrow" in cls)
                is_opinion = bool(eyebrow and "Opinion" in eyebrow.get_text())
                summary_el = a.find(attrs={"data-component": "summary"})
                summary = summary_el.get_text(strip=True) if summary_el else ""
                items.append({
                    "title": title, "link": href, "pubdate_kst": pubdate_kst,
                    "source": "EconomicsWidget", "is_opinion": is_opinion, "summary": summary,
                })
                new_count += 1

            stall = stall + 1 if new_count == 0 else 0
            if stall >= STALL_LIMIT:
                break
            if oldest_pubdate is not None and oldest_pubdate < window_start_kst:
                break

            load_more = page.get_by_role("button", name="Load more")
            if load_more.count() == 0:
                break
            load_more.first.click()
            page.wait_for_timeout(1500)

        ctx.close()
    return items


def collect_window(window_start_kst: datetime, window_end_kst: datetime) -> list[dict]:
    items = scrape_economics_widget(window_start_kst)
    for name, url in FEEDS.items():
        items.extend(load_rss_items(fetch_feed(url), name))

    # 같은 기사가 스크래핑과 RSS 양쪽에 잡힐 수 있어 쿼리스트링을 뺀 링크로 중복 제거
    seen = set()
    deduped = []
    for item in items:
        key = item["link"].split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    filtered = []
    for item in deduped:
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
        if item["summary"]:
            try:
                item["summary_ko"] = translator.translate(item["summary"])
            except Exception as e:
                print(f"[digest] 요약 번역 실패, 원문 유지: {e!r}")
                item["summary_ko"] = item["summary"]
        else:
            item["summary_ko"] = ""


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
        summary_attr = html.escape(it["summary_ko"] or "요약 없음", quote=True)
        tags_attr = html.escape(",".join(it["tags"]), quote=True)
        rows.append(
            f'<li><span class="stamp">{stamp}</span>{tags}'
            f'<a class="itemLink" href="{it["link"]}" rel="noopener" '
            f'data-summary="{summary_attr}" data-tags="{tags_attr}">{it["title_ko"]}</a></li>'
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


def main() -> None:
    now_kst = datetime.now(KST)
    window_end_kst = now_kst
    window_start_kst = (now_kst - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
    date_label = now_kst.date().isoformat()

    print(f"[digest] 창: {window_start_kst} ~ {window_end_kst}")
    items = collect_window(window_start_kst, window_end_kst)
    print(f"[digest] {len(items)}건 매칭")
    if not items:
        print("[digest] 매칭 항목 없음 — 종료")
        return

    translate_items(items)
    note = render_obsidian_note(date_label, items)
    obsidian_path = save_to_obsidian(date_label, note)
    print(f"[digest] 옵시디언 저장: {obsidian_path}")

    update_homepage(date_label, items)
    push_homepage(date_label)
    print("[digest] 완료")


if __name__ == "__main__":
    main()
