import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime
import logging
import uuid

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from models import (
    ReportRequest,
    ReportResponse,
    QueuedReportSubmitResponse,
    QueuedReportStatusResponse,
    QueuedReportListItem,
    QueuedReportListResponse,
    QueuedReportDeleteResponse,
)
from report import create_report
from pdf import create_pdf
from queue_store import build_queue_store
from cloud_artifacts import build_artifact_store
from config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
QUEUE_STATE_FILE = Path(__file__).with_name("queue_state.json")


def _report_artifact_payload(request: ReportRequest, report_response: ReportResponse) -> dict:
    request_data = request.model_dump(mode="json")
    return {
        "rapor": report_response.model_dump(mode="json"),
        "tesis": {
            "tesis_id": request_data["tesis_id"],
            "tesis_adi": request_data["tesis_adi"],
            "tesis_adresi": request_data["tesis_adresi"],
            "vardiya": request_data["vardiya"],
            "vardiya_baslangic": request_data["vardiya_baslangic"],
            "vardiya_bitis": request_data["vardiya_bitis"],
            "sorumlu_isg_uzmani": request_data["sorumlu_isg_uzmani"],
        },
        "olusturma_zamani": datetime.now().isoformat(),
    }


def _queue_artifact_name(job_id: str, suffix: str) -> str:
    return f"queue/{job_id}/{suffix}"


async def queue_worker(app: FastAPI):
    store = app.state.queue_store
    artifact_store = app.state.artifact_store
    while True:
        job_id = await store.next_job_id()

        if not job_id:
            await asyncio.sleep(0.25)
            continue

        job = await store.get_job(job_id)
        if not job or job.get("status") == "deleted":
            continue

        await store.mark_processing(job_id)

        try:
            request: ReportRequest = job["request"]
            rapor_id = str(uuid.uuid4())
            result = await create_report(request)

            report_response = ReportResponse(
                rapor_id=rapor_id,
                tesis_id=request.tesis_id,
                vardiya=request.vardiya,
                toplam_ihlal=result["toplam_ihlal"],
                kritik_ihlal=result["kritik_ihlal"],
                rapor_metni=result["rapor_metni"],
                pdf_url=None,
                olusturma_zamani=datetime.now(),
            )

            if artifact_store is not None:
                artifact_url = await artifact_store.upload_json(
                    artifact_store.object_name(_queue_artifact_name(job_id, "report.json")),
                    _report_artifact_payload(request, report_response),
                )
                report_response.artifact_url = artifact_url

            await store.mark_completed(job_id, report_response)
            logger.info(f"Kuyruk işi tamamlandı: {job_id}")
        except Exception as exc:
            await store.mark_failed(job_id, str(exc))
            logger.error(f"Kuyruk işi hatası ({job_id}): {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Raporlama servisi başlatılıyor...")
    app.state.artifact_store = None
    if config.GCS_ENABLED:
        app.state.artifact_store = await build_artifact_store(
            bucket_name=config.GCS_BUCKET,
            prefix=config.REDIS_QUEUE_PREFIX,
        )
    app.state.queue_store = await build_queue_store(
        queue_backend=config.QUEUE_BACKEND,
        redis_url=config.REDIS_URL,
        state_file=QUEUE_STATE_FILE,
        redis_prefix=config.REDIS_QUEUE_PREFIX,
    )
    app.state.queue_worker_task = asyncio.create_task(queue_worker(app))
    yield
    app.state.queue_worker_task.cancel()
    with suppress(asyncio.CancelledError):
        await app.state.queue_worker_task
    if app.state.artifact_store is not None:
        await app.state.artifact_store.close()
    await app.state.queue_store.close()
    logger.info("Raporlama servisi kapatılıyor...")


app = FastAPI(
    title="SentialX Report Service",
    description="İSG vardiya raporu oluşturma servisi",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "report",
        "queue_backend": app.state.queue_store.backend_name,
        "artifact_backend": getattr(app.state.artifact_store, "backend_name", "none"),
    }


@app.post("/report/queue", response_model=QueuedReportSubmitResponse, status_code=202)
async def queue_report(request: ReportRequest):
    """
    Rapor isteğini kuyruğa alır ve işlenme durumunu job_id ile döner.
    """
    if not request.violations:
        raise HTTPException(status_code=400, detail="İhlal listesi boş")

    job_id = await app.state.queue_store.submit(request)

    return QueuedReportSubmitResponse(
        job_id=job_id,
        status="queued",
        message="Rapor kuyruğa alındı, sonucu /report/queue/{job_id} adresinden izleyebilirsiniz.",
    )


