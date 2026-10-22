"""resume_parser.py —— 简历解析模块：PDF/TXT/粘贴文本 → ResumeData。

【模块说明】
    三条输入通道（架构 v1.1 M4：扫描件不给 OCR，改给"粘贴文本"轻量降级）：
        1. PDF 文件：pypdf 提取文本层（顺带尝试提取首页证件照）→ 质量校验 → LLM 结构化；
        2. TXT 文件：直接读取（支持 utf-8 / gbk 回退）→ LLM 结构化；
        3. 粘贴文本：用户直接粘贴简历文字 → LLM 结构化。
    文本层质量校验（架构 v1.1 S3）：长度 ≥ PDF_MIN_TEXT_LENGTH 且
    中文字符占比 ≥ PDF_MIN_CHINESE_RATIO，否则按扫描件抛 PDFParseError，
    由界面引导用户改用 TXT 或粘贴文本。

    v2 变更（简历 PDF 生成器需求）：
        LLM 直接产出富结构（name / contacts / *_entries），本模块负责：
        - 由 *_entries 组合出 education / internships / projects 字符串列表
          （gap_matcher 的 payload 形状不变，组合规则为纯函数，逐位可复现）；
        - 回填 raw_text 与 photo_bytes（LLM 不产出这两个字段，见 contracts 契约表）。

【依赖清单】
    第三方：pypdf（requirements.txt 锁定主版本）
    项目内：config, contracts, llm_client

【审查提示（给 DeepSeek）】
    extract_text_from_pdf / _combine_legacy_fields 为纯函数，可离线单测；
    LLM 依赖同样只经 llm_client.chat，可注入假输出测试。
"""

from __future__ import annotations

import config
import llm_client
from contracts import PDFParseError, ResumeData, ResumeEntry, validate_resume_data


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """从 PDF 字节流提取文本层内容。

    Args:
        file_bytes: 上传的 PDF 文件二进制内容。

    Returns:
        拼接全部页面的纯文本。

    Raises:
        PDFParseError: 以下三种情况——文件不是合法 PDF；提取文本长度不足；
            中文字符占比过低（疑似扫描件/图片型 PDF，无文本层）。
    """
    import io  # 局部导入：仅本函数使用的重依赖，保持模块导入轻量

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except PDFParseError:
        raise
    except Exception as exc:
        # pypdf 对损坏/加密文件抛出多种异常，统一收敛为业务异常
        raise PDFParseError(f"PDF 文件无法解析（文件可能损坏或加密）: {exc}") from exc

    if len(text.strip()) < config.PDF_MIN_TEXT_LENGTH:
        raise PDFParseError("PDF 提取文本过短，疑似扫描件（无文本层），请改用 TXT 上传或直接粘贴简历文本")
    chinese = sum(1 for c in text if "一" <= c <= "鿿")
    if len(text.strip()) > 0 and chinese / len(text.strip()) < config.PDF_MIN_CHINESE_RATIO:
        raise PDFParseError("PDF 文本中文占比过低，疑似扫描件或乱码，请改用 TXT 上传或直接粘贴简历文本")
    return text


def extract_photo_from_pdf(file_bytes: bytes) -> bytes | None:
    """尝试从 PDF 首页提取证件照（v2：供简历排版生成器复用，免去用户二次上传）。

    策略：取首页第一张位图。简历 PDF 通常只有证件照一张图，命中即为所求；
    无图或多图简历不保证语义正确，故失败/无图一律返回 None，界面直接省略照片位。

    Args:
        file_bytes: 上传的 PDF 文件二进制内容。

    Returns:
        图片二进制内容；提取失败或无图片时返回 None（不抛异常，照片是可选元素）。
    """
    import io

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        if not reader.pages:
            return None
        images = reader.pages[0].images  # pypdf 惰性加载，仅访问首页
        if not images:
            return None
        return bytes(images[0].data)
    except Exception:
        # 照片提取是尽力而为的增强功能，任何异常都不应阻塞主流程
        return None


