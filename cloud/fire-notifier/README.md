# SentialX Fire Notifier

Frame Worker tarafindan `fire-alerts` Pub/Sub topic'ine yayinlanan yangin
mesajlarini alir. Mesaj semasini dogrular ve Cloud Logging'e `CRITICAL`
seviyesinde yapilandirilmis alarm kaydi yazar.

## Uclar

- `GET /health`: servis saglik kontrolu
- `POST /pubsub/fire`: Pub/Sub push hedefi

Pub/Sub aboneligi private Cloud Run servisine OIDC kimligiyle cagri yapacak
sekilde kurulmalidir. Bu prototip e-posta, SMS veya siren entegrasyonu
gondermez; alarm kaydi bu tur bir notification channel'a baglanabilir.
