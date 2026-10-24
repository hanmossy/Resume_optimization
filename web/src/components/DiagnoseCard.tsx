import { useRef, useState } from "react";
import type { Background } from "../types";

interface Props {
  demoHint: string | null; // 演示模式提示文案（非空则锁定输入）
  /** 一键换岗后保留的简历姓名（null 表示无保留简历）；非空时允许免上传直接诊断 */
  retainedName: string | null;
  onDiagnose: (payload: {
    file: File | null; text: string;
    background: Background;
  }) => void;
  busy: boolean;
}

const GRADES = ["大一", "大二", "大三", "大四", "研究生"];
const GOALS = ["实习", "求职"];
const WEEKLY_DAYS = ["3 天以下", "3-4 天", "5 天全勤"];
const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

/** 合成 availability 字符串（与 Streamlit 版 _build_availability 同口径）；
    非法输入返回 null——实习时间是"实习时长/稳定性"类能力项的判断前提（第十二轮指令）。 */
function buildAvailability(start: string, end: string, days: string): string | null {
  if (!MONTH_RE.test(start) || !MONTH_RE.test(end) || start > end) return null;
  return `可实习 ${start} 至 ${end}，每周 ${days}`;
}

/** 第二步（交互上）：前置必填信息（含实习时间）+ 上传简历 + 开始诊断。支持拖拽上传。 */
export default function DiagnoseCard({ demoHint, retainedName, onDiagnose, busy }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [grade, setGrade] = useState("大三");
  const [major, setMajor] = useState("");
  const [goal, setGoal] = useState("实习");
  const [availStart, setAvailStart] = useState("");
  const [availEnd, setAvailEnd] = useState("");
  const [availDays, setAvailDays] = useState("3-4 天");
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const locked = demoHint !== null;

  // 前端必填拦截（第十二轮指令）：不到填实习时间不允许发起诊断；
  // 后端 /api/diagnose 的 422 是兜底，前端先拦住体验更好
  const availability = buildAvailability(availStart, availEnd, availDays);
  const availInvalid = !locked && (availStart !== "" || availEnd !== "") && availability === null;
  const canSubmit = locked || availability !== null;

  return (
    <section className="card">
      <h2 className="mb-1 text-lg font-semibold">第二步：填写前置信息，上传简历，开始诊断</h2>
      {locked && (
        <p className="mb-3 rounded-lg bg-indigo-50 px-3 py-2 text-sm text-indigo-700">{demoHint}</p>
      )}
      {!locked && retainedName && (
        <p className="mb-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          ✅ 已为你保留简历（{retainedName}），可直接点击「开始诊断」；如需更换，重新上传或粘贴新文本即可。
        </p>
      )}

      {/* 前置必填信息（第十二轮指令：面板改名并上移到上传区之前）——
          可到岗实习时间是"实习时长/稳定性"类能力项的判断前提；年级/专业供 AI 按阶段
          调整软性指标基线，核心硬门槛恒定不变 */}
      <div className="rounded-xl border border-slate-100 bg-slate-50/60 px-4 py-3">
        <p className="mb-1 text-xs font-medium text-slate-500">
          前置必填信息（AI 将根据你的阶段与可到岗时间调整评估标准）
        </p>
        <p className="mb-2 text-xs leading-relaxed text-slate-400">
          AI 会根据你的当前阶段动态调整部分软性指标的期望值（例如，对大二学生的实习项目要求与大四求职不同）。但岗位的核心硬门槛标准恒定不变。
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <select value={grade} disabled={locked} onChange={(e) => setGrade(e.target.value)}
                  className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand disabled:opacity-50">
            {GRADES.map((g) => <option key={g}>{g}</option>)}
          </select>
          <input value={major} disabled={locked} onChange={(e) => setMajor(e.target.value)}
                 placeholder="专业"
                 className="w-32 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand disabled:opacity-50" />
          <div className="flex gap-1.5">
            {GOALS.map((g) => (
              <button key={g} type="button" disabled={locked} onClick={() => setGoal(g)}
                      className={`rounded-full px-3 py-1.5 text-sm transition disabled:opacity-50
                        ${goal === g ? "bg-brand text-white" : "bg-white text-slate-600 border border-slate-200 hover:border-brand/50"}`}>
                {g}
              </button>
            ))}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-3">
          <label className="flex items-center gap-1.5 text-sm text-slate-600">
            实习时间
            <input type="month" value={availStart} disabled={locked}
                   onChange={(e) => setAvailStart(e.target.value)}
                   className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm outline-none focus:border-brand disabled:opacity-50" />
            <span className="text-slate-400">至</span>
            <input type="month" value={availEnd} disabled={locked}
                   onChange={(e) => setAvailEnd(e.target.value)}
                   className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm outline-none focus:border-brand disabled:opacity-50" />
          </label>
          <label className="flex items-center gap-1.5 text-sm text-slate-600">
            每周到岗
            <select value={availDays} disabled={locked} onChange={(e) => setAvailDays(e.target.value)}
                    className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm outline-none focus:border-brand disabled:opacity-50">
              {WEEKLY_DAYS.map((d) => <option key={d}>{d}</option>)}
            </select>
          </label>
        </div>
        {!locked && availability === null && (
          <p className="mt-2 text-xs text-amber-600">
            {availInvalid
              ? "⚠️ 起止月份格式或顺序有误（开始不能晚于结束）"
              : "⚠️ 请填写可到岗实习的起止月份——这是 AI 判断「实习时长/稳定性」要求的必要前提"}
          </p>
        )}
      </div>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault(); setDragOver(false);
          const f = e.dataTransfer.files?.[0];
          if (f) setFile(f);
        }}
        onClick={() => !locked && fileInput.current?.click()}
        className={`mt-3 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-8 text-sm transition
          ${dragOver ? "border-brand bg-indigo-50" : "border-slate-300 hover:border-brand/60 hover:bg-slate-50"}
          ${locked ? "pointer-events-none opacity-50" : ""}`}
      >
        <div className="text-2xl">📄</div>
        <p className="mt-2 text-slate-600">
          {file ? `已选择：${file.name}` : "拖拽简历到此处，或点击选择文件（PDF / TXT）"}
        </p>
        <input ref={fileInput} type="file" accept=".pdf,.txt" className="hidden"
               onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </div>

      <textarea rows={3} value={text} disabled={locked}
                onChange={(e) => setText(e.target.value)}
                placeholder="或直接粘贴简历文本（扫描件 PDF 请走这里）"
                className="mt-3 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:opacity-50" />

      <div className="mt-3 flex justify-end">
        <button className="btn-primary" disabled={busy || !canSubmit}
                title={!canSubmit ? "请先填写可到岗实习的起止月份" : undefined}
                onClick={() => onDiagnose({
                  file, text,
                  background: {
                    年级: grade, 专业: major || "未填写", 目标: goal,
                    availability: availability ?? "",
                  },
                })}>
          {busy ? "AI 诊断中…" : "开始诊断"}
        </button>
      </div>
    </section>
  );
}
