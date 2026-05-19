import axios, { type AxiosRequestConfig, type AxiosResponse } from "axios";
import { useNotificationStore } from "@/store/notificationStore";

// L2 fix (Session 58 round-2, ISSUES_PENDING_REGISTRY §10 L2): runtime config support.
// 旧 pattern build-time-only `import.meta.env.VITE_API_BASE_URL` 需 rebuild on deploy.
// Now supports `window.__APP_CONFIG__.apiBaseUrl` runtime override via index.html
// script injection (e.g. nginx envsubst at container start). Build-time fallback retained.
//
// Usage at deploy time (e.g. Docker entrypoint OR nginx):
//   <script>window.__APP_CONFIG__ = { apiBaseUrl: "https://api.prod.example.com" };</script>
// Injected BEFORE main bundle <script src="/assets/index-*.js">.
declare global {
  interface Window {
    __APP_CONFIG__?: {
      apiBaseUrl?: string;
      wsUrl?: string;
      wsBaseUrl?: string;
    };
  }
}

const _runtimeConfig = (typeof window !== "undefined" ? window.__APP_CONFIG__ : undefined) ?? {};
const BASE_URL =
  _runtimeConfig.apiBaseUrl ??
  import.meta.env.VITE_API_BASE_URL ??
  "/api";

export const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
  headers: { "Content-Type": "application/json" },
  // S1 P0-22 fix (Session 57+1, 2026-05-19): withCredentials=true sends
  // HttpOnly cookies (admin_token) automatically. Required for cookie-based
  // auth migration from localStorage. Same-origin works without CORS.
  withCredentials: true,
});

// Request interceptor: attach auth token
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("auth_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor: global error handling + toast
apiClient.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error) => {
    const original = error.config as AxiosRequestConfig & { _retry?: boolean; _silent?: boolean };
    const status = error.response?.status;
    const notify = useNotificationStore.getState().add;

    // 401: token expired
    if (status === 401 && !original._retry) {
      original._retry = true;
      localStorage.removeItem("auth_token");
      window.dispatchEvent(new CustomEvent("auth:expired"));
      return Promise.reject(error);
    }

    // Skip toast for silent requests or 404 (may be valid empty data)
    if (original._silent || status === 404) {
      return Promise.reject(error);
    }

    // Global error toast
    if (status === 403) {
      notify({ type: "error", title: "权限不足", message: "该操作需要更高权限" });
    } else if (status === 422) {
      const detail = error.response?.data?.detail;
      notify({ type: "warning", title: "请求参数错误", message: typeof detail === "string" ? detail : "请检查输入" });
    } else if (status === 429) {
      notify({ type: "warning", title: "操作频率过高", message: error.response?.data?.detail || "请稍后再试" });
    } else if (status === 503) {
      notify({ type: "warning", title: "服务不可用", message: "QMT未连接或后端服务维护中" });
    } else if (status && status >= 500) {
      notify({ type: "error", title: "服务器错误", message: "请稍后重试，如持续出现请联系管理员" });
    } else if (!error.response) {
      // Network error (no response at all)
      notify({ type: "error", title: "网络连接失败", message: "无法连接到后端服务" });
    }

    return Promise.reject(error);
  },
);

export default apiClient;
