import { useState } from "react";
import type { DemoCase, JobMeta } from "../types";

interface Props {
  jobs: JobMeta[];
  demoCases: DemoCase[];
  onPickJob: (jobId: string) => void;
  onPickDemo: (c: DemoCase) => void;
  onAnalyzeJd: (jdText: string) => void;
  onSearch: (query: string) => void;
  busy: boolean;
  /** 检索进行中的步骤提示（"正在全网搜索…" → "AI 正在提取能力项…"），null 表示空闲 */
  searchStage: string | null;
}

/** 第一步：选岗卡片（演示案例 / 岗位库下拉 / 全网检索 / 粘贴 JD 四入口）。 */
export default function JobSelect({ jobs, demoCases, onPickJob, onPickDemo, onAnalyzeJd, onSearch, busy, searchStage }: Props) {
  const [query, setQuery] = useState("");
  return (
    <section className="card" id="step1">
      <h2 className="mb-1 text-lg font-semibold">第一步：选择目标岗位</h2>
      <p className="mb-4 text-sm text-slate-500">演示案例可一键跑通全流程；也可以从岗位库选择、全网检索或粘贴自定义 JD。</p>

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

      {/* AI 全网检索入口（第九轮指令：带保险丝的增强项） */}
      <div className="mt-4 rounded-xl border border-cyan-100 bg-cyan-50/50 px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm font-medium text-cyan-700">🔍 全网检索岗位</span>
          <input value={query} disabled={busy}
                 onChange={(e) => setQuery(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && query.trim() && !busy && onSearch(query.trim())}
                 placeholder="如：字节跳动 数据分析 实习 招聘要求"
                 className="min-w-64 flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20" />
          <button className="btn-ghost" disabled={busy || !query.trim()}
                  onClick={() => onSearch(query.trim())}>
            AI 检索
          </button>
        </div>
        {searchStage ? (
          <p className="mt-2 flex items-center gap-2 text-xs text-cyan-600">
            <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-cyan-300 border-t-cyan-600" />
            {searchStage}
          </p>
        ) : (
          <p className="mt-2 text-xs text-slate-400">
            联网搜索公开招聘摘要并提取岗位要求；检索失败会自动提示，可改用上方预设岗位库。
          </p>
        )}
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
