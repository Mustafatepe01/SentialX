# SentialX

SentialX, is sagligi ve guvenligi olaylarini goruntu analizi, RAG ve
otomatik raporlama ile islemek icin gelistirilen bir prototiptir.

## Sistem Mimarisi

```text
Kamera / RTSP simulasyonu
          |
          v
Edge Agent (FFmpeg + MOG2 + Haar Cascade)
          |
          | en iyi 3 kare / olay
          v
GCS + Pub/Sub -> Frame Worker
                     |
                     +-> PPE modeli
                     +-> Yangin modeli -> anlik fire-alerts alarmi -> VLM
                     +-> PageIndex RAG -> Rapor LLM -> JSON/PDF
                     +-> Supabase violations tablosu
```

Her kameranin `analysis_types` alani, karenin PPE, yangin veya iki modele
birden yonlendirilmesini belirler. Edge Agent hareket modunda MOG2 ile olay
penceresi acar, puani en yuksek uc kareyi secer, Haar Cascade ile bulunan
yuzleri bulaniklastirir ve yerel outbox'a yazar. Baglanti varsa kareler
GCS'ye yuklenir ve olay Pub/Sub'a gonderilir; baglanti kesilirse paketler
yeniden denemek uzere yerelde tutulur. Frame Worker ilgili model servislerini
cagirir; yangin ihlalinde VLM ve rapor islemlerini beklemeden ayri alarm
mesaji yayinlar. Mevcut kod VLM'yi yangin kolunda kullanir; yalnizca PPE
ihlalleri vardiya raporu icin kuyruklanir.

## Depo Yapisi

- `edge/agent`: RTSP okuma, MOG2 hareket secimi, uc kare secimi, yuz
  bulaniklastirma, offline outbox ve cloud gonderimi.
- `edge/camera-simulator`: FFmpeg ve MediaMTX ile yerel RTSP test akislari.
- `cloud/frame-worker`: Kamera yapilandirma API'si ve olay orkestrasyonu.
- `cloud/fire-notifier`: Yangin alarmlarini alan Pub/Sub push servisi.
- `cloud_two_service/rag-service`: PageIndex tabanli ISG baglami.
- `cloud_two_service/report-service`: JSON/PDF vardiya raporu.
- `supabase/functions/violations-ingest`: Dogrulanmis ihlal kaydi Edge
  Function'i.
- `infrastructure/cloud-config-migration`: Cloud SQL kamera yapilandirma
  semasi ve ornek veriler.
- `docs/MODEL_CARDS.md`: Model sorumluluklari ve bilinen sinirlar.

PPE, yangin ve VLM servislerinin cagrilma akisi repoda yer alir; ancak bu
uc model servisinin agirliklari ve servis kaynak kodlari bu kopyada yoktur.
Bu nedenle model endpoint'leri ayrica saglanmalidir.

## Hizli Baslangic

Python 3.11 ve FFmpeg onerilir. Edge Agent kurulumu:

```powershell
cd edge\agent
Copy-Item settings.example.json settings.json
Copy-Item cameras.example.json cameras.json
Copy-Item secrets.local.example.json secrets.local.json
.\install.ps1
.\.venv\Scripts\python.exe .\health_check.py
.\.venv\Scripts\python.exe .\main.py
```

Kamera simulasyonu icin
[`edge/camera-simulator/README.md`](edge/camera-simulator/README.md)
dosyasina bakin.

Rapor servisi:

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
python -m compileall -q edge cloud cloud_two_service infrastructure
```

## Cloud Run Dagitimi

RAG ve rapor servisleri:

```powershell
cd cloud_two_service
.\deploy_two_services.ps1 `
  -ProjectId "YOUR_GCP_PROJECT_ID" `
  -ReportBucket "YOUR_REPORT_BUCKET"
```

Frame Worker ve yangin bildirimi:

```powershell
cd cloud
.\deploy_frame_worker.ps1 `
  -ProjectId "YOUR_GCP_PROJECT_ID" `
  -FrameBucket "YOUR_FRAME_BUCKET"
.\deploy_fire_notifier.ps1 -ProjectId "YOUR_GCP_PROJECT_ID"
```

Gercek API anahtarlarini, servis hesabi dosyalarini, `.env` dosyalarini veya
kamera parolalarini Git'e eklemeyin. Ayrintilar icin
`cloud_two_service/README.md` dosyasina bakin.

## Model Bilgileri

PPE, yangin, VLM, PageIndex RAG ve rapor LLM bilesenlerinin gorevleri,
dogrulanabilen yapilandirmalari ve bilinen sinirlari
[`docs/MODEL_CARDS.md`](docs/MODEL_CARDS.md) dosyasinda belgelenmistir.
Olculmemis model basari ve performans degerleri bu belgeye eklenmemistir.

## Bilinen Sinirlar

- PPE, yangin ve VLM model servisleri ile model agirliklari bu depoda yoktur.
- Kamera simulasyonunda kullanilan video dosyalari ve MediaMTX binary'si
  boyut ve lisans nedenleriyle Git'e eklenmez.
- Kuyruk endpoint'leri `QUEUE_BACKEND=file` ile Cloud Run uzerinde kalici
  degildir; uretimde Redis veya yonetilen bir kuyruk kullanilmalidir.
- GCS artifact adresleri `gs://` bicimindedir ve tarayicida dogrudan acilmaz.
- RAG ve rapor kalitesi harici LLM kotasina ve yanitlarina baglidir.
- Depo icin henuz bir acik kaynak lisansi secilmemistir.
