export type Role = "care_coordinator" | "support_engineer" | "qa_engineer";
export type Me = { id: number; email: string; full_name: string; role: Role; permissions: string[] };

export type DeviceStatus = "online" | "offline" | "never_seen";
export type DeviceSummary = {
  serial: string; status: DeviceStatus; firmware: string; battery_pct: number | null; roll_remaining: number | null;
  roll_capacity: number; rssi_dbm: number | null; clock_offset_s: number | null; last_seen_at: string | null;
  client: { code: string; name: string; care_team: string; timezone: string };
  open_alerts: number; faults: string[]; adherence_24h: number | null; doses_24h: number;
};
export type AlertBrief = {
  id: number; code: string; type: string; severity: Severity; status: AlertStatus; message: string;
  created_at: string; ack_due_at: string;
};
export type DoseRow = {
  id: number; due_at: string; due_local: string; status: string; taken_at: string | null; confirmed_at: string | null;
  failure_reason: string | null;
};
export type CommandRow = {
  id: number; type: string; status: string; created_at: string; sent_at: string | null; completed_at: string | null; result: string | null;
};
export type DeviceDetail = DeviceSummary & {
  schedule: string[]; local_time: string; alerts: AlertBrief[]; doses: DoseRow[]; commands: CommandRow[];
};

export type Severity = "critical" | "high" | "medium" | "low";
export type AlertStatus = "open" | "acknowledged" | "resolved";
export type Alert = AlertBrief & {
  overdue: boolean; acknowledged_at: string | null; acknowledged_by: string | null; resolved_at: string | null;
  resolved_by: string | null; auto_resolved: boolean; resolution: string | null; dose_id: number | null;
  device: { serial: string; status: DeviceStatus; client_code: string; client_name: string; care_team: string };
  tickets?: { id: number; code: string; status: string }[];
};

export type Message = {
  id: number; msg_id: string | null; serial: string | null; type: string | null; seq: number | null;
  device_ts: string | null; received_at: string; status: "accepted" | "duplicate" | "invalid" | "unknown_device";
  out_of_order: boolean; buffered: boolean; error: string | null; payload: Record<string, unknown> | null; raw: string | null;
};

export type Ticket = {
  id: number; code: string; subject: string; priority: string; status: string; reporter: string;
  device_serial: string | null; alert_id: number | null; created_at: string; updated_at: string;
  description?: string; resolution?: string | null; notes?: { id: number; body: string; author: string; created_at: string }[];
};

export type SimStatus = {
  now: string; speed: number; simulator_enabled: boolean; grace_minutes: number; offline_after_minutes: number;
  heartbeat_minutes: number; runtime: Record<string, number>;
};
