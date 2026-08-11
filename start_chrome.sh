#!/bin/bash
# 크롬을 계속 켜둔 채로 재사용하기 위한 런처. digest.py는 이 크롬에 CDP로 붙어서
# 작업한다(2026-08-12, "매번 새 창을 여니까 차단이 걸리는 것 아니냐"는 사용자 추측으로
# 시도) — 매번 launch_persistent_context()로 새 프로세스를 띄우는 대신, 하나의 지속
# 세션을 계속 재사용하면 PerimeterX가 덜 의심할 수도 있다는 가설.
cd "$(dirname "$0")"
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9333 \
  --user-data-dir="$(pwd)/data/browser_profile" \
  --disable-blink-features=AutomationControlled \
  --no-first-run \
  --no-default-browser-check \
  about:blank
