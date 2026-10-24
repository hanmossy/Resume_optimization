"""server/main.py —— FastAPI 入口：RESTful API + 前端静态托管。

【模块说明】
    前后端分离架构的后端层（团队拍板重构，Streamlit 版保留于 streamlit-legacy 分支）。
    本层只做入参出参组装与 HTTP 语义映射，业务逻辑全部复用 app/ 模块，零算法改动。

    端点清单：
        GET  /api/health            服务状态与运行模式
        POST /api/auth              访问密码校验（PUBLIC_MODE）
        GET  /api/jobs              岗位库目录（JobMeta[]）
        GET  /api/demo-cases        演示案例注册表（前端一键载入）
        GET  /api/demo-resume/{fn}  演示简历文本
        POST /api/analyze-job       岗位分析（job_id 或 jd_text）
        POST /api/parse-resume      简历解析（multipart 文件 或 文本）
        POST /api/diagnose          Gap 诊断 + Top3 改写（串联 gap_matcher/rewriter）
        POST /api/export-report     诊断报告 PDF（application/pdf 流）
        POST /api/export-resume     中英简历 PDF（lang=zh/en）

    异常映射（contracts 五类业务异常 → HTTP 状态码 + JSON detail）：
        PDFParseError→422, LLMOutputError→502, LLMUnavailableError→503,
        CacheMissError→409, PDFExportError→500, 其他→500

【依赖清单】
    第三方：fastapi, uvicorn, python-multipart
    项目内：config, contracts, llm_client, job_analyzer, resume_parser,
            gap_matcher, rewriter, pdf_exporter, resume_pdf, server.schemas, server.deps

【运行】开发：uvicorn server.main:app --reload --port 8000
        生产：python -m server.main（托管 web/dist 静态文件，单端口 8501）
"""
from __future__ import annotations

import sys
from pathlib import Path

# 业务模块在 app/ 目录，加入 import 路径（server 与 app 平级）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

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
    SearchUnavailableError,
)
from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from server.deps import check_session_quota, extract_bocha_key, inject_byok, verify_access
from server.schemas import (
    AnalyzeJobRequest,
    AuthRequest,
    DiagnoseRequest,
    ExportReportRequest,
    ExportResumeRequest,
    SearchJobRequest,
    resume_from_wire,
    resume_to_wire,
)

app = FastAPI(title="求职简历诊断助手 API", version="2.0", docs_url="/api/docs")

# 演示案例简历文件白名单（防路径穿越：只允许 DEMO_CASES 注册的文件名）
_DEMO_FILES = {case[2] for case in config.DEMO_CASES}

# 异常 → HTTP 状态码映射表（v1.1 S3 异常分类的 HTTP 兑现）
_ERROR_STATUS = {
    PDFParseError: 422,       # 输入内容问题
    LLMOutputError: 502,      # 上游 AI 输出异常
    LLMUnavailableError: 503, # 上游不可用（含限流）
    CacheMissError: 409,      # 演示缓存未命中
    PDFExportError: 500,
}


@app.exception_handler(AppError)
async def app_error_handler(_req: Request, exc: AppError) -> JSONResponse:
    """业务异常统一映射为 JSON 错误（前端按状态码分级提示）。"""
    status = next((v for k, v in _ERROR_STATUS.items() if isinstance(exc, k)), 500)
    return JSONResponse(status_code=status, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# 基础端点
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    """服务状态（前端启动时探测运行模式，决定 UI 提示口径）。"""
    return {
        "ok": True,
        "public_mode": config.PUBLIC_MODE,
        "demo_cache_mode": config.DEMO_CACHE_MODE,
        "session_quota": config.PUBLIC_SESSION_QUOTA,
    }


@app.post("/api/auth")
def auth(body: AuthRequest) -> dict:
    """访问密码校验（PUBLIC_MODE）；非公网模式恒通过。"""
    if not config.PUBLIC_MODE or not config.ACCESS_PASSWORD:
        return {"ok": True}
    if body.password != config.ACCESS_PASSWORD:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="访问密码错误")
    return {"ok": True}


@app.get("/api/jobs", dependencies=[Depends(verify_access)])
def list_jobs() -> list[dict]:
    """岗位库目录（供选岗下拉框）。"""
    return [dict(m) for m in job_analyzer.load_preset_jobs()]


