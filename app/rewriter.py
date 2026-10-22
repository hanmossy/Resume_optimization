"""rewriter.py —— 改写建议模块：Top-N Gap 的诊断 + 建议 + 前后对照示例。

【模块说明】
    仅对 GapReport.top_gaps（默认 3 条，config.TOP_GAPS_COUNT）逐条调用 LLM，
    与诊断结果在「开始诊断」一次点击内同时产出（架构 v1.1 M2，交互≤2轮约束）。
    防虚构双保险（评分标准扣分项②防线）：
        1. Prompt 硬约束：只允许重组简历已有事实，禁止虚构经历（文本可被审查）；
        2. 代码校验：example_before 必须能在简历原文中找到（normalize 后子串匹配），
           找不到则抛 LLMOutputError——LLM 引用了不存在的"原文"即判输出异常。

【依赖清单】
    项目内：contracts, llm_client

【审查提示（给 DeepSeek）】
    _verify_before_quote 是本模块的质量阀门（纯函数，可单测）；
    rewrite_all 的循环逐条调用是刻意的：单条失败不影响其他条，
    界面可展示已成功的部分（故障隔离，服务演示稳定性）。
"""

from __future__ import annotations

import llm_client
from contracts import (
    GapItem,
    JobRequirements,
    LLMOutputError,
    ResumeData,
    RewriteResult,
    validate_rewrite_result,
)


def _verify_before_quote(example_before: str, raw_text: str) -> None:
    """校验 example_before 确实摘自简历原文（防虚构第二道保险，纯函数）。

    P1-3 修订：统一使用 llm_client.normalize_content（NFKC + 去零宽 + 折叠空白），
    不再用本模块的简易版——口径不一致会把正确引用误判为虚构。

    Args:
        example_before: LLM 输出的"改写前"文本。
        raw_text: 简历原文全文。

    Raises:
        LLMOutputError: 规范化后 example_before 不是 raw_text 的子串，
            说明 LLM 引用了简历中不存在的内容，判输出异常。
    """
    # Prompt 规则3 约定的合法哨兵值：简历确实无相关素材时允许此占位文本
    if example_before.strip() == "（简历中无相关原文）":
        return
    if llm_client.normalize_content(example_before) not in llm_client.normalize_content(raw_text):
        raise LLMOutputError("改写示例的『原文引用』在简历中找不到对应内容，疑似 AI 虚构，已拦截")


def rewrite(gap: GapItem, resume: ResumeData, job: JobRequirements) -> RewriteResult:
    """对单条 Gap 生成诊断、建议与改写示例。

    Args:
        gap: 目标 GapItem（含 gap_id / ability / status / reason）。
        resume: 简历结构化数据（raw_text 用于原文校验）。
        job: 岗位结构化数据（为改写提供岗位语境）。

    Returns:
        RewriteResult，gap_id 由本函数回填（契约约定 LLM 不输出该字段）。

    Raises:
        LLMOutputError: 输出结构校验失败，或原文引用校验失败（疑似虚构）。
        LLMUnavailableError / CacheMissError: 透传自 llm_client。
    """
    payload = {
        "job_title": job["job_title"],
        "gap_ability": gap["ability"],
        "gap_status": gap["status"],
        "gap_reason": gap["reason"],
        "resume": {k: resume[k] for k in ("education", "internships", "projects", "skills")},
        "resume_raw_text": resume["raw_text"],
    }
    data = llm_client.chat("gap_rewrite", payload)
    validate_rewrite_result(data)
    _verify_before_quote(data["example_before"], resume["raw_text"])
    data["gap_id"] = gap["gap_id"]  # 回填关联键，界面据此把改写结果挂回 Gap 条目
    return data  # type: ignore[return-value]


def rewrite_all(report_top_gaps: list[GapItem], resume: ResumeData, job: JobRequirements) -> tuple[list[RewriteResult], list[str]]:
    """对 Top-N Gap 逐条生成改写。

    异常策略（第二轮审查 P0-3/P1-4 修订，文档与实现对齐）：
        - LLMOutputError（单条输出质量/虚构问题）→ **单条隔离**：记入失败列表，
          其余条目继续，界面展示已成功部分并提示该条可重试；
        - CacheMissError / LLMUnavailableError（全局环境问题）→ **整体中断并上抛**：
          演示模式下缓存未命中意味着后续每条都会失败，继续循环只会放大错误，
          由 main.py 捕获后按全局失败处理（清空改写结果，保留诊断报告）。

    Args:
        report_top_gaps: GapReport.top_gaps（默认 3 条）。
        resume / job: 同 rewrite()。

    Returns:
        (成功的 RewriteResult 列表, 失败说明列表)。

    Raises:
        CacheMissError / LLMUnavailableError: 全局性失败，整体中断上抛。
    """
    results: list[RewriteResult] = []
    failures: list[str] = []
    for gap in report_top_gaps:
        try:
            results.append(rewrite(gap, resume, job))
        except LLMOutputError as exc:
            # 单条质量失败：隔离，不影响其余条目
            failures.append(f"能力项「{gap['ability']}」的改写建议生成失败: {exc}")
        # CacheMissError / LLMUnavailableError 不捕获——全局问题，直接上抛
    return results, failures