def read_txt_file(file_bytes: bytes) -> str:
    """读取 TXT 字节流，utf-8 优先、gbk 回退（覆盖 Windows 常见编码）。

    Args:
        file_bytes: TXT 文件二进制内容。

    Returns:
        解码后的文本。

    Raises:
        PDFParseError: 两种编码均解码失败，或内容过短。
    """
    for encoding in ("utf-8", "gbk"):
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise PDFParseError("TXT 文件编码无法识别（已尝试 utf-8 / gbk），请另存为 UTF-8 后重试")
    if len(text.strip()) < config.PDF_MIN_TEXT_LENGTH:
        raise PDFParseError("文本内容过短，请确认上传了完整的简历文本")
    return text


def _entry_to_legacy_line(entry: ResumeEntry) -> str:
    """把单条富结构经历组合为旧版字符串行（gap_matcher 的 payload 形状保持不变）。

    组合格式："org role（period）：bullet1；bullet2"，
    与 v1 prompt 时代的平铺字符串在信息上等价，规则固定、逐位可复现。
    """
    head = " ".join(x for x in (entry["org"], entry["role"]) if x.strip())
    if entry["period"].strip():
        head = f"{head}（{entry['period']}）"
    if entry["bullets"]:
        return f"{head}：{'；'.join(entry['bullets'])}"
    return head


def _combine_legacy_fields(data: dict) -> None:
    """由 *_entries 富结构组合出 education / internships / projects 字符串列表。

    就地修改 data。纯函数逻辑：给定相同 entries，组合结果逐位一致，
    保证 gap_matcher 的输入与缓存键稳定。
    """
    data["education"] = [_entry_to_legacy_line(e) for e in data.get("education_entries", [])]
    data["internships"] = [_entry_to_legacy_line(e) for e in data.get("internship_entries", [])]
    data["projects"] = [_entry_to_legacy_line(e) for e in data.get("project_entries", [])]


def structure_resume(raw_text: str, photo_bytes: bytes | None = None) -> ResumeData:
    """调用 LLM 把简历原文结构化为 ResumeData（v2 富结构）。

    Args:
        raw_text: 简历纯文本（来自 PDF 提取 / TXT / 粘贴，三条通道已统一）。
        photo_bytes: 从 PDF 提取的证件照；TXT/粘贴通道传 None。

    Returns:
        ResumeData，legacy 字符串列表 / raw_text / photo_bytes 由本函数回填
        （契约约定 LLM 不输出这些字段）。

    Raises:
        LLMOutputError: LLM 输出业务校验失败。
        LLMUnavailableError / CacheMissError: 透传自 llm_client。
    """
    data = llm_client.chat("resume_extract", raw_text)
    validate_resume_data(data)
    _combine_legacy_fields(data)
    data["raw_text"] = raw_text  # 原文回填，供 rewriter 引用（禁止 LLM 复述冒充原文）
    data["photo_bytes"] = photo_bytes
    return data  # type: ignore[return-value]


def parse_resume(file_bytes: bytes, filename: str) -> ResumeData:
    """简历解析主接口：按文件类型分发到对应通道。

    Args:
        file_bytes: 上传文件二进制内容。
        filename: 文件名（按扩展名分发，不区分大小写）。

    Returns:
        ResumeData。

    Raises:
        PDFParseError: 不支持的文件类型，或文本提取/质量问题（见各通道说明）。
    """
    lower = filename.lower()
    if lower.endswith(".pdf"):
        raw_text = extract_text_from_pdf(file_bytes)
        photo_bytes = extract_photo_from_pdf(file_bytes)
    elif lower.endswith(".txt"):
        raw_text = read_txt_file(file_bytes)
        photo_bytes = None  # TXT 无图片概念
    else:
        raise PDFParseError(f"不支持的文件类型: {filename}（仅支持 PDF / TXT，或直接粘贴文本）")
    return structure_resume(raw_text, photo_bytes=photo_bytes)


def parse_pasted_text(text: str) -> ResumeData:
    """粘贴文本通道入口（扫描件降级路径，架构 v1.1 M4）。

    Args:
        text: 用户粘贴的简历文本。

    Returns:
        ResumeData。

    Raises:
        PDFParseError: 文本过短。
    """
    if len(text.strip()) < config.PDF_MIN_TEXT_LENGTH:
        raise PDFParseError("粘贴的文本过短，请粘贴完整的简历内容")
    return structure_resume(text, photo_bytes=None)
