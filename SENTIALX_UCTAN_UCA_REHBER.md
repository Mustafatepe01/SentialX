# SentialX Uctan Uca Teknik ve Kullanim Rehberi

Degerlendirme tarihi: 11 Haziran 2026

Bu belge, SentialX'in neden var oldugunu, hangi bilesenlerden olustugunu,
yerelde ve Google Cloud tarafinda nasil calistigini, nasil kurulacagini,
verinin sistemde nasil ilerledigini ve mevcut projede hangi kisimlarin
tamamlanmis veya eksik oldugunu aciklar.

## 1. SentialX Nedir?

SentialX, fabrika ve agir sanayi ortamlarindaki kamera goruntulerini kullanarak
is sagligi ve guvenligi olaylarini otomatik izlemeyi hedefleyen bir sistemdir.

Temel hedefleri:

1. Bir insanin tum kameralari surekli izlemesi ihtiyacini azaltmak.
2. Baret, eldiven ve diger KKD ihlallerini tespit etmek.
3. Yangin veya acik alev gibi kritik durumlari erken fark etmek.
4. Olay anindan en anlamli goruntu karelerini secmek.
5. Kisisel veriyi azaltmak icin yuzleri edge cihazinda bulaniklastirmak.
6. Internet kesilse bile olay paketini kaybetmemek.
7. Ihlali mevzuat ve teknik dokumanlarla zenginlestirmek.
8. Vardiya bazli Turkce rapor ve PDF uretmek.
9. Yangin gibi kritik olaylarda alarm olusturmak.

Sistem su anda tek parca, tamamlanmis bir ticari urun degildir. Calisan
prototipler, yerel demo otomasyonu ve bulut servisleri vardir; ancak tum
bilesenlerin tek depoda, tek surumde ve eksiksiz test edilen bir urun olarak
birlesmesi henuz tamamlanmamistir.

## 2. Projedeki Kopyalar

Bu makinede iki onemli konum vardir:

### 2.1 Calisma alani

```text
<REPO_ROOT>
```

Burada:

- `cloud_two_service`: RAG ve rapor servislerinin calisabilir kopyasi.
- `staging`: Birlesik proje aciklamasi ve durum raporu.
- `SENTIALX_SUNUM_TEST_REHBERI.md`: Yerel sunum kullanim rehberi.

### 2.2 Yerel demo ve birlesik arsiv

```text
<SENTIALX_WORKSPACE>
```

Burada:

- Yerel RTSP demo otomasyonu.
- Edge Agent.
- MediaMTX.
- Test videolari.
- Kamera yonetim scriptleri.
- `workspace` altinda eski ve yeni servislerin birlesik kopyalari.

Not: Windows Turkce klasor adini ekranda `Masaustu` veya `Masaüstü` olarak
gosterebilir.

## 3. Genel Mimari

Hedeflenen uctan uca akis:

```text
IP Kamera veya Test Videosu
          |
          v
MediaMTX RTSP Sunucusu
          |
          v
Edge Agent
  - kamera okuma
  - hareket/periyot/surekli secim
  - yuz bulaniklastirma
  - en anlamli kareleri secme
  - kalici outbox
          |
          +----> Google Cloud Storage
          |
          +----> Pub/Sub: sentialx-frames
                         |
                         v
                 Frame Worker
                 - PPE analizi
                 - yangin analizi
                         |
             +-----------+-----------+
             |                       |
          ihlal yok                ihlal var
             |                       |
      goruntuleri sil          VLM aciklamasi
                                     |
                                     v
                               Report Service
                                     |
                                     v
                                RAG Service
                                     |
                                     v
                          Turkce rapor / PDF / GCS
                                     |
                                     v
                                  Cloud SQL

Yangin varsa ek olarak:

Frame Worker -> fire-alerts -> Fire Notifier -> kritik log/e-posta alarmi
```

## 4. Yerel Demo Katmani

### 4.1 MediaMTX

MediaMTX, RTSP yayini alan ve istemcilere dagitan sunucudur.

Ana dosyalar:

```text
rtsp\mediamtx.exe
rtsp\mediamtx.yml
```

Kullanilan temel port:

```text
8554/TCP ve gerektiginde RTSP UDP portlari
```

Yapilandirmada:

