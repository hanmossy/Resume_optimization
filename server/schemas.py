"""server/schemas.py —— FastAPI 请求/响应模型（Pydantic v2）。

【模块说明】
    API 层只做入参出参组装，业务逻辑全部复用 app/ 模块（绝不修改算法）。
    ResumeData 跨网络传输时 photo_bytes 以 base64 字符串承载。

【依赖清单】第三方：pydantic（FastAPI 自带）
"""
from __future__ import annotations

import base64
from typing import Any

from pydantic import BaseModel, Field

from contracts import JobRequirements, ResumeData  # noqa: F401  (类型注解用)


class AuthRequest(BaseModel):
    """访问密码校验请求（PUBLIC_MODE）。"""

    password: str


class AnalyzeJobRequest(BaseModel):
    """岗位分析请求：预设 ID 与自定义 JD 二选一。"""

    job_id: str | None = None
    jd_text: str | None = None


class SearchJobRequest(BaseModel):
    """联网检索岗位请求（第九轮指令：博查搜索 → LLM 抽取岗位画像）。"""

    query: str = Field(min_length=1, max_length=100)


class Background(BaseModel):
    """用户背景信息（进入 gap_judge 的缓存键，字段名与 DEMO_CASES 一致）。

    v1.5 新增 availability（可到岗实习时间，如 "可实习 2026-01 至 2026-06，
    每周 5 天全勤"）：前端由"起止月份 + 每周到岗"两个输入合成；
    供 gap_judge 规则 6（实习时间匹配）与规则 7（背景门槛防误判）使用。
    """

    年级: str = "大三"
    专业: str = "未填写"
    目标: str = "实习"
    availability: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"年级": self.年级, "专业": self.专业, "目标": self.目标,
                "availability": self.availability}


class DiagnoseRequest(BaseModel):
    """诊断请求：岗位画像 + 简历数据 + 背景（无状态，前端回传 analyze 结果）。"""

    job: dict[str, Any]
    resume: dict[str, Any]  # ResumeData，photo_bytes 为 base64 字符串或 None
    background: Background = Field(default_factory=Background)


class ExportReportRequest(BaseModel):
    """诊断报告导出请求。"""

    job: dict[str, Any]
    report: dict[str, Any]
    rewrites: list[dict[str, Any]] = []


class ExportResumeRequest(BaseModel):
    """简历导出请求（中英双语）。

    job_title（v1.3 新增）：导出时注入简历的"求职意向"字段——
    界面层传入当前选中岗位的名称（含 AI 检索生成的岗位）。
    """

    resume: dict[str, Any]
    rewrites: list[dict[str, Any]] = []
    lang: str = "zh"  # zh / en
    job_title: str = ""


def resume_from_wire(data: dict[str, Any]) -> dict[str, Any]:
    """线格式 → 内部格式：photo_bytes 从 base64 字符串还原为 bytes。"""
    d = dict(data)
    photo = d.get("photo_bytes")
    d["photo_bytes"] = base64.b64decode(photo) if isinstance(photo, str) and photo else None
    return d


def resume_to_wire(resume: dict[str, Any]) -> dict[str, Any]:
    """内部格式 → 线格式：photo_bytes 从 bytes 编码为 base64 字符串。"""
    d = dict(resume)
    photo = d.get("photo_bytes")
    d["photo_bytes"] = base64.b64encode(photo).decode("ascii") if photo else None
    return d
