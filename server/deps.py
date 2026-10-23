"""server/deps.py —— FastAPI 依赖注入：访问密码、BYOK 注入、会话限流。

【模块说明】
    公网模式三件套在 API 层的兑现（对齐 Streamlit 版口径）：
        1. 访问密码：X-Access-Password 头校验，未通过一律 401；
        2. 强制 BYOK：X-User-Api-Key 头注入 contextvar（请求级，并发安全）；
        3. 限流：全局每小时滑动窗口（llm_client 层）+ 会话级批次数（本层）。

【依赖清单】第三方：fastapi；项目内：config, llm_client
"""
from __future__ import annotations

import time

import config
import llm_client
from fastapi import Header, HTTPException

# 会话级配额计数：{会话标识: (已用次数, 窗口起点时间戳)}
# 会话标识 = 访问密码（公网邀请制下同密码即同批用户，诚实简化为共享额度）
_session_usage: dict[str, tuple[int, float]] = {}
_SESSION_WINDOW_SEC = 24 * 3600  # 会话额度窗口：24 小时


def verify_access(x_access_password: str = Header(default="")) -> str:
    """访问密码门依赖：PUBLIC_MODE 且配置了密码时强制校验。

    Returns:
        会话标识（密码本身，供限流计数使用）。

    Raises:
        HTTPException 401: 密码缺失或错误。
    """
    if not config.PUBLIC_MODE or not config.ACCESS_PASSWORD:
        return "local"  # 本地/开发模式：无密码门
    if x_access_password != config.ACCESS_PASSWORD:
        raise HTTPException(status_code=401, detail="访问密码缺失或错误")
    return x_access_password


async def inject_byok(x_user_api_key: str = Header(default="")) -> None:
    """BYOK 注入依赖：把用户 Key 写入请求级 contextvar（多用户并发安全）。

    PUBLIC_MODE 下强制：未提供 Key 的请求直接 400，绝不回退团队 Key
    （服务器环境本就刻意不配团队 Key）。

    【为何必须是 async】FastAPI 会把 sync 依赖放进线程池执行，而
    contextvar 的 set 只发生在被复制的线程上下文里，依赖返回后
    主上下文丢失该值——用户 Key 静默变 None，DeepSeek 收到空
    Bearer 报 401（公网实测复现）。async 依赖直接在请求任务的
    事件循环上下文执行，set 生效，随后 run_in_threadpool 复制
    该上下文进入业务线程，Key 链路完整。
    """
    if config.PUBLIC_MODE and not x_user_api_key.strip():
        raise HTTPException(
            status_code=400,
            detail="缺少 DeepSeek API Key：请在左侧设置栏填入你自己的 Key（BYOK）")
    llm_client.set_request_api_key(x_user_api_key or None)


def extract_bocha_key(x_user_bocha_key: str = Header(default="")) -> str:
    """博查 Key 提取依赖（BYOK，与 DeepSeek 同一逻辑——团队 Key 绝不上公网）。

    Returns:
        请求级博查 Key（可能为空字符串，本地模式由 search_client 回落团队 Key）。

    Raises:
        HTTPException 400: PUBLIC_MODE 下未提供——公网用户必须用自己的博查 Key。
    """
    if config.PUBLIC_MODE and not x_user_bocha_key.strip():
        raise HTTPException(
            status_code=400,
            detail="缺少博查 API Key：联网检索需要在左侧设置栏填入你自己的博查 Key（BYOK），或改用预设岗位库")
    return x_user_bocha_key.strip()


def check_session_quota(session_id: str) -> None:
    """会话级限流依赖：超过每会话配额抛 429。

    只对消耗 LLM 的端点挂载（analyze 自定义 JD / diagnose / export-resume-en）。
    """
    if not config.PUBLIC_MODE:
        return
    used, window_start = _session_usage.get(session_id, (0, time.time()))
    if time.time() - window_start > _SESSION_WINDOW_SEC:
        used, window_start = 0, time.time()  # 窗口过期，重置
    if used >= config.PUBLIC_SESSION_QUOTA:
        raise HTTPException(
            status_code=429,
            detail=f"本会话体验额度已用完（{config.PUBLIC_SESSION_QUOTA} 次/24小时）")
    _session_usage[session_id] = (used + 1, window_start)
