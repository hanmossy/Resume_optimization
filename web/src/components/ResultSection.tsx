import { useEffect, useState } from "react";
import type { GapReport, GapStatus, RewriteResult, ScoreDetail } from "../types";

/** 状态三色口径（与 Streamlit 版冻结色值一致：绿/黄/红） */
const STATUS_META: Record<GapStatus, { label: string; pill: string }> = {
  matched: { label: "✓ 已具备", pill: "bg-green-100 text-green-700" },
  partial: { label: "◐ 部分匹配", pill: "bg-amber-100 text-amber-700" },
  missing: { label: "✗ 缺失", pill: "bg-red-100 text-red-700" },
};

/** 数字滚动动画：0 → target，约 900ms（录屏时展示"运算过程"的核心动效）。 */
function useCountUp(target: number, duration = 900): number {
  const [value, setValue] = useState(0);
  useEffect(() => {
    let raf = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      const p = Math.min((now - t0) / duration, 1);
      // easeOutCubic：先快后慢，落点干脆
      setValue(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);
  return value;
}

/** 匹配度环形进度条（SVG，非原生进度条——对齐设计稿；数字滚动由 useCountUp 驱动）。 */
function ScoreRing({ score }: { score: number }) {
  const shown = useCountUp(score);
  const R = 52;
  const C = 2 * Math.PI * R;
  const color = score >= 75 ? "#16a34a" : score >= 55 ? "#d97706" : "#dc2626";
  return (
    <div className="flex items-center gap-5">
      <svg width="128" height="128" viewBox="0 0 128 128">
        <circle cx="64" cy="64" r={R} fill="none" stroke="#e5e9f5" strokeWidth="12" />
        <circle cx="64" cy="64" r={R} fill="none" stroke={color} strokeWidth="12"
                strokeLinecap="round" strokeDasharray={C}
                strokeDashoffset={C * (1 - shown / 100)}
                transform="rotate(-90 64 64)" className="transition-all duration-150" />
        <text x="64" y="60" textAnchor="middle" className="fill-slate-800 text-2xl font-bold">{shown}</text>
        <text x="64" y="80" textAnchor="middle" className="fill-slate-400 text-xs">/ 100</text>
      </svg>
      <div>
        <div className="text-sm font-semibold text-slate-700">简历与岗位匹配度</div>
        <p className="mt-1 max-w-xs text-xs leading-relaxed text-slate-400">
          评分口径：Σ(权重 × 命中系数)÷Σ权重×100。系数：已具备(强证据)1.0 / 已具备(弱证据)0.7 / 部分匹配0.4 / 缺失0.0；软技能权重5折；核心门槛未达标总分×0.6且封顶60。
        </p>
      </div>
    </div>
  );
}

/** 运算过程面板：逐项展示 重要度 × 命中系数 = 单项得分（人机协同透明度落地项）。 */
function ScoreDrawer({ detail }: { detail: ScoreDetail }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-indigo-100 bg-indigo-50/40">
      <button onClick={() => setOpen(!open)}
              className="flex w-full items-center justify-between px-4 py-2.5 text-sm font-medium text-indigo-700 transition hover:bg-indigo-50">
        <span>🔍 查看运算过程（匹配度是怎么算出来的）</span>
        <span className={`transition-transform ${open ? "rotate-180" : ""}`}>▾</span>
      </button>
      {open && (
        <div className="border-t border-indigo-100 px-4 py-3">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-slate-400">
                <th className="py-1.5 font-medium">能力项</th>
                <th className="py-1.5 font-medium">权重</th>
                <th className="py-1.5 font-medium">命中状态</th>
                <th className="py-1.5 font-medium">证据强度</th>
                <th className="py-1.5 font-medium">系数</th>
                <th className="py-1.5 text-right font-medium">单项得分</th>
              </tr>
            </thead>
            <tbody>
              {detail.items.map((it) => (
                <tr key={it.gap_id} className="border-t border-indigo-100/60 text-slate-600">
                  <td className="py-1.5 pr-2">
                    {it.ability}
                    {it.is_core && <span className="ml-1 rounded bg-red-50 px-1 py-0.5 text-red-600">核心</span>}
                  </td>
                  <td className="py-1.5">
                    {it.weight}
                    {it.soft_discounted && <span className="ml-1 text-slate-400" title="软技能权重 5 折">(5折)</span>}
                  </td>
                  <td className="py-1.5">
                    <span className={`rounded-full px-2 py-0.5 ${STATUS_META[it.status].pill}`}>
                      {STATUS_META[it.status].label}
                    </span>
                  </td>
                  <td className="py-1.5">
                    {it.status === "matched"
                      ? (it.evidence_strength === "strong" ? "强证据" : "弱证据↓")
                      : "—"}
                  </td>
                  <td className="py-1.5">× {it.coefficient}</td>
                  <td className="py-1.5 text-right font-mono">{it.earned}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-indigo-200 font-medium text-slate-700">
                <td className="py-2" colSpan={5}>合计：{detail.total_earned} ÷ {detail.total_weight} × 100</td>
                <td className="py-2 text-right font-mono">= {detail.raw_score} 分</td>
              </tr>
              {detail.core_penalty_applied && (
                <tr className="font-medium text-red-600">
                  <td className="py-1.5" colSpan={5}>
                    ⚠️ 核心门槛未达标（{detail.core_gap_abilities.join("、")}）：× 0.6 且封顶 60
                  </td>
                  <td className="py-1.5 text-right font-mono">→ {detail.match_score} 分</td>
                </tr>
              )}
            </tfoot>
          </table>
          <p className="mt-2 text-xs leading-relaxed text-slate-400">
            AI 只负责判断每项命中状态、证据强度并引用简历原文，分数完全由上表规则公式计算（含软技能降权与核心门槛否决）——同一输入逐位可复现，这就是"人机协同"的分工边界。
          </p>
        </div>
      )}
    </div>
  );
}

interface Props {
  report: GapReport;
  rewrites: RewriteResult[];
  failures: string[];
  scoreDetail: ScoreDetail;
  /** 一键换岗（第十一轮指令）：保留简历、清空岗位与结果，滚动回选岗区 */
  onSwitchJob: () => void;
}

/** 诊断结果区：环形匹配度 + 运算过程面板 + 能力对照网格（Pill 标签）+ 改写左右对照卡片。 */
export default function ResultSection({ report, rewrites, failures, scoreDetail, onSwitchJob }: Props) {
  const abilityOf = Object.fromEntries(report.items.map((it) => [it.gap_id, it.ability]));
  return (
    <section className="card space-y-6">
      <h2 className="text-lg font-semibold">诊断结果</h2>

      <ScoreRing score={report.match_score} />

      {report.core_penalty_applied && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm font-medium text-red-700">
          ⚠️ 核心门槛未达标：缺少【{report.core_gap_abilities.join("、")}】能力，导致整体匹配度受限（总分 ×0.6 且封顶 60 分）。
        </p>
      )}

      <ScoreDrawer detail={scoreDetail} />

      <div>
        <h3 className="mb-3 text-sm font-semibold text-slate-600">能力对照（岗位需求 ↔ 简历命中）</h3>
        <div className="overflow-hidden rounded-xl border border-slate-100">
          <div className="grid grid-cols-2 gap-0 bg-slate-50 px-4 py-2 text-xs font-medium text-slate-400">
            <div>岗位能力项</div><div>简历命中情况</div>
          </div>
          {report.items.map((it, idx) => (
            <div key={it.gap_id}
                 className="animate-row-in grid grid-cols-1 gap-2 border-t border-slate-100 px-4 py-3 text-sm md:grid-cols-2"
                 style={{ animationDelay: `${900 + idx * 120}ms` }}>
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

      {/* 一键换岗（第十一轮指令）：体验闭环——测完一个岗位直接换下一个，简历保留 */}
      <div className="flex justify-center border-t border-slate-100 pt-5">
        <button className="btn-ghost" onClick={onSwitchJob}>
          🔄 换一个岗位试试（简历已保留，无需重新上传）
        </button>
      </div>
    </section>
  );
}
