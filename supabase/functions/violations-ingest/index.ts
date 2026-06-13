type ViolationPayload = {
  violation_id: string;
  camera_id: string;
  policy_id: number;
  occurred_at: string;
  severity?: string;
  status?: string;
  confidence_score?: number | null;
  ai_summary?: string | null;
  model_payload?: Record<string, unknown> | null;
  snapshot_url?: string | null;
  clip_url?: string | null;
};

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ALLOWED_KEYS = new Set([
  "violation_id",
  "camera_id",
  "policy_id",
  "occurred_at",
  "severity",
  "status",
  "confidence_score",
  "ai_summary",
  "model_payload",
  "snapshot_url",
  "clip_url",
]);

function jsonResponse(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function validatePayload(value: unknown): ViolationPayload {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("JSON object required");
  }

  const payload = value as Record<string, unknown>;
  const unknownKeys = Object.keys(payload).filter((key) => !ALLOWED_KEYS.has(key));
  if (unknownKeys.length > 0) {
    throw new Error(`Unsupported fields: ${unknownKeys.join(", ")}`);
  }
  if (!UUID_PATTERN.test(String(payload.violation_id ?? ""))) {
    throw new Error("violation_id must be a UUID");
  }
  if (!UUID_PATTERN.test(String(payload.camera_id ?? ""))) {
    throw new Error("camera_id must be a UUID");
  }
  if (![1, 3].includes(Number(payload.policy_id))) {
    throw new Error("policy_id must be 1 (PPE) or 3 (fire)");
  }
  if (Number.isNaN(Date.parse(String(payload.occurred_at ?? "")))) {
    throw new Error("occurred_at must be an ISO timestamp");
  }

  return {
    violation_id: String(payload.violation_id),
    camera_id: String(payload.camera_id),
    policy_id: Number(payload.policy_id),
    occurred_at: String(payload.occurred_at),
    severity: String(payload.severity ?? "medium"),
    status: String(payload.status ?? "open"),
    confidence_score:
      payload.confidence_score == null ? null : Number(payload.confidence_score),
    ai_summary: payload.ai_summary == null ? null : String(payload.ai_summary),
    model_payload:
      payload.model_payload && typeof payload.model_payload === "object"
        ? payload.model_payload as Record<string, unknown>
        : null,
    snapshot_url:
      payload.snapshot_url == null ? null : String(payload.snapshot_url),
    clip_url: payload.clip_url == null ? null : String(payload.clip_url),
  };
}

Deno.serve(async (request) => {
  if (request.method !== "POST") {
    return jsonResponse(405, { error: "POST only" });
  }

  const ingestToken = Deno.env.get("INGEST_TOKEN");
  const suppliedToken = request.headers.get("x-ingest-token");
  if (!ingestToken || suppliedToken !== ingestToken) {
    return jsonResponse(401, { error: "Unauthorized" });
  }

  let payload: ViolationPayload;
  try {
    payload = validatePayload(await request.json());
  } catch (error) {
    return jsonResponse(400, {
      error: error instanceof Error ? error.message : "Invalid payload",
    });
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!supabaseUrl || !serviceRoleKey) {
    return jsonResponse(500, { error: "Supabase runtime credentials missing" });
  }

  const response = await fetch(
    `${supabaseUrl}/rest/v1/violations?on_conflict=violation_id`,
    {
      method: "POST",
      headers: {
        apikey: serviceRoleKey,
        authorization: `Bearer ${serviceRoleKey}`,
        "content-type": "application/json",
        prefer: "resolution=ignore-duplicates,return=minimal",
      },
      body: JSON.stringify({
        ...payload,
        recorded_at: new Date().toISOString(),
      }),
    },
  );

  if (!response.ok) {
    return jsonResponse(502, {
      error: "Supabase insert failed",
      status: response.status,
      detail: await response.text(),
    });
  }

  return jsonResponse(202, {
    accepted: true,
    violation_id: payload.violation_id,
  });
});
