// Web V2 入口（对齐 DSH：单页 #root；主题预载在 index.html 内联脚本完成）
import React from "react";
import ReactDOM from "react-dom/client";
import "./tokens/theme.css";
import "./tokens/app.css";
import "./tokens/conversation.css";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
