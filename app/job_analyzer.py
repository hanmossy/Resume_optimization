"""job_analyzer.py —— 岗位 JD 解析模块：预设岗位库 + 自定义 JD 抽取。

【模块说明】
    两条输入路径（接口契约见技术架构白皮书 2.3）：
        1. 预设路径：job_id → 读 data/jobs/<job_id>.json，零 LLM 调用、秒回
           （DeepSeek 确认的架构优点，主链路稳定性来源）；
        2. 自定义路径：用户粘贴 JD 原文 → llm_client.chat("job_extract") →
           contracts.validate_job_requirements 业务校验 → 补齐元字段。
    岗位库加载时统一 schema 校验（架构 v1.1 M3）：任何 JSON 格式错误
    **启动即失败并报文件名**，故障暴露在开发期而非演示现场。

【依赖清单】
    标准库：json
    项目内：config, contracts, llm_client

【审查提示（给 DeepSeek）】
    预设路径无任何 LLM 依赖，可离线完整单测；自定义路径的 LLM 依赖
    全部经由 llm_client.chat，可通过替换该函数注入假输出测试。
"""

from __future__ import annotations

import json
from pathlib import Path

import config
import llm_client
from contracts import JobMeta, JobRequirements

# 3 个精修演示岗位（架构 v1.1 M3：演示走这三个，配套缓存与 Demo 简历）
DEMO_JOB_IDS: tuple[str, str, str] = (
    "internet_data_analyst",   # 互联网·数据分析实习
    "big4_audit",              # 四大·审计实习
    "securities_research",     # 金融·券商行研实习
)


