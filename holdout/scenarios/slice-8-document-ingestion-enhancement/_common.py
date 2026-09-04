"""共享 harness：S8 文档摄取考卷（真实 LLM + 真实 bge-m3）。

文件解析与「解析→图」的整条链要真跑（解析层是真的、图抽取是 LLM 的活），
考卷必须用真实 LLM（火山）+ bge-m3（Ollama），复用 S6 的做法。

HTTP 层（4xx 文案、大小上限、白名单）由 tests/test_upload.py 覆盖（12 例）；
本考卷聚焦业务语义：字节→文本→图、覆盖更新、解析失败可见、无文本层检出。

每个场景独立 tempdir + 唯一 workspace（隔离 LightRAG 全局存储缓存）。
"""

from __future__ import annotations

import os
import tempfile
from io import BytesIO

from graphkb.config import load_config
from graphkb.rag import init_rag

# 中文内容句（与 S6/S7 考卷同源的稳定抽取句）
DOCX_TEXT = "张三是一位软件工程师，他居住在北京。张三于2020年加入了字节跳动公司，担任后端工程师。"
XLSX_TEXT = "李四是一名产品经理，他在北京工作。李四于2021年加入了字节跳动公司。"
PPTX_TEXT = "周杰伦在台北小巨蛋开演唱会，蔡依林也参加了演出。"
# PDF 正例用 ASCII（手写最小 PDF 无 CID 字体，只能嵌拉丁文本）
PDF_TEXT = "Alice works at Acme Inc in Boston. Bob is her colleague at Acme."


# ---- 内存造文件（与 tests/test_upload.py 同源，S8 判定不依赖磁盘）----

def make_docx(text: str = DOCX_TEXT) -> bytes:
    from docx import Document

    doc = Document()
    for para in text.splitlines():
        doc.add_paragraph(para)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_xlsx(texts: list[str]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    for i, text in enumerate(texts, start=1):
        ws = wb.create_sheet(f"sheet{i}")
        for row in text.splitlines():
            ws.append([row])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def minimal_text_pdf(text: str) -> bytes:
    """手写合法最小 PDF（xref 逐字节精确）——纯标准库，S8 不引入 PDF 写入库。"""
    objs: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += b"trailer\n<< /Size " + str(len(objs) + 1).encode() + b" /Root 1 0 R >>\n"
    out += f"startxref\n{xref_pos}\n%%EOF\n".encode()
    return bytes(out)


def make_pdf(text: str = PDF_TEXT) -> bytes:
    return minimal_text_pdf(text)


def make_pdf_blank() -> bytes:
    """无文本层的空 PDF（扫描版形态）：pypdf 只能造这种，正好当 fixture。"""
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = BytesIO()
    w.write(buf)
    return buf.getvalue()


# ---- rag 生命周期（同 slice-6 _common.py 模式）----

def make_config(workdir):
    cfg = load_config()
    cfg.working_dir = str(workdir)
    cfg.workspace = f"s8-{os.path.basename(str(workdir))}"
    return cfg


async def run_with_rag(fn):
    """构建真实 rag，执行 fn(rag) -> (passed, detail)，自动清理临时目录。"""
    td = tempfile.TemporaryDirectory()
    try:
        rag = await init_rag(make_config(td.name))
        result = await fn(rag)
        await rag.finalize_storages()
        return result
    finally:
        td.cleanup()
