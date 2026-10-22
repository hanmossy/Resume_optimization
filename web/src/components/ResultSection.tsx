import type { GapReport, GapStatus, RewriteResult } from "../types";

/** 状态三色口径（与 Streamlit 版冻结色值一致：绿/黄/红） */
const STATUS_META: Record<GapStatus, { label: string; pill: string }> = {
  matched: { label: "✓ 已具备", pill: "bg-green-100 text-green-700" },
  partial: { label: "◐ 部分匹配", pill: "bg-amber-100 text-amber-700" },
  missing: { label: "✗ 缺失", pill: "bg-red-100 text-red-700" },
};

/** 匹配度环形进度条（SVG，非原生进度条——对齐设计稿）。 */
function ScoreRing({ score }: { score: number }) {
  const R = 52;
  const C = 2 * Math.PI * R;
  const color = score >= 75 ? "#16a34a" : score >= 55 ? "#d97706" : "#dc2626";
  return (
    <div className="flex items-center gap-5">
      <svg width="128" height="128" viewBox="0 0 128 128">
        <circle cx="64" cy="64" r={R} fill="none" stroke="#e5e9f5" strokeWidth="12" />
        <circle cx="64" cy="64" r={R} fill="none" stroke={color} strokeWidth="12"
                strokeLinecap="round" strokeDasharray={C}
                strokeDashoffset={C * (1 - score / 100)}
                transform="rotate(-90 64 64)" className="transition-all duration-700" />
        <text x="64" y="60" textAnchor="middle" className="fill-slate-800 text-2xl font-bold">{score}</text>
        <text x="64" y="80" textAnchor="middle" className="fill-slate-400 text-xs">/ 100</text>
      </svg>
      <div>
        <div className="text-sm font-semibold text-slate-700">简历与岗位匹配度</div>
        <p className="mt-1 max-w-xs text-xs leading-relaxed text-slate-400">
          评分口径：各能力项重要度 × 命中系数（已具备 1.0 / 部分匹配 0.5 / 缺失 0.0）加权求和，可用公式逐位复算。
        </p>
      </div>
    </div>
  );
}

interface Props {
  report: GapReport;
  rewrites: RewriteResult[];
  failures: string[];
}

/** 诊断结果区：环形匹配度 + 能力对照网格（Pill 标签）+ 改写左右对照卡片。 */
export default function ResultSection({ report, rewrites, failures }: Props) {
  const abilityOf = Object.fromEntries(report.items.map((it) => [it.gap_id, it.ability]));
  return (
    <section className="card space-y-6">
      <h2 className="text-lg font-semibold">诊断结果</h2>

      <ScoreRing score={report.match_score} />

      <div>
        <h3 className="mb-3 text-sm font-semibold text-slate-600">能力对照（岗位需求 ↔ 简历命中）</h3>
        <div className="overflow-hidden rounded-xl border border-slate-100">
          <div className="grid grid-cols-2 gap-0 bg-slate-50 px-4 py-2 text-xs font-medium text-slate-400">
            <div>岗位能力项</div><div>简历命中情况</div>
          </div>
          {report.items.map((it) => (
            <div key={it.gap_id} className="grid grid-cols-1 gap-2 border-t border-slate-100 px-4 py-3 text-sm md:grid-cols-2">
              <div>
                <span className="font-medium">{it.ability}</span>
                <span className="ml-2 text-xs text-amber-500">{"★".repeat(it.importance)}</span>
              </div>
              <div className="flex items-start gap-2">
                <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_META[it.status].pill}`}>
                  {STATUS_META[it.status].label}
                </span>
                <span className="text-xs leading-relaxed text-slate-500">{it.reason}</span>
              </div>
            </div>
          ))}
        </div>
        {report.warnings.map((w, i) => (
          <p key={i} className="mt-2 text-xs text-amber-600">⚠️ {w}</p>
        ))}
      </div>

      {rewrites.length > 0 && (
        <div>
          <h3 className="mb-3 text-sm font-semibold text-slate-600">重点改写建议</h3>
          <div className="space-y-3">
            {rewrites.map((rw) => (
              <details key={rw.gap_id} className="rounded-xl border border-slate-100">
                <summary className="cursor-pointer px-4 py-3 text-sm font-medium transition hover:bg-slate-50">
                  能力项：{abilityOf[rw.gap_id] ?? rw.gap_id}
                </summary>
                <div className="space-y-3 px-4 pb-4 pt-1 text-sm">
                  <p className="text-slate-600"><span className="font-medium text-slate-700">诊断：</span>{rw.diagnosis}</p>
                  <p className="text-slate-600"><span className="font-medium text-slate-700">建议：</span>{rw.suggestion}</p>
                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-lg bg-slate-50 p-3">
                      <div className="mb-1 text-xs font-medium text-slate-400">改写前</div>
                      <p className="whitespace-pre-wrap text-xs leading-relaxed text-slate-600">{rw.example_before}</p>
                    </div>
                    <div className="rounded-lg bg-green-50 p-3">
                      <div className="mb-1 text-xs font-medium text-green-600">改写后</div>
                      <p className="whitespace-pre-wrap text-xs leading-relaxed text-slate-700">{rw.example_after}</p>
                    </div>
                  </div>
                </div>
              </details>
            ))}
          </div>
        </div>
      )}

      {failures.map((f, i) => (
        <p key={i} className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">{f}</p>
      ))}
    </section>
  );
}
