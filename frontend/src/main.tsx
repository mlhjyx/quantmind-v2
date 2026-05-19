import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { NotificationProvider } from "./contexts/NotificationContext";
import { ToastContainer } from "./components/ui/Toast";
import { ToastFromStore } from "./components/ui/ToastFromStore";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <NotificationProvider>
      <App />
      <ToastContainer />
      {/* A3 partial close (Session 58 round-2): Zustand store toast renderer.
          axios interceptor (client.ts) → useNotificationStore.add() — was silent
          before this. Coexists with Context-based ToastContainer (4→2 systems,
          full 4→1 consolidation留 Phase I ~4-6h refactor per notificationStore docstring). */}
      <ToastFromStore />
    </NotificationProvider>
  </StrictMode>,
);
