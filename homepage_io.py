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