- RTSP aciktir.
- RTMP, HLS, WebRTC ve SRT kapatilmistir.
- Yayin ve okuma icin ayri kullanicilar vardir.
- Parolalar su anda dosyada acik metindir.
- API, metrics ve pprof kapatilmistir.
- Kayit ozelligi kapatilmistir.

Parolalar repoya veya paylasilan dokumana konulmamalidir. Mevcut parolalar
degistirilmeli ve secret/config yonetimine alinmalidir.

### 4.2 FFmpeg test yayincisi

Gercek IP kamera olmadiginda `serverVideo.mp4`, FFmpeg ile gercek zaman
hizinda okunur, H.264'e kodlanir ve MediaMTX'e gonderilir.

Mantiksal komut:

```powershell
ffmpeg -re -stream_loop -1 `
  -i .\rtsp\serverVideo.mp4 `
  -c:v libx264 -preset ultrafast -tune zerolatency -an `
  -f rtsp rtsp://127.0.0.1:8554/kamera1
```

Parametreler:

- `-re`: Videoyu dosya hizi yerine gercek zaman hizinda okur.
- `-stream_loop -1`: Videoyu sonsuz donguye alir.
- `libx264`: Goruntuyu H.264 olarak kodlar.
- `ultrafast`: CPU yukunu azaltir.
- `zerolatency`: Canli yayin gecikmesini azaltir.
- `-an`: Ses kanalini gondermez.

### 4.3 Baslatma sirasi

`BASLAT.bat` su zinciri calistirir:

```text
scripts\baslat.ps1
  -> rtsp-baslat.ps1
     -> MediaMTX
     -> FFmpeg
  -> rtsp-test.ps1
     -> ffprobe ile kamera testi
  -> edge-baslat.ps1
     -> Edge Agent
  -> durum.ps1
```

Surec kimlikleri `.runtime` altinda tutulur:

```text
.runtime\mediamtx.pid
.runtime\ffmpeg.pid
.runtime\edge.pid
```

Loglar:

```text
.runtime\logs\mediamtx.log
.runtime\logs\mediamtx-error.log
.runtime\logs\ffmpeg.log
.runtime\logs\ffmpeg-error.log
.runtime\logs\edge-console.log
.runtime\logs\edge-error.log
edge-agent\logs\trigger.log
```

## 5. Edge Agent

Edge Agent, kamera tarafina en yakin calisan bilesendir. Ana dosyalar:

```text
edge-agent\trigger.py
edge-agent\camera.py
edge-agent\sender.py
edge-agent\config.py
edge-agent\camera.json
edge-agent\system_config.json
```

### 5.1 Neden edge katmani var?

- Tum videoyu buluta gondermek pahali ve yavas olur.
- Fabrikada internet kesilebilir.
- Yuz bulaniklastirma buluta gondermeden once yapilmalidir.
- Hareket olmayan goruntulerin analiz edilmesi gereksiz maliyet olusturur.
- Kamera baglantisi ve gecici dosyalar tesis tarafinda kontrol edilebilir.

### 5.2 Kamera yapilandirmasi

`camera.json`, kurumlari ve her kuruma bagli kameralari tutar.

Ornek sema:

```json
{
  "kurumlar": {
    "test-musteri": {
      "ad": "Test Fabrikasi",
      "kameralar": {
        "kamera-1": {
          "url": "rtsp://KULLANICI:PAROLA@127.0.0.1:8554/kamera1",
          "ad": "Test Kamera",
          "alan": "uretim",
          "mod": "motion",
          "tip": "ppe+fire",
          "threshold": 0.2,
          "window_sn": 10,
          "top_n": 3
        }
      }
    }
  }
}
```

URL degerinin icine ayrica cift tirnak karakteri yazilmamalidir. JSON zaten
metni tirnak icine alir.

### 5.3 Kamera modlari

#### Motion

Hareket oldugunda bir pencere acar.

Parametreler:

- `threshold`: Hareket maskesinin esigi.
- `window_sn`: Olay penceresinin suresi.
- `top_n`: En yuksek hareket skoruna sahip kac karenin secilecegi.

Akis:

1. MOG2 arka plan ayirici olusturulur.
2. Her karede hareket orani hesaplanir.
3. Esik asilinca olay penceresi baslar.
4. Kareler ve degisim skorlari biriktirilir.
5. Pencere bitince en yuksek skorlu kareler secilir.
6. Yuzler bulaniklastirilir.
7. Kareler outbox paketine donusturulur.

#### Periyodik

Belirli araliklarla bir veya daha fazla kare alir.

Parametreler:

- `interval_dk`: Iki tarama arasindaki dakika.
- `frame_sayisi`: Tarama basina kare sayisi.
- `frame_aralik_dk`: Kareler arasi dakika.

#### Surekli

Kamerayi acik tutar ve belirlenen saniye araliginda bir kare gonderir.

Parametre:

- `interval_sn`: Iki kare arasindaki saniye.

Yangin gibi kritik ve surekli izlenmesi gereken alanlarda kullanilmasi
dusunulmustur.

### 5.4 Yuz bulaniklastirma

`camera.py`, OpenCV Haar Cascade ile yuz tespiti yapar. Bulunan yuz bolgesi
Gaussian blur ile bulaniklastirilir.

Bu yontem:

- Basit ve hizlidir.
- CPU'da calisabilir.
- Profil, maske, kask, uzaklik ve kotu isikta yuz kacirabilir.
- Uretim icin daha guclu bir yuz algilayici ve kalite testi gerekir.

### 5.5 Outbox deseni

Her olay once yerel diske atomik olarak yazilir:

```text
edge-agent\buffer\outbox\{event_id}\
  event.json
  frame_00.jpg
  frame_01.jpg
  frame_02.jpg
