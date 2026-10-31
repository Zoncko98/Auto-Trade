FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py paper_engine.py risk_controls.py ai_review.py dashboard_control.py cloud_models.py schwab_gateway.py ./

RUN mkdir -p /logs /state

CMD ["python", "-u", "/app/bot.py"]
