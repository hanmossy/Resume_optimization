"""main.py —— Streamlit 界面与流程编排（唯一依赖 streamlit 的文件）。

【模块说明】
    四个页面区块（架构白皮书 2.8 + v1.1 M2 修订）：
        1. 选岗区：演示案例快捷按钮 / 预设岗位下拉框 / 粘贴 JD →「分析岗位」；
        2. 岗位画像区：职责 + 能力项清单（含重要度与其来源标注）；
        3. 上传诊断区：简历 PDF/TXT 上传或粘贴文本 + 背景信息 →「开始诊断」
           （一步同时产出 GapReport + Top3 改写，2 次点击出完整报告）；
        4. 结果导出区：匹配度仪表 + 左右对照视图（三色标注）+ 改写建议 + 导出 PDF。
    状态契约（v1.1 M2）：session_state 仅使用 4 个键——
        job_req / resume_data / gap_report / rewrites（另加 failures 展示告警）。
    按钮幂等：结果存于 state，Streamlit rerun 时直接从 state 渲染，
    不重复调用 LLM；只有用户再次点击按钮才会重新计算。
    错误处理（v1.1 S3）：每步独立 try-except，按 5 类异常给出对应提示，
    已完成步骤的状态不清空，任何单步失败不整页崩溃。

【依赖清单】
    第三方：streamlit
    项目内：config, contracts, llm_client, job_analyzer, resume_parser,
            gap_matcher, rewriter, pdf_exporter, resume_pdf

【审查提示（给 DeepSeek）】
    本文件只做"编排与渲染"，不含算法；所有业务函数均来自其他模块。
    重点审查：按钮幂等逻辑、异常分支与 state 清理边界。
"""

from __future__ import annotations

import streamlit as st

import config
import gap_matcher
import job_analyzer
import llm_client
import pdf_exporter
import resume_parser
import resume_pdf
import rewriter
import search_client
from contracts import (
    AppError,
    CacheMissError,
    LLMOutputError,
    LLMUnavailableError,
    PDFExportError,
    PDFParseError,
)

# 状态三色（架构 v1.1 M5 冻结色值：绿/黄/红）
STATUS_STYLE = {
    "matched": ("#28a745", "✓ 已具备"),
    "partial": ("#ffc107", "◐ 部分匹配"),
    "missing": ("#dc3545", "✗ 缺失"),
}

# 演示案例注册表从 config 导入（第二轮审查 P0-3：单一来源，禁止另存字面量）
DEMO_CASES = config.DEMO_CASES


def init_state() -> None:
    """初始化 session_state 契约键（幂等，重复调用安全）。

    P0-2 修订：契约键扩为 7 个——job_req / resume_data / gap_report /
    rewrites / rewrite_failures / demo_resume_file / pdf_bytes。
    第三轮需求扩展：新增 resume_zh_bytes / resume_en_bytes（中英简历 PDF）。
    """
    for key in ("job_req", "resume_data", "gap_report", "rewrites",
                "demo_resume_file", "demo_bg", "pdf_bytes",
                "resume_zh_bytes", "resume_en_bytes", "search_urls"):
        st.session_state.setdefault(key, None)
    st.session_state.setdefault("rewrite_failures", [])


def _clear_export_bytes() -> None:
    """清空全部 PDF 字节缓存（诊断报告 + 中英简历）。

    换岗/换简历/重新诊断时统一调用：诊断内容变了，旧导出物一律作废，
    杜绝"新数据配旧 PDF"的错配（P0-2 状态事务的扩展）。
    """
    for key in ("pdf_bytes", "resume_zh_bytes", "resume_en_bytes"):
        st.session_state[key] = None


