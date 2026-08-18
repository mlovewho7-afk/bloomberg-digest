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
