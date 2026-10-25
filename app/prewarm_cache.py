"""prewarm_cache.py —— 演示缓存预热脚本（拍摄/提交前必跑）。

【用途】
    在联网环境下运行一次，把 3 个演示案例的全流程 LLM 输出沉淀到
    data/cache/。之后开启演示缓存模式（默认）即可断网演示。

【用法】
    1. 在 .env 中填入真实 DEEPSEEK_API_KEY；
    2. 设置 DEMO_CACHE_MODE=0（联网模式）；
    3. 运行：python prewarm_cache.py
    4. 确认 3 个案例全部成功后，把 DEMO_CACHE_MODE 改回 1。

【依赖清单】项目内全部业务模块；需联网。
"""

from __future__ import annotations

import sys

import config
import gap_matcher
import job_analyzer
import resume_parser
import resume_pdf
import rewriter

# 第二轮审查 P0-3：DEMO_CASES 从 config 单一来源导入，与 main.py 共用；
# 第三轮审查 P0 回归修复：四元组含固定背景，预热与演示使用**完全相同**的
# 诊断参数——缓存键含 background，键一致是"预热成功=演示命中"的前提。
DEMO_CASES = config.DEMO_CASES

# 案例级重试上限：LLM 随机性导致的单条改写虚构拦截，重试重摇大多可通过；
# 超过上限仍失败说明 Prompt 或数据有系统性问题，必须人工介入而非硬刷
MAX_ATTEMPTS = 3


def _snapshot_cache() -> set[str]:
    """返回当前全部缓存文件的相对路径集合（manifest 差量记录用）。"""
    if not config.CACHE_DIR.is_dir():
        return set()
    return {str(p.relative_to(config.CACHE_DIR)) for p in config.CACHE_DIR.rglob("*.json")
            if p.name != "manifest.json"}