def show_error(exc: Exception) -> None:
    """按异常类型给出对应提示（v1.1 S3 异常分类的界面兑现）。"""
    if isinstance(exc, CacheMissError):
        st.warning(f"演示缓存未命中：{exc}")
    elif isinstance(exc, PDFParseError):
        st.error(f"简历解析失败：{exc}")
    elif isinstance(exc, LLMOutputError):
        st.error(f"AI 输出异常，请点击重试：{exc}")
    elif isinstance(exc, LLMUnavailableError):
        st.error(f"AI 服务暂时不可用（请检查网络，或开启演示缓存模式）：{exc}")
    elif isinstance(exc, PDFExportError):
        st.error(f"PDF 导出失败：{exc}")
    elif isinstance(exc, AppError):
        st.error(f"应用错误：{exc}")
    else:
        st.error(f"未预期的错误：{exc}")


def access_gate() -> None:
    """公网模式访问密码门（团队部署要求）：未通过验证直接停止渲染。

    密码经环境变量 ACCESS_PASSWORD 注入，不进代码、不进仓库；
    验证状态存 session_state，一次通过当次会话有效。
    """
    if not config.PUBLIC_MODE or not config.ACCESS_PASSWORD:
        return
    if st.session_state.get("gate_passed"):
        return
    st.title("求职简历诊断助手")
    st.caption("本站点为邀请体验版，请输入访问密码")
    pwd = st.text_input("访问密码", type="password")
    if st.button("进入"):
        if pwd == config.ACCESS_PASSWORD:
            st.session_state["gate_passed"] = True
            st.rerun()
        else:
            st.error("密码错误")
    st.stop()  # 未通过：下方全部内容不渲染


def require_byok_and_quota() -> bool:
    """公网模式双闸门：强制 BYOK + 会话限流（团队部署要求）。

    Returns:
        True 放行；False 已在界面提示原因，调用方应中止本次操作。
    """
    if not config.PUBLIC_MODE:
        return True
    if not llm_client.has_runtime_key():
        st.error("请先在左侧栏填入你的 DeepSeek API Key（本服务不内置 Key，各人使用各人的额度）")
        return False
    used = st.session_state.get("quota_used", 0)
    if used >= config.PUBLIC_SESSION_QUOTA:
        st.warning(f"本会话体验额度已用完（{config.PUBLIC_SESSION_QUOTA} 次 AI 操作），"
                   "感谢体验——这是公网演示的防刷限制")
        return False
    st.session_state["quota_used"] = used + 1
    return True


def section_job_select() -> None:
    """区块 1：选岗。三种入口：演示案例 / 预设岗位 / 粘贴 JD。"""
    st.header("第一步：选择目标岗位")

    # 一键换岗引导（第十一轮指令）：换岗后简历仍保留，提示一次性展示
    if st.session_state.get("switch_notice"):
        st.info("已为你保留简历，请选择新的岗位开始诊断（无需重新上传）。")
        st.session_state["switch_notice"] = False

    # 演示案例快捷入口（拍摄现场推荐走这里，全程缓存、断网可跑）
    cols = st.columns(3)
    for col, (label, job_id, resume_file, bg) in zip(cols, DEMO_CASES):
        if col.button(label, use_container_width=True):
            _run_job_analysis(job_id=job_id, demo_resume_file=resume_file, demo_bg=bg)

    st.divider()
    metas = st.session_state["job_metas"]
    options = {f"{'⭐ ' if m['is_demo'] else ''}{m['job_title']}（{m['company_type']}）": m["job_id"] for m in metas}
    choice = st.selectbox("或从岗位库选择", list(options.keys()))
    if st.button("分析岗位", type="primary"):
        _run_job_analysis(job_id=options[choice])

    with st.expander("没有目标岗位？粘贴 JD 原文试试"):
        jd_text = st.text_area("粘贴岗位描述（JD）原文", height=150)
        if st.button("解析这份 JD"):
            if jd_text.strip():
                _run_job_analysis(jd_text=jd_text)
            else:
                st.warning("请先粘贴 JD 原文")

    with st.expander("🔍 全网检索岗位（AI 联网搜索 JD，增强项）"):
        query = st.text_input("输入岗位关键词", placeholder="如：字节跳动 产品经理 实习")
        if st.button("检索并生成岗位画像"):
            if query.strip():
                _run_job_search(query.strip())
            else:
                st.warning("请先输入岗位关键词")


