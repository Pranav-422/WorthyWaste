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
  | "cancelled"
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
  kind: "waste_picker" | "door_to_door";
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
  /** Door-to-door collectors only (Phase 2); empty for waste pickers. */
  pickups: { id: number; day: string; segregation: string; status: string; distance_m: number; photo_url: string | null; created_at: string; household_name: string; fee: number | null; fee_status: string | null }[];
  insurance: InsuranceStatus;
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
  /** When the dealer last pinned the shop from their phone; null = never (collectors may not find it). */
  location_set_at: string | null;
  plan: "free" | "pro";
};

export type MassBalance = { bought_kg: number; sold_kg: number; gap_pct: number | null };

/** A shop the collector can pick, from GET /dealers/nearby. Never carries contact details. */
export type NearbyDealer = {
  id: number;
  shop_name: string;
  distance_m: number;
  last_used: boolean;
};

/** One of the collector's own sales, from GET /collectors/me/requests. */
export type MyRequest = {
  id: number;
  material: string;
  est_kg: number;
  scale_kg: number | null;
  status: RequestStatus;
  created_at: string;
  expires_at: string;
  dealer_material: string | null;
  ai_verdict: AiVerdict | null;
  ai_material: string | null;
  photo_url: string | null;
  shop_name: string | null;
  label_en: string;
  label_hi: string;
  /** Set once the sale is paid. */
  amount: number | null;
  credits: number | null;
};

export type Batch = {
  id: number;
  code: string;
  material: string;
  total_kg: number;
  label_en: string;
  created_at: string;
};

// ---------- Phase 2: door-to-door collection, households, revenue ----------

export type CollectorKind = "waste_picker" | "door_to_door";

export type InsuranceStatus = {
  policy: { id: number; partner: string; cover: number; monthly_premium: number; status: string; started_at: string } | null;
  offer: { partner: string; cover: number; monthly_premium: number };
};

/** One door on a door-to-door collector's route, from GET /collectors/me/route. */
export type RouteHome = {
  id: number;
  name: string;
  kind: "home" | "bulk";
  lat: number;
  lng: number;
  today_segregation: "separated" | "mixed" | null;
  today_status: "done" | "disputed" | null;
  last_day: string | null;
};

export type Route = {
  day: string;
  homes: RouteHome[];
  done: number;
  separated: number;
  earnings: { today: number; month_paid: number; month_pending: number };
  recent: { id: number; day: string; segregation: string; status: string; created_at: string; name: string; fee: number | null; fee_status: string | null }[];
};

export type FeeStatus = "accrued" | "due" | "paid" | "cancelled" | "refunded";

export type PickupResult = {
  pickup: { id: number; segregation: "separated" | "mixed"; day: string; photo_url: string | null };
  fee: { id: number; fee: number; platform_fee: number; plan: "per_pickup" | "monthly"; status: FeeStatus };
  points: number;
  household: { id: number; name: string; kind: "home" | "bulk" };
};

export type HouseholdPickup = {
  id: number;
  day: string;
  segregation: "separated" | "mixed";
  points: number;
  status: "done" | "disputed";
  created_at: string;
  fee: number | null;
  platform_fee: number | null;
  debited: number | null;
  credit_used: number | null;
  fee_status: FeeStatus | null;
  plan: string | null;
  can_dispute: boolean;
};

export type ComplianceReport = {
  subscribed: boolean;
  monthly_fee: number;
  month: string;
  name: string;
  ward: string;
  days: number;
  handed_over: number;
  separated: number;
  separated_pct: number | null;
  missed: string[];
  log: { day: string; segregation: string; status: string; created_at: string; collector_name: string }[];
};

export type HouseholdView = {
  household: {
    id: number;
    kind: "home" | "bulk";
    name: string;
    contact_name: string | null;
    phone: string;
    language: "hi" | "en";
    ward: string;
    door_qr: string;
    fee_plan: "per_pickup" | "monthly";
  };
  collector_name: string | null;
  wallet: {
    mandate_status: "active" | "none";
    mandate_limit: number;
    mandate_vpa: string | null;
    spent_month: number;
    upcoming: number;
    due: number;
    fee_credit: number;
    fee_plan: "per_pickup" | "monthly";
    fee_per_pickup: number;
    monthly_fee: number;
    platform_fee: number;
  };
  points: {
    balance: number;
    value: number;
    redeem_step: number;
    earned_month: number;
    monthly_cap: number;
    streak: number;
    streak_every: number;
    streak_bonus: number;
    per_separated: number;
  };
  month: { pickups: number; separated: number };
  today: HouseholdPickup | null;
  pickups: HouseholdPickup[];
  messages: { id: number; text: string; language: string; created_at: string }[];
  compliance: ComplianceReport | null;
};

export type RevenueStream = { stream: string; label: string; total: number; month: number; count: number };

export type OpsOverview = {
  revenue: { streams: RevenueStream[]; net_month: number; net_total: number; weekly: { week_start: string; value: number }[] };
  day: string;
  wards: { ward: string; homes: number; mandates: number; bulk: number; picked_today: number; separated_pct_30d: number | null }[];
  separated_by_week: { week_start: string; value: number }[];
  missed: { id: number; name: string; ward: string; collector_name: string | null; last_day: string | null }[];
  collectors: { id: number; name: string; score: number | null; homes: number; today: number; disputes_30d: number; open_flags: number }[];
  points_liability: number;
  dues: number;
  dealers_pro: number;
  dealers: number;
  policies: number;
  bulk_subscribed: number;
};

export type PurchaseBill = {
  id: number;
  bill_no: string;
  created_at: string;
  material: string;
  label_en: string;
  label_hi: string;
  scale_kg: number;
  rate_per_kg: number;
  amount: number;
  upi_ref: string;
  collector_name: string;
  shop_name: string;
  owner_name: string;
};
