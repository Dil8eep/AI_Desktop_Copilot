import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "highlight.js/styles/github-dark.css";
import "./styles.css";
import { OverlayApp } from "./overlay/OverlayApp";

document.documentElement.classList.add("overlay-root");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <OverlayApp />
  </StrictMode>,
);