def _run_job_search(query: str) -> None:
    """AI 联网检索岗位（第九轮指令的"带保险丝增强项" Streamlit 侧兑现）。

    保险丝语义：检索失败 / 缓存未命中 / Key 缺失 → 显式报错并引导回
    预设岗位库，绝不影响主链路状态（与 FastAPI 版 503/409/400 同口径）。
    Key 逻辑（BYOK）：公网模式强制用户自带博查 Key；本地模式留空时
    由 search_client 回落团队 Key（仅存于开发机 .env）。
    """
    bocha_key = st.session_state.get("user_bocha_key", "")
    if config.PUBLIC_MODE and not bocha_key.strip():
        st.error("请先在左侧栏填入你的博查 API Key（联网检索用），或改用预设岗位库")
        return
    if not require_byok_and_quota():  # 检索后还有 LLM 抽取，受双闸门约束
        return
    try:
        with st.spinner("正在全网搜索相关 JD…"):
            found = search_client.search(query, bocha_key.strip() or None)
        with st.spinner("AI 正在提取能力项…"):
            new_job = job_analyzer.analyze_job(jd_text=found["text"])
        # 元字段标注（与 server/main.py search_job 端点同口径）
        new_job["job_id"] = "search"
        new_job["source_note"] = f"AI 联网检索生成（{len(found['urls'])} 个网页摘要），请人工核验"
        # P0-2 状态事务：与 _run_job_analysis 同一清场顺序，失败时旧状态原样保留
        st.session_state["gap_report"] = None
        st.session_state["rewrites"] = None
        st.session_state["rewrite_failures"] = []
        st.session_state["demo_resume_file"] = None
        st.session_state["demo_bg"] = None
        _clear_export_bytes()
        st.session_state["job_req"] = new_job
        st.session_state["search_urls"] = found["urls"]  # 来源链接，岗位画像区展示
    except Exception as exc:
        show_error(exc)


def _run_job_analysis(job_id: str | None = None, jd_text: str | None = None,
                      demo_resume_file: str | None = None,
                      demo_bg: dict[str, str] | None = None) -> None:
    """执行岗位分析并写入 state；失败时保留旧状态（按钮幂等的前提）。

    P0-2 状态事务：换岗时一次性清空全部下游状态（含 demo_resume_file），
    防止"Demo1 诊断后切 Demo2 仍自动读 Demo1 简历"的错配；
    只有演示案例按钮才在清空后写入新的配套简历文件名与固定背景。
    """
    try:
        if jd_text and not require_byok_and_quota():
            return  # 公网模式：自定义 JD 解析走 LLM，受双闸门约束（预设岗位是本地 JSON，不消耗）
        with st.spinner("AI 正在分析岗位要求…"):
            new_job = job_analyzer.analyze_job(job_id=job_id, jd_text=jd_text)
        # 分析成功才提交：先清空下游，再写入新岗位（失败时旧状态原样保留）
        st.session_state["gap_report"] = None
        st.session_state["rewrites"] = None
        st.session_state["rewrite_failures"] = []
        st.session_state["demo_resume_file"] = demo_resume_file  # None 即清空
        st.session_state["demo_bg"] = demo_bg                    # 固定背景随案例走
        st.session_state["search_urls"] = None  # 非检索路径清空来源链接
        _clear_export_bytes()
        st.session_state["job_req"] = new_job
    except Exception as exc:
        show_error(exc)