@app.get("/api/demo-cases", dependencies=[Depends(verify_access)])
def demo_cases() -> list[dict]:
    """演示案例注册表（label/job_id/简历文件名/固定背景）。"""
    return [
        {"label": label, "job_id": job_id, "resume_file": rf, "background": bg}
        for label, job_id, rf, bg in config.DEMO_CASES
    ]


@app.get("/api/demo-resume/{filename}", dependencies=[Depends(verify_access)])
def demo_resume(filename: str) -> dict:
    """读取演示简历文本（白名单校验，防路径穿越）。"""
    if filename not in _DEMO_FILES:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="演示简历不存在")
    text = (config.DEMO_DIR / filename).read_text(encoding="utf-8")
    return {"filename": filename, "text": text}


# ---------------------------------------------------------------------------
# 核心业务端点（全部无状态：前端持有 job/resume/report 数据并回传）
# ---------------------------------------------------------------------------


@app.post("/api/analyze-job")
async def analyze_job(body: AnalyzeJobRequest,
                      session_id: str = Depends(verify_access),
                      _key: None = Depends(inject_byok)) -> dict:
    """岗位分析：预设 ID 或自定义 JD 二选一（预设岗位为本地 JSON，不调 LLM）。

    自定义 JD 走 LLM，PUBLIC_MODE 下受 BYOK 与限流约束。
    """
    if body.jd_text:  # 仅 LLM 路径消耗会话配额
        check_session_quota(session_id)
    result = await run_in_threadpool(
        job_analyzer.analyze_job, job_id=body.job_id, jd_text=body.jd_text)
    return dict(result)


@app.post("/api/search-job")
async def search_job(body: SearchJobRequest,
                     session_id: str = Depends(verify_access),
                     _key: None = Depends(inject_byok),
                     bocha_key: str = Depends(extract_bocha_key)) -> dict:
    """AI 联网检索岗位（第九轮指令）：博查搜索 → 合成文本 → job_extract 抽取。

    保险丝语义：
        - 检索失败（超时/断网/无 Key）→ SearchUnavailableError → 503，
          前端引导改用预设岗位库，主链路不受影响；
        - 演示缓存模式下 query 未预热 → CacheMissError → 409；
        - 消耗会话配额（LLM 调用 + 检索双重成本）。

    Key 逻辑（BYOK，与 DeepSeek 一致）：公网用户必须用自己的博查 Key
    （X-User-Bocha-Key 头，PUBLIC_MODE 缺失即 400）；团队 Key 仅存在于
    开发机 .env 用于预热，公网服务器刻意不配置。

    Returns:
        {"job": JobRequirements, "source": "AI联网检索", "source_urls": [...],
         "opinion_urls": [...], "opinion_status": "ok" | "none"}
        job 是独立字段——下游 /api/diagnose 只认 job，来源信息仅供展示。
        v1.6（第十二轮 Human-in-the-loop）：双通道检索——JD 摘要 + 小红书/知乎
        舆情摘要合并进 job_extract，产出带 source_type 的指标池（含环境情报）。
    """
    check_session_quota(session_id)
    found = await run_in_threadpool(search_client.search, body.query, bocha_key or None)
    # 舆情通道（保险丝）：失败/未预热/无结果一律降级为 none，绝不阻塞主链路
    opinion_urls: list[str] = []
    opinion_results: list[dict[str, str]] | None = None
    try:
        opinion = await run_in_threadpool(
            search_client.search, search_client.build_opinion_query(body.query), bocha_key or None)
        opinion_results = opinion["results"]
        opinion_urls = opinion["urls"]
    except (SearchUnavailableError, CacheMissError):
        pass  # 舆情是增强维度：降级后指标池显示"暂无显著舆论风险"
    combined = search_client.synthesize_combined(body.query, found["results"], opinion_results)
    job = await run_in_threadpool(job_analyzer.analyze_job, None, combined)
    # 覆盖元字段：标注检索来源（importance_source 已被 analyze_job 标为 LLM评估）
    job["job_id"] = "search"
    opinion_note = f"，含 {len(opinion_urls)} 条小红书/知乎舆情" if opinion_urls else "（未检索到舆情信息）"
    job["source_note"] = f"AI 联网检索生成（{len(found['urls'])} 个 JD 网页摘要{opinion_note}），请人工核验"
    return {"job": dict(job), "source": "AI联网检索", "source_urls": found["urls"],
            "opinion_urls": opinion_urls,
            "opinion_status": "ok" if opinion_urls else "none"}


