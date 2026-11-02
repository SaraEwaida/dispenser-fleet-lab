import { expect, type APIRequestContext, type Page } from "@playwright/test";

export type Role = "coordinator" | "support" | "qa";

export async function login(page: Page, role: Role) {
  await page.goto("/login");
  await page.getByTestId(`demo-${role}`).click();
  await expect(page).not.toHaveURL(/\/login/);
}

/** Clear every injected fault through the API so each test starts from a healthy fleet. */
export async function clearFaults(request: APIRequestContext) {
  const r = await request.post("/api/v1/auth/login", { data: { email: "qa@fleet.example.com", password: "Demo@2026!" } });
  const { access_token } = await r.json();
  await request.delete("/api/v1/faults", { headers: { Authorization: `Bearer ${access_token}` } });
}

export async function api(request: APIRequestContext, email: string) {
  const r = await request.post("/api/v1/auth/login", { data: { email, password: "Demo@2026!" } });
  const { access_token } = await r.json();
  return { Authorization: `Bearer ${access_token}` };
}