def section_job_profile() -> None:
    """区块 2：岗位画像（需求侧解构的可视化，"先分析"的载体）。"""
    job = st.session_state["job_req"]
    if not job:
        return
    st.header(f"岗位画像：{job['job_title']}")
    st.caption(f"信息来源：{job['source_note']}")
    # AI 联网检索路径：来源链接可追溯展示（信息素养口径，与前端 JobProfile 一致）
    search_urls = st.session_state.get("search_urls")
    if job.get("job_id") == "search" and search_urls:
        with st.expander(f"⚠️ AI 联网检索生成，请人工核验｜{len(search_urls)} 个来源网页", expanded=True):
            for url in search_urls:
                st.markdown(f"- {url}")
    if job["salary_hint"]:
        st.caption(f"薪资参考：{job['salary_hint']}")
    # 岗位职责收进 Expander（第十轮 UI 优化：职责长短不一导致左右分栏失衡，
    # 收起后把主要视觉空间留给能力要求清单——后者才是 Gap 对照的主体）
    with st.expander(f"岗位职责（{len(job['responsibilities'])} 条，点击展开）"):
        for r in job["responsibilities"]:
            st.markdown(f"- {r}")
    st.subheader("能力要求清单")
    for ab in job["abilities"]:
        st.markdown(
            f"- **{ab['name']}**（{ab['category']}｜重要度 {'★' * ab['importance']}｜{ab['importance_source']}）  \n"
            f"  JD 依据：{ab['evidence']}"
        )


def section_diagnose() -> None:
    """区块 3：上传简历 + 背景信息 + 开始诊断（一次点击出 GapReport + Top3 改写）。"""
    if not st.session_state["job_req"]:
        return
    st.header("第二步：上传简历，开始诊断")

    # 演示案例配套简历一键带出；第三轮审查 P0 回归修复：演示路径**锁死背景**，
    # 背景输入禁用——缓存键含 background，用户改背景必然 CacheMiss，
    # 锁死比"改了再报错"更不容易出事故
    demo_file = st.session_state.get("demo_resume_file")
    demo_bg = st.session_state.get("demo_bg")
    demo_mode = bool(demo_file and demo_bg)
    if demo_mode:
        st.info(f"已载入演示配套简历：{demo_file}｜背景已固定为："
                f"{demo_bg['年级']} / {demo_bg['专业']} / 目标{demo_bg['目标']}（点击「开始诊断」即可）")
    elif st.session_state.get("resume_data"):
        # 一键换岗后的保留简历提示（非演示路径）：免上传直接诊断
        kept = st.session_state["resume_data"].get("name") or "已解析简历"
        st.success(f"已为你保留简历（{kept}），可直接点击「开始诊断」；如需更换，重新上传或粘贴新文本即可。")

    uploaded = st.file_uploader("上传简历（PDF / TXT）", type=["pdf", "txt"],
                                disabled=demo_mode)
    pasted = st.text_area("或直接粘贴简历文本（扫描件 PDF 请走这里）", height=120,
                          disabled=demo_mode)
    # 背景信息收进带说明标题的容器（第十一轮 UI 指令：降低表单压迫感，
    # 并让用户知道"填了有什么用"——AI 按阶段调整评估基线）
    with st.container(border=True):
        st.caption("**补充背景信息**（选填，AI 将根据你的阶段调整评估标准）")
        st.caption("AI 会根据你的当前阶段动态调整部分软性指标的期望值"
                   "（例如，对大二学生的实习项目要求与大四求职不同）。"
                   "但岗位的核心硬门槛标准恒定不变。")
        cols = st.columns(3)
        grade = cols[0].selectbox("年级", ["大一", "大二", "大三", "大四", "研究生"],
                                  disabled=demo_mode)
        major = cols[1].text_input("专业", disabled=demo_mode)
        goal = cols[2].selectbox("目标", ["实习", "求职"], disabled=demo_mode)

    if st.button("开始诊断", type="primary"):
        # 演示路径用注册表固定背景；自由路径用用户输入
        background = demo_bg if demo_mode else {"年级": grade, "专业": major or "未填写", "目标": goal}
        _run_diagnosis(uploaded, pasted, demo_file, background)


