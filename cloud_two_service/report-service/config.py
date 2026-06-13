import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Mock/offline demo modu
    MOCK_MODE = os.getenv("MOCK_MODE", "1").lower() in {"1", "true", "yes", "on"}

    # Gemini (rapor yazımı için)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini/gemini-3-flash-preview")

    # RAG servisi URL
    RAG_SERVICE_URL = os.getenv("RAG_SERVICE_URL", "http://localhost:8083")
    RAG_AUTH_MODE = os.getenv("RAG_AUTH_MODE", "none").lower()

    # GCS (PDF arşiv)
    GCS_BUCKET = os.getenv("GCS_BUCKET", "sentialx-reports")
    GCS_ENABLED = os.getenv("GCS_ENABLED", "0").lower() in {"1", "true", "yes", "on"}

    # Kuyruk arka planı
    QUEUE_BACKEND = os.getenv("QUEUE_BACKEND", "auto")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_QUEUE_PREFIX = os.getenv("REDIS_QUEUE_PREFIX", "sentialx:report")

    # Servis
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 8084))

    # Vardiya saatleri
    VARDIYA_SAATLERI = {
        "1": {"baslangic": "00:00", "bitis": "08:00", "ad": "Gece Vardiyası"},
        "2": {"baslangic": "08:00", "bitis": "16:00", "ad": "Sabah Vardiyası"},
        "3": {"baslangic": "16:00", "bitis": "24:00", "ad": "Öğle Vardiyası"},
    }

config = Config()
