from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from models import RAGRequest, RAGResponse
from rag import load_tree, query_rag
from config import config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global tree ve node_map
tree = None
node_map = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global tree, node_map
    logger.info(f"PageIndex yükleniyor: {config.INDEX_PATH}")
    tree, node_map = load_tree(config.INDEX_PATH)
    logger.info(f"PageIndex yüklendi. Node sayısı: {len(node_map)}")
    yield
    logger.info("Servis kapatılıyor...")


app = FastAPI(
    title="SentialX RAG Service",
    description="İSG ihlalleri için mevzuat ve teknik bağlam sağlayan RAG servisi",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "node_count": len(node_map) if node_map else 0
    }


@app.post("/query", response_model=RAGResponse)
async def query(request: RAGRequest):
    if tree is None or node_map is None:
        raise HTTPException(status_code=503, detail="PageIndex henüz yüklenmedi")

    try:
        result = await query_rag(
            violation_type=request.violation_type,
            violation_subtype=request.violation_subtype,
            process=request.process,
            zone=request.zone,
            description=request.description,
            tree=tree,
            node_map=node_map
        )
        return RAGResponse(**result)

    except Exception:
        logger.exception("RAG sorgusu işlenemedi")
        raise HTTPException(status_code=500, detail="RAG sorgusu işlenemedi")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)
