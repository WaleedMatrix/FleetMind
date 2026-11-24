import { ALERT_INFO, type AlertLevel } from "@/lib/predictions";

export function AlertBadge({ level }: { level: AlertLevel }) {
  const { tone, label } = ALERT_INFO[level];
  return <span className={`alert-badge badge-${tone}`}><i aria-hidden="true" />{label}</span>;
}
