@echo off
REM ===== mineral_supply_risk 윈도우 초기 설정/실행 =====
where python >nul 2>nul || (echo [오류] Python이 설치/PATH에 없습니다 & exit /b 1)
if not exist .venv (
  echo [1/3] 가상환경 생성...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
echo [2/3] 패키지 설치...
pip install -r requirements.txt
echo [3/3] 완료. 사용 예:
echo    python -m scripts.run collect-ecos
echo    python -m scripts.run collect-customs 201301 202512
echo    python -m scripts.run features
