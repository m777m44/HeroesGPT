import type { CallJob } from "./call-job";
import type { Registry } from "./registry";

export interface Env {
  CALL_JOB: DurableObjectNamespace<CallJob>;
  REGISTRY: DurableObjectNamespace<Registry>;
  PHONECALL_TOKEN: string;
  XAI_API_KEY: string;
  XAI_WEBHOOK_SECRET: string;
  SIP_USERNAME: string;
  SIP_PASSWORD: string;
  TWILIO_ACCOUNT_SID: string;
  TWILIO_AUTH_TOKEN: string;
  TWILIO_PHONE_NUMBER: string;
  // Who calls are made for, unless a call says otherwise.
  PRINCIPAL_NAME?: string;
  // A second xAI SIP number for simulated calls. Optional.
  SIM_NUMBER?: string;
  AGENT_NAME?: string;
  VOICE?: string;
  SUMMARY_MODEL?: string;
}

export type JobStatus = "dialing" | "ringing" | "connected" | "ended" | "done";

export interface Job {
  id: string;
  to: string;
  brief: string;
  principal: string;
  agentName: string;
  voice: string;
  maxMinutes: number;
  answerTimeoutSec: number;
  // Persona for a simulated callee; when set, the call goes to a second Grok agent instead of a phone.
  simulate?: string;
  origin: string;
  status: JobStatus;
  createdAt: number;
  twilioCallSid?: string;
  twilioStatus?: string;
  xaiCallId?: string;
  simCallId?: string;
  answeredAt?: number;
  endedAt?: number;
  durationSec?: number;
  endCall?: { outcome: string; notes?: string };
  report?: Report;
}

export interface Report {
  outcome: string;
  summary: string;
  details: Record<string, string>;
  commitments: string[];
  follow_ups: string[];
}

export interface Question {
  id: string;
  question: string;
  status: "pending" | "answered" | "timed_out";
  answer: string | null;
  askedAt: number;
  answeredAt: number | null;
}

export interface JobEvent {
  seq: number;
  at: number;
  type: string;
  // `any` rather than `unknown`: Durable Object RPC types collapse `unknown` to `never`.
  data: Record<string, any>;
}
