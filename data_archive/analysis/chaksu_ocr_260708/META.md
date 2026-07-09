# META — 착수보고 OCR 전문
- 원본: documents/260623 핵심광물 수급위기 진단모델 구축_착수보고 ver1.pdf (39p)
- 문제: 임베딩 폰트의 유니코드 매핑 파손 — pypdf/PyMuPDF 모두 한글이 "기기"로 추출됨(유효비율 ~20%)
- 생성: 2026-07-08, PyMuPDF 180dpi 렌더 → easyocr(ko+en, CPU) 페이지별 OCR
- 용도: mineral_risk_model_v1.md 작성의 원문 근거. 표·숫자 일부 오독 있음(구조 파악용, 인용 시 원본 대조 권장)
