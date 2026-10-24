"""config.py —— 全局配置层：密钥、模型参数、路径、评分系数、演示模式开关。

【模块说明】
    全应用唯一的配置入口（架构规范：配置与逻辑分离，禁止在业务模块硬编码）。
    - 密钥仅从环境变量读取，缺失时自动落入演示缓存模式并给出警告；
    - DEMO_CACHE_MODE 默认为 True（架构 v1.1 S2 姿态反转：默认安全，联网是显式选择）；
    - self_check() 供启动时调用，把字体缺失、目录缺失等故障暴露在开发期而非演示现场。

【依赖清单】
    标准库：os, pathlib
    第三方：python-dotenv（可选；缺失时跳过 .env 加载，直接读环境变量）

【审查提示（给 DeepSeek）】
    本文件无网络调用。唯一的副作用是 load_dotenv() 读本地 .env 文件。
"""

from __future__ import annotations

import os
from pathlib import Path

# 可选依赖：存在 .env 文件时加载（.env 不进 Git，模板见 .env.example）
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # 演示机直接设系统环境变量即可，python-dotenv 非必需

# ---------------------------------------------------------------------------
# 路径配置（全部相对项目根目录，保证演示机拉下代码即可跑）
# ---------------------------------------------------------------------------

BASE_DIR: Path = Path(__file__).resolve().parent          # app/ 目录
PROJECT_ROOT: Path = BASE_DIR.parent                      # 项目根目录
DATA_DIR: Path = PROJECT_ROOT / "data"
JOBS_DIR: Path = DATA_DIR / "jobs"                        # 预设岗位库（16 个 JSON）
PROMPTS_DIR: Path = DATA_DIR / "prompts"                  # Prompt 模板（含版本号）
CACHE_DIR: Path = DATA_DIR / "cache"                      # 演示缓存（按 prompt_key 分目录）
DEMO_DIR: Path = DATA_DIR / "demo"                        # 3 个固定 Demo 案例输入
FONTS_DIR: Path = PROJECT_ROOT / "assets" / "fonts"       # 随项目分发的字体

# ---------------------------------------------------------------------------
# LLM 配置（架构 v1.1 S6：已砍备用模型，单模型 DeepSeek；B 计划 = 缓存 + 热点）
# ---------------------------------------------------------------------------

DEEPSEEK_API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"       # OpenAI 兼容协议端点
PRIMARY_MODEL: str = "deepseek-chat"
LLM_TIMEOUT_SEC: int = 20     # 架构 v1.1 M8：从 30s 压到 20s，匹配演示节奏
LLM_MAX_RETRIES: int = 1      # 重试 1 次后抛 LLMUnavailableError
LLM_TEMPERATURE: float = 0.0  # 架构 v1.1 S5：t=0 是"全链路可复现"的一环

# ---------------------------------------------------------------------------
# 演示缓存模式（架构 v1.1 S2：默认 True；置 "0"/"false" 环境变量可关闭）
# ---------------------------------------------------------------------------

_env_demo = os.environ.get("DEMO_CACHE_MODE", "1").strip().lower()
DEMO_CACHE_MODE: bool = _env_demo not in ("0", "false", "off")

# ---------------------------------------------------------------------------
# 公网部署模式（团队拍板上线，第六轮后新增）
# ---------------------------------------------------------------------------

# PUBLIC_MODE=1 时启用：访问密码门 + 强制 BYOK + 限流三件套。
# 服务器环境变量**绝不放 DEEPSEEK_API_KEY**——团队 Key 零暴露，
# 所有公网用户必须填自己的 Key（内存会话级，BYOK）。
PUBLIC_MODE: bool = os.environ.get("PUBLIC_MODE", "0").strip().lower() in ("1", "true", "on")
# 访问密码：未设置时密码门不启用（self_check 会警告——公网裸奔属配置事故）
ACCESS_PASSWORD: str = os.environ.get("ACCESS_PASSWORD", "")
# 限流参数（轻量级、进程内实现，诚实说明：不防专业攻击，防误刷与薅羊毛）
PUBLIC_SESSION_QUOTA: int = int(os.environ.get("PUBLIC_SESSION_QUOTA", "10"))        # 每会话 AI 调用批次数
PUBLIC_GLOBAL_HOURLY_QUOTA: int = int(os.environ.get("PUBLIC_GLOBAL_HOURLY_QUOTA", "300"))  # 全局每小时 LLM 调用数

# 无 Key 时强制进入缓存模式（否则任何调用必然失败）；
# 公网模式例外：服务器刻意不放团队 Key，Key 由用户 BYOK 在会话中注入
if not DEEPSEEK_API_KEY and not DEMO_CACHE_MODE and not PUBLIC_MODE:
    DEMO_CACHE_MODE = True

# ---------------------------------------------------------------------------
# 联网检索配置（第九轮指令：博查 Web Search，"带保险丝的增强项"）
# ---------------------------------------------------------------------------

