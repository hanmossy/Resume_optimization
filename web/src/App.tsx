import { useCallback, useEffect, useState } from "react";
import { api, ApiError, creds } from "./api";
import Banner from "./components/Banner";
import DiagnoseCard from "./components/DiagnoseCard";
import ExportPanel from "./components/ExportPanel";
import JobProfile from "./components/JobProfile";
import JobSelect from "./components/JobSelect";
import ResultSection from "./components/ResultSection";
import Sidebar from "./components/Sidebar";
import type {
  DemoCase, DiagnoseResponse, GapReport, JobMeta, JobRequirements,
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
  const [publicMode, setPublicMode] = useState(false);
  const [demoCacheMode, setDemoCacheMode] = useState(true);
  const [gatePassed, setGatePassed] = useState(false);

  // ---- 业务状态（原 Streamlit session_state 的 React 化，无页面刷新） ----
  const [jobs, setJobs] = useState<JobMeta[]>([]);
  const [demoCases, setDemoCases] = useState<DemoCase[]>([]);
  const [job, setJob] = useState<JobRequirements | null>(null);
  const [resume, setResume] = useState<ResumeData | null>(null);
  const [report, setReport] = useState<GapReport | null>(null);
  const [rewrites, setRewrites] = useState<RewriteResult[]>([]);
  const [failures, setFailures] = useState<string[]>([]);
  const [scoreDetail, setScoreDetail] = useState<ScoreDetail | null>(null);
  const [serverDown, setServerDown] = useState(false);
  const [demoHint, setDemoHint] = useState<string | null>(null);
  const [demoResumeText, setDemoResumeText] = useState<string | null>(null);
  const [demoBg, setDemoBg] = useState<{ 年级: string; 专业: string; 目标: string } | null>(null);
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
  }, []);

  const handleError = useCallback((e: unknown) => {
    setError(e instanceof ApiError ? e : new ApiError(500, String(e)));
  }, []);

  const runAnalyze = useCallback(async (payload: { job_id?: string; jd_text?: string }) => {
    setBusy(true); setError(null);
    try {
      const j = await api.analyzeJob(payload);
      clearDownstream();
      setJob(j);
    } catch (e) { handleError(e); } finally { setBusy(false); }
  }, [clearDownstream, handleError]);

  const pickDemo = useCallback(async (c: DemoCase) => {
    setBusy(true); setError(null);
    try {
      const [j, r] = await Promise.all([
        api.analyzeJob({ job_id: c.job_id }),
        api.demoResume(c.resume_file),
      ]);
      clearDownstream();
      setJob(j);
      setDemoResumeText(r.text);
      setDemoBg(c.background);
      setDemoHint(`已载入演示配套简历：${c.resume_file}｜背景已固定为：${c.background.年级} / ${c.background.专业} / 目标${c.background.目标}（点击「开始诊断」即可）`);
    } catch (e) { handleError(e); } finally { setBusy(false); }
  }, [clearDownstream, handleError]);

  const runDiagnose = useCallback(async (input: {
    file: File | null; text: string;
    background: { 年级: string; 专业: string; 目标: string };
  }) => {
    if (!job) return;
    const text = demoResumeText ?? input.text;
    const file = demoResumeText ? null : input.file;
    if (!file && !text.trim()) {
      setError(new ApiError(422, "请上传简历文件，或粘贴简历文本"));
      return;
    }
    const background = demoBg ?? input.background;
    setBusy(true); setError(null);
    try {
      const r = await api.parseResume(file, text);
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
  }, [job, demoResumeText, demoBg, handleError]);

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
               publicMode={publicMode} demoCacheMode={demoCacheMode} />
      <main className="ml-64 space-y-6 px-8 py-8">
        <Banner />
        {error && <ErrorBanner err={error} onClose={() => setError(null)} />}
        <JobSelect jobs={jobs} demoCases={demoCases} busy={busy}
                   onPickJob={(id) => runAnalyze({ job_id: id })}
                   onPickDemo={pickDemo}
                   onAnalyzeJd={(jd) => runAnalyze({ jd_text: jd })} />
        {job && <JobProfile job={job} />}
        {job && <DiagnoseCard demoHint={demoHint} busy={busy} onDiagnose={runDiagnose} />}
        {job && report && scoreDetail && (
          <>
            <ResultSection report={report} rewrites={rewrites} failures={failures}
                           scoreDetail={scoreDetail} />
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
