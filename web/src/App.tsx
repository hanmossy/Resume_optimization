import { useCallback, useEffect, useState } from "react";
import { api, ApiError, creds } from "./api";
import Banner from "./components/Banner";
import DiagnoseCard from "./components/DiagnoseCard";
import ExportPanel from "./components/ExportPanel";
import JobProfile from "./components/JobProfile";
import JobSelect from "./components/JobSelect";
import MetricPool from "./components/MetricPool";
import ResultSection from "./components/ResultSection";
import Sidebar from "./components/Sidebar";
import type {
  AbilityItem, Background, DemoCase, DiagnoseResponse, GapReport, JobMeta, JobRequirements,
  ResumeData, RewriteResult, ScoreDetail,
} from "./types";

/** 全局错误提示条（按 HTTP 状态码分级配色）。 */
function ErrorBanner({ err, onClose }: { err: ApiError; onClose: () => void }) {
  const tone = err.status === 401 ? "bg-red-50 text-red-700 border-red-200"
    : err.status === 409 ? "bg-amber-50 text-amber-700 border-amber-200"
    : "bg-red-50 text-red-700 border-red-200";
  return (
    <div className={`flex items-start justify-between gap-3 rounded-lg border px-4 py-3 text-sm ${tone}`}>
      <span>{err.message}</span>
      <button onClick={onClose} className="shrink-0 opacity-60 transition hover:opacity-100">✕</button>
    </div>
  );
}

