"use client";

import { useCallback, useState } from "react";
import { Dialog, DialogTitle } from "@/components/dialog";
import { Icon } from "@/components/icons";
import { api, reportDeleted, type Investigation } from "@/lib/api";

export function canDeleteReport(report: Investigation) {
  return ["completed", "failed", "cancelled"].includes(report.status);
}

export function ReportDeleteDialog({ report, close, deleted }: {
  report: Investigation; close: () => void; deleted: (id: string) => void;
}) {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const dismiss = useCallback(() => { if (!busy) close(); }, [busy, close]);
  async function remove() {
    if (busy) return;
    setBusy(true); setError("");
    try {
      await api(`/investigations/${encodeURIComponent(report.id)}`, { method: "DELETE" });
      reportDeleted(report.id);
      deleted(report.id);
    } catch (error) { setError((error as Error).message); setBusy(false); }
  }
  return <Dialog close={dismiss} className="settings-dialog report-delete-dialog">
    <div className="settings-dialog-heading"><div><span className="eyebrow">Reports</span><DialogTitle>Delete report?</DialogTitle></div><button className="icon-button" disabled={busy} aria-label="Close deletion confirmation" onClick={dismiss}><Icon name="close"/></button></div>
    <strong className="report-delete-name">{report.domain}</strong>
    <p className="report-delete-summary">This report and its saved sources, findings, questions and processing history will be permanently removed.</p>
    {error&&<p className="editor-error" role="alert">{error}</p>}
    <div className="settings-dialog-actions"><button className="quiet-button" disabled={busy} onClick={dismiss}>Keep report</button><button className="action-button danger-action" disabled={busy} onClick={()=>void remove()}>{busy?"Deleting…":"Delete report"}<Icon name="trash"/></button></div>
  </Dialog>;
}
