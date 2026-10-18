export function classificationLabel(value: string) {
  return ({ observed: "Documented", inferred: "Inferred", hypothesis: "Proposed" } as Record<string, string>)[value] ?? value;
}

export function statusLabel(value: string) {
  return ({ completed: "Ready to review", queued: "Queued", exploring: "Preparing evidence", analyzing: "Assessing evidence", failed: "Processing interrupted", cancelled: "Stopped" } as Record<string, string>)[value] ?? value;
}

export function formatDate(value: string) {
  const normalized = value.endsWith("Z") || /[+-]\d\d:\d\d$/.test(value) ? value : value + "Z";
  return new Date(normalized).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
