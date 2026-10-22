import type { JobRequirements } from "../types";

/** 第二步：岗位画像（AI 解构结果的可视化，"先分析"的载体）。 */
export default function JobProfile({ job }: { job: JobRequirements }) {
  return (
    <section className="card">
      <h2 className="mb-1 text-lg font-semibold">
        岗位画像：{job.job_title}
        <span className="ml-2 rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-medium text-indigo-600">{job.company_type}</span>
      </h2>
      <p className="mb-4 text-xs text-slate-400">信息来源：{job.source_note}{job.salary_hint ? `｜薪资参考：${job.salary_hint}` : ""}</p>

      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold text-slate-600">岗位职责</h3>
          <ul className="space-y-1.5 text-sm text-slate-600">
            {job.responsibilities.map((r, i) => (
              <li key={i} className="flex gap-2"><span className="text-brand">·</span>{r}</li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold text-slate-600">能力要求清单（{job.abilities.length} 项）</h3>
          <ul className="space-y-2">
            {job.abilities.map((ab, i) => (
              <li key={i} className="rounded-lg bg-slate-50 px-3 py-2">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium">{ab.name}</span>
                  <span className="rounded bg-white px-1.5 py-0.5 text-xs text-slate-500">{ab.category}</span>
                  <span className="text-xs text-amber-500">{"★".repeat(ab.importance)}</span>
                  <span className="text-xs text-slate-400">{ab.importance_source}</span>
                </div>
                <p className="mt-1 text-xs text-slate-400">JD 依据：{ab.evidence}</p>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