/** 访问密码门（PUBLIC_MODE）：验证通过前不渲染任何业务内容。 */
function PasswordGate({ onPass }: { onPass: () => void }) {
  const [pwd, setPwd] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true); setErr("");
    try {
      creds.password = pwd;
      await api.auth(pwd);
      onPass();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex min-h-screen items-center justify-center bg-page">
      <div className="card w-full max-w-sm text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-brand text-xl text-white">简</div>
        <h1 className="text-lg font-semibold">求职简历诊断助手</h1>
        <p className="mb-4 mt-1 text-sm text-slate-500">邀请体验版，请输入访问密码</p>
        <input type="password" value={pwd} autoFocus
               onChange={(e) => setPwd(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && submit()}
               placeholder="访问密码"
               className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20" />
        {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
        <button className="btn-primary mt-4 w-full" disabled={busy || !pwd} onClick={submit}>
          {busy ? "验证中…" : "进入"}
        </button>
      </div>
    </div>
  );
}

export default function App() {
  // ---- 凭证与模式 ----
  const [apiKey, setApiKey] = useState(creds.apiKey);
  const [bochaKey, setBochaKey] = useState(creds.bochaKey);
  const [publicMode, setPublicMode] = useState(false);
  const [demoCacheMode, setDemoCacheMode] = useState(true);
  const [gatePassed, setGatePassed] = useState(false);

  // ---- 业务状态（原 Streamlit session_state 的 React 化，无页面刷新） ----
  const [jobs, setJobs] = useState<JobMeta[]>([]);
  const [demoCases, setDemoCases] = useState<DemoCase[]>([]);
  const [poolJob, setPoolJob] = useState<JobRequirements | null>(null);  // v1.6：AI 提取的完整指标池（待用户确认）
  const [job, setJob] = useState<JobRequirements | null>(null);  // 用户确认后的评估框架（筛选+调权重）
  const [excluded, setExcluded] = useState<AbilityItem[]>([]);  // v1.6：用户排除的 AI 建议指标
  const [resume, setResume] = useState<ResumeData | null>(null);
  const [searchUrls, setSearchUrls] = useState<string[] | null>(null);  // AI 检索来源链接
  const [opinionUrls, setOpinionUrls] = useState<string[] | null>(null);  // v1.6：舆情来源链接
  const [opinionStatus, setOpinionStatus] = useState<"ok" | "none" | null>(null);
  const [searchStage, setSearchStage] = useState<string | null>(null);  // 检索步骤提示
  const [report, setReport] = useState<GapReport | null>(null);
  const [rewrites, setRewrites] = useState<RewriteResult[]>([]);
  const [failures, setFailures] = useState<string[]>([]);
  const [scoreDetail, setScoreDetail] = useState<ScoreDetail | null>(null);
  const [serverDown, setServerDown] = useState(false);
  const [demoHint, setDemoHint] = useState<string | null>(null);
  const [demoResumeText, setDemoResumeText] = useState<string | null>(null);
  const [demoBg, setDemoBg] = useState<Background | null>(null);
  const [notice, setNotice] = useState<string | null>(null);  // 一键换岗后的引导提示
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  // 启动：探测运行模式 → 公网模式先过密码门 → 加载岗位目录
  useEffect(() => {
    (async () => {
      try {
        const h = await api.health();
        setPublicMode(h.public_mode);
        setDemoCacheMode(h.demo_cache_mode);
        if (!h.public_mode) setGatePassed(true);
      } catch {
        // health 失败分环境处理（第七轮审查第3条）：
        // 本地开发（localhost）放行以便看页面调样式；公网环境绝不能放用户进一个
        // "能点但没反应"的残破页面——展示维护兜底页
        const local = ["localhost", "127.0.0.1"].includes(window.location.hostname);
        if (local) setGatePassed(true); else setServerDown(true);
      }
    })();
  }, []);

  useEffect(() => {
    if (!gatePassed) return;
    (async () => {
      try {
        setJobs(await api.listJobs());
        setDemoCases(await api.demoCases());
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) setGatePassed(false);
      }
    })();
  }, [gatePassed]);

  /** 状态事务：换岗时清空全部下游（对齐 Streamlit 版 P0-2 语义） */
  const clearDownstream = useCallback(() => {
    setReport(null); setRewrites([]); setFailures([]); setScoreDetail(null);
    setDemoHint(null); setDemoResumeText(null); setDemoBg(null);
    setSearchUrls(null); setOpinionUrls(null); setOpinionStatus(null);
    setPoolJob(null); setExcluded([]);
  }, []);

  /** 一键换岗（第十一轮指令）：保留已解析简历，清空岗位与全部下游结果，
      平滑滚动回选岗区并给出引导提示；用户选完新岗位后无需重新上传简历。 */
  const switchJob = useCallback(() => {
    setJob(null);
    clearDownstream();
    setNotice("已为你保留简历，请选择新的岗位开始诊断（无需重新上传）");
    document.getElementById("step1")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [clearDownstream]);

  /** v1.6 决策阻断点：用户在指标池中勾选/调权重后确认评估框架。
      filtered 只含被采纳的 jd_requirement 指标（含用户调整的重要度）；
      excluded 记录被排除的 AI 建议，供诊断结果页对比展示。 */
  const confirmPool = useCallback((filtered: JobRequirements, ex: AbilityItem[]) => {
    setJob(filtered);
    setExcluded(ex);
    setPoolJob(null);  // 指标池完成使命，卸下
    setNotice(`已按你的评估框架（${filtered.abilities.length} 项指标）构建诊断标准，请上传简历`);
  }, []);

  const handleError = useCallback((e: unknown) => {
    setError(e instanceof ApiError ? e : new ApiError(500, String(e)));
  }, []);

  const runAnalyze = useCallback(async (payload: { job_id?: string; jd_text?: string }) => {
    setBusy(true); setError(null);
    try {
      const j = await api.analyzeJob(payload);
      clearDownstream();
      setNotice(null);  // 新岗位就绪，换岗引导提示使命完成
      setPoolJob(j);  // v1.6：先进指标池（决策阻断点），不直接进诊断
    } catch (e) { handleError(e); } finally { setBusy(false); }
  }, [clearDownstream, handleError]);

  /** AI 联网检索岗位：两段式步骤提示（搜索 → 提取），保险丝失败引导回预设库 */
  const runSearch = useCallback(async (query: string) => {
    // 前端拦截（第八轮审查）：未填博查 Key 时不发请求，直接引导——
    // 后端 extract_bocha_key 的 400 是兜底，前端先拦住体验更好
    if (!creds.bochaKey.trim()) {
      handleError(new ApiError(400, "请先在左侧填入你的博查 API Key，或改用预设岗位库 / 粘贴 JD（主功能不受影响）"));
      return;
    }
    setBusy(true); setError(null);
    setSearchStage("正在全网搜索相关 JD…");
    // 步骤提示的第二阶段：搜索与抽取是同一个请求，用定时器模拟阶段切换（纯 UI 提示）
    const stageTimer = setTimeout(() => setSearchStage("AI 正在提取能力项…"), 2000);
    try {
      const r = await api.searchJob(query);
      clearDownstream();
      setNotice(null);
      setPoolJob(r.job);  // v1.6：检索结果进指标池（含舆情环境情报）
      setSearchUrls(r.source_urls);
      setOpinionUrls(r.opinion_urls);
      setOpinionStatus(r.opinion_status);
    } catch (e) {
      // 503/409 已在 ApiError 内：追加引导文案，帮助用户回退到主链路
      if (e instanceof ApiError && (e.status === 503 || e.status === 409)) {
        handleError(new ApiError(e.status, `${e.message}——可改用预设岗位库或粘贴 JD，主功能不受影响`));
      } else {
        handleError(e);
      }
    } finally {
      clearTimeout(stageTimer);
      setSearchStage(null);
      setBusy(false);
    }
  }, [clearDownstream, handleError]);

  const pickDemo = useCallback(async (c: DemoCase) => {
    setBusy(true); setError(null);
    try {
      const [j, r] = await Promise.all([
        api.analyzeJob({ job_id: c.job_id }),
        api.demoResume(c.resume_file),
      ]);
      clearDownstream();
      setNotice(null);
      setPoolJob(j);  // v1.6：演示案例同样过指标池（Human-in-the-loop 是主叙事）
      setDemoResumeText(r.text);
      setDemoBg(c.background);
      setDemoHint(`已载入演示配套简历：${c.resume_file}｜背景已固定为：${c.background.年级} / ${c.background.专业} / 目标${c.background.目标} / ${c.background.availability}（点击「开始诊断」即可）`);
    } catch (e) { handleError(e); } finally { setBusy(false); }
  }, [clearDownstream, handleError]);

  const runDiagnose = useCallback(async (input: {
    file: File | null; text: string;
    background: Background;
  }) => {
    if (!job) return;
    const background = demoBg ?? input.background;
    setBusy(true); setError(null);
    try {
      // 简历来源三级优先（一键换岗的核心，第十一轮指令）：
      // ① 演示案例固定文本 → ② 用户本次新上传/粘贴 → ③ 上次已解析的简历（换岗复用，
      // 无需重新上传）；三者皆无才提示补充输入
      let r: ResumeData | null = null;
      if (demoResumeText) {
        r = await api.parseResume(null, demoResumeText);
      } else if (input.file || input.text.trim()) {
        r = await api.parseResume(input.file, input.text);
      } else if (resume) {
        r = resume;
      } else {
        setError(new ApiError(422, "请上传简历文件，或粘贴简历文本"));
        return;
      }
      setResume(r);
      const d: DiagnoseResponse = await api.diagnose({ job, resume: r, background });
      setReport(d.report);
      setRewrites(d.rewrites);
      setFailures(d.rewrite_failures);
      setScoreDetail(d.score_detail);
    } catch (e) {
      setReport(null); setRewrites([]); setFailures([]); setScoreDetail(null);
      handleError(e);
    } finally { setBusy(false); }
  }, [job, resume, demoResumeText, demoBg, handleError]);

  // 公网后端不可用时的维护兜底页（第七轮审查第3条：不给公网用户看残破页面）
  if (serverDown) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-page">
        <div className="card w-full max-w-sm text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-300 text-xl text-white">🛠</div>
          <h1 className="text-lg font-semibold">系统维护中</h1>
          <p className="mb-4 mt-1 text-sm text-slate-500">服务暂时不可用，请稍后刷新重试</p>
          <button className="btn-ghost w-full" onClick={() => window.location.reload()}>刷新页面</button>
        </div>
      </div>
    );
  }

  if (!gatePassed) return <PasswordGate onPass={() => setGatePassed(true)} />;

  return (
    <div className="min-h-screen bg-page">
      <Sidebar apiKey={apiKey} onApiKeyChange={setApiKey}
               bochaKey={bochaKey} onBochaKeyChange={setBochaKey}
               publicMode={publicMode} demoCacheMode={demoCacheMode} />
      <main className="ml-64 space-y-6 px-8 py-8">
        <Banner />
        {error && <ErrorBanner err={error} onClose={() => setError(null)} />}
        {notice && (
          <div className="flex items-start justify-between gap-3 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-700">
            <span>💡 {notice}</span>
            <button onClick={() => setNotice(null)} className="shrink-0 opacity-60 transition hover:opacity-100">✕</button>
          </div>
        )}
        <JobSelect jobs={jobs} demoCases={demoCases} busy={busy} searchStage={searchStage}
                   onPickJob={(id) => runAnalyze({ job_id: id })}
                   onPickDemo={pickDemo}
                   onAnalyzeJd={(jd) => runAnalyze({ jd_text: jd })}
                   onSearch={runSearch} />
        {poolJob && (
          <MetricPool job={poolJob} opinionUrls={opinionUrls} opinionStatus={opinionStatus}
                      demoCacheMode={demoCacheMode} busy={busy} onConfirm={confirmPool} />
        )}
        {job && <JobProfile job={job} searchUrls={searchUrls} />}
        {job && <DiagnoseCard demoHint={demoHint} busy={busy}
                              retainedName={!demoResumeText && resume ? (resume.name || "已解析简历") : null}
                              onDiagnose={runDiagnose} />}
        {job && report && scoreDetail && (
          <>
            <ResultSection report={report} rewrites={rewrites} failures={failures}
                           scoreDetail={scoreDetail} excluded={excluded} onSwitchJob={switchJob} />
            {resume && (
              <ExportPanel job={job} resume={resume} report={report}
                           rewrites={rewrites} onError={setError} />
            )}
          </>
        )}
        <footer className="pb-4 pt-2 text-center text-xs text-slate-400">
          AI 生成内容需人工核验后使用｜岗位信息来源见界面标注｜仅供参考，不构成求职承诺
        </footer>
      </main>
    </div>
  );
}
