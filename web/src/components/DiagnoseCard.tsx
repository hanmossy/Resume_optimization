import { useRef, useState } from "react";

interface Props {
  demoHint: string | null; // 演示模式提示文案（非空则锁定输入）
  /** 一键换岗后保留的简历姓名（null 表示无保留简历）；非空时允许免上传直接诊断 */
  retainedName: string | null;
  onDiagnose: (payload: {
    file: File | null; text: string;
    background: { 年级: string; 专业: string; 目标: string };
  }) => void;
  busy: boolean;
}

const GRADES = ["大一", "大二", "大三", "大四", "研究生"];
const GOALS = ["实习", "求职"];

/** 第二步（交互上）：上传简历 + 背景信息 + 开始诊断。支持拖拽上传。 */
export default function DiagnoseCard({ demoHint, retainedName, onDiagnose, busy }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [grade, setGrade] = useState("大三");
  const [major, setMajor] = useState("");
  const [goal, setGoal] = useState("实习");
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const locked = demoHint !== null;

  return (
    <section className="card">
      <h2 className="mb-1 text-lg font-semibold">第二步：上传简历，开始诊断</h2>
      {locked && (
        <p className="mb-3 rounded-lg bg-indigo-50 px-3 py-2 text-sm text-indigo-700">{demoHint}</p>
      )}
      {!locked && retainedName && (
        <p className="mb-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          ✅ 已为你保留简历（{retainedName}），可直接点击「开始诊断」；如需更换，重新上传或粘贴新文本即可。
        </p>
      )}

      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault(); setDragOver(false);
          const f = e.dataTransfer.files?.[0];
          if (f) setFile(f);
        }}
        onClick={() => !locked && fileInput.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-8 text-sm transition
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

      {/* 背景信息面板（第十一轮 UI 指令：带说明标题的卡片，降低表单压迫感，
          并让用户知道"填了有什么用"）；按钮移出面板保持主行动线清晰 */}
      <div className="mt-3 rounded-xl border border-slate-100 bg-slate-50/60 px-4 py-3">
        <p className="mb-2 text-xs font-medium text-slate-500">
          补充背景信息（选填，AI 将根据你的阶段调整评估标准）
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
                 className="w-40 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand disabled:opacity-50" />
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
      </div>

      <div className="mt-3 flex justify-end">
        <button className="btn-primary" disabled={busy}
                onClick={() => onDiagnose({ file, text, background: { 年级: grade, 专业: major || "未填写", 目标: goal } })}>
          {busy ? "AI 诊断中…" : "开始诊断"}
        </button>
      </div>
    </section>
  );
}
