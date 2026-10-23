"""contracts.py —— 全局契约层：跨模块数据结构、异常体系、Prompt 契约表、业务校验函数。

【模块说明】
    本模块是整个应用的"契约源头"（架构 v1.1 新增，回应 DeepSeek 审查 S1/M1）：
    - 全部跨模块 TypedDict 集中定义于此，业务模块只导入、不自行定义；
    - 5 类业务异常集中定义，main.py 依据异常类型决定界面降级行为；
    - PROMPT_CONTRACTS 表声明每个 prompt_key 的输出结构与校验责任方；
    - validate_* 系列纯函数负责 LLM 输出的"业务字段校验"
      （JSON 语法校验在 llm_client 完成，职责边界见 llm_client.py 模块说明）。

【依赖清单】
    仅标准库：typing。无任何第三方依赖，可被所有模块安全导入，不会循环导入。

【审查提示（给 DeepSeek）】
    本文件无 IO、无网络、无全局可变状态，全部为类型定义与纯函数，可整体静态审查。
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

# ---------------------------------------------------------------------------
# 常量：schema 版本（进入缓存键，结构变更时必须递增，使旧缓存自动失效）
# ---------------------------------------------------------------------------

# v1.2：resume_extract 升级为富结构 v2.0（name/contacts/entries），旧缓存自动失效
SCHEMA_VERSION: str = "1.2"

# Gap 命中状态的合法取值，同时驱动 UI 三色标注（绿/黄/红）
GapStatus = Literal["matched", "partial", "missing"]

# importance 来源标注（架构 v1.1 M6：评委追问评分依据时的解释载体）
ImportanceSource = Literal["人工核定", "LLM评估"]


# ---------------------------------------------------------------------------
# 异常体系（架构 v1.1 S3：5 类异常，每类对应明确的界面降级行为）
# ---------------------------------------------------------------------------


class AppError(Exception):
    """全部业务异常的基类，便于 main.py 统一捕获后再细分。"""


class PDFParseError(AppError):
    """简历 PDF 解析失败（无文本层/文本过短/疑似扫描件）。

    界面降级：提示用户改用 TXT 上传或粘贴简历文本。
    """


class LLMUnavailableError(AppError):
    """LLM 网络层失败（超时、连接错误、HTTP 5xx），重试后仍失败。

    界面降级：提示检查网络，或切换到演示缓存模式。
    """


class SearchUnavailableError(LLMUnavailableError):
    """联网检索（博查 API）失败：超时、断网、HTTP 错误或未配置 Key。

    继承 LLMUnavailableError——API 层异常映射自动归入 503，无需新增分支。
    界面降级（保险丝语义）：提示"联网检索暂不可用"，引导改用预设岗位库
    或粘贴 JD——搜索是增强项，挂了绝不影响主链路。
    """


class LLMOutputError(AppError):
    """LLM 输出语法合法但业务校验失败（缺字段/类型错/数量不对齐）。

    界面降级：提示"AI 输出异常，请重试"，已完成步骤的状态保留。
    """


class CacheMissError(AppError):
    """演示缓存模式下缓存未命中。

    界面降级：提示"演示模式仅支持 3 个内置案例"，严禁静默回退到网络调用。
    """


class PDFExportError(AppError):
    """PDF 导出失败（字体缺失、写入无权限等）。

    界面降级：提示具体原因，报告数据保留在 session_state 中可重试。
    """


# ---------------------------------------------------------------------------
# 数据结构契约（TypedDict，跨模块唯一权威定义）
# ---------------------------------------------------------------------------


class AbilityItem(TypedDict):
    """岗位 JD 拆解出的单项能力要求，Gap 对比的原子单位。"""

    name: str  # 能力项名，如 "SQL 数据分析"
    category: str  # 硬技能 / 软技能 / 背景门槛
    importance: int  # 1-5，岗位方重要度
    importance_source: ImportanceSource  # 预设岗位=人工核定；自定义 JD=LLM评估
    evidence: str  # JD 原文依据引文，供界面展示与人工核验


class JobRequirements(TypedDict):
    """岗位需求侧的结构化画像（job_analyzer 的输出契约）。"""

    job_id: str  # 预设岗位 ID；自定义 JD 时为 "custom"
    job_title: str
    company_type: str  # 金融/互联网/四大/快消/咨询/泛用
    responsibilities: list[str]  # 职责列表
    abilities: list[AbilityItem]  # LLM 路径 6-12 项；预设库精简岗位可少至 5 项
    salary_hint: str  # 可空字符串；预设库人工填写，LLM 不得编造
    source_note: str  # JD 来源与人工核验记录（扣分项②防线）


class JobMeta(TypedDict):
    """岗位库目录条目（供选岗下拉框展示，不含完整 JD 内容）。"""

    job_id: str
    job_title: str
    company_type: str
    is_demo: bool  # 是否为 3 个精修演示岗位之一


class ResumeEntry(TypedDict):
    """简历经历条目（简历排版生成器的最小单元，第三轮需求扩展新增）。

    "组织名 | 职位 | 时间"三栏布局 + ➢ bullet 的数据载体。
    """

    org: str  # 组织名（公司/学校/项目名）
    role: str  # 职位/角色/专业学位
    period: str  # 时间段，如 "2025.07-2025.09"
    bullets: list[str]  # 该条目下的要点（每条一句，不含符号前缀）


class ResumeData(TypedDict):
    """简历供给侧的结构化数据（resume_parser 的输出契约，v2 扩展）。

    v2 变更（简历 PDF 生成器需求）：
        - 新增 name / contacts / *_entries 富结构字段（LLM 直接产出）；
        - 原 education/internships/projects 字符串列表保留，由 resume_parser
          从 entries 组合生成（gap_matcher 的 payload 形状不变，纯函数可复现）。
    """

    name: str  # 姓名（允许空串：部分简历未署名）
    contacts: list[str]  # 联系方式（电话/邮箱/其他，逐条）
    education: list[str]  # 教育经历条目（由 education_entries 组合；界面展示时学校名脱敏）
    internships: list[str]  # 实习经历条目（由 internship_entries 组合）
    projects: list[str]  # 项目经历条目（由 project_entries 组合）
    skills: list[str]  # 技能清单
    education_entries: list[ResumeEntry]  # 富结构：教育
    internship_entries: list[ResumeEntry]  # 富结构：实习
    project_entries: list[ResumeEntry]  # 富结构：项目
    photo_bytes: bytes | None  # 从 PDF 简历提取的证件照；TXT/粘贴通道为 None
    raw_text: str  # 简历原文全文，供改写模块引用


class GapItem(TypedDict):
    """单个能力项的 Gap 诊断结果（gap_matcher 中 LLM 通道的输出单元）。

    注意：LLM 只输出 status 与 reason，分数由规则通道计算，本结构不含分数字段。
    """

    gap_id: str  # 唯一标识 = f"{job_id}#{序号}"，消除能力重名歧义（v1.1 S5）
    ability: str  # 能力项名（与 JobRequirements.abilities[i].name 一一对应）
    status: GapStatus  # matched=绿 / partial=黄 / missing=红
    importance: int  # 从岗位侧透传，规则评分使用
    reason: str  # LLM 判断依据（须引用简历原文）


class GapReport(TypedDict):
    """完整 Gap 诊断报告（gap_matcher 的最终输出契约）。"""

    match_score: int  # 0-100，规则通道产出，给定 status 序列后逐位可复现
    items: list[GapItem]  # 与岗位能力项一一对应，数量严格相等
    top_gaps: list[GapItem]  # 按 importance × 缺失度排序的 Top3，供 rewriter 聚焦
    warnings: list[str]  # LLM 输出对齐过程中的缺项/截断等告警，界面可选展示


class RewriteResult(TypedDict):
    """单条 Gap 的改写产出（rewriter 的输出契约）。"""

    gap_id: str  # 与 GapItem.gap_id 对应
    diagnosis: str  # 问题诊断：为什么这条是 Gap
    suggestion: str  # 修改建议（方法论层面）
    example_before: str  # 简历原文相关段落（引用，不得虚构）
    example_after: str  # 改写示例（只允许重组已有事实，禁止虚构经历）


# ---------------------------------------------------------------------------
# Prompt 契约表（架构 v1.1 S1：每个 prompt_key 的输出结构与校验责任方）
# ---------------------------------------------------------------------------

# 值 = (输出结构说明, 校验函数名)。llm_client 只保证"返回语法合法的 JSON dict"，
# 业务字段是否符合下表结构，由对应 validate_* 函数在业务模块内显式校验。
# 注意（P1-1 修订）：chat() 返回类型恒为 dict，列表型输出以 {"items": [...]} 包装。
PROMPT_CONTRACTS: dict[str, tuple[str, str]] = {
    "job_extract": ("JobRequirements(无job_id/source_note，由调用方补)", "validate_job_requirements"),
    "resume_extract": ("ResumeData(无raw_text，由调用方补)", "validate_resume_data"),
    "gap_judge": ('{"items": list[GapItem]}(无gap_id/importance，由调用方补)', "validate_gap_items"),
    "gap_rewrite": ("RewriteResult(无gap_id，由调用方补)", "validate_rewrite_result"),
    # 第三轮需求扩展：英文简历翻译，输入/输出同为 ResumeData 富结构（无raw_text/photo_bytes）
    "resume_translate": ("ResumeData富结构(英文，无raw_text/photo_bytes)", "validate_resume_data"),
}


# ---------------------------------------------------------------------------
# 业务校验函数（纯函数，校验失败一律抛 LLMOutputError）
# ---------------------------------------------------------------------------


def _require(cond: bool, msg: str) -> None:
    """内部工具：条件不满足时抛 LLMOutputError，统一错误前缀便于日志定位。"""
    if not cond:
        raise LLMOutputError(f"LLM 输出校验失败: {msg}")


# 能力项数量合法区间（LLM 输出与预设岗位库共用口径，第二轮审查 P0-4 统一为 6-12）
ABILITY_COUNT_MIN: int = 6
ABILITY_COUNT_MAX: int = 12

# 单项能力的合法取值集合（预设岗位库加载校验与 LLM 输出校验共用，P1-2）
LEGAL_CATEGORIES: tuple[str, ...] = ("硬技能", "软技能", "背景门槛")
LEGAL_IMPORTANCE_SOURCES: tuple[str, ...] = ("人工核定", "LLM评估")


def validate_ability_item(ab: Any, where: str, strict_source: bool = False) -> None:
    """校验单个能力项的字段与类型（job_extract 输出与岗位库 JSON 共用）。

    Args:
        ab: 待校验的能力项 dict。
        where: 错误定位前缀，如 "abilities[2]" 或 "big4_audit.json abilities[0]"。
        strict_source: True 时额外校验 importance_source 合法值
            （预设岗位库必须为"人工核定"；LLM 输出允许缺省由调用方补标）。

    Raises:
        LLMOutputError: 字段缺失、类型错误或取值越界。
    """
    _require(isinstance(ab.get("name"), str) and ab["name"].strip(), f"{where}.name 缺失")
    # 第三轮审查 P2-5：category 校验合法值（不只非空），拼写错误在启动期/校验期拦截
    _require(ab.get("category") in LEGAL_CATEGORIES,
             f"{where}.category={ab.get('category')!r} 非法，须为 {LEGAL_CATEGORIES}")
    _require(isinstance(ab.get("importance"), int) and not isinstance(ab.get("importance"), bool)
             and 1 <= ab["importance"] <= 5,
             f"{where}.importance 须为 1-5 整数")  # bool 是 int 子类，须显式排除
    _require(isinstance(ab.get("evidence"), str), f"{where}.evidence 缺失")
    if strict_source:
        _require(ab.get("importance_source") in LEGAL_IMPORTANCE_SOURCES,
                 f"{where}.importance_source 须为 {LEGAL_IMPORTANCE_SOURCES}")


def validate_job_requirements(data: dict[str, Any]) -> None:
    """校验 job_extract 的 LLM 输出是否符合 JobRequirements 结构。

    Args:
        data: llm_client 返回的语法合法 JSON dict（job_id/source_note 允许缺失，
            由 job_analyzer 在调用后补齐）。

    Raises:
        LLMOutputError: 任一必填字段缺失、类型错误或 abilities 数量越界。
    """
    _require(isinstance(data.get("job_title"), str) and data["job_title"].strip(), "job_title 缺失或为空")
    _require(isinstance(data.get("company_type"), str) and data["company_type"].strip(),
             "company_type 缺失")
    resp = data.get("responsibilities")
    _require(isinstance(resp, list), "responsibilities 不是列表")
    # P0-4：元素类型也须校验，否则界面渲染非字符串时报错
    _require(all(isinstance(r, str) for r in resp), "responsibilities 含非字符串元素")
    abilities = data.get("abilities")
    _require(isinstance(abilities, list), "abilities 不是列表")
    # 能力项数量约束：过少说明 JD 拆解不充分，过多说明 LLM 发散，均属输出异常
    _require(ABILITY_COUNT_MIN <= len(abilities) <= ABILITY_COUNT_MAX,
             f"abilities 数量 {len(abilities)} 超出 {ABILITY_COUNT_MIN}-{ABILITY_COUNT_MAX} 范围")
    for i, ab in enumerate(abilities):
        validate_ability_item(ab, f"abilities[{i}]")


def _validate_entry_list(value: Any, field: str) -> None:
    """校验经历条目列表的富结构（ResumeEntry：org/role/period/bullets）。"""
    _require(isinstance(value, list), f"{field} 不是列表")
    for i, e in enumerate(value):
        _require(isinstance(e, dict), f"{field}[{i}] 不是对象")
        for f_ in ("org", "role", "period"):
            _require(isinstance(e.get(f_), str), f"{field}[{i}].{f_} 缺失或非字符串")
        bullets = e.get("bullets")
        _require(isinstance(bullets, list) and all(isinstance(b, str) for b in bullets),
                 f"{field}[{i}].bullets 缺失或含非字符串元素")


def validate_resume_data(data: dict[str, Any]) -> None:
    """校验 resume_extract 的 LLM 输出是否符合 ResumeData v2 富结构。

    Args:
        data: llm_client 返回的 JSON dict（raw_text/photo_bytes 与字符串列表字段
            由 resume_parser 补齐，此处只校验 LLM 直接产出的富结构字段）。

    Raises:
        LLMOutputError: 字段缺失、类型错误或条目结构不合法。
    """
    # 姓名允许空串（简历可能未署名），但必须存在且为字符串
    _require(isinstance(data.get("name"), str), "name 缺失或非字符串")
    contacts = data.get("contacts")
    _require(isinstance(contacts, list) and all(isinstance(c, str) for c in contacts),
             "contacts 缺失或含非字符串元素")
    _validate_entry_list(data.get("education_entries"), "education_entries")
    _validate_entry_list(data.get("internship_entries"), "internship_entries")
    _validate_entry_list(data.get("project_entries"), "project_entries")
    skills = data.get("skills")
    _require(isinstance(skills, list) and all(isinstance(x, str) for x in skills),
             "skills 缺失或含非字符串元素")


def validate_gap_items(data: Any, expected_count: int) -> None:
    """校验 gap_judge 的 LLM 输出：数量为基准能力的整数倍关系由对齐函数处理，
    此处只校验单条结构合法性（数量对齐策略见 gap_matcher.align_items）。

    Args:
        data: llm_client 返回的 JSON（应为 list）。
        expected_count: 岗位能力项数量，用于上界检查（多项截断在 align_items 执行）。

    Raises:
        LLMOutputError: 非列表、为空、单条缺 status/ability，或 status 取值非法。
    """
    _require(isinstance(data, list), "gap_judge 输出不是列表")
    _require(len(data) > 0, "gap_judge 输出为空列表")
    # 允许 LLM 多返回（align_items 会截断），但不允许超过 2 倍——超出说明输出失控
    _require(len(data) <= expected_count * 2,
             f"gap_judge 返回 {len(data)} 条，远超能力项数 {expected_count}")
    legal = ("matched", "partial", "missing")
    for i, item in enumerate(data):
        _require(isinstance(item, dict), f"items[{i}] 不是对象")
        _require(isinstance(item.get("ability"), str), f"items[{i}].ability 缺失")
        _require(item.get("status") in legal,
                 f"items[{i}].status={item.get('status')!r} 非法，须为 {legal}")
        _require(isinstance(item.get("reason"), str), f"items[{i}].reason 缺失")


def validate_rewrite_result(data: dict[str, Any]) -> None:
    """校验 gap_rewrite 的 LLM 输出是否符合 RewriteResult 结构。

    Args:
        data: llm_client 返回的 JSON dict（gap_id 允许缺失，由 rewriter 补齐）。

    Raises:
        LLMOutputError: 四个文本字段缺失或为空。
    """
    for field in ("diagnosis", "suggestion", "example_before", "example_after"):
        _require(isinstance(data.get(field), str) and data[field].strip(),
                 f"{field} 缺失或为空")
