import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AuthState {
  token: string | null;
  isAuthenticated: boolean;
  setToken: (token: string) => void;
  clearToken: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      isAuthenticated: false,
      setToken: (token) => {
        localStorage.setItem("auth_token", token);
        set({ token, isAuthenticated: true });
      },
      clearToken: () => {
        localStorage.removeItem("auth_token");
        set({ token: null, isAuthenticated: false });
      },
    }),
    {
      name: "quantmind-auth",
      partialize: (state) => ({ token: state.token }),
    },
  ),
);
