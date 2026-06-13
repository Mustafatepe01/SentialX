# SentialX Edge Agent

Akis:

```text
RTSP -> hareket/periyot -> en iyi 3 kare -> yuz bulaniklastirma -> outbox
     -> GCS -> Pub/Sub -> cloud worker
```

## Kurulum

```powershell
Copy-Item settings.example.json settings.json
Copy-Item cameras.example.json cameras.json
Copy-Item secrets.local.example.json secrets.local.json
.\install.ps1
```

`settings.json` cloud hedeflerini, `secrets.local.json` RTSP parolasini
tutar. Bu dosyalar Git tarafindan yok sayilir. `cameras.json`, cloud
yapilandirma API'sinden alinan son basarili cevabin offline onbellegidir;
ilk yerel test icin `cameras.example.json` kopyalanabilir.

## Saglik kontrolu

```powershell
.\.venv\Scripts\python.exe .\health_check.py
```

## Calistirma

```powershell
.\.venv\Scripts\python.exe .\main.py
```

Kamera ayarlari private Cloud Run API uzerinden Cloud SQL'den alinir.
`cameras.json` yalnizca son basarili ayarlarin offline onbellegidir.
RTSP parolasi Git tarafindan yok sayilan `secrets.local.json` icindedir.

Cloud baglantisi kesilirse olay paketleri `buffer/outbox` altinda bekler.
Baglanti geri geldiginde GCS ve Pub/Sub gonderimi otomatik yeniden denenir.

## Kamera ve Model Secimi

Her kamera kaydinda `analysis_types` listesi vardir. Ornegin `["ppe"]`
yalnizca PPE servisini, `["fire"]` yalnizca yangin servisini,
`["ppe", "fire"]` ise iki modeli de calistirir. `policy_map`, model
sonucunun Supabase politika kimligine eslenmesini saglar.

`motion` modunda MOG2 hareket maskesi ile bes saniyelik varsayilan olay
penceresi acilir ve hareket puani en yuksek uc kare secilir. `interval`
modunda belirlenen aralikla tek kare alinir. Her iki modda da Haar Cascade
ile bulunan yuzler cloud'a gonderilmeden once Gaussian blur ile
bulaniklastirilir.
