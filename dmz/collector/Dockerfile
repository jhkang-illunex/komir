# komir 수집기 — 분석기(geo)와 별도 서버에서 단독 실행
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app/collector/
ENV COLLECT_OUT=/data
VOLUME /data
CMD ["python", "-m", "collector", "daemon", "--interval-mins", "60"]