def _run_diagnosis(uploaded, pasted: str, demo_file: str | None, background: dict[str, str]) -> None:
    """诊断主流程：解析简历 → Gap 诊断 → Top3 改写（分步 spinner，v1.1 M8）。

    P0-2 状态事务：诊断与改写在局部变量中算完后**一次性提交**；
    任何环节失败都只保留简历解析结果，下游（gap_report/rewrites/
    failures/pdf_bytes）一律清空——杜绝"新诊断配旧改写"的错配。
    第三轮 P0 回归修复：background 由调用方组装（演示路径=注册表固定值，
    自由路径=用户输入），与 prewarm_cache.py 保持同一来源、同一参数。
    """
    job = st.session_state["job_req"]
    if not require_byok_and_quota():
        return  # 公网模式：诊断必走 LLM，双闸门拦截
    try:
        with st.spinner("正在解析简历…（1/3）"):
            if demo_file and not uploaded and not pasted.strip():
                raw = (config.DEMO_DIR / demo_file).read_text(encoding="utf-8")
                resume = resume_parser.parse_pasted_text(raw)
            elif uploaded is not None:
                resume = resume_parser.parse_resume(uploaded.getvalue(), uploaded.name)
            elif pasted.strip():
                resume = resume_parser.parse_pasted_text(pasted)
            elif st.session_state.get("resume_data") is not None:
                # 一键换岗复用（第十一轮指令）：保留的简历直接进诊断，免重复解析
                resume = st.session_state["resume_data"]
            else:
                st.warning("请上传简历文件，或粘贴简历文本")
                return
        # 简历解析成功即可提交（后续环节失败不影响已解析结果）
        st.session_state["resume_data"] = resume

        with st.spinner("正在逐项对比岗位能力…（2/3）"):
            new_report = gap_matcher.diagnose(job, resume, background)

        try:
            with st.spinner("正在生成重点改写建议…（3/3）"):
                new_rewrites, new_failures = rewriter.rewrite_all(new_report["top_gaps"], resume, job)
        except (CacheMissError, LLMUnavailableError) as exc:
            # P0-3：全局性失败（缓存未命中/断网）——改写整体作废但诊断报告保留，
            # 显式提交"有诊断 + 空改写 + 失败说明"，杜绝静默错配
            new_rewrites, new_failures = [], [f"改写建议整体不可用：{exc}"]

        # 事务提交点：诊断 + 改写结果（含失败说明）就绪后一次性写入
        st.session_state["gap_report"] = new_report
        st.session_state["rewrites"] = new_rewrites
        st.session_state["rewrite_failures"] = new_failures
        _clear_export_bytes()  # 诊断内容变了，旧 PDF（报告+简历）一律作废
    except Exception as exc:
        # 失败时清空下游（保留 resume_data），防止错配数据残留
        st.session_state["gap_report"] = None
        st.session_state["rewrites"] = None
        st.session_state["rewrite_failures"] = []
        _clear_export_bytes()
        show_error(exc)


