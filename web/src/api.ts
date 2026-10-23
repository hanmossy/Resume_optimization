/**
 * api.ts —— 前端 API 封装层。
 * 所有请求携带两个头：X-Access-Password（访问密码门）、X-User-Api-Key（BYOK）。
 * 错误统一抛 ApiError（含 HTTP 状态码与后端 detail 文案），组件按 status 分级提示。
 */
import type {
  DemoCase, DiagnoseResponse, JobMeta, JobRequirements, ResumeData, SearchJobResponse,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

// 凭证存 localStorage：刷新页面免重输；密码与 Key 都不会发给第三方
export const creds = {
  get password() { return localStorage.getItem("access_password") ?? ""; },
  set password(v: string) { localStorage.setItem("access_password", v); },
  get apiKey() { return localStorage.getItem("user_api_key") ?? ""; },
  set apiKey(v: string) { localStorage.setItem("user_api_key", v); },
  get bochaKey() { return localStorage.getItem("user_bocha_key") ?? ""; },
  set bochaKey(v: string) { localStorage.setItem("user_bocha_key", v); },
};

async function requestRaw(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  headers.set("X-Access-Password", creds.password);
  headers.set("X-User-Api-Key", creds.apiKey);
  headers.set("X-User-Bocha-Key", creds.bochaKey);  // 博查 BYOK（与 DeepSeek 同逻辑）
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch { /* 非 JSON 错误体 */ }
    throw new ApiError(res.status, String(detail));
  }
  return res;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return (await requestRaw(path, init)).json() as Promise<T>;
}

/** POST JSON 但不解析响应体——调用方按内容类型自取（json / blob） */
function jsonPostRaw(path: string, body: unknown): Promise<Response> {
  return requestRaw(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const api = {
  health: () => request<{ ok: boolean; public_mode: boolean; demo_cache_mode: boolean }>("/api/health"),
  auth: (password: string) =>
    request<{ ok: boolean }>("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    }),
  listJobs: () => request<JobMeta[]>("/api/jobs"),
  demoCases: () => request<DemoCase[]>("/api/demo-cases"),
  demoResume: (filename: string) =>
    request<{ filename: string; text: string }>(`/api/demo-resume/${encodeURIComponent(filename)}`),
  analyzeJob: (payload: { job_id?: string; jd_text?: string }) =>
    jsonPostRaw("/api/analyze-job", payload).then((r) => r.json() as Promise<JobRequirements>),
  /** AI 联网检索岗位：博查搜索 → LLM 抽取岗位画像（带 8s 保险丝，失败抛 503） */
  searchJob: (query: string) =>
    jsonPostRaw("/api/search-job", { query }).then((r) => r.json() as Promise<SearchJobResponse>),
  parseResume: (file: File | null, text: string) => {
    const form = new FormData();
    if (file) form.append("file", file);
    form.append("text", text);
    return request<ResumeData>("/api/parse-resume", { method: "POST", body: form });
  },
  diagnose: (payload: unknown) =>
    jsonPostRaw("/api/diagnose", payload).then((r) => r.json() as Promise<DiagnoseResponse>),
  /** PDF 导出：返回 Blob，前端触发下载 */
  exportPdf: (path: "/api/export-report" | "/api/export-resume", body: unknown) =>
    jsonPostRaw(path, body).then((r) => r.blob()),
};

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
