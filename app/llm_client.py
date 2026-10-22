"""llm_client.py —— LLM 调用封装：DeepSeek 单模型 + 演示缓存 + 显式异常。

【模块说明】
    全应用唯一访问 LLM 的入口，业务模块只面向 chat() 一个接口编程。
    职责边界（架构 v1.1 S1，四件事，除此之外一概不管）：
        1. 传输：DeepSeek API（OpenAI 兼容协议），标准库 urllib 实现，零 SDK 依赖；
        2. JSON 语法解析：语法不合法 → 重试 1 次 → 抛 LLMOutputError；
        3. 重试：网络层失败重试 1 次（超时 20s）→ 抛 LLMUnavailableError；
        4. 缓存：演示模式（默认）只读缓存，未命中抛 CacheMissError，严禁静默回网络；
           联网模式调用成功后写穿缓存（用于演示前预热 Demo 案例）。
    业务字段校验不在此模块，由调用方使用 contracts.validate_* 完成。

【缓存键规范（架构 v1.1 S2，勿擅自修改）】
    key = sha256(prompt_key + prompt_version + model + SCHEMA_VERSION + normalize(user_content))
    normalize(): NFKC 归一 → 去除零宽不可见字符 → 折叠连续空白；
    dict/list 输入先 json.dumps(sort_keys=True, ensure_ascii=False) 保证序列化稳定。
    缓存文件按 prompt_key 分目录存放：data/cache/<prompt_key>/<key>.json

【Prompt 模板规范】
    文件：data/prompts/<prompt_key>.txt；首行必须为 "# version: x.y"，
    版本号进入缓存键——改 Prompt 不改版本号会导致启动校验之外的缓存错乱，
    因此 load_prompt 解析失败时直接抛 LLMOutputError（暴露在开发期）。

【输出约定】
    chat() 一律返回 dict。对列表型输出（gap_judge），Prompt 要求模型返回
    {"items": [...]} 包装对象，由业务模块取 ["items"]——保持本模块返回类型统一。

【依赖清单】
    标准库：hashlib, json, time, unicodedata, urllib.request, urllib.error
    项目内：config, contracts
"""

from __future__ import annotations

import hashlib
import json
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import config
from contracts import (
    PROMPT_CONTRACTS,
    SCHEMA_VERSION,
    CacheMissError,
    LLMOutputError,
    LLMUnavailableError,
)

# 零宽/不可见字符表：PDF 提取文本常夹带这些字符，会导致同一简历缓存键漂移（S2）
_INVISIBLE_CHARS = "​‌‍⁠﻿"

# ---------------------------------------------------------------------------
# API Key 分层（产品化要求：开发者 Key 与用户 Key 分离）
#   第一层 团队/开发 Key：来自 .env 的 DEEPSEEK_API_KEY，仅用于本地开发与
#           演示缓存预热（prewarm_cache.py），**不随产品分发给最终用户**；
#   第二层 用户自带 Key：最终用户在界面侧栏填入自己的 Key（BYOK），
#           经 set_runtime_api_key 注入，仅存在于内存会话，不落盘、不缓存。
#   解析顺序：用户 Key 优先，未提供时回退团队 Key；两者皆无且非缓存模式
#   → 调用必然失败并报 LLMUnavailableError（config 已强制转入缓存模式）。
# ---------------------------------------------------------------------------

_runtime_api_key: str | None = None


def set_runtime_api_key(key: str | None) -> None:
    """注入用户自带 Key（BYOK）。传 None 或空串则回退到团队 Key。

    Args:
        key: 用户在界面输入的 DeepSeek API Key；仅保存在内存中，
            会话结束即销毁，不写入任何文件。
    """
    global _runtime_api_key
    _runtime_api_key = key.strip() if key and key.strip() else None


def _effective_api_key() -> str:
    """返回当前生效的 Key：用户自带优先，其次团队 .env 配置。"""
    return _runtime_api_key or config.DEEPSEEK_API_KEY


