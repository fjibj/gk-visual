"""S8 测试：文件上传 → 解析 → S6 管线（覆盖更新）。

四种真实格式用内存字节直造（python-docx/openpyxl/python-pptx/pypdf），不落盘。
pdf 的「文本型正例」需要 PDF 写入库（reportlab/fpdf），本项目未装、也不该为测试
引入，故文本 PDF → 图留人工验收（holdout/浏览器），这里只覆盖 pypdf 能做的
「无文本层 PDF → 明确报错」路径（expectations Boundary 2）。
"""

from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from graphkb.config import Config
from graphkb.server import SUPPORTED_UPLOAD_SUFFIXES, create_app

# ---- 内存造文件 ----

SENTENCE = "周杰伦在台北小巨蛋开演唱会，蔡依林也参加了演出。"


def make_docx(text: str = SENTENCE) -> bytes:
    from docx import Document

    doc = Document()
    for para in text.splitlines():
        doc.add_paragraph(para)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_xlsx(text: str = SENTENCE) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "sheet1"
    for row in text.splitlines():
        ws.append([row])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_pptx(text: str = SENTENCE) -> bytes:
    from pptx import Presentation

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])  # blank layout
    slide.shapes.title.text = text if text else " "
    buf = BytesIO()
    prs.save(buf)
    return buf.getvalue()


def make_pdf_blank() -> bytes:
    """pypdf 只能造无文本层的空 PDF——正好是「扫描版」形态的 fixture。"""
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = BytesIO()
    w.write(buf)
    return buf.getvalue()


@pytest.fixture
def client(mock_config):
    """每测试一个独立 app：fresh rag（mock LLM/embedding）+ 可控 max_upload_mb。"""
    app = create_app(config=mock_config)
    with TestClient(app) as c:
        yield c


# ---- 解析层单测（extract_text 是 LightRAG 的，这里锁行为防升级静默变）----

def test_extract_text_formats():
    from lightrag.parser.legacy import extract_text

    assert SENTENCE in extract_text(make_docx(), "docx")
    assert SENTENCE in extract_text(make_xlsx(), "xlsx")
    assert SENTENCE in extract_text(make_pptx(), "pptx")
    assert "你好 world" == extract_text("你好 world".encode("utf-8"), "txt")


def test_extract_text_blank_pdf_yields_empty():
    from lightrag.parser.legacy import extract_text

    assert extract_text(make_pdf_blank(), "pdf").strip() == ""


# ---- 端点上成功路径 ----

def test_upload_docx_grows_document_list(client):
    r = client.post(
        "/api/documents/upload",
        files={"file": ("演唱会.docx", make_docx(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "演唱会"  # 未给 title → 文件名 stem
    assert body["doc_id"] == "演唱会"
    assert body["chars"] > 0
    # 文档确实进了列表（mock LLM 抽不出实体，但 doc 记录与计数结构都在）
    docs = client.get("/api/documents").json()["documents"]
    assert any(d["doc_id"] == "演唱会" for d in docs)


def test_upload_with_explicit_title_overrides_stem(client):
    r = client.post(
        "/api/documents/upload",
        data={"title": "周杰伦演唱会记录"},
        files={"file": ("random_name.xlsx", make_xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["doc_id"] == "周杰伦演唱会记录"


def test_upload_txt(client):
    r = client.post(
        "/api/documents/upload",
        files={"file": ("note.txt", "纯文本内容，张三住在北京。".encode("utf-8"), "text/plain")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["title"] == "note"


# ---- 端点上失败路径 ----

def test_upload_unsupported_suffix_rejected(client):
    r = client.post("/api/documents/upload", files={"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")})
    assert r.status_code == 400
    assert "不支持" in r.json()["detail"]


def test_upload_no_extension_rejected(client):
    r = client.post("/api/documents/upload", files={"file": ("README", b"data", "text/plain")})
    assert r.status_code == 400
    assert "不支持" in r.json()["detail"]


def test_upload_corrupt_docx_reports_error(client):
    r = client.post(
        "/api/documents/upload",
        files={"file": ("broken.docx", b"PK\x03\x04 not really a zip", "application/octet-stream")},
    )
    assert r.status_code == 400
    assert "解析失败" in r.json()["detail"]


def test_upload_empty_docx_rejected(client):
    """合法 docx 但没有任何段落 → 明确报错，不入库（Failure 3）。"""
    empty = make_docx("")
    r = client.post(
        "/api/documents/upload",
        files={"file": ("空文档.docx", empty, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert r.status_code == 400
    assert "抽不出文本" in r.json()["detail"]


def test_upload_blank_pdf_rejected_with_ocr_hint(client):
    """扫描版 PDF（无文本层）→ 提示需 OCR（Boundary 2）。"""
    r = client.post(
        "/api/documents/upload",
        files={"file": ("scan.pdf", make_pdf_blank(), "application/pdf")},
    )
    assert r.status_code == 400
    assert "OCR" in r.json()["detail"]


def test_upload_oversize_rejected(client, mock_config):
    mock_config.max_upload_mb = 0  # 任何非空文件都超限
    r = client.post(
        "/api/documents/upload",
        files={"file": ("big.pdf", b"x" * 100, "application/pdf")},
    )
    assert r.status_code == 413
    assert "上限" in r.json()["detail"]


def test_supported_suffix_whitelist_contains_docs_formats():
    assert {"docx", "xlsx", "pptx", "pdf", "txt", "md"} <= SUPPORTED_UPLOAD_SUFFIXES
