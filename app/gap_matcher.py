"""gap_matcher.py —— Gap 诊断模块（双通道核心）：LLM 语义判断 + 规则确定性评分。

【模块说明】
    双通道设计（团队已冻结的架构原则）：
        LLM 通道：对岗位每个能力项判断简历侧命中状态（matched/partial/missing）
                  并输出依据（须引用简历原文）——LLM 只输出判断，**不输出分数**；
        规则通道：写死公式计算匹配度（见 compute_score），给定相同 status 序列
                  结果逐位可复现（架构 v1.1 S5 口径）。
    输出对齐策略（架构 v1.1 S5）：以 job.abilities 为基准，LLM 返回数量
    不足补 missing 并记 warning、超出截断并记 warning、单条非法抛 LLMOutputError。

【依赖清单】
    项目内：config, contracts, llm_client

【审查提示（给 DeepSeek）】
    align_items / compute_score / select_top_gaps 为纯函数（无 IO 无 LLM），
    是本模块的算法核心，合计约 80 行，可独立单测——这是架构承诺的"审查地图"落点。
"""

from __future__ import annotations

from typing import Any

import config
import llm_client
from contracts import (
    AbilityItem,
    GapItem,
    GapReport,
    JobRequirements,
    LLMOutputError,
    ResumeData,
    validate_gap_items,
)


def _norm_name(name: str) -> str:
    """能力项名称规范化：去空白并小写化，容忍 LLM 输出的空格/大小写抖动。"""
    return "".join(str(name).split()).lower()


def align_items(llm_items: list[dict[str, Any]], abilities: list[AbilityItem], job_id: str) -> tuple[list[GapItem], list[str]]:
    """把 LLM 判断结果与岗位能力项基准对齐（纯函数，可单测）。

    对齐规则（第二轮审查 P0-1 修订：名称匹配为主，位置仅作兜底）：
        1. 主规则：按规范化名称匹配——LLM 返回顺序整体打乱也不受影响；
        2. 兜底：名称匹配失败且同位置的 LLM 项尚未被认领时，按位置取用
           并记 warning（覆盖 LLM 改名但顺序正确的场景）；
        3. 仍未匹配 → 补 status="missing" 并记 warning；
        4. LLM 重复返回同名能力 → 取第一条，其余记 warning；
        5. 位置兜底成功时 ability 名以岗位基准为准，
           因为评分与 UI 展示都以岗位侧为锚。

    Args:
        llm_items: LLM 返回的判断列表（已过 validate_gap_items 结构校验）。
        abilities: 岗位能力项基准清单。
        job_id: 岗位 ID，用于生成 gap_id（f"{job_id}#{序号}"，消除重名歧义）。

    Returns:
        (对齐后的 GapItem 列表, 告警列表)，列表长度恒等于 len(abilities)。
    """
    items: list[GapItem] = []
    warnings: list[str] = []

    # 建立名称索引；同名重复项保留第一条，其余计入告警
    by_name: dict[str, int] = {}
    for idx, raw in enumerate(llm_items):
        key = _norm_name(raw["ability"])
        if key in by_name:
            warnings.append(f"AI 重复返回能力项 {raw['ability']!r}，已取第一条")
        else:
            by_name[key] = idx

    claimed: set[int] = set()  # 已被认领的 LLM 项下标（防止一项两用）

    for i, ab in enumerate(abilities):
        gap_id = f"{job_id}#{i + 1}"
        key = _norm_name(ab["name"])
        raw: dict[str, Any] | None = None

        # 主规则：名称匹配（顺序打乱不受影响的根本原因）
        if key in by_name and by_name[key] not in claimed:
            raw = llm_items[by_name[key]]
            claimed.add(by_name[key])
        # 兜底：同位置未认领时按位置取用（必须显式记 warning）
        elif i < len(llm_items) and i not in claimed:
            raw = llm_items[i]
            claimed.add(i)
            warnings.append(
                f"第 {i + 1} 项按位置兜底对齐（AI:{raw['ability']!r} / 基准:{ab['name']!r}），已采用基准名")

        if raw is not None:
            items.append(GapItem(
                gap_id=gap_id,
                ability=ab["name"],
                status=raw["status"],
                importance=ab["importance"],
                reason=raw["reason"],
            ))
        else:
            warnings.append(f"AI 未返回能力项 {ab['name']!r} 的判断，已按 missing 补齐")
            items.append(GapItem(
                gap_id=gap_id,
                ability=ab["name"],
                status="missing",
                importance=ab["importance"],
                reason="AI 未返回该项判断，按未命中处理",
            ))

    # LLM 多返回且未被任何基准认领的项，显式告警（不允许静默丢弃）
    leftover = len(llm_items) - len(claimed)
    if leftover > 0:
        warnings.append(f"AI 多返回 {leftover} 项无法匹配的判断，已忽略")
    return items, warnings


