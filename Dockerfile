FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# src/는 prompt.prompt, utils.doc_preprocessing 임포트에 필요
COPY src/ ./src/
COPY app/ ./app/

# src/ 하위 모듈을 직접 임포트할 수 있도록 PYTHONPATH에 추가
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
