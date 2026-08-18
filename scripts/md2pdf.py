"""md → PDF（reportlab 表格渲染，pandoc/weasyprint 不可用时的方案）."""
import sys
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

# 注册 CJK 字体（中文支持，STSong-Light 为 reportlab 内置 CID 字体）
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))

def md2pdf(md_path, pdf_path):
    md = open(md_path).read()
    doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                            leftMargin=15*mm, rightMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle('h1c', parent=styles['Heading1'], fontName='STSong-Light', fontSize=16, spaceAfter=8)
    h2 = ParagraphStyle('h2c', parent=styles['Heading2'], fontName='STSong-Light', fontSize=13, spaceAfter=6)
    body = ParagraphStyle('bodyc', parent=styles['BodyText'], fontName='STSong-Light', fontSize=9, leading=13)
    story = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('# '):
            story.append(Paragraph(line[2:], h1))
        elif line.startswith('## '):
            story.append(Paragraph(line[3:], h2))
        elif line.startswith('> '):
            story.append(Paragraph(line[2:], body))
        elif line.startswith('|') and i+1 < len(lines) and lines[i+1].startswith('|:'):
            table_lines = []
            while i < len(lines) and lines[i].startswith('|'):
                table_lines.append(lines[i]); i += 1
            if len(table_lines) >= 2:
                header = [c.strip() for c in table_lines[0].strip('|').split('|')]
                rows = [[c.strip() for c in l.strip('|').split('|')] for l in table_lines[2:]]
                t = Table([header] + rows, repeatRows=1)
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e8e8e8')),
                    ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                    ('FONTSIZE', (0,0), (-1,-1), 8),
                    ('FONTNAME', (0,0), (-1,-1), 'STSong-Light'),
                    ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ]))
                story.append(t); story.append(Spacer(1, 6))
            continue
        elif line.strip() == '':
            story.append(Spacer(1, 4))
        elif line.startswith('- '):
            story.append(Paragraph('• ' + line[2:], body))
        else:
            story.append(Paragraph(line, body))
        i += 1
    doc.build(story)

if __name__ == '__main__':
    md2pdf(sys.argv[1], sys.argv[2])
    print(f'PDF 生成: {sys.argv[2]}')
