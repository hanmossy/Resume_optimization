import type { DemoCase, JobMeta } from "../types";

interface Props {
  jobs: JobMeta[];
  demoCases: DemoCase[];
  onPickJob: (jobId: string) => void;
  onPickDemo: (c: DemoCase) => void;
  onAnalyzeJd: (jdText: string) => void;
  busy: boolean;
}

/** 第一步：选岗卡片（演示案例 / 岗位库下拉 / 粘贴 JD 三入口）。 */
export default function JobSelect({ jobs, demoCases, onPickJob, onPickDemo, onAnalyzeJd, busy }: Props) {
  return (
    <section className="card">
      <h2 className="mb-1 text-lg font-semibold">第一步：选择目标岗位</h2>
      <p className="mb-4 text-sm text-slate-500">演示案例可一键跑通全流程；也可以从岗位库选择或粘贴自定义 JD。</p>

      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {demoCases.map((c) => (
          <button key={c.job_id} disabled={busy} onClick={() => onPickDemo(c)}
                  className="rounded-xl border border-brand/30 bg-gradient-to-br from-indigo-50 to-purple-50 px-4 py-3 text-left text-sm font-medium text-indigo-700 transition hover:border-brand hover:shadow-md active:scale-[0.98] disabled:opacity-50">
            {c.label}
            <span className="mt-1 block text-xs font-normal text-slate-500">
              {c.background.年级} · {c.background.专业} · 目标{c.background.目标}
            </span>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <select id="job-select" disabled={busy}
                className="min-w-64 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20">
          {jobs.map((j) => (
            <option key={j.job_id} value={j.job_id}>
              {j.is_demo ? "⭐ " : ""}{j.job_title}（{j.company_type}）
            </option>
          ))}
        </select>
        <button className="btn-primary" disabled={busy}
                onClick={() => {
                  const sel = document.getElementById("job-select") as HTMLSelectElement;
                  if (sel?.value) onPickJob(sel.value);
                }}>
          分析岗位
        </button>
      </div>

      <details className="mt-4">
        <summary className="cursor-pointer text-sm text-slate-500 transition hover:text-brand">
          没有目标岗位？粘贴 JD 原文试试
        </summary>
        <textarea id="jd-text" rows={4} placeholder="粘贴岗位描述（JD）原文…"
                  className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20" />
        <button className="btn-ghost mt-2" disabled={busy}
                onClick={() => {
                  const ta = document.getElementById("jd-text") as HTMLTextAreaElement;
                  if (ta?.value.trim()) onAnalyzeJd(ta.value.trim());
                }}>
          解析这份 JD
        </button>
      </details>
    </section>
  );
}
