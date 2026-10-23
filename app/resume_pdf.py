"""resume_pdf.py —— 简历排版生成器：ResumeData + 改写结果 → 正式简历 PDF（中英双语）。

【模块说明】
    第三轮需求扩展（团队拍板）：导出物在"诊断报告"之外，新增"排版后的正式
    修改版简历"，中文版 + 英文版（面向投递外企场景）。
    排版规格（团队提供的视觉稿 + 第十轮专业化升级）：
        - A4 版面，目标单页（内容溢出时自然分页，不截断、不丢信息）；
        - 姓名超大粗体（左上），证件照右上（从旧 PDF 提取复用，无照片则省略）；
        - 姓名下方醒目展示"求职意向"（job_intent，导出时由界面传入当前岗位名）；
        - 联系信息双列；分节标题粗体 + 粗黑分割线；
        - 经历条目"组织名 | 职位 | 时间"三栏布局，全部按时间倒序（最近的在最前）；
        - 要点以 ➢ 符号逐条列出，行首【小标题】加粗渲染（HR 扫读锚点）；
        - 不渲染"自我评价"（resume_extract 已不提取该区块），不印任何内部过程提示。
    改写应用策略：
        先按 normalize 匹配把 rewrites 应用到富结构条目（纯函数，可单测），
        英文版在"改写之后"整体翻译（只翻译一次，保证中英内容一致）。

【依赖清单】
    第三方：reportlab
    项目内：config, contracts, llm_client

【审查提示（给 DeepSeek）】
    apply_rewrites 是纯函数（不进不出 LLM），匹配规则逐位可复现，建议优先单测；
    英文版新增的 LLM 调用仅经 llm_client.chat("resume_translate", ...)，
    缓存键由输入富结构决定，预热脚本会覆盖该 prompt_key。
"""

from __future__ import annotations

import io
import json
import re

import config
import llm_client
from contracts import (
    PDFExportError,
    ResumeData,
    ResumeEntry,
    RewriteResult,
    validate_resume_data,
)

# 经历分节在页面上的展示顺序与标题（中英对照表）
_SECTIONS = {
    "zh": [("education_entries", "教育背景"), ("internship_entries", "实习经历"),
           ("project_entries", "项目经历")],
    "en": [("education_entries", "EDUCATION"), ("internship_entries", "INTERNSHIP"),
           ("project_entries", "PROJECTS")],
}
_SKILLS_TITLE = {"zh": "技能证书", "en": "SKILLS"}
_INTENT_LABEL = {"zh": "求职意向", "en": "Career Objective"}

# 经历时间倒序：period 尾部的年月作为排序键（如 "2023.07-2023.09" → (2023, 9)）
_PERIOD_DATE_RE = re.compile(r"(\d{4})\s*[./年-]\s*(\d{1,2})")
_PRESENT_WORDS = ("至今", "现在", "present", "now", "current")

# 改写匹配允许的最低重叠度（防止 example_before 与 bullet 仅个别字相同就误替换）
_MIN_OVERLAP_CHARS = 8


def _period_sort_key(period: str) -> tuple[int, int, int]:
    """从时间段文本提取倒序排序键（越大越新）。

    规则（专业简历惯例：最近经历排最前）：
        - 含"至今/present"等词 → 最大键（ ongoing 经历永远最前）；
        - 取 period 中**最后一个**年月（结束时间，如 "2023.07-2023.09" → 2023.09）；
          只有单个年月时用它本身；
        - 完全无法解析 → 最小键（排在最后，稳定排序保持原相对顺序）。

    Returns:
        (是否可解析, 年, 月) 三元组，可直接用于 sorted(key=..., reverse=True)。
    """
    text = period.strip().lower()
    if any(w in text for w in _PRESENT_WORDS):
        return (2, 9999, 12)  # 进行中：永远排最前
    matches = _PERIOD_DATE_RE.findall(text)
    if not matches:
        return (0, 0, 0)  # 不可解析：排最后
    year, month = matches[-1]  # 结束时间代表"最近程度"
    return (1, int(year), int(month))


