"""infomax.py를 검증한다. .venv/bin/python test_infomax.py 로 직접 실행."""
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from infomax import KST, fetch_rss, load_store, merge_items, parse_rss_xml, save_store, stale_pubdate_warning

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


if __name__ == "__main__":
    test_parse_rss_xml_unescapes_double_encoded_entities()
    test_parse_rss_xml_empty_channel_returns_empty_list()
    test_stale_pubdate_warning_none_when_recent()
    test_stale_pubdate_warning_set_when_drift_over_2h()
    test_stale_pubdate_warning_none_when_empty()
    test_load_store_returns_empty_dict_when_file_absent()
    test_save_and_load_store_roundtrip()
    test_merge_items_dedups_by_link_and_skips_unchanged()
    test_merge_items_buckets_by_own_pubdate_not_fixed_window()
    print("ALL TESTS PASSED (Task 4)")
