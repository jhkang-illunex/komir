# -*- coding: utf-8 -*-
"""report_gen 서비스 앱 패키지(uvicorn `app.main:app`).

- `generator.py` — 템플릿×정형데이터 조립 → `out_report` 적재(실동작 경로)
- `scheduler.py` — `REPORT_SCHEDULE_CRON` 주기 실행
- `analysis/` — 외부repo komis-report-generator-main의 `analysis/` 이식본
- `_bootstrap.py` — `services/shared/*` import 경로 해결(소스트리·컨테이너 공용)
"""