def _load_job_file(path: Path) -> JobRequirements:
    """加载单个岗位 JSON 并做全字段校验。

    Args:
        path: 岗位 JSON 文件路径。

    Returns:
        校验通过的 JobRequirements。

    Raises:
        ValueError: 文件缺失、JSON 语法错误、必填字段缺失或类型错误。
            属开发期数据错误，启动阶段暴露，不进入运行时异常降级体系。
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"岗位库文件 {path.name} JSON 语法错误: {exc}") from exc
    # 必填字段清单（精简岗位同样遵守统一 schema，简化的是内容而非结构）
    required = ("job_id", "job_title", "company_type", "responsibilities", "abilities")
    for field in required:
        if field not in data:
            raise ValueError(f"岗位库文件 {path.name} 缺少必填字段: {field}")
    # 第三轮审查 P1-3：job_id 必须与文件名一致——下拉框 value 用 JSON 内 job_id，
    # 加载按文件名找，两者不一致会导致选中即 ValueError（启动期暴露优于演示期）
    if path.stem != data["job_id"]:
        raise ValueError(
            f"岗位库文件 {path.name} 内 job_id={data['job_id']!r} 与文件名不一致")
    # P1-2：不只查字段存在，复用 contracts 的强校验（类型/范围/合法值），
    # 数据错误全部在启动期暴露。LLMOutputError 在此等价于数据错误，转述为 ValueError。
    from contracts import LLMOutputError, validate_ability_item

    if not all(isinstance(r, str) for r in data["responsibilities"]):
        raise ValueError(f"岗位库文件 {path.name} responsibilities 含非字符串元素")
    try:
        for i, ab in enumerate(data["abilities"]):
            validate_ability_item(ab, f"{path.name} abilities[{i}]", strict_source=True)
    except LLMOutputError as exc:
        raise ValueError(f"岗位库文件 {path.name} 校验失败: {exc}") from exc
    # 可选字段补默认值，保证下游拿到的结构完整
    data.setdefault("salary_hint", "")
    data.setdefault("source_note", "待人工核验")
    for ab in data["abilities"]:
        ab.setdefault("is_core", False)  # v1.4：未标注核心项的岗位默认无门槛否决
        ab.setdefault("source_type", "jd_requirement")  # v1.6：预设库全部来自人工核验 JD
    return data  # type: ignore[return-value]


def load_preset_jobs() -> list[JobMeta]:
    """加载岗位库目录，供选岗下拉框展示；同时完成全量 schema 校验。

    设计意图（架构 v1.1 M3）：main.py 启动时调用本函数即完成 16 个文件
    的格式校验，格式错则应用启动失败并指明文件名。

    Returns:
        岗位目录列表（演示岗位排在最前，便于界面引导）。

    Raises:
        ValueError: 岗位库目录缺失或任一文件格式错误。
    """
    if not config.JOBS_DIR.is_dir():
        raise ValueError(f"岗位库目录缺失: {config.JOBS_DIR}")
    metas: list[JobMeta] = []
    for path in sorted(config.JOBS_DIR.glob("*.json")):
        job = _load_job_file(path)
        metas.append(JobMeta(
            job_id=job["job_id"],
            job_title=job["job_title"],
            company_type=job["company_type"],
            is_demo=job["job_id"] in DEMO_JOB_IDS,
        ))
    if not metas:
        raise ValueError(f"岗位库为空: {config.JOBS_DIR}")
    # 演示岗位置顶，界面默认选中第一个
    metas.sort(key=lambda m: not m["is_demo"])
    return metas


def analyze_job(job_id: str | None = None, jd_text: str | None = None) -> JobRequirements:
    """岗位分析主接口：预设 ID 与自定义 JD 二选一。

    Args:
        job_id: 预设岗位 ID（走本地 JSON，零 LLM 调用）。
        jd_text: 用户粘贴的 JD 原文（走 LLM 抽取）。

    Returns:
        JobRequirements。预设路径 importance_source=人工核定；
        自定义路径由本函数统一标注 importance_source=LLM评估（架构 v1.1 M6）。

    Raises:
        ValueError: 两个参数都提供或都未提供、job_id 不存在。
        LLMOutputError: 自定义路径 LLM 输出业务校验失败。
        LLMUnavailableError / CacheMissError: 透传自 llm_client。
    """
    if (job_id is None) == (jd_text is None):
        raise ValueError("job_id 与 jd_text 必须且只能提供一个")

    if job_id is not None:
        path = config.JOBS_DIR / f"{job_id}.json"
        if not path.is_file():
            raise ValueError(f"预设岗位不存在: {job_id}")
        return _load_job_file(path)

    # 自定义 JD 路径：LLM 抽取 + 业务校验 + 元字段补齐
    # 校验失败重试一次：模型偶发返回结构跑偏的 JSON（如 abilities 元素是
    # 纯字符串——公网实测复现），重试一次即可恢复；重试耗尽后作废坏缓存
    # （防演示模式端出同一损坏条目）并显式抛错，绝不静默放行脏数据。
    assert jd_text is not None  # 供类型检查器收敛；上方已保证互斥
    from contracts import (  # 局部导入，保持模块顶部依赖清晰
        LLMOutputError,
        validate_job_requirements,
    )
    data = None
    for attempt in range(2):
        data = llm_client.chat("job_extract", jd_text)
        try:
            validate_job_requirements(data)
            break
        except LLMOutputError:
            if attempt == 1:
                llm_client.discard_cached("job_extract", jd_text)
                raise
            # 首次校验失败：落到循环下一次，重新调用模型
    assert data is not None
    # LLM 不产出的元字段由本模块补齐（契约表约定："无job_id/source_note，由调用方补"）
    data["job_id"] = "custom"
    data["source_note"] = "用户提供的 JD 原文，由 AI 实时解析"
    data.setdefault("salary_hint", "")  # LLM 不得在 JD 无薪资信息时编造（扣分项②防线）
    for ab in data["abilities"]:
        ab["importance_source"] = "LLM评估"
        ab.setdefault("is_core", False)  # v1.4：LLM 未标核心项时默认 False（保守无否决）
        ab.setdefault("source_type", "jd_requirement")  # v1.6：缺省视为 JD 直接要求
    return data  # type: ignore[return-value]
