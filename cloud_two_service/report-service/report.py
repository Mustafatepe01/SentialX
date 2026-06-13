import asyncio
import httpx
import litellm
from typing import List, Dict
from collections import defaultdict
from datetime import datetime
from models import Violation, ViolationGroup, ReportRequest
from config import config
import logging

try:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2 import id_token
except ImportError:  # Local mock mode does not require Google auth.
    GoogleAuthRequest = None
    id_token = None

logger = logging.getLogger(__name__)


def count_critical_violations(groups: List[ViolationGroup]) -> int:
    return sum(group.adet for group in groups if group.ihlal_tipi == "yangin")


def _fetch_rag_identity_token() -> str:
    if GoogleAuthRequest is None or id_token is None:
        raise RuntimeError("google-auth paketi RAG OIDC kimlik doğrulaması için gerekli")

    return id_token.fetch_id_token(
        GoogleAuthRequest(),
        config.RAG_SERVICE_URL.rstrip("/")
    )


async def _rag_headers() -> Dict[str, str]:
    if config.RAG_AUTH_MODE != "google_id_token":
        return {}

    token = await asyncio.to_thread(_fetch_rag_identity_token)
    return {"Authorization": f"Bearer {token}"}


def build_mock_report(request: ReportRequest, groups: List[ViolationGroup]) -> str:
    toplam_ihlal = sum(g.adet for g in groups)
    kritik_ihlal = count_critical_violations(groups)

    lines = [
        "YÖNETİCİ ÖZETİ",
        f"{request.tesis_adi} tesisinde {len(groups)} farklı ihlal grubu ve toplam {toplam_ihlal} tespit bulundu.",
        "",
        "İHLAL DETAYLARI",
    ]

    for group in groups:
        lines.append(
            f"- {group.bolge} / {group.ihlal_tipi}{' / ' + group.ihlal_alt_tipi if group.ihlal_alt_tipi else ''}: {group.adet} adet"
        )

    lines.extend([
        "",
        "YASAL YÜKÜMLÜLÜKLER",
        "İşveren, iş sağlığı ve güvenliği önlemlerini almak ve riskleri azaltmakla yükümlüdür.",
        "",
        "DÜZELTİCİ FAALİYET ÖNERİLERİ",
        "- Acil: Riskli alanların kontrol altına alınması ve ilgili çalışanların bilgilendirilmesi.",
        "- Kısa vadeli: Tekrarlayan ihlaller için denetim ve eğitim planı oluşturulması.",
        "- Uzun vadeli: Süreç iyileştirme ve kalıcı önleyici tedbirlerin devreye alınması.",
        "",
        f"Kritik ihlal sayısı: {kritik_ihlal}",
        "SONUÇ VE İMZA ALANI",
        "Bu rapor mock modda üretilmiştir.",
    ])

    return "\n".join(lines)


# ─── Gruplama ───────────────────────────────────────────────────────────────

def group_violations(violations: List[Violation]) -> List[ViolationGroup]:
    """
    İhlalleri bölge + ihlal_tipi + ihlal_alt_tipi kombinasyonuna göre grupla.
    Aynı kombinasyon → tek grup (adet bilgisiyle).
    """
    groups: Dict[str, ViolationGroup] = defaultdict(lambda: None)

    for v in violations:
        key = f"{v.bolge}|{v.ihlal_tipi}|{v.ihlal_alt_tipi or ''}"

        if groups[key] is None:
            groups[key] = ViolationGroup(
                bolge=v.bolge,
                ihlal_tipi=v.ihlal_tipi,
                ihlal_alt_tipi=v.ihlal_alt_tipi,
                adet=0,
                zamanlar=[],
                frame_urls=[],
                aciklamalar=[]
            )

        g = groups[key]
        g.adet += 1
        g.zamanlar.append(v.tespit_zamani.strftime("%H:%M"))
        if v.frame_url:
            g.frame_urls.append(v.frame_url)
        if v.aciklama:
            g.aciklamalar.append(v.aciklama)

    return list(groups.values())


# ─── RAG Entegrasyonu ────────────────────────────────────────────────────────

async def enrich_with_rag(group: ViolationGroup) -> ViolationGroup:
    """
    Her ihlal grubu için RAG servisinden mevzuat ve teknik bağlam çek.
    """
    if config.MOCK_MODE:
        return group

    try:
        headers = await _rag_headers()
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{config.RAG_SERVICE_URL}/query",
                headers=headers,
                json={
                    "violation_type": group.ihlal_tipi,
                    "violation_subtype": group.ihlal_alt_tipi,
                    "zone": group.bolge,
                    "description": group.aciklamalar[0] if group.aciklamalar else None
                }
            )
            response.raise_for_status()
            group.rag_context = response.json()
    except Exception as e:
        logger.warning(f"RAG servisi hatası ({group.bolge}): {e}")

    return group