def _sort_entries_desc(entries: list[ResumeEntry]) -> list[ResumeEntry]:
    """经历条目按时间倒序排列（纯函数，不修改入参）。

    应用于教育/实习/项目全部分节（第十轮指令模块二第 3 条）。
    稳定排序：时间相同或都不可解析的条目保持原有相对顺序。
    """
    return sorted(entries, key=lambda e: _period_sort_key(e["period"]), reverse=True)


def _normalize(text: str) -> str:
    """匹配用归一化：移除全部空白字符（与 llm_client 对 str 的缓存口径一致）。"""
    return re.sub(r"\s+", "", text)


def _strip_md_prefix(line: str) -> str:
    """剥掉行首 markdown 符号（与 pdf_exporter._clean_md 同口径，此处只需单行版）。"""
    return re.sub(r"^\s{0,4}(?:[-*•➢]|#{1,6})\s+", "", line).strip()


def _split_after(example_after: str) -> list[str]:
    """把改写后文本拆成 bullet 列表：按行拆分、剥符号前缀、去空行。

    防御规则：拆分后为空时返回空列表（调用方决定保留原 bullet，不删信息）。
    """
    return [s for s in (_strip_md_prefix(x) for x in example_after.split("\n")) if s]


def _bullet_matches(bullet: str, before: str) -> bool:
    """判断单条 bullet 是否被某条改写的 example_before 命中。

    规则（双向包含 + 最低重叠度）：
        normalize 后 before 是 bullet 的子串，或 bullet 是 before 的子串，
        且较短者长度 ≥ _MIN_OVERLAP_CHARS。
    双向包含覆盖两种常见情况：LLM 引用整段（before 更长）/ 引用片段（before 更短）。
    """
    nb, nf = _normalize(bullet), _normalize(before)
    if not nb or not nf:
        return False
    if min(len(nb), len(nf)) < _MIN_OVERLAP_CHARS:
        return False
    return nf in nb or nb in nf


def apply_rewrites(
    entries: list[ResumeEntry],
    rewrites: list[RewriteResult],
) -> tuple[list[ResumeEntry], list[str]]:
    """把改写结果应用到经历条目（纯函数，不修改入参）。

    Args:
        entries: 某一类经历条目（internship_entries 等任一列表均可传入）。
        rewrites: 改写结果列表；example_before 命中某 bullet 则整条替换，
            多命中只取第一个（后续命中不再处理，防止同一段被覆盖两次）。

    Returns:
        (新条目列表, 实际应用的 gap_id 列表)。未命中的改写不在返回的 id 列表中，
        供调用方/界面提示"该建议需人工手动应用"。
    """
    # 深拷贝到足够粒度：bullets 列表会被替换，entry dict 需新建
    new_entries: list[ResumeEntry] = [
        {"org": e["org"], "role": e["role"], "period": e["period"], "bullets": list(e["bullets"])}
        for e in entries
    ]
    applied: list[str] = []
    for rw in rewrites:
        hit = False
        for entry in new_entries:
            for idx, bullet in enumerate(entry["bullets"]):
                if _bullet_matches(bullet, rw["example_before"]):
                    replacement = _split_after(rw["example_after"])
                    if replacement:
                        # 命中：该 bullet 原位替换为改写后内容（一条可展开为多条）
                        entry["bullets"][idx:idx + 1] = replacement
                        applied.append(rw["gap_id"])
                        hit = True
                    break
            if hit:
                break
    return new_entries, applied


