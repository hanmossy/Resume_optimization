/** 顶部 Banner：蓝紫粉渐变背景 + 大标题（对齐 Figma 设计稿顶部区域）。 */
export default function Banner() {
  return (
    <header className="relative overflow-hidden rounded-card bg-gradient-to-r from-bannerFrom via-bannerVia to-bannerTo px-8 py-10 shadow-card">
      <div className="pointer-events-none absolute -right-10 -top-16 h-56 w-56 rounded-full bg-white/30 blur-2xl" />
      <h1 className="text-3xl font-bold tracking-tight text-slate-800">求职简历诊断助手</h1>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-600">
        先分析岗位，再对照简历——把 JD 解构为能力清单，逐项对照你的简历，
        找出 Gap 并给出可核验的改写建议，一键导出中英双语简历。
      </p>
      <div className="mt-4 flex gap-2 text-xs text-slate-500">
        <span className="rounded-full bg-white/60 px-3 py-1">① 选岗</span>
        <span className="rounded-full bg-white/60 px-3 py-1">② AI 解析岗位</span>
        <span className="rounded-full bg-white/60 px-3 py-1">③ 上传简历</span>
        <span className="rounded-full bg-white/60 px-3 py-1">④ Gap 诊断</span>
        <span className="rounded-full bg-white/60 px-3 py-1">⑤ 改写导出</span>
      </div>
    </header>
  );
}
