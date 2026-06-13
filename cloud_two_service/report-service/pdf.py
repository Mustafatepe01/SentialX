import io
import os
from datetime import datetime
from pathlib import Path
from typing import List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from config import config
from models import ReportRequest, ViolationGroup
from report import count_critical_violations


def create_pdf(
    request: ReportRequest,
    groups: List[ViolationGroup],
    rapor_metni: str,
    rapor_id: str,
) -> bytes:
    font_name = _register_unicode_font()

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.8 * cm,
        leftMargin=1.8 * cm,
        topMargin=1.7 * cm,
        bottomMargin=1.6 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleCustom",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=17,
        leading=21,
        textColor=colors.HexColor("#1d3557"),
        spaceAfter=10,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleCustom",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=10.5,
        leading=13,
        textColor=colors.HexColor("#4a4a4a"),
    )
    section_style = ParagraphStyle(
        "SectionCustom",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=12.5,
        leading=15,
        textColor=colors.HexColor("#1d3557"),
        spaceBefore=8,
        spaceAfter=5,
    )
    normal_style = ParagraphStyle(
        "NormalCustom",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=9.8,
        leading=13,
    )
    small_style = ParagraphStyle(
        "SmallCustom",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=8.6,
        leading=10.5,
        textColor=colors.HexColor("#666666"),
    )

    vardiya_bilgisi = config.VARDIYA_SAATLERI.get(request.vardiya, {})
    vardiya_adi = vardiya_bilgisi.get("ad", f"Vardiya {request.vardiya}")
    toplam_ihlal = sum(g.adet for g in groups)
    kritik_ihlal = count_critical_violations(groups)
    bolge_sayisi = len(set(g.bolge for g in groups))

    story = []
    story.append(Paragraph("SENTIALX İŞ SAĞLIĞI VE GÜVENLİĞİ VARDİYA RAPORU", title_style))
    story.append(Paragraph("Resmi İç Kullanım Raporu", subtitle_style))
    story.append(Spacer(1, 6))

    info_rows = [
        [Paragraph("Rapor No", normal_style), Paragraph(rapor_id[:8].upper(), normal_style), Paragraph("Tarih", normal_style), Paragraph(request.vardiya_baslangic.strftime("%d.%m.%Y"), normal_style)],
        [Paragraph("Tesis Adı", normal_style), Paragraph(_escape_pdf_text(request.tesis_adi), normal_style), Paragraph("Vardiya", normal_style), Paragraph(_escape_pdf_text(vardiya_adi), normal_style)],
        [Paragraph("Saat Aralığı", normal_style), Paragraph(f"{request.vardiya_baslangic.strftime('%H:%M')} - {request.vardiya_bitis.strftime('%H:%M')}", normal_style), Paragraph("Hazırlayan", normal_style), Paragraph(_escape_pdf_text(request.sorumlu_isg_uzmani or "İSG Uzmanı"), normal_style)],
    ]
    info_table = Table(info_rows, colWidths=[2.6 * cm, 5.6 * cm, 2.4 * cm, 5.0 * cm])
    info_table.setStyle(_table_style(header=False))
    story.append(info_table)
    story.append(Spacer(1, 10))

    story.extend(_section_block("1. Yönetici Özeti", section_style, normal_style,
        [
            f"Bu rapor, {request.tesis_adi} tesisinde {vardiya_adi} sırasında tespit edilen güvenlik ihlallerini resmi kayıt amacıyla özetlemektedir.",
            f"Toplam {toplam_ihlal} ihlal tespit edilmiş, {bolge_sayisi} farklı bölge etkilenmiş ve {kritik_ihlal} kritik ihlal kayda alınmıştır.",
        ]
    ))

    story.append(Paragraph("2. İhlal Detayları", section_style))
    detail_rows = [[
        Paragraph("Bölge", normal_style),
        Paragraph("İhlal Türü", normal_style),
        Paragraph("Alt Tür", normal_style),
        Paragraph("Adet", normal_style),
        Paragraph("Tespit Saatleri", normal_style),
    ]]
    for group in groups:
        detail_rows.append([
            Paragraph(_escape_pdf_text(group.bolge), normal_style),
            Paragraph(_escape_pdf_text(group.ihlal_tipi), normal_style),
            Paragraph(_escape_pdf_text(group.ihlal_alt_tipi or "-"), normal_style),
            Paragraph(str(group.adet), normal_style),
            Paragraph(_escape_pdf_text(", ".join(group.zamanlar)), normal_style),
        ])
    detail_table = Table(detail_rows, colWidths=[3.2 * cm, 3.2 * cm, 3.2 * cm, 1.2 * cm, 4.8 * cm])
    detail_table.setStyle(_table_style(header=True))
    story.append(detail_table)
    story.append(Spacer(1, 8))

    story.append(Paragraph("3. LLM Tarafından Oluşturulan Metin", section_style))
    for line in rapor_metni.splitlines():
        text = line.strip()
        if not text:
            story.append(Spacer(1, 3))
            continue
        if text.startswith(("1.", "2.", "3.", "4.", "5.")):
            story.append(Paragraph(_escape_pdf_text(text), normal_style))
        else:
            story.append(Paragraph(_escape_pdf_text(text), normal_style))

    story.append(Spacer(1, 8))
    story.append(Paragraph("4. Düzeltici Faaliyet Planı", section_style))
    action_rows = [[
        Paragraph("Öncelik", normal_style),
        Paragraph("Zaman", normal_style),
        Paragraph("Faaliyet", normal_style),
    ],
        [Paragraph("Acil", normal_style), Paragraph("0-24 saat", normal_style), Paragraph("Riskli alanların kontrol altına alınması, ilgili çalışanların bilgilendirilmesi ve geçici önlem uygulanması.", normal_style)],
        [Paragraph("Kısa Vadeli", normal_style), Paragraph("1-4 hafta", normal_style), Paragraph("Tekrarlayan ihlaller için eğitim, denetim ve takip planının devreye alınması.", normal_style)],
        [Paragraph("Uzun Vadeli", normal_style), Paragraph("1-6 ay", normal_style), Paragraph("Süreç iyileştirme, kalıcı önleyici tedbirler ve periyodik performans takibi.", normal_style)],
    ]
    action_table = Table(action_rows, colWidths=[2.3 * cm, 2.8 * cm, 9.5 * cm])
    action_table.setStyle(_table_style(header=True))
    story.append(action_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("5. Onay ve İmza", section_style))
    sign_rows = [[
        Paragraph(_escape_pdf_text(request.sorumlu_isg_uzmani or "İSG Uzmanı"), normal_style),
        Paragraph("Tesis Yöneticisi", normal_style),
    ],
    [
        Paragraph("İmza / Tarih", small_style),
        Paragraph("İmza / Tarih", small_style),
    ]]
    sign_table = Table(sign_rows, colWidths=[8.0 * cm, 8.0 * cm])
    sign_table.setStyle(_table_style(header=False, emphasize_bottom=True))
    story.append(sign_table)
    story.append(Spacer(1, 8))

    footer_rows = [[
        Paragraph(f"Hazırlanma Zamanı: {datetime.now().strftime('%d.%m.%Y %H:%M')}", small_style),
        Paragraph("6331 sayılı İş Sağlığı ve Güvenliği Kanunu kapsamında hazırlanmıştır.", small_style),
    ]]
    footer_table = Table(footer_rows, colWidths=[8.0 * cm, 8.0 * cm])
    footer_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f6f8")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d0d7de")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d0d7de")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(footer_table)

    document.build(story)
    return buffer.getvalue()


