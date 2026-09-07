FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libxml2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt sqlalchemy openpyxl
COPY . /app/
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
# 서비스별 command로 스테이지 지정 (예: -m scripts.run features / -m scripts.train)
ENTRYPOINT ["python"]
CMD ["-m", "scripts.run", "all"]
