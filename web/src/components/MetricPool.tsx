import { useMemo, useState } from "react";
import type { AbilityItem, JobRequirements } from "../types";

/**
 * MetricPool —— 「AI 调研报告 + 指标池」面板（第十二轮 Human-in-the-loop 核心组件）。
 *
 * 流程位置：AI 提取岗位后 → 本面板（决策阻断点）→ 用户确认评估框架 → 上传简历诊断。
 * 分区设计（架构决策，防止评分荒谬）：
 *   - 匹配指标（jd_requirement）：可勾选、可调星级，只有它们进入 Gap 评分；
 *   - 环境情报（public_opinion / policy_background）：加班/转正/政策等岗位环境信息，
 *     任何简历都无法"命中"，只读展示供求职决策参考，UI 明示不参与评分。
 */

const CATEGORY_STYLE: Record<string, string> = {
  硬技能: "bg-indigo-50 text-indigo-600",
  软技能: "bg-slate-100 text-slate-500",
  背景门槛: "bg-amber-50 text-amber-600",
};

const SOURCE_LABEL: Record<string, { label: string; pill: string }> = {
  public_opinion: { label: "舆情体验", pill: "bg-cyan-50 text-cyan-600" },
  policy_background: { label: "背景政策", pill: "bg-violet-50 text-violet-600" },
};

/** 可交互星级（1-5）：点击设置重要度；stopPropagation 避免触发卡片勾选切换 */
function StarPicker({ value, onChange, disabled }: {
  value: number; onChange: (v: number) => void; disabled: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-0.5" onClick={(e) => e.stopPropagation()}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} type="button" disabled={disabled} onClick={() => onChange(n)}
                className={`text-sm transition hover:scale-125 disabled:cursor-not-allowed
                  ${n <= value ? "text-amber-400" : "text-slate-300"}`}>
          ★
        </button>
      ))}
    </span>
  );
}

interface Props {
  job: JobRequirements;
  opinionUrls: string[] | null;
  opinionStatus: "ok" | "none" | null;
  demoCacheMode: boolean; // 演示缓存模式：调整勾选/星级必然 CacheMiss，需提示保持默认
  busy: boolean;
  onConfirm: (filtered: JobRequirements, excluded: AbilityItem[]) => void;
}

