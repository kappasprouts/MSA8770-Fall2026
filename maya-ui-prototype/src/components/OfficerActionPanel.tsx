"use client";

import { useState } from "react";

const ACTIONS = [
  { id: "second-reader", label: "Send to second reader", description: "Continue standard human review." },
  { id: "further-review", label: "Request further review", description: "Hold for additional officer analysis." },
  { id: "special-review", label: "Escalate exception", description: "Route an unusual case to a counselor." },
  { id: "waitlist", label: "Recommend waitlist", description: "Record a preliminary human recommendation." },
  { id: "decline", label: "Recommend decline", description: "Record a preliminary human recommendation." },
];

export default function OfficerActionPanel({ appId }: { appId: string }) {
  const [selected, setSelected] = useState("");
  const [notes, setNotes] = useState("");
  const [recorded, setRecorded] = useState(false);

  function recordAction() {
    if (!selected) return;
    setRecorded(true);
  }

  return (
    <div className="mx-auto max-w-4xl">
      <div className="rounded-xl border border-violet-200 bg-violet-50 p-4">
        <p className="text-sm font-semibold text-violet-900">Human-in-the-loop demonstration</p>
        <p className="mt-1 text-sm leading-relaxed text-violet-700">
          The AI does not choose an admissions outcome. This panel simulates the action an authorized admissions officer would record after reviewing the source documents and evidence.
        </p>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(280px,.8fr)]">
        <div>
          <h3 className="text-base font-semibold text-ink">Select an officer action</h3>
          <div className="mt-3 space-y-2">
            {ACTIONS.map((action) => (
              <label
                key={action.id}
                className={`flex cursor-pointer gap-3 rounded-xl border p-4 transition ${
                  selected === action.id ? "border-accent bg-violet-50 ring-1 ring-accent" : "border-border hover:bg-surface-alt"
                }`}
              >
                <input
                  type="radio"
                  name="officer-action"
                  value={action.id}
                  checked={selected === action.id}
                  onChange={(event) => {
                    setSelected(event.target.value);
                    setRecorded(false);
                  }}
                  className="mt-1 accent-violet-700"
                />
                <span>
                  <span className="block text-sm font-semibold text-ink">{action.label}</span>
                  <span className="mt-0.5 block text-xs text-ink-muted">{action.description}</span>
                </span>
              </label>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-border bg-surface-alt p-5">
          <h3 className="text-base font-semibold text-ink">Review notes</h3>
          <p className="mt-1 text-xs text-ink-muted">Application {appId}</p>
          <textarea
            value={notes}
            onChange={(event) => {
              setNotes(event.target.value);
              setRecorded(false);
            }}
            placeholder="Document the reason for the selected action..."
            className="mt-4 h-40 w-full resize-none rounded-xl border border-border bg-white px-3 py-3 text-sm text-ink outline-none placeholder:text-ink-muted focus:border-accent"
          />
          <button
            type="button"
            onClick={recordAction}
            disabled={!selected}
            className="mt-3 w-full rounded-xl bg-accent-strong px-4 py-3 text-sm font-semibold text-white transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-45"
          >
            Record simulated action
          </button>
          {recorded && (
            <p className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
              Simulated action recorded in this browser session. It was not written to the production database.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
