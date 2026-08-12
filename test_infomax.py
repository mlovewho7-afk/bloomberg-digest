"""infomax.py를 검증한다. .venv/bin/python test_infomax.py 로 직접 실행."""
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from infomax import KST, fetch_rss, load_store, merge_items, parse_rss_xml, render_infomax_day_section_html, save_store, stale_pubdate_warning, update_infomax_pane

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
    test_render_infomax_day_section_html_newest_first()
    test_render_infomax_day_section_html_empty_items()
    test_update_infomax_pane_bootstraps_from_template_when_file_absent()
    test_update_infomax_pane_inserts_new_date_above_existing()
    test_update_infomax_pane_replaces_same_day_not_duplicates()
    test_update_infomax_pane_raises_when_marker_missing_and_does_not_write()
    test_update_infomax_pane_raises_when_template_itself_lacks_marker()
    print("ALL TESTS PASSED (Task 6)")