```

Paket once gizli gecici klasorde olusturulur:

```text
.{event_id}.tmp
```

Tum dosyalar tamamlaninca klasor asil `event_id` adina cevrilir. Bu sayede
yarim yazilmis paket normal kuyrukta gorunmez.

Olay alanlari:

- `schema_version`
- `event_id`
- `customer_id`
- `camera_id`
- `institution_name`
- `camera_name`
- `area`
- `captured_at`
- `analysis_types`
- `mode`
- `frame_count`
- `frames`
- `gcs_uploaded`
- `published`

### 5.6 GCS ve Pub/Sub gonderimi

Gonderim sirasi ozellikle onemlidir:

1. Kareler GCS'ye yuklenir.
2. `meta.json` GCS'ye yazilir.
3. Yerel `event.json` icinde `gcs_uploaded=true` yapilir.
4. Pub/Sub mesaji yayimlanir.
5. `published=true` yapilir.
6. Paket yerel outbox'tan silinir.

GCS yolu:

```text
gs://BUCKET/{customer_id}/frames/{camera_id}/{YYYY-MM-DD}/{event_id}/
```

Yuklemelerde `if_generation_match=0` kullanilir. Ayni olay tekrar
gonderildiginde mevcut nesnenin yanlislikla ezilmesi engellenir.

Internet veya Pub/Sub kesilirse paket silinmez. Arka plan thread'i varsayilan
olarak her 30 saniyede tekrar dener.

### 5.7 Cloud kimligi

Edge Agent, JSON servis hesabi anahtari tasimak yerine:

1. Google Application Default Credentials alir.
2. Sinirli `sentialx-edge` servis hesabini impersonate eder.
3. GCS ve Pub/Sub istemcilerini bu gecici kimlikle olusturur.

Bu nedenle yerel makinede Google Cloud CLI ve ADC oturumu gerekir:

```powershell
gcloud auth login
gcloud auth application-default login
```

Kaynak kullanicinin hedef edge servis hesabini taklit etme yetkisi de
olmalidir.

## 6. Frame Worker

Frame Worker, `sentialx-frames` Pub/Sub mesajlarini alan bulut servisidir.

Ana gorevleri:

1. Pub/Sub zarfini base64'ten cozer.
2. Zorunlu olay alanlarini dogrular.
3. `event_id` ile Cloud SQL kaydi acar.
4. GCS'den kareleri indirir.
5. `analysis_types` degerine gore PPE ve/veya yangin servisini cagirir.
6. Ihlal yoksa GCS olay klasorunu hemen siler.
7. Ihlal varsa VLM servisini cagirir.
8. Rapor servisine uygun `ReportRequest` olusturur.
9. Rapor sonucunu Cloud SQL'e yazar.
10. Yangin varsa `fire-alerts` konusuna alarm yayimlar.

Cloud SQL tablosu `frame_events` su tip bilgileri tutar:

- Olay ve kamera kimlikleri.
- Yakalama zamani.
- Analiz turleri.
- GCS adresi.
- Islem durumu.
- Detection sonuclari.
- Rapor sonucu.
- Ihlal ve yangin bayraklari.
- Goruntulerin silinip silinmedigi.
- Silme zamani ve suresi.
- Hata metni.

`event_id` birincil anahtardir. Tamamlanmis bir olay tekrar gelirse analiz
yeniden yapilmaz; mesaj duplicate olarak onaylanir.

Hata halinde HTTP 500 doner. Pub/Sub tekrar dener. Yapilandirmada en fazla bes
teslim denemesinden sonra mesaj dead-letter konusuna gidebilir.

## 7. PPE, Yangin ve VLM Servisleri

Frame Worker su servis URL'lerini bekler:

- PPE detection: resimden KKD ihlali sonucu.
- Fire detection: resimden yangin/acik alev alarmi.
- VLM service: olay cevresi ve risk aciklamasi.

Bu servislerin canli Cloud Run adresleri `system_config.json` ve dagitim
scriptlerinde referans edilmektedir; ancak PPE, yangin ve VLM servislerinin
kaynak kodlari bu birlesik calisma kopyasinda bulunmamaktadir.

Bu nedenle sistemin bulut zincirini sifirdan kurmak icin bu uc servisin kaynak
depolari veya container imajlari ayrica gereklidir.

## 8. RAG Service

RAG servisi, ISG dokuman agacindan olayla ilgili dugumleri secip mevzuat ve
teknik baglam uretir.

Calisma alani:

```text
cloud_two_service\rag-service
```

Uclar:

```text
GET  /health
POST /query
```

`/health`:

```json
{
  "status": "ok",
  "node_count": 234
}
```

Sorgu ornegi:

```json
{
  "violation_type": "ppe_ihlali",
  "violation_subtype": "baretsiz",
  "process": "kaynak",
  "zone": "Hat-3",
  "description": "Calisan koruyucu baret olmadan gorunuyor"
}
```

Akis:

1. Servis acilisinda PageIndex JSON dosyasi yuklenir.
2. Tum dugumler `node_id -> node` haritasina donusturulur.
3. Metin alanlari cikartilmis dokuman agaci LLM'e verilir.
4. LLM ilgili `node_id` listesini JSON olarak dondurur.
5. Secilen dugumlerin tam metni birlestirilir.
6. Regex ile kaynak, mevzuat, zorunlu ve onerilen kriterler cikartilir.
7. Ikinci LLM cagrisi yalniz secilen icerige dayanarak Turkce cevap uretir.

RAG cevabi:

- Olusturulan soru.
- Teknik baglam ozeti.
- Benzer olaylar.
- Mevzuat listesi.
- Zorunlu ve onerilen cozum kriterleri.
- Kaynaklar.
- Kullanilan dugum basliklari.
- Nihai cevap.

Riskler:

- Dugum secimi tamamen LLM JSON cikisina baglidir.
- JSON bozuk gelirse istek hata verir.
- Regex tabanli kaynak cikarma, dokuman formati degisirse kacirabilir.
- Kaynak dogrulugu icin otomatik atif testi yoktur.
- Varsayilan model adi preview modeldir; zamanla degisebilir.

## 9. Report Service

Rapor servisi ihlalleri gruplar, RAG ile zenginlestirir ve Turkce vardiya
raporu veya PDF uretir.

Calisma alani:

```text
cloud_two_service\report-service
```

Uclar:

```text
GET    /health
POST   /report
POST   /report/pdf
POST   /report/queue
GET    /report/queue
GET    /report/queue/{job_id}
DELETE /report/queue/{job_id}
```

### 9.1 ReportRequest

```json
{
  "tesis_id": "T-1001",
  "tesis_adi": "Demo Fabrika",
  "tesis_adresi": "Istanbul",
  "vardiya": "2",
  "vardiya_baslangic": "2026-06-11T08:00:00+03:00",
  "vardiya_bitis": "2026-06-11T16:00:00+03:00",
  "sorumlu_isg_uzmani": "A. Test",
  "violations": [
    {
      "id": "v1",
      "tesis_id": "T-1001",
      "kamera_id": "cam-01",
      "ihlal_tipi": "ppe_ihlali",
      "ihlal_alt_tipi": "baretsiz",
      "bolge": "Hat-3",
      "guven_skoru": 0.98,
      "frame_url": "gs://ornek/frame.jpg",
      "aciklama": "Calisan baret kullanmiyor",
      "tespit_zamani": "2026-06-11T10:15:00+03:00",
      "vardiya": "2"
    }
  ]
}
```

### 9.2 Gruplama

Ihlaller su anahtarla gruplanir:

```text
bolge + ihlal_tipi + ihlal_alt_tipi
```

Ayni bolgede ayni ihlal turu birden cok kez gorulurse tek grup olur; `adet`,
zamanlar, kare URL'leri ve aciklamalar grup icinde biriktirilir.

### 9.3 RAG entegrasyonu

Mock modu kapaliysa her grup icin RAG `/query` ucu cagrilir. Cloud Run'da
`RAG_AUTH_MODE=google_id_token` ise rapor servisi RAG servisinin URL'sini
audience kabul eden OIDC token uretir.

RAG hatasi rapor islemini tamamen durdurmaz. Hata loglanir ve grup RAG
baglami olmadan rapora devam eder.

### 9.4 LLM raporu

Gemini prompt'u:

- Tesis bilgilerini.
- Vardiya tarih ve saatini.
- Toplam ihlal sayisini.
- Etkilenen bolge sayisini.
- Yangin sayisini.
- Gruplanmis olaylari.
- RAG mevzuat ve onlem bilgilerini

kullanir.

Istenen bolumler:

1. Yonetici ozeti.
2. Ihlal detaylari.
3. Yasal yukumlulukler.
4. Acil, kisa ve uzun vadeli duzeltici faaliyetler.
5. Sonuc ve imza alani.

`MOCK_MODE=1` oldugunda Gemini ve RAG cagrilmaz; sabit ama anlamli bir demo
raporu uretilir.

### 9.5 PDF

PDF, ReportLab ile A4 olarak uretilir. Turkce karakterler icin Windows'ta
Arial, Linux container'da DejaVu Sans veya Noto Sans aranir.

PDF'de:

- Rapor kimligi.
- Tesis ve vardiya bilgisi.
- Yonetici ozeti.
- Ihlal tablosu.
- LLM rapor metni.
- Duzeltici faaliyet tablosu.
- Imza alani

bulunur.

### 9.6 Kuyruk

Desteklenen gercek implementasyonlar:

- `file`: `queue_state.json`.
- `redis`: Redis liste, hash ve sorted set.

Kodda `GCSQueueStore` sinifi vardir; ancak `build_queue_store` su anda GCS
secenegini kabul etmez. Yani aktif secenek degildir.

Cloud Run'da `file` kuyrugu kalici degildir. Instance kapaninca veya baska
instance istegi aldiginda is durumu kaybolabilir. Cloud Run icin senkron
`/report`, `/report/pdf`, Cloud Tasks veya Redis tercih edilmelidir.

## 10. Fire Notifier

Fire Notifier, `fire-alerts` Pub/Sub mesajini alir ve `CRITICAL` seviyesinde
yapisal bir Cloud Logging kaydi yazar.

Bu log, Cloud Monitoring log tabanli alarm politikasiyla e-postaya
donusturulur.

Mevcut servis dogrudan SMS, telefon veya siren cagrisi yapmaz. Bu tur
entegrasyonlar ayrica eklenmelidir.

## 11. Yerel Kurulum

### 11.1 Gereksinimler

- Windows.
- MediaMTX executable.
- FFmpeg ve FFprobe.
- Python 3.13.
- Google Cloud CLI.
- GCP projesi, bucket ve Pub/Sub topic.
- ADC ve service-account impersonation yetkisi.

### 11.2 Ilk kurulum

Yerel demo klasorunde:

```text
KURULUM.bat
```

Script:

1. MediaMTX dosyasini kontrol eder.
2. FFmpeg ve FFprobe'u PATH icinde arar.
3. Edge Agent icin `.venv` olusturur.
4. Python paketlerini kurar.
5. Google Cloud CLI'nin belirli yerel yolunu kontrol eder.

Edge Agent gereksinimleri:

```text
google-cloud-pubsub
google-cloud-storage
opencv-python-headless
```

Kurulum scripti `py -3.13` kullandigi icin Python 3.13 launcher
calisabilmelidir. Sanal ortam baska bilgisayardan kopyalanmamali; hedef
makinede yeniden olusturulmalidir.

### 11.3 Kamera ekleme

1. Once MediaMTX ve FFmpeg test yayinini baslatin:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\rtsp-baslat.ps1
```