def translate_resume(resume: ResumeData) -> ResumeData:
    """调用 LLM 把富结构简历翻译为英文版（改写应用之后调用，只翻译一次）。

    Args:
        resume: 中文版 ResumeData（已应用改写）。

    Returns:
        英文版 ResumeData：富结构字段来自 LLM 翻译并经校验；
        raw_text / photo_bytes 直接透传（照片与语言无关；raw_text 仅供调试）。

    Raises:
        LLMOutputError: 翻译输出业务校验失败。
        LLMUnavailableError / CacheMissError: 透传自 llm_client
            （演示缓存模式下未预热会抛 CacheMissError，预热脚本已覆盖本 prompt_key）。
    """
    payload = {  # 只传 LLM 产出的字段；sort_keys 保证缓存键稳定
        "name": resume["name"],
        "contacts": resume["contacts"],
        "job_intent": resume.get("job_intent", ""),  # 求职意向随简历整体翻译（v1.2 新增）
        "education_entries": resume["education_entries"],
        "internship_entries": resume["internship_entries"],
        "project_entries": resume["project_entries"],
        "skills": resume["skills"],
    }
    data = llm_client.chat(
        "resume_translate", json.dumps(payload, ensure_ascii=False, sort_keys=True))
    validate_resume_data(data)
    data["raw_text"] = resume["raw_text"]
    data["photo_bytes"] = resume["photo_bytes"]
    # 求职意向透传兜底：翻译漏字段时保留原文（宁缺翻译，不丢信息）
    if not isinstance(data.get("job_intent"), str) or not data["job_intent"].strip():
        data["job_intent"] = resume.get("job_intent", "")
    _combine_legacy(data)
    return data  # type: ignore[return-value]


def _combine_legacy(data: dict) -> None:
    """翻译结果同样补出 legacy 字符串列表，保持 ResumeData 契约完整。"""
    for src, dst in (("education_entries", "education"),
                     ("internship_entries", "internships"),
                     ("project_entries", "projects")):
        data[dst] = [
            " ".join(x for x in (e["org"], e["role"]) if x.strip())
            + (f"（{e['period']}）" if e["period"].strip() else "")
            + (f"：{'；'.join(e['bullets'])}" if e["bullets"] else "")
            for e in data.get(src, [])
        ]


def _register_fonts() -> tuple[str, str, str]:
    """注册正文/粗体/符号三个字体，返回 (regular_name, bold_name, symbol_name)。

    符号字体（DejaVu Sans）专用于 ➢ bullet——思源黑体不含该字模，
    混排时经 Paragraph 的 <font name=...> 标签逐符号指定。

    Raises:
        PDFExportError: 字体文件缺失或注册失败（config.self_check 会提前暴露）。
    """
    for path in (config.PDF_FONT_PATH, config.PDF_FONT_BOLD_PATH, config.PDF_FONT_SYMBOL_PATH):
        if not path.is_file():
            raise PDFExportError(f"字体缺失: {path}，请检查 assets/fonts 目录")
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        for name, path in ((config.PDF_FONT_NAME, config.PDF_FONT_PATH),
                           (config.PDF_FONT_BOLD_NAME, config.PDF_FONT_BOLD_PATH),
                           (config.PDF_FONT_SYMBOL_NAME, config.PDF_FONT_SYMBOL_PATH)):
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(path)))
        return config.PDF_FONT_NAME, config.PDF_FONT_BOLD_NAME, config.PDF_FONT_SYMBOL_NAME
    except PDFExportError:
        raise
    except Exception as exc:
        raise PDFExportError(f"字体注册失败: {exc}") from exc


