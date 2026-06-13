FROM python:3.11-slim

# WeasyPrint için sistem bağımlılıkları
RUN apt-get update && apt-get install -y \
    fonts-dejavu-core \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libffi-dev \
    libjpeg-dev \
    libopenjp2-7 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8084

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8084}"]