def has_runtime_key() -> bool:
    """用户是否已在会话中注入自带 Key（main.py 强制 BYOK 检查用）。"""
    return _runtime_api_key is not None


# ---------------------------------------------------------------------------
# 公网全局限流（PUBLIC_MODE，第六轮后新增）
# 实现说明（诚实口径）：进程内滑动窗口计数，轻量级——防误刷、防薅羊毛，
# 不防专业攻击（那需要网关/WAF 层）。多线程下 GIL 保证列表操作原子性，
# 精度对本场景足够。进程重启计数清零，属可接受偏差。
# ---------------------------------------------------------------------------

import time as _time

_global_call_times: list[float] = []  # 最近一小时内每次 LLM 调用的时间戳


def _check_global_quota() -> None:
    """公网模式全局每小时限流，超限抛 LLMUnavailableError（界面提示稍后再试）。"""
    if not config.PUBLIC_MODE:
        return
    now = _time.time()
    cutoff = now - 3600
    while _global_call_times and _global_call_times[0] < cutoff:
        _global_call_times.pop(0)
    if len(_global_call_times) >= config.PUBLIC_GLOBAL_HOURLY_QUOTA:
        raise LLMUnavailableError(
            f"公共服务已达每小时调用上限（{config.PUBLIC_GLOBAL_HOURLY_QUOTA} 次），请稍后再试")
    _global_call_times.append(now)


# ---------------------------------------------------------------------------
# Prompt 加载与版本解析
# ---------------------------------------------------------------------------


def load_prompt(prompt_key: str) -> tuple[str, str]:
    """读取 Prompt 模板并解析版本号。

    Args:
        prompt_key: 契约表中的键，如 "job_extract"。

    Returns:
        (版本号, 模板正文)，版本号取自模板首行 "# version: x.y"。

    Raises:
        LLMOutputError: prompt_key 不在契约表、模板文件缺失、或首行版本号缺失。
            三者均为开发期错误，必须立即暴露而非运行时降级。
    """
    if prompt_key not in PROMPT_CONTRACTS:
        raise LLMOutputError(f"未知 prompt_key: {prompt_key!r}，须在 contracts.PROMPT_CONTRACTS 中登记")
    path = config.PROMPTS_DIR / f"{prompt_key}.txt"
    if not path.is_file():
        raise LLMOutputError(f"Prompt 模板缺失: {path}")
    text = path.read_text(encoding="utf-8")
    first_line = text.split("\n", 1)[0].strip()
    if not (first_line.startswith("#") and "version:" in first_line):
        raise LLMOutputError(f"Prompt 模板 {path.name} 首行缺少版本号（格式：# version: x.y）")
    version = first_line.split("version:", 1)[1].strip()
    body = text.split("\n", 1)[1] if "\n" in text else ""
    return version, body


def list_prompt_versions() -> dict[str, str]:
    """列出全部已登记 Prompt 的版本号，供启动自检打印（架构 v1.1 建议项2）。

    Returns:
        {prompt_key: 版本号或错误说明}，不抛异常——自检函数必须自身健壮。
    """
    result: dict[str, str] = {}
    for key in PROMPT_CONTRACTS:
        try:
            version, _ = load_prompt(key)
            result[key] = version
        except LLMOutputError as exc:
            result[key] = f"错误: {exc}"
    return result


# ---------------------------------------------------------------------------
# 输入规范化与缓存键
# ---------------------------------------------------------------------------


