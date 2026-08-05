FROM python:3.12-slim

# hwp/olefile 등에 필요한 최소 시스템 라이브러리
RUN apt-get update && apt-get install -y --no-install-recommends libxml2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 코드만 이미지에(데이터·비밀은 볼륨/env)
COPY . /app/geo/
ENV GEO_DATA=/data \
    PYTHONUNBUFFERED=1

# 상태는 전부 /data 볼륨. 3스테이지를 argv로 디스패치.
ENTRYPOINT ["python", "-m", "geo"]
CMD ["--help"]