@app.get("/report/queue", response_model=QueuedReportListResponse)
async def list_queued_reports():
    jobs = await app.state.queue_store.list_jobs()
    items = [
        QueuedReportListItem(
            job_id=job["job_id"],
            status=job["status"],
            message=job.get("message"),
            tesis_id=job["request"].tesis_id,
            tesis_adi=job["request"].tesis_adi,
            vardiya=job["request"].vardiya,
            toplam_ihlal=len(job["request"].violations),
            created_at=job["created_at"],
            updated_at=job["updated_at"],
        )
        for job in jobs
    ]

    return QueuedReportListResponse(total=len(items), items=items)


@app.get("/report/queue/{job_id}", response_model=QueuedReportStatusResponse)
async def get_queued_report(job_id: str):
    job = await app.state.queue_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="İş bulunamadı")

    if job.get("status") == "deleted":
        raise HTTPException(status_code=404, detail="İş bulunamadı")

    return QueuedReportStatusResponse(
        job_id=job_id,
        status=job["status"],
        message=job.get("message"),
        result=job.get("result"),
        error=job.get("error"),
    )


@app.delete("/report/queue/{job_id}", response_model=QueuedReportDeleteResponse)
async def delete_queued_report(job_id: str):
    job = await app.state.queue_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="İş bulunamadı")

    await app.state.queue_store.delete_job(job_id)

    if job.get("status") == "processing":
        return QueuedReportDeleteResponse(
            job_id=job_id,
            deleted=True,
            message="İş liste dışına alındı. Çalışan iş hemen durdurulamaz, ama sonuç kaydedilmez.",
        )

    return QueuedReportDeleteResponse(
        job_id=job_id,
        deleted=True,
        message="İş silindi",
    )


@app.post("/report", response_model=ReportResponse)
async def generate_report(request: ReportRequest):
    """
    Vardiya ihlallerini alıp Türkçe İSG raporu üretir.
    """
    if not request.violations:
        raise HTTPException(status_code=400, detail="İhlal listesi boş")

    try:
        rapor_id = str(uuid.uuid4())
        logger.info(f"Rapor oluşturuluyor: {rapor_id} | Tesis: {request.tesis_adi}")

        # Rapor üret
        result = await create_report(request)

        report_response = ReportResponse(
            rapor_id=rapor_id,
            tesis_id=request.tesis_id,
            vardiya=request.vardiya,
            toplam_ihlal=result["toplam_ihlal"],
            kritik_ihlal=result["kritik_ihlal"],
            rapor_metni=result["rapor_metni"],
            pdf_url=None,
            olusturma_zamani=datetime.now(),
        )

        if app.state.artifact_store is not None:
            artifact_url = await app.state.artifact_store.upload_json(
                app.state.artifact_store.object_name("reports", rapor_id, "report.json"),
                _report_artifact_payload(request, report_response),
            )
            report_response.artifact_url = artifact_url

        return report_response

    except Exception:
        logger.exception("Rapor oluşturulamadı")
        raise HTTPException(status_code=500, detail="Rapor oluşturulamadı")


@app.post("/report/pdf")
async def generate_report_pdf(request: ReportRequest):
    """
    Vardiya ihlallerini alıp PDF raporu döner.
    """
    if not request.violations:
        raise HTTPException(status_code=400, detail="İhlal listesi boş")

    try:
        rapor_id = str(uuid.uuid4())
        logger.info(f"PDF raporu oluşturuluyor: {rapor_id}")

        # Rapor üret
        result = await create_report(request)

        # PDF oluştur
        pdf_bytes = create_pdf(
            request=request,
            groups=result["groups"],
            rapor_metni=result["rapor_metni"],
            rapor_id=rapor_id
        )

        dosya_adi = f"sentialx_rapor_{request.tesis_id}_{request.vardiya}_{rapor_id[:8]}.pdf"
        cloud_url = None
        if app.state.artifact_store is not None:
            cloud_url = await app.state.artifact_store.upload_pdf(
                app.state.artifact_store.object_name("reports", rapor_id, "report.pdf"),
                pdf_bytes,
            )

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={dosya_adi}",
                **({"X-Cloud-Url": cloud_url} if cloud_url else {}),
            }
        )

    except Exception:
        logger.exception("PDF raporu oluşturulamadı")
        raise HTTPException(status_code=500, detail="PDF raporu oluşturulamadı")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)
