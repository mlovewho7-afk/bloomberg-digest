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