def section_result() -> None:
    """区块 4：结果展示与导出（"先分析再润色"的可视化核心，创新分载体）。"""
    report = st.session_state["gap_report"]
    job = st.session_state["job_req"]
    if not (report and job):
        return
    st.header("诊断结果")

    # 一键换岗（第十一轮指令）：保留已解析简历，清空岗位与全部下游结果——
    # 测完一个岗位直接换下一个，无需重新上传；清场清单与 _run_job_analysis 同口径
    if st.button("🔄 换一个岗位试试（简历已保留，无需重新上传）"):
        st.session_state["job_req"] = None
        st.session_state["gap_report"] = None
        st.session_state["rewrites"] = None
        st.session_state["rewrite_failures"] = []
        st.session_state["demo_resume_file"] = None
        st.session_state["demo_bg"] = None
        st.session_state["search_urls"] = None
        _clear_export_bytes()
        st.session_state["switch_notice"] = True  # 选岗区展示引导提示（一次性）
        st.rerun()

    st.metric("简历与岗位匹配度", f"{report['match_score']} / 100")
    st.caption("评分口径：Σ(权重 × 命中系数) ÷ Σ权重 × 100｜系数：已具备(强证据) 1.0 / "
               "已具备(弱证据) 0.7 / 部分匹配 0.4 / 缺失 0.0｜软技能权重 5 折｜"
               "核心门槛未达标总分 ×0.6 且封顶 60")

    # v1.4 核心项否决警示（第十一轮指令：红色提示行，必须显眼）
    if report.get("core_penalty_applied"):
        st.error(f"⚠️ 核心门槛未达标：缺少【{'、'.join(report['core_gap_abilities'])}】"
                 "能力，导致整体匹配度受限（总分 ×0.6 且封顶 60 分）。")

    # 左右对照视图：左=岗位能力项（需求侧），右=简历命中情况（供给侧）
    st.subheader("能力对照")
    for it in report["items"]:
        color, label = STATUS_STYLE[it["status"]]
        left, right = st.columns(2)
        core_mark = "｜🎯 核心门槛" if it.get("is_core") else ""
        left.markdown(f"**{it['ability']}**（重要度 {'★' * it['importance']}{core_mark}）")
        # v1.4：matched 项标注证据强度（强/弱），弱证据是降档系数的直接原因
        strength_mark = ""
        if it["status"] == "matched":
            strength_mark = "（强证据）" if it.get("evidence_strength") == "strong" else "（弱证据）"
        right.markdown(f"<span style='color:{color};font-weight:bold'>{label}{strength_mark}</span>：{it['reason']}",
                       unsafe_allow_html=True)
    for w in report["warnings"]:
        st.caption(f"⚠️ {w}")

    # 改写建议（前后对照）
    rewrites = st.session_state.get("rewrites")
    if rewrites:
        st.subheader("重点改写建议")
        ability_of = {it["gap_id"]: it["ability"] for it in report["items"]}
        for rw_ in rewrites:
            with st.expander(f"能力项：{ability_of.get(rw_['gap_id'], rw_['gap_id'])}"):
                st.markdown(f"**诊断**：{rw_['diagnosis']}")
                st.markdown(f"**建议**：{rw_['suggestion']}")
                st.markdown(f"**改写前**：{rw_['example_before']}")
                st.markdown(f"**改写后**：{rw_['example_after']}")
    for f_ in st.session_state.get("rewrite_failures", []):
        st.warning(f_)

    # 导出 PDF（P1-6：pdf_bytes 存入 session_state，下载按钮独立渲染——
    # rerun 后按钮不消失，可重复下载；返回 bytes 契约不依赖本地路径）
    st.subheader("导出诊断报告")
    if st.button("生成 PDF 报告"):
        try:
            with st.spinner("正在生成 PDF…"):
                st.session_state["pdf_bytes"] = pdf_exporter.export_pdf(
                    job, st.session_state["resume_data"], report, rewrites or [])
        except Exception as exc:
            show_error(exc)
    if st.session_state.get("pdf_bytes"):
        st.download_button("下载诊断报告 PDF", data=st.session_state["pdf_bytes"],
                           file_name="简历诊断报告.pdf", mime="application/pdf")

    # ---- 导出排版后的正式简历（第三轮需求扩展：中英双语）----
    # 前置条件：必须有简历数据；改写可有可无（无改写则导出原文排版版）
    resume_data = st.session_state.get("resume_data")
    if resume_data:
        # 求职意向注入（第十轮指令）：当前选中岗位名 → 简历头部"求职意向"行
        job = st.session_state.get("job_req")
        resume_for_export = dict(resume_data)
        resume_for_export["job_intent"] = job["job_title"] if job else ""
        st.subheader("导出修改后简历（排版版）")
        st.caption("已命中的改写建议会自动并入；英文版面向投递外企场景，由 AI 在改写后整体翻译。")
        col_zh, col_en = st.columns(2)
        with col_zh:
            if st.button("生成中文简历 PDF"):
                try:
                    with st.spinner("正在排版中文简历…"):
                        st.session_state["resume_zh_bytes"] = resume_pdf.export_resume_pdf(
                            resume_for_export, rewrites or [], lang="zh")
                except Exception as exc:
                    show_error(exc)
            if st.session_state.get("resume_zh_bytes"):
                st.download_button("下载中文简历 PDF", data=st.session_state["resume_zh_bytes"],
                                   file_name="修改后简历-中文.pdf", mime="application/pdf")
        with col_en:
            if st.button("生成英文简历 PDF") and require_byok_and_quota():
                # 公网模式：翻译走 LLM，双闸门拦截（不通过时函数内已提示，跳过生成）
                try:
                    with st.spinner("正在翻译并排版英文简历…"):
                        st.session_state["resume_en_bytes"] = resume_pdf.export_resume_pdf(
                            resume_for_export, rewrites or [], lang="en")
                except Exception as exc:
                    show_error(exc)
            if st.session_state.get("resume_en_bytes"):
                st.download_button("Download English Resume PDF",
                                   data=st.session_state["resume_en_bytes"],
                                   file_name="Resume-EN.pdf", mime="application/pdf")