2. `KAMERA_EKLE.bat` calistirin.
3. Kurum, kamera, alan, RTSP URL, mod ve analiz tipini girin.
4. URL'yi elle yazarken basina/sonuna fazladan `"` koymayin.
5. `KAMERA_LISTELE.bat` ile kaydi dogrulayin.

Test otomasyonu `rtsp-test.ps1` icinde su kimligi sabit beklemektedir:

```text
test-musteri / kamera-1
```

Farkli kimlik kullanilirsa `BASLAT.bat`, RTSP yayini calissa bile test
asamasinda durur. Bu scriptin genel hale getirilmesi gerekir.

### 11.4 Normal calistirma

```text
BASLAT.bat
DURUM.bat
SAGLIK_KONTROL.bat
DURDUR.bat
```

Canli goruntu:

```powershell
ffplay -rtsp_transport tcp "rtsp://KULLANICI:PAROLA@127.0.0.1:8554/kamera1"
```

Parolayi komut gecmisine yazmamak icin uretimde kimlik bilgisini daha guvenli
bir yontemle vermek gerekir.

## 12. RAG ve Report Servislerini Yerelde Calistirma

Her servis icin ayri sanal ortam onerilir.

### 12.1 RAG

```powershell
cd cloud_two_service\rag-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:GEMINI_API_KEY="SECRET"
$env:PORT="8083"
uvicorn main:app --host 0.0.0.0 --port 8083
```