def normalize_content(content: str | dict | list) -> str:
    """把输入规范化为稳定字符串，消除缓存键/原文匹配漂移。

    分类型处理（第三轮审查 P1-3 修订，防过度归一）：
        - dict/list：json.dumps(sort_keys) 后仅做 NFKC + 去不可见字符，
          **保留空白**——结构化输入中 "x y" 与 "xy" 是不同语义，不得共享缓存；
        - str：NFKC + 去不可见字符 + 移除全部空白——中文文本无需空格分词，
          彻底移除才能容忍"负责 SQL 取数"与"负责SQL取数"的引用差异。
    注意：本函数只服务缓存键与原文子串匹配；发给模型的输入走
    _format_model_input（保留段落结构，P1-8）。

    Args:
        content: 原始输入（str / dict / list）。

    Returns:
        规范化后的字符串，同一语义输入必得同一输出。
    """
    if isinstance(content, (dict, list)):
        # sort_keys 保证字段序不影响键；保留空白以区分语义不同的值
        text = json.dumps(content, sort_keys=True, ensure_ascii=False)
        text = unicodedata.normalize("NFKC", text)
        return text.translate({ord(c): None for c in _INVISIBLE_CHARS})
    text = unicodedata.normalize("NFKC", str(content))
    text = text.translate({ord(c): None for c in _INVISIBLE_CHARS})
    return "".join(text.split())  # 移除一切空白字符（含换行、空格、制表符）


