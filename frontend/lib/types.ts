export type Material = {
  code: string;
  label_en: string;
  label_hi: string;
  rate_per_kg: number;
  co2e_per_kg: number | null;
};

export type RequestStatus =
  | "open"
  | "accepted"
  | "weighed"
  | "paying"
  | "completed"
  | "expired"
  | "rejected"
  | "awaiting_ivr";

/** "unchecked" means the verifier was unavailable, never that the photo looked wrong. */
export type AiVerdict = "match" | "mismatch" | "uncertain" | "unchecked";

export type SaleRequest = {
  id: number;
  collector_id: number;
  dealer_id: number | null;
  material: string;
  est_kg: number;
  photo_url: string | null;
  lat: number | null;
  lng: number | null;
  channel: "app" | "ivr";
  status: RequestStatus;
  gps_distance_m: number | null;
  scale_kg: number | null;
  /** Photo check (backend/app/adapters.py PhotoVerifier). */
  ai_material: string | null;
  ai_confidence: number | null;
  ai_verdict: AiVerdict | null;
  ai_notes: string | null;
  ai_real_scene: number | null;
  /** What the dealer confirmed at the scale; this is what was paid for and traced. */
  dealer_material: string | null;
  created_at: string;
  expires_at: string;
  // queue extras
  collector_name?: string;
  label_en?: string;
  rate_per_kg?: number;
  distance_m?: number;
  basic_phone?: number;
};

/** Evidence on a 409 from POST /requests with rule "photo_mismatch". */
export type PhotoMismatch = {
  chose: string;
  chose_label_hi: string;
  chose_label_en: string;
  verdict: AiVerdict;
  material: string | null;
  confidence: number | null;
  real_scene: boolean | null;
  notes: string | null;
};

export type Transaction = {
  id: number;
  request_id: number;
  collector_id: number;
  dealer_id: number;
  material: string;
  est_kg: number;
  scale_kg: number;
  rate_per_kg: number;
  amount: number;
  upi_ref: string;
  credits: number;
  batch_id: number | null;
  created_at: string;
  shop_name?: string;
  collector_name?: string;
  label_en?: string;
  label_hi?: string;
};

export type ScoreInput = {
  value: number;
  weight: number;
  label: string;
  why: string;
  monthly_income?: number[];
};

export type Score = {
  score: number;
  inputs: Record<"A" | "C" | "T" | "D" | "R", ScoreInput>;
  computed_at: string;
};

export type Eligibility = {
  eligible: boolean;
  checks: { key: string; ok: boolean; label: string; detail: string }[];
  limit: number;
  next_limit: number;
  cycle: number;
  sales_to_unlock: number;
  days_to_unlock: number;
};

export type Collector = {
  id: number;
  name: string;
  phone: string;
  language: "hi" | "en";
  group_id: number | null;
  group_name: string | null;
  group_guarantee: number;
  qr_token: string;
  upi_vpa: string;
  basic_phone: number;
  equipment: string;
  credits: number;
  created_at: string;
  city?: string;
};

export type Message = {
  id: number;
  channel: string;
  language: string;
  text: string;
  /** Structured fields for voicing, e.g. { kind: "sale_confirmation", amount, kg, material, credits }. */
  meta: Record<string, unknown> | null;
  created_at: string;
};

export type Loan = {
  id: number;
  principal: number;
  tenure_m: number;
  status: string;
  instalments_due: number;
  instalments_on_time: number;
  disbursed_at: string;
};

export type Flag = {
  id: number;
  entity_type: string;
  entity_id: number;
  rule: string;
  rule_label: string;
  detail: string;
  evidence: Record<string, unknown> | null;
  collector_id: number | null;
  dealer_id: number | null;
  collector_name: string | null;
  shop_name: string | null;
  status: "open" | "confirmed" | "dismissed";
  created_at: string;
};

export type CollectorProfile = {
  collector: Collector;
  score: Score | null;
  eligibility: Eligibility;
  transactions: Transaction[];
  requests: SaleRequest[];
  messages: Message[];
  loans: Loan[];
  flags: Flag[];
  income_by_week: { week_start: string; value: number }[];
};

export type Dealer = {
  id: number;
  shop_name: string;
  owner_name: string;
  phone: string;
  lat: number;
  lng: number;
  scale_id: string;
  upi_vpa: string;
  reputation: number;
};

export type MassBalance = { bought_kg: number; sold_kg: number; gap_pct: number | null };

export type Batch = {
  id: number;
  code: string;
  material: string;
  total_kg: number;
  label_en: string;
  created_at: string;
};
