"""프리미엄 다중 포맷(Word .docx / PDF .pdf / 요약 카드 Image .png) 보고서 생성기."""

from __future__ import annotations

import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import first_existing_font
from app.services.ocr_masking import get_korean_font_path

BASE_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = BASE_DIR / "generated_reports"


def _register_pdf_font() -> str:
    """ReportLab에 한글 TTF 폰트를 등록하고 폰트 이름을 반환한다."""
    font_name = "MedihanGothic"
    if font_name in pdfmetrics.getRegisteredFontNames():
        return font_name

    font_path = first_existing_font()
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont(font_name, font_path, subfontIndex=0) if font_path.lower().endswith(".ttc") else TTFont(font_name, font_path))
            return font_name
        except Exception:
            pass
    return "Helvetica"


def _load_pil_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_path = get_korean_font_path()
    if font_path:
        try:
            return ImageFont.truetype(font_path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def generate_word_report(payload: Dict[str, Any], out_path: Path) -> Path:
    """Word(.docx) 형식의 의료 서류 해설 보고서를 생성한다."""
    doc = Document()

    normal_style = doc.styles["Normal"]
    font_path = first_existing_font()
    if font_path:
        normal_style.font.name = Path(font_path).stem
    normal_style.font.size = Pt(10.5)

    title = doc.add_heading("메디한(Medihan) 의료 서류 해설 리포트", level=0)
    for run in title.runs:
        run.font.color.rgb = RGBColor(15, 76, 129)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    meta = doc.add_paragraph()
    meta.add_run(f"생성 일시: {now_str}\n").bold = True
    meta.add_run("개인정보 보호: 비식별 처리 완료 (민감정보 미포함)")

    doc.add_heading("1. 검진 수치 판정 결과", level=1)
    evaluations: List[Dict[str, Any]] = payload.get("evaluations", [])
    if evaluations:
        table = doc.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        headers = ["검사항목", "측정 수치", "참고치", "판정", "권고 진료과"]
        for i, h in enumerate(headers):
            cell = table.rows[0].cells[i]
            cell.text = h
            for p in cell.paragraphs:
                for r in p.runs:
                    r.bold = True

        for ev in evaluations:
            row = table.add_row().cells
            row[0].text = str(ev.get("item", ""))
            row[1].text = f"{ev.get('value', '')} {ev.get('unit', '')}".strip()
            row[2].text = str(ev.get("reference", ""))
            row[3].text = str(ev.get("status", ""))
            row[4].text = str(ev.get("department", "-"))
    else:
        doc.add_paragraph("이 서류에서 판정 가능한 검진 수치가 확인되지 않았습니다.")

    doc.add_heading("2. 서류 해설", level=1)
    summary_text = str(payload.get("summary_text", ""))
    for line in summary_text.splitlines():
        clean = line.replace("**", "").strip()
        if clean:
            doc.add_paragraph(clean)

    rag_sources: List[Dict[str, Any]] = payload.get("rag_sources", [])
    if rag_sources:
        doc.add_heading("3. 참고 근거 자료", level=1)
        for src in rag_sources:
            p = doc.add_paragraph(style="List Bullet")
            p.add_run(f"{src.get('title', '')} ").bold = True
            p.add_run(f"({src.get('source', '')})")

    hospitals: List[Dict[str, Any]] = payload.get("hospitals", [])
    if hospitals:
        doc.add_heading("4. 병원 검색 결과", level=1)
        for hosp in hospitals:
            p = doc.add_paragraph(style="List Bullet")
            p.add_run(f"[{hosp.get('department', '')}] {hosp.get('name', '')}").bold = True
            p.add_run(f" - {hosp.get('address', '')} / {hosp.get('reason', '')}")

    doc.add_paragraph("\n※ 본 보고서는 이해를 돕기 위한 참고 자료이며 원본 서류와 담당 의사의 설명이 우선입니다.").italic = True
    doc.save(str(out_path))
    return out_path


def generate_pdf_report(payload: Dict[str, Any], out_path: Path) -> Path:
    """PDF(.pdf) 형식의 의료 서류 해설 보고서를 생성한다."""
    font_name = _register_pdf_font()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=44,
        bottomMargin=40,
    )

    base_styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "MedihanTitle",
        parent=base_styles["Normal"],
        fontName=font_name,
        fontSize=18,
        leading=24,
        textColor=colors.HexColor("#0F4C81"),
        spaceAfter=10,
    )
    style_h2 = ParagraphStyle(
        "MedihanH2",
        parent=base_styles["Normal"],
        fontName=font_name,
        fontSize=13,
        leading=18,
        textColor=colors.HexColor("#0F4C81"),
        spaceBefore=12,
        spaceAfter=6,
    )
    style_body = ParagraphStyle(
        "MedihanBody",
        parent=base_styles["Normal"],
        fontName=font_name,
        fontSize=9.5,
        leading=14.5,
        textColor=colors.HexColor("#1E293B"),
        spaceAfter=4,
    )
    style_cell = ParagraphStyle(
        "MedihanCell",
        parent=base_styles["Normal"],
        fontName=font_name,
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#1E293B"),
    )

    story: List[Any] = []
    story.append(Paragraph("메디한(Medihan) 의료 서류 해설 리포트", style_title))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    story.append(
        Paragraph(
            f"생성 일시: {now_str}  |  개인정보 보호: 민감정보 비식별 처리 완료",
            style_body,
        )
    )
    story.append(Spacer(1, 8))

    story.append(Paragraph("1. 검진 수치 판정 결과", style_h2))
    evaluations: List[Dict[str, Any]] = payload.get("evaluations", [])
    if evaluations:
        table_data = [
            [
                Paragraph("검사항목", style_cell),
                Paragraph("측정값", style_cell),
                Paragraph("참고치", style_cell),
                Paragraph("판정", style_cell),
                Paragraph("권고 진료과", style_cell),
            ]
        ]
        for ev in evaluations:
            table_data.append(
                [
                    Paragraph(str(ev.get("item", "")), style_cell),
                    Paragraph(f"{ev.get('value', '')} {ev.get('unit', '')}", style_cell),
                    Paragraph(str(ev.get("reference", "")), style_cell),
                    Paragraph(str(ev.get("status", "")), style_cell),
                    Paragraph(str(ev.get("department", "-")), style_cell),
                ]
            )
        tbl = Table(table_data, colWidths=[125, 95, 115, 80, 95])
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F0F8")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(tbl)
    else:
        story.append(Paragraph("이 서류에서 판정 가능한 검진 수치가 확인되지 않았습니다.", style_body))

    story.append(Paragraph("2. 서류 해설", style_h2))
    summary_text = str(payload.get("summary_text", ""))
    for line in summary_text.splitlines():
        safe_line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("**", "").strip()
        if safe_line:
            story.append(Paragraph(safe_line, style_body))

    rag_sources: List[Dict[str, Any]] = payload.get("rag_sources", [])
    if rag_sources:
        story.append(Paragraph("3. 참고 근거 자료", style_h2))
        for src in rag_sources:
            t = f"• {src.get('title', '')} ({src.get('source', '')})".replace("&", "&amp;")
            story.append(Paragraph(t, style_body))

    hospitals: List[Dict[str, Any]] = payload.get("hospitals", [])
    if hospitals:
        story.append(Paragraph("4. 병원 검색 결과", style_h2))
        for hosp in hospitals:
            line = f"• [{hosp.get('department', '')}] {hosp.get('name', '')} - {hosp.get('address', '')}"
            story.append(Paragraph(line.replace("&", "&amp;"), style_body))

    doc.build(story)
    return out_path


