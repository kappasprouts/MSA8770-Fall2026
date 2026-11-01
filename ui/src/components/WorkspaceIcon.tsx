export type WorkspaceIconName = "home" | "processing" | "review" | "decisions" | "statistics" | "errors" | "back" | "collapse" | "expand";

export default function WorkspaceIcon({ name }: { name: WorkspaceIconName }) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {name === "back" && <path d="M19 12H5M12 19l-7-7 7-7" />}
      {name === "collapse" && <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16M17 9l-3 3 3 3" /></>}
      {name === "expand" && <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16m5 5 3 3-3 3" /></>}
      {name === "home" && <><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z" /><path d="M9 21v-8h6v8" /></>}
      {name === "processing" && <><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M3 9h18M9 9v12M13 13h4M13 17h4" /></>}
      {name === "review" && <><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Z" /><path d="M14 3v6h6M8 13h8M8 17h5" /></>}
      {name === "decisions" && <><rect x="4" y="5" width="16" height="16" rx="2" /><path d="M9 5V3h6v2M8 13l3 3 5-6" /></>}
      {name === "statistics" && <><path d="M4 3v17h17M9 16v-5M14 16V7M19 16V4" /></>}
      {name === "errors" && <><path d="M12 3 2.5 20h19L12 3Z" /><path d="M12 9v4M12 17h.01" /></>}
    </svg>
  );
}
