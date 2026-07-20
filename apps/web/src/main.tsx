import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@radix-ui/themes/styles.css";
import "./styles.css";
import "./core/core.css";
import { App } from "./App";
import { CoreAuthProvider } from "./core/AuthContext";
import { ThemeProvider } from "./context/ThemeContext";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <CoreAuthProvider>
        <App />
      </CoreAuthProvider>
    </ThemeProvider>
  </StrictMode>,
);