Kontrol:

```powershell
Invoke-RestMethod http://localhost:8083/health
```

Beklenen dugum sayisi `234`tur.

### 12.2 Report Service mock modu

```powershell
cd cloud_two_service\report-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:MOCK_MODE="1"
$env:QUEUE_BACKEND="file"
uvicorn main:app --host 0.0.0.0 --port 8084
```

Hizli offline test:

```powershell
python .\mock_example.py
```

11 Haziran 2026 dogrulamasinda bu test:

- 3 toplam ihlal.
- 2 ihlal grubu.
- 1 kritik ihlal

ureterek basarili calismistir.

### 12.3 Canli RAG + LLM

Report Service icin:

```powershell
$env:MOCK_MODE="0"
$env:GEMINI_API_KEY="SECRET"
$env:RAG_SERVICE_URL="http://localhost:8083"
$env:RAG_AUTH_MODE="none"
uvicorn main:app --host 0.0.0.0 --port 8084
```

Yerel RAG servisi 8083'te, rapor servisi 8084'te olmalidir.

## 13. Docker ile Rapor Servisi

Birlesik `workspace\services\report-service` kopyasinda Redis'li
`docker-compose.yml` vardir:

```powershell
docker compose up --build
```

Bu:

- Redis 7.
- Rapor servisi.
- `QUEUE_BACKEND=redis`.
- `MOCK_MODE=1`

