"""Boundary 2：多工作表 .xlsx → 所有工作表文本都被解析（行为可预期，不漏表）。"""
from _common import make_xlsx, run_with_rag
from lightrag.parser.legacy import extract_text

SHEET1 = "王五是一名产品设计师，他在深圳工作。"
SHEET2 = "赵六是一名数据工程师，他在广州工作。"

NAME = "b2_multisheet_xlsx_all_sheets"
EXPECTATION = "Boundary 3: 多工作表 xlsx → 所有表都进文本"


async def run():
    async def body(rag):
        text = extract_text(make_xlsx([SHEET1, SHEET2]), "xlsx")
        # 两张表的人物都应出现在同一份解析文本里（漏表 = 行为不可预期）
        ok = "王五" in text and "赵六" in text and "深圳" in text and "广州" in text
        if not ok:
            return False, f"多表解析漏内容: {text[:120]!r}"
        return ok, f"两张表都解析到（共 {len(text)} 字符）"

    return await run_with_rag(body)