def _esc(text: str) -> str:
    """Paragraph XML 转义（与 pdf_exporter._escape 同口径，去掉换行替换——
    简历 bullet 为单行语义，换行由段落拆分处理）。"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# bullet 行首小标题标记：【小标题】具体职责与业绩（gap_rewrite v1.1 输出约定）；
# 英文版由 resume_translate v1.2 转写为 [Headline] 格式，一并识别
_HEADLINE_RE = re.compile(r"^(【[^【】]{1,20}】|\[[^\[\]]{1,30}\])(.*)$", re.S)


def _bullet_html(bullet: str, bold_font: str) -> str:
    """bullet → Paragraph HTML：行首【小标题】用粗体字体渲染，其余正文常规字体。

    无小标题的 bullet（未被改写命中的原文条目）原样转义返回——
    排版层只做"识别与强调"，不替 LLM 补写小标题（内容权在 LLM，排版权在本模块）。
    """
    m = _HEADLINE_RE.match(bullet.strip())
    if not m:
        return _esc(bullet)
    return f'<font name="{bold_font}">{_esc(m.group(1))}</font>{_esc(m.group(2))}'


def export_resume_pdf(resume: ResumeData, rewrites: list[RewriteResult], lang: str = "zh") -> bytes:
    """生成排版后的正式简历 PDF（中文或英文版）。

    Args:
        resume: 简历富结构数据（resume_parser 输出）。
        rewrites: 改写结果列表，会应用到经历条目（未命中的跳过不报错）。
        lang: "zh" 中文版；"en" 英文版（内部先翻译再排版）。

    Returns:
        PDF 文件字节流（Streamlit st.download_button 直接消费）。

    Raises:
        PDFExportError: 字体缺失/渲染异常；lang 非法。
        LLMOutputError / LLMUnavailableError / CacheMissError: 英文版翻译透传。
    """
    if lang not in ("zh", "en"):
        raise PDFExportError(f"不支持的简历语言: {lang!r}（仅支持 zh / en）")
    font, bold, symbol = _register_fonts()

    # 1) 先应用改写（中文富结构上），保证中英两版内容一致
    data: ResumeData = {
        "name": resume["name"], "contacts": list(resume["contacts"]),
        "job_intent": resume.get("job_intent", ""),  # 求职意向（调用方传入，LLM 不产出）
        "education": [], "internships": [], "projects": [],
        "skills": list(resume["skills"]),
        "education_entries": list(resume["education_entries"]),
        "internship_entries": list(resume["internship_entries"]),
        "project_entries": list(resume["project_entries"]),
        "photo_bytes": resume["photo_bytes"], "raw_text": resume["raw_text"],
    }
    for field in ("education_entries", "internship_entries", "project_entries"):
        new_list, _ids = apply_rewrites(data[field], rewrites)  # type: ignore[literal-required]
        data[field] = new_list  # type: ignore[literal-required]

    # 2) 英文版：改写之后整体翻译（LLM 调用，缓存键由富结构决定）
    if lang == "en":
        data = translate_resume(data)

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )

        # ---- 样式族（A4 单页目标：字号收敛、行距紧凑）----
        name_style = ParagraphStyle("name", fontName=bold, fontSize=24, leading=30)
        contact_style = ParagraphStyle("contact", fontName=font, fontSize=9.5, leading=13,
                                       wordWrap="CJK")
        section_style = ParagraphStyle("section", fontName=bold, fontSize=13, leading=17,
                                       spaceBefore=7, spaceAfter=2)
        org_style = ParagraphStyle("org", fontName=bold, fontSize=10.5, leading=14,
                                   wordWrap="CJK")
        role_style = ParagraphStyle("role", fontName=font, fontSize=10, leading=14,
                                    wordWrap="CJK")
        period_style = ParagraphStyle("period", fontName=font, fontSize=9.5, leading=14,
                                      alignment=2)  # 右对齐
        bullet_style = ParagraphStyle("bullet", fontName=font, fontSize=9.5, leading=13.5,
                                      wordWrap="CJK")
        # ➢ 符号样式：wordWrap='CJK' 会击穿 Paragraph 的 <font> 标签（实测豆腐块），
        # 故符号与正文拆成 Table 两列，符号列整格用 DejaVu 符号字体渲染
        sym_style = ParagraphStyle("sym", fontName=symbol, fontSize=9.5, leading=13.5)
        skill_style = ParagraphStyle("skill", fontName=font, fontSize=9.5, leading=14,
                                     wordWrap="CJK")

        story: list = []
        usable_width = A4[0] - 30 * mm  # 左右边距各 15mm

        # ---- 头部：姓名（左）+ 证件照（右上，无照片则省略不占位）----
        left_col: list = [Paragraph(_esc(data["name"] or "（未署名）"), name_style)]
        if data["photo_bytes"]:
            try:
                # 第六轮审查 P2-2：preserveAspectRatio 防止非 25:35 证件照被拉伸变形
                photo = Image(io.BytesIO(data["photo_bytes"]), width=25 * mm, height=35 * mm,
                              preserveAspectRatio=True, anchor="c")
                header = Table([[left_col, photo]], colWidths=[usable_width - 28 * mm, 28 * mm])
            except Exception:
                # 照片字节损坏不应阻塞简历导出：省略照片继续
                header = Table([[left_col]], colWidths=[usable_width])
        else:
            header = Table([[left_col]], colWidths=[usable_width])
        header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                    ("ALIGN", (-1, 0), (-1, 0), "RIGHT"),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                    ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(header)

        # ---- 求职意向（第十轮指令模块二第 1 条：姓名/联系方式下方的醒目展示）----
        intent = (data.get("job_intent") or "").strip()
        if intent:
            intent_style = ParagraphStyle("intent", fontName=font, fontSize=10, leading=14,
                                          wordWrap="CJK", spaceBefore=2)
            story.append(Paragraph(
                f'<font name="{bold}">{_esc(_INTENT_LABEL[lang])}：</font>{_esc(intent)}'
                if lang == "zh" else
                f'<font name="{bold}">{_esc(_INTENT_LABEL[lang])}:</font> {_esc(intent)}',
                intent_style))

        # ---- 联系信息：双列 ----
        contacts = [c for c in data["contacts"] if c.strip()]
        if contacts:
            half = (len(contacts) + 1) // 2  # 左列向上取整，视觉上更平衡
            rows = [
                [Paragraph(_esc(c1), contact_style),
                 Paragraph(_esc(c2), contact_style) if c2 else ""]
                for c1, c2 in zip(contacts[:half], contacts[half:] + [""] * half)
            ]
            ct = Table(rows, colWidths=[usable_width / 2] * 2)
            ct.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
            story.append(ct)

        def _section(title_text: str) -> None:
            """分节标题 + 粗黑分割线（规格要求：粗黑，thickness=1.6）。"""
            story.append(Paragraph(_esc(title_text), section_style))
            story.append(HRFlowable(width="100%", thickness=1.6, color="#000000",
                                    spaceAfter=2 * mm))

        def _entry_block(entry: ResumeEntry) -> None:
            """单条经历：三栏标题行（组织|职位|时间）+ ➢ bullets。"""
            row = Table(
                [[Paragraph(_esc(entry["org"]), org_style),
                  Paragraph(_esc(entry["role"]), role_style),
                  Paragraph(_esc(entry["period"]), period_style)]],
                colWidths=[usable_width * 0.42, usable_width * 0.33, usable_width * 0.25])
            row.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                                     ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                                     ("TOPPADDING", (0, 0), (-1, -1), 2),
                                     ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                                     ("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
            story.append(row)
            for b in entry["bullets"]:
                if b.strip():
                    # ➢ 由 DejaVu 符号字体整格渲染（思源黑体无该字模），正文列仍用 CJK 字体
                    # 第十轮模块二第 2 条：bullet 行首【小标题】加粗渲染（HR 扫读锚点）
                    bt = Table([[Paragraph("➢", sym_style),
                                 Paragraph(_bullet_html(b, bold), bullet_style)]],
                               colWidths=[5 * mm, usable_width - 5 * mm])
                    bt.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                                            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                            ("TOPPADDING", (0, 0), (-1, -1), 0.5),
                                            ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
                                            ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                    story.append(bt)

        # ---- 三段经历分节（时间倒序：最近经历排最前，专业简历惯例）----
        for field, title_text in _SECTIONS[lang]:
            entries = _sort_entries_desc(data[field])  # type: ignore[literal-required]
            if not entries:
                continue  # 空分节直接省略（简历惯例：没有的经历不占版面）
            _section(title_text)
            for entry in entries:
                _entry_block(entry)

        # ---- 技能分节（一行流式罗列，节省版面）----
        if data["skills"]:
            _section(_SKILLS_TITLE[lang])
            sep = " ｜ " if lang == "zh" else " | "
            story.append(Paragraph(_esc(sep.join(data["skills"])), skill_style))

        # 注意（第十轮指令模块一）：简历 PDF 是对外投递物，绝不印任何
        # 产品内部过程提示（如"N 条改写未并入"）——该类提示只出现在应用前端。

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
                                leftMargin=15 * mm, rightMargin=15 * mm,
                                topMargin=12 * mm, bottomMargin=12 * mm)
        doc.build(story)
        return buf.getvalue()
    except PDFExportError:
        raise
    except Exception as exc:
        # 渲染期任何异常统一收敛，界面据此提示并保留数据可重试
        raise PDFExportError(f"简历 PDF 生成失败: {exc}") from exc