def make_cache_key(prompt_key: str, prompt_version: str, user_content: str | dict | list) -> str:
    """生成完整缓存键（架构 v1.1 S2：五个成分缺一不可）。

    Args:
        prompt_key: 契约表键。
        prompt_version: 模板版本号（改 Prompt 须改版本，旧缓存自动失效）。
        user_content: 用户输入，先经 normalize_content 规范化。

    Returns:
        sha256 十六进制串。
    """
    material = "|".join([
        prompt_key,
        prompt_version,
        config.PRIMARY_MODEL,
        SCHEMA_VERSION,
        normalize_content(user_content),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _cache_path(prompt_key: str, key: str) -> Path:
    """缓存文件路径：data/cache/<prompt_key>/<key>.json（分目录便于人工检查）。"""
    return config.CACHE_DIR / prompt_key / f"{key}.json"


# ---------------------------------------------------------------------------
# DeepSeek HTTP 调用（标准库实现，OpenAI 兼容协议）
# ---------------------------------------------------------------------------


def _format_model_input(user_content: str | dict | list) -> str:
    """生成发给模型的输入文本（P1-8：与缓存键规范化分离）。

    缓存键必须折叠空白以求稳定，但模型输入要保留段落结构——
    简历原文的换行是结构化抽取的重要线索，折叠成单行会显著降低质量。

    Args:
        user_content: 原始输入（str / dict / list）。

    Returns:
        str 原样返回；dict/list 用缩进 JSON 序列化（保留层次结构）。
    """
    if isinstance(user_content, (dict, list)):
        return json.dumps(user_content, ensure_ascii=False, indent=2)
    return str(user_content)


def _call_deepseek(system_prompt: str, user_content: str) -> dict[str, Any]:
    """单次 DeepSeek chat/completions 调用（含 1 次重试，超时 20s，t=0）。

    Args:
        system_prompt: Prompt 模板正文。
        user_content: 保留段落结构的模型输入（_format_model_input 产出）。

    Returns:
        语法合法的 JSON dict（模型输出被 response_format 约束为 JSON 对象）。

    Raises:
        LLMUnavailableError: 网络/超时/HTTP 错误、响应体非法 JSON 或结构异常，
            重试后仍失败（P0-6：响应体异常统一包装，不允许未预期异常逃逸）。
        LLMOutputError: 模型 content 的 JSON 语法不合法，重试后仍失败。
    """
    payload = json.dumps({
        "model": config.PRIMARY_MODEL,
        "temperature": config.LLM_TEMPERATURE,
        "response_format": {"type": "json_object"},  # 强制 JSON 对象输出
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }).encode("utf-8")
    request = urllib.request.Request(
        url=f"{config.DEEPSEEK_BASE_URL}/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_effective_api_key()}",  # Key 分层：用户 Key 优先
        },
        method="POST",
    )

    last_network_error: str = ""
    for attempt in range(1 + config.LLM_MAX_RETRIES):
        if attempt > 0:
            time.sleep(1.0)  # 重试前短暂退避，避免瞬时故障连续命中
        try:
            with urllib.request.urlopen(request, timeout=config.LLM_TIMEOUT_SEC) as resp:
                raw_body = resp.read().decode("utf-8")
            try:
                body = json.loads(raw_body)
            except json.JSONDecodeError as exc:
                # P0-6：HTTP 200 但响应体不是 JSON（代理劫持/网关错误页等），
                # 属服务异常而非模型输出异常，归入 Unavailable
                raise LLMUnavailableError(f"API 响应体不是合法 JSON: {exc}") from exc
            try:
                content = body["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                # P0-6：响应结构不符合 OpenAI 协议（如错误对象），同样归入服务异常
                raise LLMUnavailableError(f"API 响应结构异常: {exc}，响应体前 200 字符: {raw_body[:200]!r}") from exc
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                # 模型输出 JSON 语法失败：重试一次（模型偶发输出多余文本），仍失败则抛输出异常
                if attempt < config.LLM_MAX_RETRIES:
                    continue
                raise LLMOutputError(f"模型返回非法 JSON: {exc}") from exc
            if not isinstance(parsed, dict):
                raise LLMOutputError(f"模型返回非 JSON 对象: {type(parsed).__name__}")
            return parsed
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # URLError 覆盖连接拒绝/HTTP 错误；网络层失败可重试
            last_network_error = str(exc)
            continue
    raise LLMUnavailableError(
        f"DeepSeek 调用失败（已重试 {config.LLM_MAX_RETRIES} 次）: {last_network_error}"
    )


# ---------------------------------------------------------------------------
# 对外唯一接口
# ---------------------------------------------------------------------------


def chat(prompt_key: str, user_content: str | dict | list) -> dict[str, Any]:
    """LLM 调用唯一入口：缓存优先，联网写穿，异常显式。

    行为矩阵（架构 v1.1 S2）：
        演示模式(DEMO_CACHE_MODE=True)：命中 → 返回缓存；未命中 → CacheMissError。
        联网模式：调 DeepSeek → 成功后写穿缓存 → 返回；失败按异常分类抛出。

    Args:
        prompt_key: 契约表键（决定 Prompt 模板与缓存目录）。
        user_content: 用户输入（任意可规范化类型）。

    Returns:
        语法合法的 JSON dict。列表型输出以 {"items": [...]} 包装（见模块说明）。

    Raises:
        CacheMissError: 演示模式下缓存未命中（严禁在此捕获后回退网络）。
        LLMUnavailableError: 联网模式下网络层失败。
        LLMOutputError: Prompt 模板问题或模型输出语法非法。
    """
    version, system_prompt = load_prompt(prompt_key)
    key = make_cache_key(prompt_key, version, user_content)
    cache_file = _cache_path(prompt_key, key)

    if config.DEMO_CACHE_MODE:
        if cache_file.is_file():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                # P2（第三轮审查第4条）：缓存文件损坏必须显式报错，
                # 不能落到"未预期错误"——删除损坏文件后重新预热即可恢复
                raise CacheMissError(f"演示缓存文件损坏: {cache_file.name}，请删除后重新预热") from exc
        # 显式报错而非静默联网——拍摄现场断网时静默联网 = 挂起 20s 后崩溃
        raise CacheMissError(f"演示缓存未命中（{prompt_key}），仅支持内置 Demo 案例")

    _check_global_quota()  # 公网模式：全局每小时限流（本地/预热模式直接放行）
    result = _call_deepseek(system_prompt, _format_model_input(user_content))
    # 写穿缓存：联网模式下的成功调用自动沉淀为演示缓存（预热 Demo 的机制）
    # 写穿缓存：联网模式下的成功调用自动沉淀为演示缓存（预热 Demo 的机制）
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