def generate_image_card_report(payload: Dict[str, Any], out_path: Path) -> Path:
    """가족 공유 및 모바일 확인에 적합한 요약 카드 이미지(.png)를 생성한다."""
    width, height = 1080, 1460
    img = Image.new("RGB", (width, height), (248, 250, 252))
    draw = ImageDraw.Draw(img)

    f_title = _load_pil_font(38)
    f_sub = _load_pil_font(22)
    f_h2 = _load_pil_font(26)
    f_body = _load_pil_font(21)
    f_small = _load_pil_font(18)

    # 헤더 배너
    draw.rectangle([(0, 0), (width, 165)], fill=(15, 76, 129))
    draw.text((54, 38), "메디한(Medihan) 서류 해설 한눈에 보기", fill=(255, 255, 255), font=f_title)
    draw.text(
        (54, 96),
        f"생성일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}   |   개인정보 안심 보호 완료",
        fill=(186, 230, 253),
        font=f_sub,
    )

    # 1. 주요 수치 상태 카드
    y = 200
    draw.text((54, y), "1. 검진 수치 판정", fill=(15, 76, 129), font=f_h2)
    y += 46

    evaluations: List[Dict[str, Any]] = payload.get("evaluations", [])[:7]
    if not evaluations:
        draw.rectangle([(54, y), (width - 54, y + 80)], fill=(255, 255, 255), outline=(203, 213, 225), width=2)
        draw.text((78, y + 26), "판정 가능한 검진 수치가 없는 서류입니다.", fill=(51, 65, 85), font=f_body)
        y += 100
    else:
        for ev in evaluations:
            status = str(ev.get("status", "정상"))
            pill_bg = (220, 252, 231)
            pill_fg = (22, 101, 52)
            if "의심" in status or "위험" in status:
                pill_bg = (254, 226, 226)
                pill_fg = (185, 28, 28)
            elif "경계" in status or "주의" in status or "과체중" in status:
                pill_bg = (254, 243, 199)
                pill_fg = (180, 83, 9)

            draw.rounded_rectangle(
                [(54, y), (width - 54, y + 74)],
                radius=14,
                fill=(255, 255, 255),
                outline=(226, 232, 240),
                width=2,
            )
            draw.text((80, y + 22), str(ev.get("item", "")), fill=(15, 23, 42), font=f_body)
            val_text = f"{ev.get('value', '')} {ev.get('unit', '')}".strip()
            draw.text((480, y + 22), val_text, fill=(30, 41, 59), font=f_body)

            draw.rounded_rectangle([(770, y + 14), (1000, y + 60)], radius=12, fill=pill_bg)
            draw.text((795, y + 24), status, fill=pill_fg, font=f_small)
            y += 86

    # 2. 핵심 AI 요약
    y += 16
    draw.text((54, y), "2. 서류 해설 요약", fill=(15, 76, 129), font=f_h2)
    y += 44
    box_h = max(250, min(420, height - y - 130))
    draw.rounded_rectangle([(54, y), (width - 54, y + box_h)], radius=16, fill=(255, 255, 255), outline=(203, 213, 225), width=2)

    raw_summary = str(payload.get("summary_text", "")).replace("**", "").replace("#", "")
    wrapped_lines: List[str] = []
    for para in raw_summary.splitlines():
        p = para.strip()
        if not p:
            continue
        wrapped_lines.extend(textwrap.wrap(p, width=44))

    ty = y + 24
    for line in wrapped_lines[:11]:
        if ty + 30 > y + box_h - 16:
            break
        draw.text((78, ty), line, fill=(30, 41, 59), font=f_small)
        ty += 30

    # 푸터
    draw.rectangle([(0, height - 84), (width, height)], fill=(226, 232, 240))
    draw.text(
        (54, height - 54),
        "메디한(Medihan) | 참고용 해설 · 원본 서류와 담당 의사의 설명이 우선입니다",
        fill=(71, 85, 105),
        font=f_small,
    )

    img.save(out_path, format="PNG")
    return out_path