@app.post("/api/parse-resume")
async def parse_resume(session_id: str = Depends(verify_access),
                       _key: None = Depends(inject_byok),
                       file: UploadFile | None = File(default=None),
                       text: str = Form(default="")) -> dict:
    """简历解析：multipart 文件（PDF/TXT）或粘贴文本，二选一。

    Returns:
        ResumeData（photo_bytes 为 base64 字符串）。
    """
    check_session_quota(session_id)  # LLM 调用（resume_extract）
    if file is not None and file.filename:
        data = await file.read()
        resume = await run_in_threadpool(resume_parser.parse_resume, data, file.filename)
    elif text.strip():
        resume = await run_in_threadpool(resume_parser.parse_pasted_text, text)
    else:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="请上传简历文件或粘贴简历文本")
    return resume_to_wire(resume)


@app.post("/api/diagnose")
async def diagnose(body: DiagnoseRequest,
                   session_id: str = Depends(verify_access),
                   _key: None = Depends(inject_byok)) -> dict:
    """Gap 诊断 + Top3 改写（一次调用串联两步，对齐"2 次点击"交互约束）。"""
    # v1.5 前置必填护栏（第十二轮指令）：可到岗实习时间是诊断的必要输入——
    # 缺它，"实习时长/稳定性"类能力项无从判断；422 在扣额度之前拦截
    if not body.background.availability.strip():
        raise HTTPException(status_code=422,
                            detail="请先填写可到岗实习时间（前置必填信息），再开始诊断")
    check_session_quota(session_id)  # LLM 调用（gap_judge + gap_rewrite×N）
    resume = resume_from_wire(body.resume)
    report = await run_in_threadpool(
        gap_matcher.diagnose, body.job, resume, body.background.to_dict())
    try:
        rewrites, failures = await run_in_threadpool(
            rewriter.rewrite_all, report["top_gaps"], resume, body.job)
    except (CacheMissError, LLMUnavailableError) as exc:
        # P0-3 口径：全局性失败时诊断报告保留，改写整体作废并显式说明
        rewrites, failures = [], [f"改写建议整体不可用：{exc}"]
    return {"report": dict(report), "rewrites": [dict(r) for r in rewrites],
            "rewrite_failures": failures,
            # 运算过程明细（重要度 × 命中系数逐项摊开）：前端"查看运算过程"面板的数据源，
            # 由 gap_matcher 单一公式产出，前端只渲染不复算（人机协同透明度，第七轮落地项）
            "score_detail": gap_matcher.score_breakdown(report["items"])}


@app.post("/api/export-report", dependencies=[Depends(verify_access)])
async def export_report(body: ExportReportRequest) -> Response:
    """导出诊断报告 PDF（字节流，前端 Blob 下载）。"""
    pdf = await run_in_threadpool(
        pdf_exporter.export_pdf, body.job, {}, body.report, body.rewrites)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=report.pdf"})


@app.post("/api/export-resume")
async def export_resume(body: ExportResumeRequest,
                        session_id: str = Depends(verify_access),
                        _key: None = Depends(inject_byok)) -> Response:
    """导出中英简历 PDF（lang=zh 纯排版无 LLM；lang=en 内部翻译，受 BYOK 约束）。"""
    if body.lang == "en":
        check_session_quota(session_id)  # LLM 调用（resume_translate）
    resume = resume_from_wire(body.resume)
    # 求职意向注入（v1.3）：界面层传入的当前岗位名 → 简历头部"求职意向"行
    resume["job_intent"] = body.job_title.strip()
    pdf = await run_in_threadpool(
        resume_pdf.export_resume_pdf, resume, body.rewrites, body.lang)
    filename = "resume-zh.pdf" if body.lang == "zh" else "resume-en.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


# ---------------------------------------------------------------------------
# 前端静态托管（生产模式：web/dist 与本服务同端口，天然无 CORS）
# ---------------------------------------------------------------------------

_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="web")


def main() -> None:
    """生产入口：单端口托管 API + 前端静态文件。"""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8501, log_level="info")


if __name__ == "__main__":
    main()