ile 8084 portunu acar.

Bu makinede 11 Haziran 2026 itibariyla Docker komutu PATH icinde
bulunmamaktadir.

## 14. Google Cloud Kurulumu

### 14.1 Temel kaynaklar

Gerekli kaynaklar:

- Cloud Run.
- Cloud Build.
- Artifact Registry.
- Secret Manager.
- Cloud Storage.
- Pub/Sub.
- Cloud SQL PostgreSQL.
- Cloud Monitoring.
- Ayri servis hesaplari.

### 14.2 RAG ve Report

```powershell
cd workspace\cloud
.\deploy_two_services.ps1
```

Script:

1. Gerekli API'leri acar.
2. RAG ve Report runtime servis hesaplarini olusturur.
3. Gemini secret erisimini verir.
4. Report hesabina bucket yazma yetkisi verir.
5. RAG servisini private Cloud Run olarak deploy eder.
6. Report hesabina RAG invoker yetkisi verir.
7. Report servisini private Cloud Run olarak deploy eder.

### 14.3 Frame Worker

```powershell
.\deploy_frame_worker.ps1
```

Script:

- Worker runtime ve Pub/Sub push servis hesaplarini olusturur.
- Frames, fire ve dead-letter topic'lerini olusturur.
- Worker'a bucket, Cloud SQL, Secret Manager ve Pub/Sub yetkileri verir.
- PPE, fire, VLM ve report servislerine invoker yetkisi verir.
- Worker'i Cloud Run'a deploy eder.
- OIDC kimlikli Pub/Sub push subscription olusturur.
- Bes deneme ve dead-letter politikasini kurar.