# 博查 API Key（https://bochaai.com/ 注册获取）。BYOK 逻辑与 DeepSeek 完全一致：
# 团队 Key 只存在于开发机 .env（用于本地预热检索案例）；公网服务器刻意不配置，
# 公网用户必须填自己的博查 Key（X-User-Bocha-Key 头，依赖层强制 400）。
BOCHA_API_KEY: str = os.environ.get("BOCHA_API_KEY", "")
BOCHA_API_URL: str = "https://api.bochaai.com/v1/web-search"
SEARCH_TIMEOUT_SEC: int = 8     # 保险丝：超时立即失败，绝不拖垮 FastAPI 进程
SEARCH_MAX_RESULTS: int = 10    # 取前 N 条摘要合成检索文本
SEARCH_CACHE_DIR: Path = CACHE_DIR / "web_search"  # 检索结果缓存（与 LLM 缓存同套语义）
# 演示检索案例（预热用）：query 固定，预热与演示必须逐字一致（缓存键语义同 LLM）
SEARCH_DEMO_QUERY: str = "字节跳动 数据分析 实习 招聘要求"

# v1.6（第十二轮 Human-in-the-loop 指令）：舆情检索通道——小红书/知乎定向搜索
# 岗位评价（加班/转正/带教/避雷），供 job_extract 提取"环境情报"类指标。
# 保险丝语义：舆情检索失败/无结果绝不阻塞主链路（指标池显示"暂无显著舆论风险"）。
# 注意：博查是语义搜索，不遵守 Google 式 site: 语法（实测返回结果与站点限定无关），
# 故改用关键词引导（"小红书 知乎"直接进入 query 文本）。
OPINION_QUERY_SUFFIX: str = "怎么样 评价 避雷 加班 转正 小红书 知乎"

# 演示案例注册表（第二轮审查 P0-3：全局单一来源；第三轮审查 P0 回归修订：
# 扩为四元组，**背景信息一并锁死**——缓存键含 background，预热与演示必须
# 使用完全相同的背景，否则预热成功 ≠ 演示命中）。禁止 main.py / prewarm_cache.py
# 各自维护字面量。每个案例 = (展示名, 固定岗位ID, 固定简历文件名, 固定背景)
DEMO_CASES: tuple[tuple[str, str, str, dict[str, str]], ...] = (
    ("演示案例 1：数据分析实习", "internet_data_analyst", "resume_01.txt",
     {"年级": "大三", "专业": "统计学", "目标": "实习",
      "availability": "可实习 2026-01 至 2026-06，每周 5 天全勤"}),
    ("演示案例 2：四大审计实习", "big4_audit", "resume_02.txt",
     {"年级": "大三", "专业": "会计学", "目标": "实习",
      "availability": "可实习 2026-01 至 2026-05，每周 5 天全勤"}),
    ("演示案例 3：券商行研实习", "securities_research", "resume_03.txt",
     {"年级": "大四", "专业": "金融学", "目标": "实习",
      "availability": "可实习 2026-01 至 2026-04，每周 3-4 天"}),
)

# 演示缓存清单文件（prewarm 成功后写入，self_check 据此逐项验证缓存齐全）
CACHE_MANIFEST_PATH: Path = CACHE_DIR / "manifest.json"

# ---------------------------------------------------------------------------
# Gap 评分规则参数（规则通道的唯一参数源，gap_matcher 不得自行定义）
# ---------------------------------------------------------------------------

# v1.4 防虚高公式（第十一轮指令，反例驱动：沾边即满分 + 软技能占权 + 无门槛
# 否决曾导致"大二营业厅实习 vs 中信研究所"拿到 91-96 分的荒谬结果）：
#   命中系数 = f(status, evidence_strength)：
#     matched + strong（有具体业绩/数据/深度细节） = 1.0
#     matched + weak（平铺直叙、一笔带过）         = 0.7
#     partial                                       = 0.4
#     missing                                       = 0.0
#   软技能降权：category == "软技能" 的能力项权重打 5 折；
#   核心项一票否决：任一 is_core 能力项 partial/missing → 总分 ×0.6 且封顶 60。
HIT_COEF: dict[str, dict[str, float] | float] = {
    "matched": {"strong": 1.0, "weak": 0.7},
    "partial": 0.4,
    "missing": 0.0,
}
SOFT_SKILL_WEIGHT_DISCOUNT: float = 0.5  # 软技能权重折扣
CORE_PENALTY_FACTOR: float = 0.6         # 核心项未达标时总分乘数
CORE_SCORE_CAP: int = 60                 # 核心项未达标时总分封顶
TOP_GAPS_COUNT: int = 3       # 改写模块聚焦的 Gap 数量（交互≤2轮约束的配套）

