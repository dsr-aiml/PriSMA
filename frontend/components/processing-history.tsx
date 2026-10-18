import { Icon, type IconName } from "@/components/icons";
import type { Detail } from "@/lib/api";
import { formatDate } from "@/lib/presentation";

type Event = Detail["events"][number];
const stages: Record<string, { title: string; icon: IconName }> = {
  queued: { title: "Request queued", icon: "clock" },
  exploring: { title: "Evidence preparation", icon: "document" },
  analyzing: { title: "Architecture assessment", icon: "layers" },
  cancelled: { title: "Assessment stopped", icon: "pause" },
  completed: { title: "Report saved", icon: "check" },
  failed: { title: "Processing interrupted", icon: "activity" },
};

export function ProcessingHistory({ events, expanded }: { events: Event[]; expanded: boolean }) {
  // Group consecutive stages without reordering or discarding saved records.
  const groups: { stage: string; events: Event[] }[] = [];
  for (const event of events) {
    const last = groups.at(-1);
    if (last?.stage === event.stage) last.events.push(event);
    else groups.push({ stage: event.stage, events: [event] });
  }
  return <details className="timeline" open={expanded}>
    <summary><span>Processing history</span><span className="timeline-summary-meta"><small>{events.length} records</small><Icon name="chevron" /></span></summary>
    {groups.length ? <ol className="timeline-stages" aria-label="Processing stages">
      {groups.map(group => {
        const stage = stages[group.stage] ?? { title: "Processing update", icon: "activity" as IconName };
        return <li className="timeline-stage" key={group.events[0].id}>
          <span className="timeline-marker"><Icon name={stage.icon} /></span>
          <div className="timeline-stage-content"><h3>{stage.title}</h3>
            <ol className="timeline-records" aria-label={stage.title + " records"}>
              {group.events.map(event => <li key={event.id}><p>{event.message}</p><time dateTime={event.created_at}>{formatDate(event.created_at)}</time></li>)}
            </ol>
          </div>
        </li>;
      })}
    </ol> : <p className="timeline-empty">Processing records will appear when the worker starts.</p>}
  </details>;
}