def main() -> int:
    """逐案例跑通全流程，LLM 输出经 llm_client 写穿缓存自动落盘。

    每案例预热成功后，用"前后快照差量"记录新增缓存文件；全部成功才写
    data/cache/manifest.json（供 config.self_check 逐项验证）。

    第四轮审查 P1 修复：预热开始前**清空全部旧缓存**（manifest 除外逻辑
    隐含——整个 cache 目录重建）。否则二次预热时差量为空，manifest 被空
    记录覆盖，self_check 误报"缓存清单未覆盖"。预热因此是幂等操作：
    跑几次结果一致，拍前不放心可以重复跑。

    Returns:
        退出码：0 = 全部成功并写入 manifest；1 = 有任一失败（P0-3：
        预热结果必须可脚本化判定，不能只看打印）。
    """
    if config.DEMO_CACHE_MODE:
        print("⚠️ 当前是演示缓存模式（DEMO_CACHE_MODE=1），预热需要联网。")
        print("   请设置 DEMO_CACHE_MODE=0 并配置 DEEPSEEK_API_KEY 后重试。")
        return 1
    if not config.DEEPSEEK_API_KEY:
        print("❌ 未配置 DEEPSEEK_API_KEY，无法预热。")
        return 1

    import json
    import shutil

    # 第四轮 P1：预热前清空旧缓存，保证差量记录完整（幂等预热的前提）
    if config.CACHE_DIR.is_dir():
        shutil.rmtree(config.CACHE_DIR)
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    failed = 0
    entries: list[dict[str, str]] = []
    for label, job_id, resume_file, background in DEMO_CASES:
        print(f"\n=== 预热 {label}（{job_id} + {resume_file}，背景 {background}）===")
        # 第五轮需求扩展：案例级重试（最多 MAX_ATTEMPTS 次）。
        # 背景：llm_client 对任何语法合法的 JSON 都写穿缓存，但 rewriter 的
        # "虚构拦截"等业务校验失败发生在更下游——坏输出已落缓存，同输入重试
        # 必然命中坏缓存。故每次失败后**定向删除本次新增的缓存文件**，
        # 让下一轮重试真正重新调用 LLM；上一轮之前的案例缓存不受影响。
        success = False
        case_before = _snapshot_cache()  # 案例级快照：manifest 差量记录的基准
        for attempt in range(1, MAX_ATTEMPTS + 1):
            # 第六轮审查 P2-1：分阶段快照。每完成一个 LLM 阶段就推进 stage_mark，
            # 失败时只剔除**最后一个失败阶段**的新增缓存——resume_extract/gap_judge
            # 的好缓存得以保留，重试不再浪费 20-40 秒的重复调用。
            stage_mark = _snapshot_cache()
            try:
                if attempt > 1:
                    print(f"  ↻ 第 {attempt}/{MAX_ATTEMPTS} 次尝试（只重摇失败阶段，好缓存保留）")
                job = job_analyzer.analyze_job(job_id=job_id)          # 本地 JSON，无 LLM
                raw = (config.DEMO_DIR / resume_file).read_text(encoding="utf-8")
                resume = resume_parser.parse_pasted_text(raw)          # LLM：resume_extract
                stage_mark = _snapshot_cache()                         # 保住 resume_extract 缓存
                # 关键（第三轮 P0 回归）：必须传入与 main.py 演示路径完全相同的背景
                report = gap_matcher.diagnose(job, resume, background)  # LLM：gap_judge
                stage_mark = _snapshot_cache()                         # 保住 gap_judge 缓存
                results, failures = rewriter.rewrite_all(report["top_gaps"], resume, job)  # LLM：gap_rewrite ×3
                print(f"  匹配度 {report['match_score']}/100，改写 {len(results)} 条"
                      + (f"，失败 {len(failures)} 条: {failures}" if failures else ""))
                if failures:
                    # 单条改写失败也算预热不完整，转为异常走重试路径
                    raise RuntimeError(f"改写不完整: {failures}")
                stage_mark = _snapshot_cache()                         # 保住 gap_rewrite 缓存
                # 第三轮需求扩展：英文简历翻译也须预热（LLM：resume_translate）。
                # 直接调用与 main.py 相同的 export_resume_pdf 路径——缓存键由
                # "已应用改写的富结构"决定，路径一致是"预热成功=演示命中"的前提；
                # v1.3（第十轮）：界面导出时会注入 job_intent=当前岗位名，
                # 预热必须同样注入，否则演示时翻译缓存键不同、必然 CacheMiss；
                # 顺带把样本 PDF 落盘到 实验结果/ 供拍摄前肉眼验收（虚构数据，可外传）。
                samples_dir = config.PROJECT_ROOT / "实验结果"
                samples_dir.mkdir(exist_ok=True)
                resume_with_intent = dict(resume, job_intent=job["job_title"])
                zh_bytes = resume_pdf.export_resume_pdf(resume_with_intent, results, lang="zh")  # 纯排版，无 LLM
                (samples_dir / f"简历样本-{label}-中文.pdf").write_bytes(zh_bytes)
                en_bytes = resume_pdf.export_resume_pdf(resume_with_intent, results, lang="en")  # LLM：resume_translate
                (samples_dir / f"简历样本-{label}-英文.pdf").write_bytes(en_bytes)
                print(f"  中英简历样本已落盘（中文 {len(zh_bytes)//1024}KB / 英文 {len(en_bytes)//1024}KB）")
                # 差量记录本案例新增的缓存文件（基准=案例级快照，含各阶段好缓存）
                for f in sorted(_snapshot_cache() - case_before):
                    entries.append({"case": label, "prompt_key": f.split("\\")[0].split("/")[0],
                                    "file": f})
                success = True
                break
            except Exception as exc:
                print(f"  ❌ 第 {attempt} 次失败: {exc}")
                # P2-1：只剔除最后一个失败阶段的新增缓存（含坏输出），
                # 前面阶段的好缓存保留，重试命中不重复调用
                for f in _snapshot_cache() - stage_mark:
                    (config.CACHE_DIR / f).unlink(missing_ok=True)
                if attempt == MAX_ATTEMPTS:
                    failed += 1
        if not success:
            continue
    if failed:
        print(f"\n❌ {failed}/{len(DEMO_CASES)} 个案例预热失败，缓存不完整，禁止进入拍摄。")
        return 1
    config.CACHE_MANIFEST_PATH.write_text(
        json.dumps({"entries": entries}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 全部案例预热成功，manifest 已记录 {len(entries)} 个缓存文件。")
    print("   请将 DEMO_CACHE_MODE 改回 1，并用 self_check() 验证断网可演示。")
    prewarm_search_case()  # 可选增强项：失败只警告，不影响三案例预热结果
    return 0


def prewarm_search_case() -> bool:
    """可选预热：AI 联网检索演示案例（双通道版，v1.6）。

    预热链路 = 演示链路（与 server/main.py search_job 端点逐位一致）：
        search(query) → search(build_opinion_query(query))（降级容忍）
        → synthesize_combined → analyze_job(jd_text=combined)。
    全部走写穿缓存——联网跑一次后，断网演示同一 query（逐字一致）全部命中。

    v1.6 变更：双通道后 job_extract 的输入从"单段 JD 摘要"变为
    "JD 段 + 舆情段"合成文本，旧缓存键必然失效，必须重跑本函数。

    保险丝语义：本函数的一切失败只打印警告并返回 False，
    **绝不影响三案例主预热的结果**（搜索是增强项，不是主链路）。

    Returns:
        True = 全部检索案例预热成功；False = 跳过（无 Key）或任一失败。
    """
    import search_client  # 局部导入：仅本函数使用

    # 演示词表：字节/腾讯（既有案例）+ 安永（第十三轮反虚高验收案例）。
    # 演示时检索词必须与此处逐字一致，否则缓存键不同、必然 CacheMiss。
    queries = [config.SEARCH_DEMO_QUERY,
               "腾讯 产品经理 实习 招聘要求",
               "安永 审计 寒假实习 招聘要求"]
    if not config.BOCHA_API_KEY:
        print(f"\n⚠️ 未配置 BOCHA_API_KEY，跳过联网检索案例预热（{queries}）。")
        print("   注册 https://bochaai.com/ 后在 .env 写入 BOCHA_API_KEY=... 再重跑本脚本即可。")
        return False
    ok = True
    for query in queries:
        print(f"\n=== 预热 AI 联网检索案例（query: {query}）===")
        try:
            found = search_client.search(query)  # JD 通道：博查 API + 写穿缓存
            # 面经通道 + 舆情通道（与演示链路同口径）：失败只降级，不阻断预热
            insider_results = None
            try:
                insider = search_client.search(search_client.build_insider_query(query))
                insider_results = insider["results"]
                print(f"  面经通道：{len(insider['urls'])} 条真实门槛摘要已缓存")
            except Exception as exc:
                print(f"  ⚠️ 面经通道降级（不影响 JD 主链路）: {exc}")
            opinion_results = None
            try:
                opinion = search_client.search(search_client.build_opinion_query(query))
                opinion_results = opinion["results"]
                print(f"  舆情通道：{len(opinion['urls'])} 条小红书/知乎摘要已缓存")
            except Exception as exc:
                print(f"  ⚠️ 舆情通道降级（不影响 JD 主链路）: {exc}")
            combined = search_client.synthesize_combined(
                query, found["results"], opinion_results, insider_results)
            job = job_analyzer.analyze_job(jd_text=combined)  # LLM：job_extract
            n_infer = sum(1 for ab in job["abilities"]
                          if ab.get("source_type") == "expert_inference")
            n_intel = sum(1 for ab in job["abilities"]
                          if ab.get("source_type", "jd_requirement")
                          not in ("jd_requirement", "expert_inference"))
            print(f"  ✅ 检索 {len(found['urls'])} 个 JD 来源，抽取岗位「{job['job_title']}」，"
                  f"{len(job['abilities'])} 项指标（含 {n_infer} 项隐性门槛推断、"
                  f"{n_intel} 项环境情报）——断网演示已就绪")
        except Exception as exc:  # 保险丝：任何异常都只警告
            print(f"  ⚠️ 检索案例预热失败（不影响三案例）: {exc}")
            ok = False
    return ok


if __name__ == "__main__":
    sys.exit(main())
