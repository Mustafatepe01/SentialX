# SentialX Camera Simulator

Bu klasor, kayitli bir videoyu FFmpeg ile MediaMTX'e yayinlayarak yerel RTSP
kamera akisi uretir. MediaMTX binary'si ve test videolari repoya eklenmez.

## Kurulum

1. MediaMTX ve FFmpeg'i kurun.
2. `mediamtx.example.yml` dosyasini yerel `mediamtx.yml` olarak kopyalayin.
3. Iki dosyadaki `CHANGE_ME_LOCALLY` degerlerini ayni guclu parola ile
   degistirin.
4. MediaMTX'i yerel ayar dosyasi ile baslatin.

Bir test videosunu sonsuz dongude `camera1` yoluna yayinlamak icin:

```powershell
.\start-camera.ps1 `
  -VideoPath "C:\path\ppe-test.mp4" `
  -StreamPath "camera1" `
  -PublisherPassword "YOUR_LOCAL_PASSWORD"
```

`camera2` ve `camera3` icin betigi ayri terminallerde farkli video veya
webcam kaynaklariyla calistirin. Edge Agent'taki `rtsp_path` ve
`analysis_types` alanlari, bu akisin hangi model servislerine gidecegini
belirler.