### 14.4 Fire Notifier ve monitoring

```powershell
.\deploy_fire_notifier.ps1
.\harden_cloud.ps1
.\configure_monitoring.ps1
```

Kurulan kontroller:

- Analysis servislerinden anonim erisimin kaldirilmasi.
- Cloud SQL gunluk yedek.
- Point-in-time recovery.
- Sifreli baglanti.
- Silme korumasi.
- Worker 5xx alarmi.
- Dead-letter backlog alarmi.
- Yangin kritik log e-postasi.
- Mumkunse butce esikleri.

Bu makinede `gcloud.cmd` dosyasi vardir; ancak mevcut sandbox oturumunda
calistirilmasi engellenmistir. Normal kullanici oturumunda:

```powershell
& "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" --version
```

ile kontrol edilmelidir.

## 15. Eski Core Platform

`workspace\services\core-platform`, RTSP + hareket + YOLO + Supabase kullanan
onceki prototiptir.

Tasarim:

- `CameraManager`: Tum fabrikalar.
- `FactoryManager`: Bir fabrikanin kameralari.
- `CameraWorker`: Kamera basina thread.
- `Detector`: YOLO modeli.
- `Database`: Supabase.

Ancak mevcut kopya calisir durumda degildir:

1. `main.py`, `CameraManager.start()` ve `stop()` cagirir; sinifta bu
   metotlar yoktur.
2. `camera_worker.py`, `PPEDetector` import eder; `detector.py` yalniz
   `Detector` tanimlar.
3. `best.pt` dosyasi 120 bayttir ve gercek model degil, yer tutucudur.
4. Dokuman Supabase kaydi anlatir; worker kodu veritabani sinifini cagirmiyor.
5. FastAPI yalniz `/health` sunar; kamera yonetim API'leri yoktur.

Bu nedenle eski core-platform, mevcut yerel Edge + cloud worker mimarisinin
yerine dogrudan kullanilmamalidir.

## 16. 11 Haziran 2026 Itibariyla Mevcut Yerel Durum

Mevcut masaustu kurulumunda:

- Edge Agent prosesi calisiyor gorunmektedir.
- MediaMTX prosesi calismamaktadir.
- 8554 portu kapali bulunmustur.
- FFmpeg PID dosyasi eski/stale durumdadir.
- Edge sanal ortami artik erisilemeyen bir Python 3.13 WindowsApps yoluna
  baglidir.
- Ana `python` surumu 3.14.4'tur.
- FFmpeg 8.1 PATH icinde bulunmaktadir.
- Docker PATH icinde bulunmamaktadir.
- `camera.json` beklenen `test-musteri/kamera-1` kaydini icermemektedir.
- Kamera URL degerinin icinde fazladan cift tirnak karakterleri vardir.
- Bu nedenle OpenCV kamerayi acamamaktadir.
- Outbox'ta `event.json` bulunmayan bir klasor vardir.
- Retry thread'i bu bozuk paketi her 30 saniyede tekrar denemektedir.

Sistemi duzeltmek icin guvenli sira:

1. `DURDUR.bat` ile bilinen surecleri kapatmak.
2. Gerekirse stale PID dosyalarini surecler kapaliyken temizlemek.
3. Edge `.venv` klasorunu hedef makinede Python 3.13 ile yeniden olusturmak.
4. `camera.json` kaydini `KAMERA_DUZENLE.bat` veya kontrollu duzenleme ile
   duzeltmek.
5. URL'nin icindeki fazladan tirnaklari kaldirmak.
6. Test otomasyonu kullanilacaksa kurum/kamera kimligini
   `test-musteri/kamera-1` yapmak veya `rtsp-test.ps1`i genel hale getirmek.
7. Eksik `event.json` paketini log ve GCS durumu incelendikten sonra karantinaya
   almak; dogrudan silmeden once olay kimligini kontrol etmek.
8. `KURULUM.bat` calistirmak.
9. `BASLAT.bat`, `DURUM.bat` ve `SAGLIK_KONTROL.bat` calistirmak.

