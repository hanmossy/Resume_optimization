import { creds } from "../api";

interface Props {
  apiKey: string;
  onApiKeyChange: (v: string) => void;
  publicMode: boolean;
  demoCacheMode: boolean;
}

/** 左侧固定 Sidebar：Logo + BYOK Key 设置（对齐设计稿 Sidebar 布局）。 */
export default function Sidebar({ apiKey, onApiKeyChange, publicMode, demoCacheMode }: Props) {
  return (
    <aside className="fixed inset-y-0 left-0 flex w-64 flex-col border-r border-slate-200/70 bg-white/80 backdrop-blur">
      <div className="flex items-center gap-2 px-5 py-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand text-lg text-white">简</div>
        <div>
          <div className="text-sm font-semibold">简历诊断助手</div>
          <div className="text-xs text-slate-400">AI + 信息素养</div>
        </div>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-2">
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-500">
            你的 DeepSeek API Key{publicMode ? "（必填）" : "（可选）"}
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => { creds.apiKey = e.target.value; onApiKeyChange(e.target.value); }}
            placeholder="sk-..."
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"
          />
          <p className="mt-1 text-xs leading-relaxed text-slate-400">
            {publicMode
              ? "公网体验版不内置 Key，各人使用各人的额度。Key 仅保存在你的浏览器中。"
              : "留空时使用内置开发配置；Key 仅保存在本地浏览器中。"}
          </p>
        </div>

        <div className="rounded-lg bg-slate-50 p-3 text-xs leading-relaxed text-slate-500">
          <div className="mb-1 font-medium text-slate-600">运行模式</div>
          {publicMode ? "公网体验版（强制自带 Key）" : demoCacheMode ? "演示缓存模式（断网可演示）" : "联网模式"}
        </div>

        <div className="rounded-lg bg-slate-50 p-3 text-xs leading-relaxed text-slate-500">
          <div className="mb-1 font-medium text-slate-600">评分口径</div>
          匹配度 = Σ(重要度 × 命中系数)，已具备 1.0 / 部分匹配 0.5 / 缺失 0.0。AI 只做判断，分数由规则公式计算。
        </div>
      </div>

      <div className="px-5 py-4 text-xs text-slate-400">AI 生成内容需人工核验后使用</div>
    </aside>
  );
}
