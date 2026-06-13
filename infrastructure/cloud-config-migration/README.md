# Cloud Camera Config Migration

Bu migration, Edge Agent'in kamera secimi icin kullandigi
`edge_camera_configs` tablosunu Cloud SQL PostgreSQL uzerinde olusturur.
Ornek olarak PPE, yangin ve iki analizi birlikte calistiran uc kamera kaydi
ekler.

```powershell
$env:DB_URL = "postgresql://USER:PASSWORD@HOST:5432/DATABASE"
python .\migrate.py
```

Production ortaminda ornek UUID, kamera yolu ve kurum alanlarini gercek
envanterle degistirin. RTSP parolalari veritabanina yazilmaz; `credential_key`
ile Edge cihazindaki yerel secret'a referans verilir.