# ─── LLM Rapor Üretimi (Gemini) ──────────────────────────────────────────────

def format_groups_for_prompt(groups: List[ViolationGroup]) -> str:
    text = ""
    for i, g in enumerate(groups, 1):
        text += f"\n### Grup {i}: {g.bolge} — {g.ihlal_alt_tipi or g.ihlal_tipi}\n"
        text += f"- Tespit sayısı: {g.adet} kez\n"
        text += f"- Tespit zamanları: {', '.join(g.zamanlar)}\n"

        if g.aciklamalar:
            text += f"- Açıklama: {g.aciklamalar[0]}\n"

        if g.rag_context:
            ctx = g.rag_context
            if ctx.get("regulations"):
                regs = [r["name"] for r in ctx["regulations"]]
                text += f"- İlgili mevzuat: {', '.join(regs)}\n"
            if ctx.get("solution_criteria", {}).get("mandatory"):
                text += f"- Zorunlu önlemler: {'; '.join(ctx['solution_criteria']['mandatory'][:2])}\n"
            if ctx.get("similar_incidents"):
                text += f"- Benzer olay: {ctx['similar_incidents'][0]}\n"

    return text


async def generate_report(request: ReportRequest, groups: List[ViolationGroup]) -> str:
    if config.MOCK_MODE or not config.GEMINI_API_KEY:
        return build_mock_report(request, groups)

    vardiya_bilgisi = config.VARDIYA_SAATLERI.get(request.vardiya, {})
    vardiya_adi = vardiya_bilgisi.get("ad", f"Vardiya {request.vardiya}")

    toplam_ihlal = sum(g.adet for g in groups)
    kritik_ihlal = count_critical_violations(groups)
    bolge_sayisi = len(set(g.bolge for g in groups))

    groups_text = format_groups_for_prompt(groups)

    prompt = f"""Sen deneyimli bir İş Sağlığı ve Güvenliği (İSG) uzmanısın.
Aşağıdaki ihlal verilerini kullanarak resmi bir Türkçe İSG vardiya raporu yaz.

## Tesis Bilgileri
- Tesis Adı: {request.tesis_adi}
- Adres: {request.tesis_adresi or "Belirtilmemiş"}
- Sorumlu İSG Uzmanı: {request.sorumlu_isg_uzmani or "Belirtilmemiş"}
- Vardiya: {vardiya_adi}
- Tarih: {request.vardiya_baslangic.strftime("%d.%m.%Y")}
- Saat: {request.vardiya_baslangic.strftime("%H:%M")} - {request.vardiya_bitis.strftime("%H:%M")}

## Özet İstatistik
- Toplam ihlal: {toplam_ihlal}
- Etkilenen bölge sayısı: {bolge_sayisi}
 - Kritik ihlal (yangın): {kritik_ihlal}

## Tespit Edilen İhlaller (Bölge ve Tür Bazlı)
{groups_text}

## Rapor Formatı
Raporu aşağıdaki bölümlerle yaz:

1. **YÖNETİCİ ÖZETİ** — Vardiyada yaşananların kısa özeti (3-4 cümle)

2. **İHLAL DETAYLARI** — Her grup için:
   - Bölge ve ihlal türü
   - Risk değerlendirmesi
   - İlgili mevzuat (madde numarasıyla)
   - Tespit edilen benzer olaylar

3. **YASAL YÜKÜMLÜLÜKLER** — İşverenin yasal yükümlülükleri

4. **DÜZELTİCİ FAALİYET ÖNERİLERİ**
   - Acil (0-24 saat)
   - Kısa vadeli (1-4 hafta)
   - Uzun vadeli (1-6 ay)

5. **SONUÇ VE İMZA ALANI**

Dil: Türkçe, resmi ve profesyonel üslup.
"""

    response = await litellm.acompletion(
        model=config.GEMINI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        api_key=config.GEMINI_API_KEY
    )

    return response.choices[0].message.content.strip()


# ─── Ana Fonksiyon ───────────────────────────────────────────────────────────

async def create_report(request: ReportRequest) -> Dict:
    # 1. Grupla
    groups = group_violations(request.violations)
    logger.info(f"İhlaller gruplandı: {len(groups)} grup")

    # 2. RAG ile zenginleştir
    enriched_groups = []
    for group in groups:
        enriched = await enrich_with_rag(group)
        enriched_groups.append(enriched)
    logger.info("RAG zenginleştirmesi tamamlandı")

    # 3. LLM rapor üret
    rapor_metni = await generate_report(request, enriched_groups)
    logger.info("Rapor üretildi")

    # 4. İstatistik
    toplam_ihlal = sum(g.adet for g in enriched_groups)
    kritik_ihlal = count_critical_violations(enriched_groups)

    return {
        "groups": enriched_groups,
        "rapor_metni": rapor_metni,
        "toplam_ihlal": toplam_ihlal,
        "kritik_ihlal": kritik_ihlal,
    }