export default function MetricPool({ job, opinionUrls, opinionStatus, demoCacheMode, busy, onConfirm }: Props) {
  const matchItems = useMemo(
    () => job.abilities.map((a, i) => ({ a, i })).filter(({ a }) => a.source_type === "jd_requirement"),
    [job],
  );
  const infoItems = useMemo(
    () => job.abilities.filter((a) => a.source_type !== "jd_requirement"),
    [job],
  );

  // 默认全选、星级沿用 AI 评估值——预热缓存组合即"默认全选+原始权重"，
  // 演示路径直接确认即可命中缓存（人类审核动作保留，结果稳定）
  const [sel, setSel] = useState<Record<number, boolean>>(
    () => Object.fromEntries(matchItems.map(({ i }) => [i, true])),
  );
  const [stars, setStars] = useState<Record<number, number>>(
    () => Object.fromEntries(matchItems.map(({ a, i }) => [i, a.importance])),
  );

  const selectedCount = matchItems.filter(({ i }) => sel[i]).length;

  const confirm = () => {
    const filtered: JobRequirements = {
      ...job,
      abilities: matchItems
        .filter(({ i }) => sel[i])
        .map(({ a, i }) => ({ ...a, importance: stars[i] ?? a.importance })),
    };
    const excluded = matchItems.filter(({ i }) => !sel[i]).map(({ a }) => a);
    onConfirm(filtered, excluded);
  };

  return (
    <section className="card">
      <h2 className="mb-1 text-lg font-semibold">AI 调研报告：{job.job_title}</h2>
      <p className="mb-1 text-sm text-slate-500">{job.source_note}</p>
      <p className="mb-4 rounded-lg bg-brand/5 px-3 py-2 text-sm text-brand">
        🧭 AI 已为你全网调研，作为具备信息素养的大学生，请批判性地评估并构建你的衡量标准：
        勾选纳入匹配的指标、调整重要度；环境情报仅供你的求职决策参考，不参与简历评分。
      </p>
      {demoCacheMode && (
        <p className="mb-4 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
          演示缓存模式：请保持默认勾选与星级，直接点击「确认我的评估框架」（修改组合未预热，将触发实时 AI 调用）。
        </p>
      )}

      {/* 岗位职责（信息全貌，标签流展示） */}
      <div className="mb-4">
        <h3 className="mb-2 text-sm font-semibold text-slate-600">岗位职责</h3>
        <div className="flex flex-wrap gap-2">
          {job.responsibilities.map((r, i) => (
            <span key={i} className="rounded-full bg-slate-50 px-3 py-1 text-xs text-slate-600">{r}</span>
          ))}
        </div>
      </div>

      {/* 匹配指标池：勾选 + 星级，淡入上浮动效（staggered） */}
      <h3 className="mb-2 text-sm font-semibold text-slate-600">
        匹配指标池（{selectedCount}/{matchItems.length} 已采纳，进入评分）
      </h3>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {matchItems.map(({ a, i }, order) => (
          <div key={i}
               onClick={() => setSel((s) => ({ ...s, [i]: !s[i] }))}
               className={`animate-card-in cursor-pointer rounded-xl border p-3 transition
                 ${sel[i] ? "border-brand/50 bg-white shadow-sm" : "border-slate-100 bg-slate-50/60 opacity-60"}
                 hover:border-brand`}
               style={{ animationDelay: `${order * 90}ms` }}>
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-2">
                <input type="checkbox" checked={!!sel[i]} readOnly
                       className="h-4 w-4 accent-indigo-600" />
                <span className="text-sm font-medium">{a.name}</span>
                {a.is_core && (
                  <span className="rounded bg-red-50 px-1 py-0.5 text-xs text-red-600">核心门槛</span>
                )}
              </div>
              <StarPicker value={stars[i] ?? a.importance} disabled={!sel[i]}
                          onChange={(v) => setStars((s) => ({ ...s, [i]: v }))} />
            </div>
            <div className="mt-1.5 flex items-center gap-2 text-xs">
              <span className={`rounded-full px-2 py-0.5 ${CATEGORY_STYLE[a.category] ?? "bg-slate-100 text-slate-500"}`}>
                {a.category}
              </span>
              <span className="text-slate-400">{a.importance_source}</span>
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-400">JD 依据：{a.evidence}</p>
          </div>
        ))}
      </div>

      {/* 环境情报区：只读，不参与评分 */}
      <div className="mt-5">
        <h3 className="mb-2 text-sm font-semibold text-slate-600">
          环境情报（舆情 / 政策——仅供求职决策参考，不参与简历评分）
        </h3>
        {infoItems.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {infoItems.map((a, k) => (
              <div key={k} className="animate-card-in rounded-xl border border-cyan-100 bg-cyan-50/40 p-3"
                   style={{ animationDelay: `${matchItems.length * 90 + k * 90}ms` }}>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-700">{a.name}</span>
                  <span className={`rounded-full px-2 py-0.5 text-xs ${SOURCE_LABEL[a.source_type]?.pill ?? "bg-slate-100 text-slate-500"}`}>
                    {SOURCE_LABEL[a.source_type]?.label ?? a.source_type}
                  </span>
                  <span className="text-xs text-amber-400">{"★".repeat(a.importance)}</span>
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-slate-500">来源摘要：{a.evidence}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-400">
            {opinionStatus === "none" ? "暂无显著舆论风险（未检索到小红书/知乎的相关讨论）" : "该岗位信息无舆情/政策维度指标"}
          </p>
        )}
        {opinionUrls && opinionUrls.length > 0 && (
          <details className="mt-2">
            <summary className="cursor-pointer text-xs text-slate-400 transition hover:text-brand">
              查看 {opinionUrls.length} 条舆情来源链接（可跳转人工核验）
            </summary>
            <ul className="mt-1 space-y-1">
              {opinionUrls.map((u, i) => (
                <li key={i}>
                  <a href={u} target="_blank" rel="noreferrer"
                     className="break-all text-xs text-cyan-600 hover:underline">{u}</a>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      <div className="mt-5 flex justify-end border-t border-slate-100 pt-4">
        <button className="btn-primary" disabled={busy || selectedCount === 0} onClick={confirm}>
          {busy ? "确认中…" : `✅ 确认我的评估框架（${selectedCount} 项指标）`}
        </button>
      </div>
    </section>
  );
}
