/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 设计 Token：从 Figma 设计稿采样（ui/求职简历诊断助手1440.fig）
        page: "#f3f6fd",        // 页面背景
        card: "#ffffff",        // 卡片
        bannerFrom: "#daf3fe",  // Banner 渐变左端（采样值）
        bannerVia: "#e4e3ff",   // 渐变中段（蓝紫过渡）
        bannerTo: "#fbe8fe",    // Banner 渐变右端（采样值）
        brand: "#4f46e5",       // 主色（indigo-600，配蓝紫渐变）
        ok: "#16a34a",          // 状态绿
        warn: "#d97706",        // 状态黄
        bad: "#dc2626",         // 状态红
      },
      borderRadius: {
        card: "16px",           // 卡片圆角
      },
      boxShadow: {
        card: "0 1px 3px rgba(30, 41, 82, 0.06), 0 4px 14px rgba(30, 41, 82, 0.05)",
      },
    },
  },
  plugins: [],
};
