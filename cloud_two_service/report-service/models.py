from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime


class Violation(BaseModel):
    id: str
    tesis_id: str
    kamera_id: str
    ihlal_tipi: str                    # "ppe_ihlali", "yangin", "yasak_bolge", "ramak_kala"
    ihlal_alt_tipi: Optional[str] = None  # "eldivensiz_calisma", "baretsiz" vb.
    bolge: str                         # "Hat-3 Bükme İstasyonu"
    guven_skoru: float
    frame_url: Optional[str] = None    # GCS URL (fotoğraf)
    aciklama: Optional[str] = None     # VLM açıklaması
    tespit_zamani: datetime
    vardiya: str                       # "1", "2", "3"


class ViolationGroup(BaseModel):
    bolge: str
    ihlal_tipi: str
    ihlal_alt_tipi: Optional[str] = None
    adet: int
    zamanlar: List[str]
    frame_urls: List[str]
    aciklamalar: List[str]
    rag_context: Optional[Dict] = None  # RAG'dan gelen mevzuat + bağlam


class ReportRequest(BaseModel):
    tesis_id: str
    tesis_adi: str
    tesis_adresi: Optional[str] = None
    vardiya: str                        # "1", "2", "3"
    vardiya_baslangic: datetime
    vardiya_bitis: datetime
    sorumlu_isg_uzmani: Optional[str] = None
    violations: List[Violation]


class ReportResponse(BaseModel):
    rapor_id: str
    tesis_id: str
    vardiya: str
    toplam_ihlal: int
    kritik_ihlal: int
    rapor_metni: str                    # LLM'in ürettiği Türkçe rapor
    pdf_url: Optional[str] = None      # GCS'e kaydedilen PDF
    artifact_url: Optional[str] = None  # Cloud'da saklanan JSON/PDF çıktısı
    olusturma_zamani: datetime


class QueuedReportSubmitResponse(BaseModel):
    job_id: str
    status: str
    message: str


class QueuedReportStatusResponse(BaseModel):
    job_id: str
    status: str
    message: Optional[str] = None
    result: Optional[ReportResponse] = None
    error: Optional[str] = None


class QueuedReportListItem(BaseModel):
    job_id: str
    status: str
    message: Optional[str] = None
    tesis_id: str
    tesis_adi: str
    vardiya: str
    toplam_ihlal: int
    created_at: datetime
    updated_at: datetime


class QueuedReportListResponse(BaseModel):
    total: int
    items: List[QueuedReportListItem]


class QueuedReportDeleteResponse(BaseModel):
    job_id: str
    deleted: bool
    message: str