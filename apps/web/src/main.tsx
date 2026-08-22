import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@radix-ui/themes/styles.css";
import "./styles.css";
import "./core/core.css";
import { App } from "./App";
import { CoreAuthProvider } from "./core/AuthContext";
import { LocaleProvider } from "./core/LocaleContext";
import { ToastProvider } from "./core/ToastContext";
import { ThemeProvider } from "./context/ThemeContext";
import { installChunkRecovery } from "./lib/chunkRecovery";

installChunkRecovery();
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <CoreAuthProvider>
        <LocaleProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
        </LocaleProvider>
      </CoreAuthProvider>
    </ThemeProvider>
  </StrictMode>,
);
