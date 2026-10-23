import { useState } from "react";
import { api, ApiError, downloadBlob } from "../api";
import type { GapReport, JobRequirements, ResumeData, RewriteResult } from "../types";

interface Props {
  job: JobRequirements;
  resume: ResumeData;
  report: GapReport;
  rewrites: RewriteResult[];
  onError: (e: ApiError) => void;
}

interface ExportItem {
  key: string;
  title: string;
  desc: string;
  path: "/api/export-report" | "/api/export-resume";
  buildBody: () => unknown;
  filename: string;
}

/** 导出区：并排三卡片（诊断报告 / 中文简历 / 英文简历），按钮带 loading 态。 */
export default function ExportPanel({ job, resume, report, rewrites, onError }: Props) {
  const [loading, setLoading] = useState<string | null>(null);

  const items: ExportItem[] = [
    {
      key: "report", title: "诊断报告 PDF", desc: "岗位画像 + Gap 对照 + 改写建议（含 AI 使用声明页脚）",
      path: "/api/export-report", filename: "简历诊断报告.pdf",
      buildBody: () => ({ job, report, rewrites }),
    },
    {
      key: "zh", title: "修改后简历（中文）", desc: "按正式简历版式排版，已命中的改写自动并入，含求职意向",
      path: "/api/export-resume", filename: "修改后简历-中文.pdf",
      buildBody: () => ({ resume, rewrites, lang: "zh", job_title: job.job_title }),
    },
    {
      key: "en", title: "English Resume", desc: "面向外企投递场景，AI 在改写后整体翻译",
      path: "/api/export-resume", filename: "Resume-EN.pdf",
      buildBody: () => ({ resume, rewrites, lang: "en", job_title: job.job_title }),
    },
  ];

  const run = async (item: ExportItem) => {
    setLoading(item.key);
    try {
      const blob = await api.exportPdf(item.path, item.buildBody());
      downloadBlob(blob, item.filename);
    } catch (e) {
      if (e instanceof ApiError) onError(e);
      else onError(new ApiError(500, String(e)));
    } finally {
      setLoading(null);
    }
  };

  return (
    <section className="card">
      <h2 className="mb-1 text-lg font-semibold">导出</h2>
      <p className="mb-4 text-sm text-slate-500">所有导出物均含 AI 使用声明；简历为排版版，可直接投递。</p>
      <div className="grid gap-4 md:grid-cols-3">
        {items.map((item) => (
          <div key={item.key} className="flex flex-col rounded-xl border border-slate-100 p-4 transition hover:shadow-card">
            <div className="text-sm font-semibold">{item.title}</div>
            <p className="mb-4 mt-1 flex-1 text-xs leading-relaxed text-slate-400">{item.desc}</p>
            <button className="btn-primary w-full" disabled={loading !== null} onClick={() => run(item)}>
              {loading === item.key ? (
                <>
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                  生成中…
                </>
              ) : "导出 PDF"}
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
