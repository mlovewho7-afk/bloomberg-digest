"""홈페이지의 "캡처 보기" 버튼이 호출하는 로컬 서버. 로그인된 브라우저 프로필로
기사 페이지의 <article> 영역만 스크린샷 찍어서 그대로 돌려준다 — 채팅창을 거치지
않고 홈페이지 안에서 바로 원문(사진·블룸버그 자체 AI 요약 포함)을 보게 하기 위함.

실행: .venv/bin/python capture_server.py
로그인 갱신: .venv/bin/python capture_server.py --login
"""
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from playwright.sync_api import sync_playwright

from digest import BROWSER_PROFILE_DIR

PORT = 8765
ALLOWED_ORIGIN = "https://mlovewho7-afk.github.io"
ALLOWED_URL_PREFIX = "https://www.bloomberg.com/"

_playwright = None
_context = None
_page = None


def _ensure_browser():
    global _playwright, _context, _page
    if _page is not None:
        return
    BROWSER_PROFILE_DIR.parent.mkdir(parents=True, exist_ok=True)
    _playwright = sync_playwright().start()
    _context = _playwright.chromium.launch_persistent_context(
        str(BROWSER_PROFILE_DIR),
        headless=False,
        channel="chrome",
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )
    _page = _context.new_page()


def _capture(url: str) -> bytes:
    _ensure_browser()
    _page.goto(url, wait_until="domcontentloaded", timeout=30000)
    _page.wait_for_timeout(3000)
    el = _page.query_selector("article")
    if el is not None:
        return el.screenshot()
    return _page.screenshot(full_page=True)


class Handler(BaseHTTPRequestHandler):
    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/capture":
            self.send_response(404)
            self._cors_headers()
            self.end_headers()
            return

        qs = urllib.parse.parse_qs(parsed.query)
        url = (qs.get("url") or [""])[0]
        if not url.startswith(ALLOWED_URL_PREFIX):
            self.send_response(400)
            self._cors_headers()
            self.end_headers()
            self.wfile.write(b"invalid url")
            return

        try:
            image_bytes = _capture(url)
        except Exception as e:
            print(f"[capture_server] 캐처 실패: {e!r}")
            self.send_response(500)
            self._cors_headers()
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))
            return

        self.send_response(200)
        self._cors_headers()
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(image_bytes)))
        self.end_headers()
        self.wfile.write(image_bytes)

    def log_message(self, format, *args):
        print(f"[capture_server] {format % args}")


def run_login() -> None:
    BROWSER_PROFILE_DIR.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(BROWSER_PROFILE_DIR),
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        page = ctx.new_page()
        page.goto("https://www.bloomberg.com/account/login", wait_until="domcontentloaded")
        print("브라우저에서 블룸버그 계정으로 로그인한 뒤, 이 터미널에서 Enter를 누르세요.")
        input()
        ctx.close()


if __name__ == "__main__":
    if "--login" in sys.argv:
        run_login()
    else:
        server = HTTPServer(("localhost", PORT), Handler)
        print(f"[capture_server] http://localhost:{PORT} 에서 대기 중 (Ctrl+C로 종료)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            if _context is not None:
                _context.close()
            if _playwright is not None:
                _playwright.stop()