## 17. Guvenlik ve KVKK Acisindan Onemli Noktalar

Mevcut iyi kararlar:

- Yuzler edge tarafinda bulaniklastiriliyor.
- Cloud Run servisleri private tasarlanmis.
- Servisler arasi OIDC kullaniliyor.
- JSON anahtar yerine ADC/impersonation hedeflenmis.
- Ihlal olmayan goruntuler hemen siliniyor.
- Dead-letter ve kritik alarm tasarimi var.
- Cloud SQL yedek ve silme korumasi dusunulmus.

Tamamlanmasi gerekenler:

- RTSP parolalarini acik metin dosyalardan kaldirmak.
- Parola rotasyonu yapmak.
- Tenant/kurum izolasyonunu IAM ve veritabaninda zorunlu kilmak.
- Dashboard ve son kullanici kimlik dogrulamasini eklemek.
- Saklama suresini kodla ve bucket lifecycle ile uygulamak.
- Ihlal goruntulerinin ne zaman silinecegini tanimlamak.
- Erisim ve silme denetim kayitlarini merkezi tutmak.
- Yuz bulaniklastirma basarisini test etmek.
- Raporlarin hukuki karar yerine destekleyici belge oldugunu belirtmek.

## 18. Test Stratejisi

Olmasi gereken test katmanlari:

### Birim testleri

- Kamera config dogrulama.
- Vardiya hesaplama.
- Ihlal gruplama.
- Outbox paket semasi.
- GCS URI ayrisma.
- RAG kaynak ve mevzuat cikarma.
- PDF Turkce karakter testi.

### Entegrasyon testleri

- MediaMTX + FFmpeg + OpenCV.
- Edge -> sahte GCS/PubSub.
- Pub/Sub envelope -> Frame Worker.
- Frame Worker -> sahte PPE/fire/VLM.
- Report -> RAG.
- Redis kuyruk yeniden baslatma.

### Uctan uca test

1. Test videosunu RTSP'ye yayinla.
2. Edge'in olay paketi urettigini gor.
3. GCS nesnelerini ve Pub/Sub mesajini dogrula.
4. Worker detection sonucunu kontrol et.
5. Ihlal yoksa goruntunun silindigini kontrol et.
6. Ihlal varsa VLM ve rapor sonucunu kontrol et.
7. Yangin varsa alarmi kontrol et.
8. Cloud SQL kaydini kontrol et.

Mevcut otomatik test kapsami bu seviyede degildir.

## 19. En Kritik Teknik Borclar

Oncelik sirasi:

1. Tek kanonik Git deposu belirlemek.
2. Acik parolalari ve sabit proje kimliklerini koddan cikarmak.
3. PPE, fire ve VLM kaynaklarini ayni surum yonetimine almak.
4. Ortak ve surumlu olay semasi tanimlamak.
5. Yerel kamera test scriptini sabit kimlikten kurtarmak.
6. Outbox'ta eksik/bozuk paket karantina mekanizmasi eklemek.
7. Edge hot reload'da silinen veya degisen kamerayi yonetmek.
8. Kalici Cloud Run kuyrugu kullanmak.
9. RAG JSON cikisini semayla zorlamak ve atif testi eklemek.
10. Dashboard, kimlik dogrulama ve tenant izolasyonunu tamamlamak.
11. CI icinde birim, entegrasyon ve container testleri calistirmak.
12. Model dosyalarini versiyonlu model deposuna almak.

## 20. Kisa Ozet

SentialX'in calisan fikri su zincirdir:

```text
Kamerayi oku
-> gereksiz kareleri ele
-> yuzu bulaniklastir
-> olayi kaybetmeyecek sekilde outbox'a yaz
-> GCS + Pub/Sub'a gonder
-> PPE/yangin analizi yap
-> ihlal yoksa veriyi sil
-> ihlal varsa VLM + RAG + rapor calistir
-> sonucu kaydet ve gerekiyorsa alarm ver
```

Proje teknik olarak guclu bir prototip tabanina sahiptir. En buyuk sorun
algoritmadan cok paketleme ve entegrasyondur: birden fazla kopya, eksik servis
kaynaklari, sabit yapilandirmalar, bozuk yerel ortam ve yetersiz otomatik
testler. Bunlar duzeltildiginde sistem erken MVP seviyesinden daha guvenilir
bir pilot urune tasinabilir.