def main() -> None:
    """应用入口：密码门（公网）→ 自检 → 初始化 → 四区块顺序渲染。"""
    st.set_page_config(page_title="求职简历诊断助手", layout="wide")
    access_gate()  # 公网模式：未通过访问密码验证，后续一律不渲染
    st.title("求职简历诊断助手")
    st.caption("先分析岗位，再对照简历——交互式 Gap 诊断与改写建议")

    # API Key 分层入口（BYOK）：最终用户在侧栏填自己的 Key，仅存内存会话；
    # 留空则回退团队开发 Key（仅用于开发与预热，不随产品分发）
    with st.sidebar:
        st.subheader("设置")
        if config.PUBLIC_MODE:
            # 公网模式：强制 BYOK——服务器无内置 Key，不填则所有 AI 操作被拦截
            user_key = st.text_input("你的 DeepSeek API Key（必填）", type="password",
                                     help="公网体验版不内置 Key：各人使用各人的额度，"
                                          "Key 只保存在当前会话内存中，不会被存储或传输给他方。")
            if not user_key:
                st.warning("尚未填入 Key，AI 功能不可用")
        else:
            user_key = st.text_input("你的 DeepSeek API Key（可选）", type="password",
                                     help="产品化设计：每位用户使用自己的 Key。留空时使用内置开发配置。Key 只保存在当前会话内存中，不会被存储。")
        llm_client.set_runtime_api_key(user_key)
        # 博查 Key（BYOK，与 DeepSeek 同逻辑）：仅"全网检索岗位"使用，
        # 公网模式强制；本地模式留空由 search_client 回落团队 Key
        bocha_key = st.text_input("你的博查 API Key（仅联网检索用）", type="password",
                                  help="只有点「全网检索岗位」时才需要；不填也能用预设岗位库与粘贴 JD。"
                                       "Key 只保存在当前会话内存中。")
        st.session_state["user_bocha_key"] = bocha_key
        st.caption("运行模式："
                   + ("公网体验版（强制自带 Key）" if config.PUBLIC_MODE
                      else "演示缓存模式（断网可用）" if config.DEMO_CACHE_MODE else "联网模式")
                   + ("｜使用自带 Key" if user_key else ""))
        if config.PUBLIC_MODE:
            st.caption(f"体验额度：每会话 {config.PUBLIC_SESSION_QUOTA} 次 AI 操作"
                       f"（已用 {st.session_state.get('quota_used', 0)} 次）")

    # 冷启动自检（v1.1 建议项1：字体/目录/缓存缺失在启动时暴露）
    issues = config.self_check()
    if issues:
        with st.expander("⚠️ 环境自检发现问题", expanded=True):
            for issue in issues:
                st.warning(issue)

    # P1-7：岗位库只加载一次（setdefault 会先求值参数，每次 rerun 都重读 16 个 JSON）
    if "job_metas" not in st.session_state:
        try:
            st.session_state["job_metas"] = job_analyzer.load_preset_jobs()
        except ValueError as exc:
            st.error(f"岗位库加载失败（请检查 data/jobs 目录）：{exc}")
            st.stop()

    init_state()
    section_job_select()
    section_job_profile()
    section_diagnose()
    section_result()

    st.divider()
    st.caption(
        f"运行模式：{'演示缓存模式（断网可用）' if config.DEMO_CACHE_MODE else '联网模式（DeepSeek API）'}｜"
        f"Prompt 版本：{llm_client.list_prompt_versions()}"
    )


if __name__ == "__main__":
    main()
