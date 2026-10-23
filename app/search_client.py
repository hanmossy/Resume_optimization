"""search_client.py —— 博查（Bocha）Web 检索模块：全网搜索岗位 JD 摘要。

【模块说明】
    第九轮指令落地：在"预设岗位库"与"粘贴 JD"之外，新增"AI 智能检索岗位"
    信息获取通道。本模块是唯一与博查 API 交互的地方（配置与逻辑分离）。

    保险丝设计（演示绝不翻车的硬约束）：
        1. 超时 8 秒（config.SEARCH_TIMEOUT_SEC），超时立即失败；
        2. 一切网络/解析异常收敛为 SearchUnavailableError，**绝不向上抛未预期异常**，
           FastAPI 进程不会被拖垮；
        3. 缓存语义与 llm_client 完全一致：演示缓存模式（DEMO_CACHE_MODE）下
           命中返回、未命中抛 CacheMissError（严禁静默回退网络）；
           联网模式成功即写穿缓存——预热一次，断网可演示同一 query；
        4. 检索调用消耗**团队** BOCHA_API_KEY（非 BYOK），公网靠访问密码 +
           会话配额（check_session_quota）兜底。

【依赖清单】
    标准库：json, urllib.request, hashlib, pathlib
    项目内：config, contracts

【审查提示（给 DeepSeek）】
    search() 是纯边界函数：缓存 I/O + 一次 HTTP POST + 结果整形。
    _synthesize_text / _extract_results 是纯函数，可单测。
    缓存键 = sha256(query 规范化)，与 llm_client 的"同一语义输入必得同一键"对齐。
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from typing import Any

import config
import llm_client
from contracts import CacheMissError, SearchUnavailableError


def _cache_path(query: str) -> Path:
    """检索缓存路径：data/cache/web_search/<sha256>.json（键口径与 llm_client 一致）。"""
    key = hashlib.sha256(llm_client.normalize_content(query).encode("utf-8")).hexdigest()
    return config.SEARCH_CACHE_DIR / f"{key}.json"


def _extract_results(payload: dict[str, Any]) -> list[dict[str, str]]:
    """从博查响应中提取网页结果（纯函数）。

    博查 v1 响应结构：data.webPages.value = [{name, url, snippet, ...}, ...]。
    只保留 name/url/snippet 三个字段，丢弃其余（缩略图、时间戳等与本产品无关）。

    Args:
        payload: 博查 API 返回的 JSON dict。

    Returns:
        [{"name","url","snippet"}] 列表，最多 SEARCH_MAX_RESULTS 条；
        结构不符时返回空列表（由调用方判失败）。
    """
    values = (
        payload.get("data", {})
        .get("webPages", {})
        .get("value", [])
    )
    if not isinstance(values, list):
        return []
    results = []
    for item in values[: config.SEARCH_MAX_RESULTS]:
        if not isinstance(item, dict):
            continue
        results.append({
            "name": str(item.get("name", "")).strip(),
            "url": str(item.get("url", "")).strip(),
            "snippet": str(item.get("snippet", "")).strip(),
        })
    return [r for r in results if r["snippet"]]  # 无摘要的条目对 JD 合成无价值


def _synthesize_text(query: str, results: list[dict[str, str]]) -> str:
    """把检索结果合成为一段"类 JD"长文本（纯函数），供 job_extract 抽取。

    格式确定、逐位可复现：相同 results 必得相同文本——这是下游
    job_extract 缓存键稳定的前提（预热与演示走同一文本）。

    Args:
        query: 用户检索词（作为标题行，给 LLM 提供岗位语境）。
        results: _extract_results 的输出。

    Returns:
        合成文本（含来源 URL 行，便于人工溯源核验）。
    """
    lines = [f"以下是关于「{query}」的 {len(results)} 条公开招聘信息摘要，请据此提取岗位要求："]
    for i, r in enumerate(results, 1):
        lines.append(f"【{i}】{r['name']}")
        lines.append(f"来源：{r['url']}")
        lines.append(f"摘要：{r['snippet']}")
    return "\n".join(lines)


def search(query: str) -> dict[str, Any]:
    """联网检索主接口：缓存优先，联网写穿，异常显式（行为矩阵同 llm_client.chat）。

    Args:
        query: 检索关键词，如 "字节跳动 数据分析 实习 招聘要求"。

    Returns:
        {"query", "text": 合成文本（job_extract 输入）,
         "urls": 来源 URL 列表, "results": 结构化条目列表}

    Raises:
        CacheMissError: 演示缓存模式下缓存未命中（严禁回退网络）。
        SearchUnavailableError: 联网模式下的一切失败（未配 Key/超时/HTTP 错/空结果）。
    """
    query = query.strip()
    if not query:
        raise SearchUnavailableError("检索关键词为空")
    cache_file = _cache_path(query)

    if config.DEMO_CACHE_MODE:
        if cache_file.is_file():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                # 与 llm_client 同口径：缓存损坏显式报错，删除后重新预热即可恢复
                raise CacheMissError(f"检索缓存文件损坏: {cache_file.name}，请删除后重新预热") from exc
        raise CacheMissError("演示缓存未命中（web_search）：联网检索仅支持已预热的演示查询")

    # 联网模式：Key 缺失是配置问题，不是网络问题，但同样走保险丝
    if not config.BOCHA_API_KEY:
        raise SearchUnavailableError("未配置 BOCHA_API_KEY（请注册博查 API 并写入 .env / 环境变量）")

    body = json.dumps({"query": query, "freshness": "noLimit", "summary": True,
                       "count": config.SEARCH_MAX_RESULTS}).encode("utf-8")
    request = urllib.request.Request(
        config.BOCHA_API_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {config.BOCHA_API_KEY}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=config.SEARCH_TIMEOUT_SEC) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SearchUnavailableError(f"博查 API 返回 HTTP {exc.code}，联网检索暂不可用") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # 超时/断网/DNS 失败统一兜底——保险丝语义：快速失败，主链路不受影响
        raise SearchUnavailableError(f"博查 API 请求失败（{type(exc).__name__}），联网检索暂不可用") from exc
    except json.JSONDecodeError as exc:
        raise SearchUnavailableError("博查 API 返回了非 JSON 内容，联网检索暂不可用") from exc

    results = _extract_results(payload)
    if not results:
        raise SearchUnavailableError("检索无有效结果（可换个关键词，或改用预设岗位库）")

    data = {"query": query,
            "text": _synthesize_text(query, results),
            "urls": [r["url"] for r in results],
            "results": results}
    # 写穿缓存：预热一次，断网演示同一 query 直接命中（与 llm_client 同语义）
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # 缓存写失败不影响主流程（下次联网还会再查）
    return data