def generate_reports_bundle(payload: Dict[str, Any], formats: List[str] | None = None) -> Dict[str, Dict[str, str]]:
    """고유 파일명·만료되는 임시 다운로드 URL을 사용해 보고서를 생성한다."""
    from uuid import uuid4
    from app.services.download_links import cleanup_report_files, sign_download_url

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_report_files(REPORTS_DIR)
    target_formats = formats if formats is not None else ["docx", "pdf", "png"]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]

    results: Dict[str, Dict[str, str]] = {}
    if "docx" in target_formats:
        name = f"medihan_report_{stamp}.docx"
        generate_word_report(payload, REPORTS_DIR / name)
        results["docx"] = {
            "filename": name,
            "label": "Word 보고서 (.docx)",
            "url": sign_download_url(name),
        }

    if "pdf" in target_formats:
        name = f"medihan_report_{stamp}.pdf"
        generate_pdf_report(payload, REPORTS_DIR / name)
        results["pdf"] = {
            "filename": name,
            "label": "PDF 결과지 (.pdf)",
            "url": sign_download_url(name),
        }

    if "png" in target_formats:
        name = f"medihan_report_{stamp}.png"
        generate_image_card_report(payload, REPORTS_DIR / name)
        results["png"] = {
            "filename": name,
            "label": "요약 카드 이미지 (.png)",
            "url": sign_download_url(name),
        }

    return results