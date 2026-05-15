export function buildLocationTokenRequest(workerUrl, adminToken, locationName) {
  return {
    url: `${workerUrl.replace(/\/$/, "")}/api/locations/token`,
    method: "POST",
    headers: {
      Authorization: `Bearer ${adminToken}`,
      "Content-Type": "application/json",
    },
    body: { location_name: locationName },
  };
}

export function parseLocationTokenResponse(data) {
  return {
    relayToken: data.token || data.relay_token,
    locationId: data.location_id,
  };
}

export async function healthCheck(workerUrl) {
  const url = `${workerUrl.replace(/\/$/, "")}/health`;
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(10_000) });
    return { ok: res.ok, status: res.status };
  } catch (err) {
    return { ok: false, status: null, error: err.message };
  }
}

export async function createLocationToken(workerUrl, adminToken, locationName) {
  const req = buildLocationTokenRequest(workerUrl, adminToken, locationName);
  const res = await fetch(req.url, {
    method: req.method,
    headers: req.headers,
    body: JSON.stringify(req.body),
    signal: AbortSignal.timeout(15_000),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Admin API returned ${res.status}: ${text}`);
  }

  const data = await res.json();
  return parseLocationTokenResponse(data);
}
