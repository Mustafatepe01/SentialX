# SentialX Frame Worker

Bu servis `sentialx-frames` Pub/Sub mesajlarini alir ve kareleri GCS'den
indirir. Once PPE/yangin detection calisir.

- Ihlal yoksa VLM ve LLM cagrilmaz; event klasorundeki gorseller ile
  `meta.json` hemen silinir.
- Yangin ihlali varsa gorseller korunur, VLM cevre/risk analizi yapar ve
  sonuc `sentialx-report` servisine giderek RAG + LLM raporu olusturur.
- Yalnizca PPE ihlali varsa olay vardiya raporu icin kuyruklanir; mevcut
  kod bu kolda VLM cagirmaz.
- Sonuclar ve silme denetim bilgileri Cloud SQL `frame_events` tablosuna yazilir.

## Uclar

- `GET /health`: servis ve veritabani saglik kontrolu
- `GET /edge/config/{edge_device_id}`: aktif kamera ayarlarini Edge Agent'a
  dondurur
- `POST /pubsub/frame`: kimlik dogrulamali Pub/Sub push hedefi

## Model Yonlendirme

Pub/Sub olayindaki `analysis_types`, hangi private Cloud Run model servisinin
cagrilacagini belirler. PPE ve yangin sonuclari ayri tutulur. Yangin ihlali
varsa VLM ve rapor islemlerinden once `fire-alerts` topic'ine anlik alarm
yayinlanir; PPE ihlalleri ise vardiya raporlamasi icin gruplanir. Yangin
kolunda VLM ve rapor servisleri ihlal baglami olusturur. Supabase aktarimi
yapilandirilmissa ihlal kaydi ayrica Edge Function'a gonderilir.

Yerel ayarlar icin `.env.example` dosyasini kopyalayin. Secret degerlerini
Git'e eklemeyin.

## Guvenilirlik

- `event_id` veritabaninda birincil anahtardir.
- Tamamlanmis event tekrar gelirse analiz yinelenmeden onaylanir.
- Islem hatasi HTTP 500 dondurur; Pub/Sub tekrar dener.
- Kalici hatalar dead-letter topic'e aktarilir.
- Yangin tespitinde `fire-alerts` topic'ine ayri alarm mesaji gonderilir.
- Temiz eventlerde `images_deleted_at` ve `image_deletion_duration_ms`
  alanlari veri minimizasyonunun gerceklestigini kaydeder.