# ---------------------------------------------------------------------------
# 简历解析与 PDF 导出参数
# ---------------------------------------------------------------------------

# 文本层质量阈值（架构 v1.1 S3：低于阈值按扫描件处理，抛 PDFParseError）
PDF_MIN_TEXT_LENGTH: int = 50
PDF_MIN_CHINESE_RATIO: float = 0.10

# 字体：随项目分发（架构 v1.1 S4），注册固定字体名，禁止依赖系统路径
# 思源黑体（SIL OFL 许可，可再分发）；如更换字体须同步修改此处与 pdf_exporter
PDF_FONT_NAME: str = "CJK"
PDF_FONT_PATH: Path = FONTS_DIR / "NotoSansSC-Regular.ttf"
# 粗体（简历生成器：姓名/分节标题用）；如更换字体须同步修改 resume_pdf.py
PDF_FONT_BOLD_NAME: str = "CJK-Bold"
PDF_FONT_BOLD_PATH: Path = FONTS_DIR / "NotoSansSC-Bold.ttf"
# 符号字体（简历生成器：➢ bullet 专用——思源黑体不含该字模；
# DejaVu Sans 为 Bitstream Vera 许可，可再分发，仅用于符号渲染）
# 命名注意：不能用 "Symbol"——它是 PDF 内置 14 字体之一，同名注册会被
# reportlab 静默跳过，符号被内置 Symbol 字体渲染成豆腐块（实测踩坑）
PDF_FONT_SYMBOL_NAME: str = "DejaVuSym"
PDF_FONT_SYMBOL_PATH: Path = FONTS_DIR / "DejaVuSans.ttf"


def self_check() -> list[str]:
    """启动自检：检查目录、字体与演示缓存齐全性，返回问题清单（空列表 = 全部通过）。

    设计意图（第三轮审查修订）："自检通过"必须等价于"断网可演示 3 个案例"。
    缓存齐全性以 manifest.json 为准——prewarm 预热成功时逐项记录写入的
    缓存文件，自检逐条验证文件存在；只查目录非空无法发现键不一致或缺案例。

    Returns:
        问题描述列表；空列表表示环境就绪。main.py 启动时调用并展示。
    """
    import json  # 局部导入：仅 manifest 校验使用

    issues: list[str] = []
    if PUBLIC_MODE and not ACCESS_PASSWORD:
        issues.append("公网模式未设置访问密码（ACCESS_PASSWORD 环境变量），站点处于裸奔状态")
    for d in (JOBS_DIR, PROMPTS_DIR, CACHE_DIR, DEMO_DIR):
        if not d.is_dir():
            issues.append(f"目录缺失: {d}")
    if not PDF_FONT_PATH.is_file():
        issues.append(f"字体缺失: {PDF_FONT_PATH}（PDF 导出将失败）")
    for p in (PDF_FONT_BOLD_PATH, PDF_FONT_SYMBOL_PATH):
        if not p.is_file():
            issues.append(f"字体缺失: {p}（简历生成器将失败）")

    if DEMO_CACHE_MODE:
        # Demo 输入文件齐全性（固定岗位 + 固定简历，背景已并入 DEMO_CASES）
        for label, job_id, resume_file, _bg in DEMO_CASES:
            if not (JOBS_DIR / f"{job_id}.json").is_file():
                issues.append(f"{label}：岗位文件缺失 {job_id}.json")
            if not (DEMO_DIR / resume_file).is_file():
                issues.append(f"{label}：简历文件缺失 {resume_file}")
        # manifest 逐项校验（第三轮审查 P1-9：目录非空 ≠ 3 案例缓存齐全）
        if not CACHE_MANIFEST_PATH.is_file():
            issues.append("演示缓存清单缺失: data/cache/manifest.json"
                          "（请联网运行 prewarm_cache.py 预热；退出码必须为 0）")
        else:
            try:
                manifest = json.loads(CACHE_MANIFEST_PATH.read_text(encoding="utf-8"))
                for entry in manifest.get("entries", []):
                    f = CACHE_DIR / entry["file"]
                    if not f.is_file():
                        issues.append(f"缓存文件缺失: {entry['file']}（{entry['case']} 的 {entry['prompt_key']}）")
                covered = {(e["case"], e["prompt_key"]) for e in manifest.get("entries", [])}
                for label, _, _, _bg in DEMO_CASES:
                    # 第六轮审查 P1：resume_translate 必须纳入覆盖检查——漏检会让
                    # 拍摄现场点"生成英文简历 PDF"时 CacheMissError，断在最后一个功能
                    for pk in ("resume_extract", "gap_judge", "gap_rewrite", "resume_translate"):
                        if (label, pk) not in covered:
                            issues.append(f"缓存清单未覆盖: {label} 的 {pk}")
            except (json.JSONDecodeError, KeyError) as exc:
                issues.append(f"缓存清单损坏: {exc}（请重新预热）")
    return issues
