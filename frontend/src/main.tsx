import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { NotificationProvider } from "./contexts/NotificationContext";
import { ToastContainer } from "./components/ui/Toast";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <NotificationProvider>
      <App />
      <ToastContainer />
    </NotificationProvider>
  </StrictMode>,
);
