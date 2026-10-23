/** 与后端 contracts.py 对齐的前端类型定义（字段名严格一致）。 */

export interface AbilityItem {
  name: string;
  category: string;
  importance: number;
  importance_source: string;
  evidence: string;
}

export interface JobRequirements {
  job_id: string;
  job_title: string;
  company_type: string;
  responsibilities: string[];
  abilities: AbilityItem[];
  salary_hint: string;
  source_note: string;
}

export interface ResumeEntry {
  org: string;
  role: string;
  period: string;
  bullets: string[];
}

export interface ResumeData {
  name: string;
  contacts: string[];
  job_intent: string; // 求职意向（解析时为空串，导出时由界面注入当前岗位名）
  education: string[];
  internships: string[];
  projects: string[];
  skills: string[];
  education_entries: ResumeEntry[];
  internship_entries: ResumeEntry[];
  project_entries: ResumeEntry[];
  photo_bytes: string | null; // base64
  raw_text: string;
}

export type GapStatus = "matched" | "partial" | "missing";

export interface GapItem {
  gap_id: string;
  ability: string;
  status: GapStatus;
  importance: number;
  reason: string;
}

export interface GapReport {
  match_score: number;
  items: GapItem[];
  top_gaps: GapItem[];
  warnings: string[];
}

export interface RewriteResult {
  gap_id: string;
  diagnosis: string;
  suggestion: string;
  example_before: string;
  example_after: string;
}

export interface JobMeta {
  job_id: string;
  job_title: string;
  company_type: string;
  is_demo: boolean;
}

export interface DemoCase {
  label: string;
  job_id: string;
  resume_file: string;
  background: { 年级: string; 专业: string; 目标: string };
}

export interface DiagnoseResponse {
  report: GapReport;
  rewrites: RewriteResult[];
  rewrite_failures: string[];
  score_detail: ScoreDetail;
}

/** AI 联网检索岗位响应（/api/search-job）：job 供下游诊断，来源信息仅供展示 */
export interface SearchJobResponse {
  job: JobRequirements;
  source: string;
  source_urls: string[];
}

/** 运算过程明细（后端 gap_matcher.score_breakdown 产出，前端只渲染不复算） */
export interface ScoreDetailItem {
  gap_id: string;
  ability: string;
  importance: number;
  status: GapStatus;
  coefficient: number;
  earned: number;
}

export interface ScoreDetail {
  coefficients: Record<GapStatus, number>;
  items: ScoreDetailItem[];
  total_weight: number;
  total_earned: number;
  match_score: number;
}
