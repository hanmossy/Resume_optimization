/** 与后端 contracts.py 对齐的前端类型定义（字段名严格一致）。 */

/** v1.6（Human-in-the-loop）：指标的信息来源通道——
    jd_requirement 参与匹配评分；public_opinion / policy_background 为环境情报 */
export type SourceType = "jd_requirement" | "public_opinion" | "policy_background";

export interface AbilityItem {
  name: string;
  category: string;
  importance: number;
  importance_source: string;
  evidence: string;
  is_core: boolean; // v1.4：核心硬性能力（partial/missing 触发总分否决）
  source_type: SourceType; // v1.6：指标池分区依据
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
export type EvidenceStrength = "strong" | "weak"; // v1.4：strong 有数据有深度 / weak 一笔带过

export interface GapItem {
  gap_id: string;
  ability: string;
  status: GapStatus;
  evidence_strength: EvidenceStrength;
  importance: number;
  category: string;
  is_core: boolean;
  reason: string;
}

export interface GapReport {
  match_score: number;
  items: GapItem[];
  top_gaps: GapItem[];
  warnings: string[];
  core_penalty_applied: boolean; // v1.4：核心门槛未达标（总分 ×0.6 且封顶 60）
  core_gap_abilities: string[];
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

/** 求职者背景（v1.5 新增 availability：可到岗实习时间，gap_judge 规则 6/7 的输入）。 */
export interface Background {
  年级: string;
  专业: string;
  目标: string;
  availability: string;
}

export interface DemoCase {
  label: string;
  job_id: string;
  resume_file: string;
  background: Background;
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
  opinion_urls: string[]; // v1.6：舆情来源链接（小红书/知乎等体验讨论）
  opinion_status: "ok" | "none"; // v1.6：舆情通道是否取到结果（none → "暂无显著舆论风险"）
}

/** 运算过程明细（后端 gap_matcher.score_breakdown 产出，前端只渲染不复算） */
export interface ScoreDetailItem {
  gap_id: string;
  ability: string;
  importance: number;
  weight: number; // 软技能 5 折后的实际权重
  soft_discounted: boolean;
  is_core: boolean;
  status: GapStatus;
  evidence_strength: EvidenceStrength;
  coefficient: number;
  earned: number;
}

export interface ScoreDetail {
  items: ScoreDetailItem[];
  total_weight: number;
  total_earned: number;
  raw_score: number; // 核心否决前的原始分
  core_penalty_applied: boolean;
  core_gap_abilities: string[];
  match_score: number;
}
