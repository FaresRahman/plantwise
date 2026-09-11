import React from "react";

import { ErrorBoundary } from "../components/ErrorBoundary";
import { AppRoutes } from "./routes";

export default function App() {
  return (
    <ErrorBoundary>
      <AppRoutes />
    </ErrorBoundary>
  );
}