def _section_block(title: str, section_style: ParagraphStyle, normal_style: ParagraphStyle, lines: List[str]):
    block = [Paragraph(title, section_style)]
    for line in lines:
        block.append(Paragraph(_escape_pdf_text(line), normal_style))
        block.append(Spacer(1, 2))
    block.append(Spacer(1, 4))
    return block


def _table_style(header: bool, emphasize_bottom: bool = False):
    style_commands = [
        ("FONTNAME", (0, 0), (-1, -1), "ArialUnicode"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.2),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#1d3557")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#9fb3c8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style_commands.extend([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe7f3")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1d3557")),
            ("FONTNAME", (0, 0), (-1, 0), "ArialUnicode"),
            ("FONTSIZE", (0, 0), (-1, 0), 9.3),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ])
    if emphasize_bottom:
        style_commands.append(("LINEBELOW", (0, 1), (-1, 1), 0.8, colors.HexColor("#1d3557")))
    return TableStyle(style_commands)


def _escape_pdf_text(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _register_unicode_font() -> str:
    font_name = "ArialUnicode"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        candidate_paths = [
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf",
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
        ]
        font_path = next((path for path in candidate_paths if path.exists()), None)
        if font_path is None:
            raise RuntimeError("Unicode PDF font not found")
        pdfmetrics.registerFont(TTFont(font_name, font_path))
    return font_name