def compute_score(items: list[GapItem]) -> int:
    """规则通道评分（纯函数，公式写死，给定相同 status 序列逐位可复现）。

    公式：单能力项得分 = importance × 命中系数(matched=1.0/partial=0.5/missing=0.0)
          匹配度 = Σ单项得分 / Σimportance × 100，四舍五入取整。
    系数唯一来源为 config.MATCH_COEFFICIENTS，禁止在本模块硬编码其他权重。

    Args:
        items: 对齐后的 GapItem 列表。

    Returns:
        0-100 的整数匹配度。
    """
    total_weight = sum(it["importance"] for it in items)
    if total_weight <= 0:
        return 0
    earned = sum(it["importance"] * config.MATCH_COEFFICIENTS[it["status"]] for it in items)
    return round(earned / total_weight * 100)


def score_breakdown(items: list[GapItem]) -> dict[str, Any]:
    """运算过程明细化：把 compute_score 的加权过程逐项摊开（纯函数）。

    用途（第七轮审查 + 团队战略调整）：比赛考察"人机协同"与运算透明度，
    前端"查看运算过程"面板需要逐项展示 重要度 × 命中系数 = 单项得分。
    系数与公式唯一来源仍是本模块——前端只渲染、不复算，避免两处口径漂移。

    Args:
        items: 对齐后的 GapItem 列表（与 compute_score 同一输入）。

    Returns:
        {"coefficients": 系数表副本, "items": 逐项明细（含 coefficient/earned）,
         "total_weight": 权重和, "total_earned": 得分和, "match_score": 0-100}
        match_score 与 compute_score(items) 逐位一致（同一公式同一数据）。
    """
    detail_items = []
    for it in items:
        coef = config.MATCH_COEFFICIENTS[it["status"]]
        detail_items.append({
            "gap_id": it["gap_id"],
            "ability": it["ability"],
            "importance": it["importance"],
            "status": it["status"],
            "coefficient": coef,
            "earned": round(it["importance"] * coef, 2),  # 单项得分，保留两位防浮点长尾
        })
    total_weight = sum(it["importance"] for it in items)
    total_earned = round(sum(d["earned"] for d in detail_items), 2)
    return {
        "coefficients": dict(config.MATCH_COEFFICIENTS),
        "items": detail_items,
        "total_weight": total_weight,
        "total_earned": total_earned,
        "match_score": compute_score(items),
    }


def select_top_gaps(items: list[GapItem], count: int = config.TOP_GAPS_COUNT) -> list[GapItem]:
    """选出最值得改写的 Top-N Gap（纯函数，可单测）。

    排序键 = importance × (1 - 命中系数)：重要度高且缺失度深的排前面。
    matched 项排序键为 0，自然沉底且不会被选入（改写只针对 Gap）。

    Args:
        items: 对齐后的 GapItem 列表。
        count: 选取数量，默认取 config.TOP_GAPS_COUNT（交互≤2轮约束配套）。

    Returns:
        按改写价值降序的 GapItem 子列表，长度 ≤ count。
    """
    candidates = [it for it in items if it["status"] != "matched"]
    candidates.sort(key=lambda it: it["importance"] * (1 - config.MATCH_COEFFICIENTS[it["status"]]),
                    reverse=True)
    return candidates[:count]


def diagnose(job: JobRequirements, resume: ResumeData,
             background: dict[str, str] | None = None) -> GapReport:
    """Gap 诊断主接口：LLM 通道判断 → 对齐 → 规则通道评分 → Top-N 选取。

    Args:
        job: 岗位需求侧结构化数据（job_analyzer 输出）。
        resume: 简历供给侧结构化数据（resume_parser 输出）。
        background: 求职者背景信息（年级/专业/目标），P1-5 修订：
            拼入 LLM 上下文，让 AI 按"实习/求职""年级阶段"判断期望的合理基线
            （如大三实习 vs 应届求职，对同一能力项的期望深度不同）。

    Returns:
        GapReport（match_score 由规则通道产出，items 与岗位能力项一一对应）。

    Raises:
        LLMOutputError: LLM 输出结构校验失败。
        LLMUnavailableError / CacheMissError: 透传自 llm_client。
    """
    # 组装 LLM 输入：只给模型需要的信息（能力项 + 简历结构化事实 + 背景），
    # 并以 dict 传入——llm_client 的 normalize 保证缓存键稳定
    payload: dict[str, Any] = {
        "job_title": job["job_title"],
        "abilities": [{"name": ab["name"], "category": ab["category"],
                       "importance": ab["importance"], "evidence": ab["evidence"]}
                      for ab in job["abilities"]],
        "resume": {k: resume[k] for k in ("education", "internships", "projects", "skills")},
    }
    if background:
        payload["candidate_background"] = background
    data = llm_client.chat("gap_judge", payload)
    raw_items = data.get("items")
    if raw_items is None:
        raise LLMOutputError("gap_judge 输出缺少 items 字段（应为 {\"items\": [...]} 包装）")
    validate_gap_items(raw_items, expected_count=len(job["abilities"]))

    items, warnings = align_items(raw_items, job["abilities"], job["job_id"])
    return GapReport(
        match_score=compute_score(items),
        items=items,
        top_gaps=select_top_gaps(items),
        warnings=warnings,
    )
