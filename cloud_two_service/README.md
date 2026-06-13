# SentialX Iki Servisli Cloud Run Dagitimi

Bu paket iki ozel Cloud Run servisi kurar:

1. `sentialx-rag`: PageIndex agacini yukler ve Gemini 3 Flash Preview ile
   mevzuat baglami uretir.
2. `sentialx-report`: Ihlalleri gruplar, RAG servisini OIDC ile cagirir ve
   Turkce rapor/PDF uretir.

## Guvenlik

- Iki servis de anonim erisime kapalidir.
- Yalniz `sentialx-report-runtime` servis hesabi RAG servisini cagirabilir.
- Gemini anahtari Secret Manager'dan gelir.
- Rapor servisi GCS bucket'a servis hesabi ile yazar.

## Dagitim

PowerShell:

```powershell
cd .\cloud_two_service
.\deploy_two_services.ps1 `
  -ProjectId "YOUR_GCP_PROJECT_ID" `
  -ReportBucket "YOUR_REPORT_BUCKET"
```

Docker veya yerel Terraform gerekmez. `gcloud run deploy --source .` Cloud
Build kullanir.

Dagitimdan once `gcloud auth login` ile oturum acildigini, Gemini secret'inin
ve rapor bucket'inin mevcut oldugunu kontrol edin.

## Sunum Oncesi Hizli Kontrol

Yerel offline rapor demosu varsayilan olarak `MOCK_MODE=1` ile calisir:

```powershell
cd .\report-service
python .\mock_example.py
```

RAG servisi baslatildiginda `/health` yanitindaki `node_count` degeri 234
olmalidir.

## Kaynak Ayarlari

Her iki servis:

- `min-instances=0`
- `max-instances=2`
- `1 CPU`
- `1 GiB RAM`
- `300 saniye timeout`

Bu ayarlar okul projesinde bos durum maliyetini dusuk tutar.

## Kuyruk Notu

`QUEUE_BACKEND=file`, Cloud Run'in gecici dosya sistemini kullanir. Bu nedenle
`/report` ve `/report/pdf` kullanilmalidir. Kalici asenkron kuyruk gerektiginde
Cloud Tasks veya Redis eklenmelidir.
