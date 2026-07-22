"""Bloomberg Economics+Markets RSS를 받아 관심 주제(미국/중국/일본/한국/유럽/중동리스크/
매크로/채권/주식)로 필터링하고 한글로 번역해 옵시디언 노트 + 홈페이지(index.html)에 반영한다.

자동 스케줄 없음 — 사용자가 "지금 업데이트 해줘"라고 할 때만 수동 실행한다. 그때는 창을
고정 종료시각(예: 아침 7시)이 아니라 "지금(실행 시각)"까지로 잡는다 — 명시적으로 그렇게
하기로 확정됨(2026-07-23).
"""
import re
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from deep_translator import GoogleTranslator

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent
VAULT_DIR = Path(
    "/Users/sunggeunmoon/Library/Mobile Documents/iCloud~md~obsidian/Documents"
    "/Moon/02.Finance/000.블룸버그기사"
)
FEEDS = {
    "Economics": "https://feeds.bloomberg.com/economics/news.rss",
    "Markets": "https://feeds.bloomberg.com/markets/news.rss",
}

# "Won"은 "Won't"의 일부와 겹쳐 오탐이 났던 전례가 있어 뺐다(2026-07-23 확인).
KEYWORDS = {
    "US": [r"\bU\.S\.", r"\bUS\b", r"\bUnited States\b", r"\bTrump\b", r"\bFed\b",
           r"\bWashington\b", r"\bAmerica\b", r"\bUSMCA\b"],
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
              r"\bemployment\b", r"\bjobs?\b", r"\bunemployment\b", r"\brate hike\b",
              r"\brate cut\b", r"\bcentral bank\b", r"\binterest rate\b", r"\bmonetary policy\b",
              r"\btariffs?\b", r"\btrade\b"],
    "Bonds": [r"\bbond\b", r"\byield\b", r"\bTreasury\b", r"\bdebt\b", r"\bauction\b"],
    "Stocks": [r"\bstocks?\b", r"\bequit(y|ies)\b", r"\bshares?\b"],
}
PATTERNS = {k: re.compile("|".join(v), re.IGNORECASE) for k, v in KEYWORDS.items()}


def matched_tags(title: str) -> list[str]:
    return [tag for tag, pat in PATTERNS.items() if pat.search(title)]


def fetch_feed(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def load_items(xml_bytes: bytes, source_name: str) -> list[dict]:
    tree = ET.fromstring(xml_bytes)
    out = []
    for it in tree.findall(".//item"):
        title = it.find("title").text
        link = it.find("link").text
        guid_el = it.find("guid")
        guid = guid_el.text if guid_el is not None else link
        pubdate = parsedate_to_datetime(it.find("pubDate").text)
        out.append({"title": title, "link": link, "guid": guid, "pubdate": pubdate, "source": source_name})
    return out


def collect_window(window_start_kst: datetime, window_end_kst: datetime) -> list[dict]:
    items = []
    for name, url in FEEDS.items():
        items.extend(load_items(fetch_feed(url), name))

    seen = set()
    deduped = []
    for item in items:
        if item["guid"] in seen:
            continue
        seen.add(item["guid"])
        deduped.append(item)

    filtered = []
    for item in deduped:
        pubdate_kst = item["pubdate"].astimezone(KST)
        if not (window_start_kst <= pubdate_kst < window_end_kst):
            continue
        tags = matched_tags(item["title"])
        if tags:
            filtered.append({**item, "pubdate_kst": pubdate_kst, "tags": tags})

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


def main():
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
