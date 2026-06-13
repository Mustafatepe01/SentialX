import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # LLM
    MODEL = os.getenv("LLM_MODEL", "gemini/gemini-3-flash-preview")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "")

    @property
    def llm_api_key(self) -> str:
        return self.GEMINI_API_KEY or self.OPENROUTER_API_KEY or self.OPENAI_API_KEY

    # PageIndex JSON path
    INDEX_PATH = os.getenv("INDEX_PATH", "data/sentialx_isg_kaynak_url_fixed_structure.json")

    # Servis
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 8080))

config = Config()
