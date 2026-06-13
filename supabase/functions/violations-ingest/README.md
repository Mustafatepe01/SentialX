# Violations Ingest Edge Function

Frame Worker'dan gelen PPE ve yangin ihlallerini dogrular ve Supabase
`violations` tablosuna `violation_id` uzerinden idempotent olarak ekler.

Gerekli Supabase secret'lari:

- `INGEST_TOKEN`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Istekler `x-ingest-token` basligi tasimalidir. Function yalnizca `POST`
kabul eder; kamera ve ihlal kimliklerini UUID, politika kimligini ise
PPE icin `1` veya yangin icin `3` olarak dogrular.
