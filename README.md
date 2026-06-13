# SentialX

SentialX, is sagligi ve guvenligi olaylarini goruntu analizi, RAG ve
otomatik raporlama ile islemek icin gelistirilen bir prototiptir.

## Bu Deponun Kapsami

Bu calisma kopyasi su anda yalnizca iki calistirilabilir cloud servisini
icerir:

- `cloud_two_service/rag-service`: PageIndex tabanli ISG baglami uretir.
- `cloud_two_service/report-service`: Ihlalleri gruplar ve JSON/PDF raporu
  uretir.

Canli sistemde kullanilan Edge Agent, frame worker, bildirim servisi,
Supabase function ve PPE/yangin/VLM model servislerinin guncel kaynaklari bu
depoda bulunmamaktadir. Bu nedenle mevcut depo tek basina tum SentialX
sistemini yeniden kurmaz.

## Hizli Baslangic

Python 3.11 onerilir. Her servisi ayri sanal ortamda calistirin.

```powershell
cd cloud_two_service\report-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python mock_example.py
```

RAG servisi:

```powershell
cd cloud_two_service\rag-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn main:app --host 127.0.0.1 --port 8083
```

## Test

```powershell
python -m unittest discover -s tests -v
python -m compileall -q cloud_two_service
```

## Cloud Run Dagitimi

```powershell
cd cloud_two_service
.\deploy_two_services.ps1 `
  -ProjectId "YOUR_GCP_PROJECT_ID" `
  -ReportBucket "YOUR_REPORT_BUCKET"
```

Gercek API anahtarlarini, servis hesabi dosyalarini, `.env` dosyalarini veya
kamera parolalarini Git'e eklemeyin. Ayrintilar icin
`cloud_two_service/README.md` dosyasina bakin.

## Bilinen Sinirlar

- Kuyruk endpoint'leri `QUEUE_BACKEND=file` ile Cloud Run uzerinde kalici
  degildir; uretimde Redis veya yonetilen bir kuyruk kullanilmalidir.
- GCS artifact adresleri `gs://` bicimindedir ve tarayicida dogrudan acilmaz.
- RAG ve rapor kalitesi harici LLM kotasina ve yanitlarina baglidir.
- Depo icin henuz bir acik kaynak lisansi secilmemistir.

