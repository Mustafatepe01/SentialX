# SentialX Model Kartlari

Bu belge, SentialX veri akisinda kullanilan yapay zeka bilesenlerini ve
mevcut depoda dogrulanabilen bilgileri ozetler. Olculmemis dogruluk, gecikme,
FPS veya hata orani degerleri bilerek eklenmemistir.

## Model Envanteri

| Bilesen | Gorev | Depodaki durum |
|---|---|---|
| PPE Detection | Kisisel koruyucu donanim ihlallerini belirleme | Canli serviste kullaniliyor; kaynak kodu ve agirliklar bu depoda yok |
| Fire Detection | Yangin veya acik alev belirtisini belirleme | Canli serviste kullaniliyor; kaynak kodu ve agirliklar bu depoda yok |
| VLM Service | Ihlal goruntusunu dogal dilde aciklama | Canli serviste kullaniliyor; model kodu ve promptlari bu depoda yok |
| PageIndex RAG LLM | Ilgili ISG dugumlerini secme ve kaynak-temelli cevap uretme | Kaynak kodu ve indeks bu depoda mevcut |
| Report LLM | Ihlal gruplarindan Turkce vardiya raporu uretme | Kaynak kodu bu depoda mevcut |

## PPE Detection

**Amac:** Kamera olaylarinda KKD kullanimi ile ilgili ihlal sonucunu
uretmektir.

**Cagirilma kosulu:** Kamera/olay yapilandirmasindaki `analysis_types`
alaninda PPE analizi etkin oldugunda Frame Worker tarafindan cagrilir.

**Girdi:** Edge tarafinda secilmis ve yuzleri bulaniklastirilmis olay
goruntuleri.

**Cikti:** Frame Worker tarafindan olay kaydina eklenen yapilandirilmis KKD
tespit sonucu ve ihlal bayragi.

**Sinirlar:**

- Model mimarisi, sinif listesi, agirlik surumu ve karar esigi bu depodan
  dogrulanamamaktadir.
- Eski prototipte YOLO referansi bulunmasi, canli servisin ayni modeli
  kullandigini kanitlamaz.
- Model basarisi icin kontrollu precision, recall, F1 veya mAP testi
  paylasilmamistir.

## Fire Detection

**Amac:** Olay goruntulerinde yangin veya acik alev belirtisini
degerlendirmektir.

**Cagirilma kosulu:** `analysis_types` alaninda yangin analizi etkin oldugunda
Frame Worker tarafindan cagrilir.

**Girdi:** Edge tarafinda hazirlanan, gizlilik islemi uygulanmis olay
goruntuleri.

**Cikti:** Yangin/alev sonucu ve kritik olay bayragi. Pozitif sonuc normal
vardiya raporu beklenmeden `fire-alerts` bildirim hattini tetikler.

**Sinirlar:**

- Model turu, egitim veri seti, agirlik surumu ve karar esigi bu depoda
  bulunmamaktadir.
- Yanlis alarm ve kacirilan tespit oranlari kontrollu bir testle
  olculmemistir.
- Alarm mekanizmasi model sonucunu iletir; model sonucunun tek basina kesin
  saha karari olmadigi dikkate alinmalidir.

## VLM Service

**Amac:** Tespit edilen ihlalin sahne ve risk baglamini dogal dilde
aciklamaktir.

**Cagirilma kosulu:** PPE veya yangin analizinden ihlal sonucu alindiginda
Frame Worker tarafindan cagrilir.

**Girdi:** Ihlal goruntuleri, olay metadata'si ve mevcut tespit sonucu.

**Cikti:** Olay kaydinda ve RAG sorgusunda kullanilabilen metinsel aciklama.

**Sinirlar:**

- VLM temel tespit modelinin yerine gecmez; destekleyici aciklama uretir.
- Kullanilan model adi, prompt surumu ve cikti semasi bu depoda yer
  almamaktadir.
- Uretken model ciktilari hatali yorum veya halusinasyon icerebilir.

## PageIndex Tabanli RAG

**Amac:** Ihlal turu, alt turu, proses, bolge ve VLM aciklamasina gore ilgili
ISG bilgisini bulmak; mevzuat, risk ve cozum kriterleriyle cevap uretmektir.

**Indeks:** Depodaki PageIndex JSON dosyasi yukleme testinde 234 dugum
icermektedir.

**Varsayilan LLM:** `gemini/gemini-3-flash-preview`. Model adi
`LLM_MODEL` ortam degiskeniyle degistirilebilir. LiteLLM uzerinden Gemini,
OpenRouter veya OpenAI uyumlu bir saglayici kullanilabilir.

**Calisma akisi:**

1. Metinleri cikartilmis PageIndex agaci LLM'e verilir.
2. LLM ilgili `node_id` listesini JSON olarak secer.
3. Secilen dugumlerin tam metni birlestirilir.
4. Kaynaklar, mevzuat ve cozum kriterleri cikartilir.
5. Ikinci LLM cagrisi yalniz getirilen icerige dayanarak Turkce cevap uretir.

**Cikti alanlari:** Teknik baglam, benzer olaylar, mevzuat, zorunlu ve
onerilen onlemler, kaynaklar, kullanilan dugumler ve nihai cevap.

**Sinirlar:**

- Dugum secimi LLM'in gecerli JSON uretmesine baglidir.
- Kaynak ve mevzuat cikarma kurallari dokuman bicimi degistiginde eksik sonuc
  uretebilir.
- Otomatik retrieval/atif kalite benchmark'i henuz bulunmamaktadir.
- Varsayilan model bir preview modelidir ve zaman icinde degisebilir.

## Report LLM

**Amac:** Gruplanmis ihlallerden resmi Turkce vardiya raporu olusturmaktir.

**Varsayilan model:** `gemini/gemini-3-flash-preview`. Model
`GEMINI_MODEL` ortam degiskeniyle degistirilebilir.

**Girdi:** Tesis ve vardiya bilgileri, gruplanmis ihlaller, VLM aciklamalari
ve mevcutsa PageIndex RAG baglami.

**Cikti:** Yonetici ozeti, ihlal ayrintilari, yasal yukumlulukler ve
duzeltici faaliyet onerileri iceren rapor metni. Servis JSON ve PDF ciktilari
destekler.

**Offline davranis:** `MOCK_MODE=1` oldugunda harici LLM ve RAG cagrisi
yapilmadan sabit yapili bir demo raporu uretilir.

**Sinirlar:**

- Uretilen rapor yetkili ISG uzmani onayinin yerine gecmez.
- RAG kullanilamadiginda rapor daha az kaynak baglamiyla uretilir.
- Rapor kalitesi icin insan degerlendirmeli sabit bir test seti henuz
  bulunmamaktadir.

## Surumleme ve Tekrar Uretilebilirlik

PPE, yangin ve VLM servisleri icin asagidaki bilgiler canli servis
kaynaklarina erisildiginde bu belgeye eklenmelidir:

- Model mimarisi ve kesin model adi
- Agirlik/dataset surumu
- SHA256 model dosyasi ozeti
- Sinif listesi
- On isleme adimlari ve karar esikleri
- Egitim, dogrulama ve test veri seti ozeti
- Precision, recall, F1, mAP ve confusion matrix
- Model lisansi ve veri seti lisansi
- Bilinen yanliliklar ve uygun olmayan kullanim senaryolari

Bu bilgiler tamamlanana kadar depo, tespit modellerinin tam olarak yeniden
uretilebildigini iddia etmemektedir.

