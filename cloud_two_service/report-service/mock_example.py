import asyncio
from datetime import datetime, timedelta

from models import ReportRequest, Violation
from report import create_report


async def main() -> None:
    now = datetime.now()
    request = ReportRequest(
        tesis_id="T-1001",
        tesis_adi="Demo Fabrika",
        tesis_adresi="İstanbul",
        vardiya="2",
        vardiya_baslangic=now - timedelta(hours=4),
        vardiya_bitis=now,
        sorumlu_isg_uzmani="A. Test",
        violations=[
            Violation(
                id="v1",
                tesis_id="T-1001",
                kamera_id="cam-01",
                ihlal_tipi="ppe_ihlali",
                ihlal_alt_tipi="baretsiz",
                bolge="Hat-3",
                guven_skoru=0.98,
                tespit_zamani=now - timedelta(minutes=18),
                vardiya="2",
            ),
            Violation(
                id="v2",
                tesis_id="T-1001",
                kamera_id="cam-02",
                ihlal_tipi="yangin",
                ihlal_alt_tipi="acik_alev",
                bolge="Depo",
                guven_skoru=0.94,
                tespit_zamani=now - timedelta(minutes=11),
                vardiya="2",
            ),
            Violation(
                id="v3",
                tesis_id="T-1001",
                kamera_id="cam-03",
                ihlal_tipi="ppe_ihlali",
                ihlal_alt_tipi="baretsiz",
                bolge="Hat-3",
                guven_skoru=0.96,
                tespit_zamani=now - timedelta(minutes=7),
                vardiya="2",
            ),
        ],
    )

    result = await create_report(request)
    print("Toplam ihlal:", result["toplam_ihlal"])
    print("Kritik ihlal:", result["kritik_ihlal"])
    print("\n--- Rapor Metni ---\n")
    print(result["rapor_metni"])


if __name__ == "__main__":
    asyncio.run(main())
