FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tools/ tools/
RUN mkdir -p .tmp

CMD ["python", "tools/mirror_bot.py"]
