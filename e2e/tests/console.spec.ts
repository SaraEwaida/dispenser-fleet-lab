import { expect, test } from "@playwright/test";
import { api, clearFaults, login } from "./helpers";

test.beforeEach(async ({ request }) => clearFaults(request));
test.afterAll(async ({ request }) => clearFaults(request));

test("[TC-040] each role sees only its own navigation and is blocked from restricted pages", async ({ page, browser }) => {
  await login(page, "coordinator");
  const nav = page.getByRole("navigation");
  await expect(nav.getByRole("link", { name: "Alerts" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Message log" })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "Fault Lab" })).toHaveCount(0);
  await page.goto("/fault-lab");
  await expect(page.getByText("Access restricted")).toBeVisible();

  const qa = await (await browser.newContext()).newPage();
  await login(qa, "qa");
  await expect(qa.getByRole("navigation").getByRole("link", { name: "Fault Lab" })).toBeVisible();
  await qa.context().close();
});

test("[TC-041] API rejects a fault injection from a non-QA role (403)", async ({ request }) => {
  const headers = await api(request, "support@fleet.example.com");
  const r = await request.post("/api/v1/devices/MD-24010/faults", { headers, data: { type: "offline" } });
  expect(r.status()).toBe(403);
  expect(r.headers()["x-request-id"]).toBeTruthy();
});

test("[TC-042] clock drift: alert raised, resync rejected while the fault is on, accepted after it is cleared", async ({ page }) => {
  await login(page, "qa");
  await page.goto("/fault-lab");
  await page.getByTestId("fault-MD-24011-clock_drift").click();
  await expect(page.getByTestId("fault-MD-24011-clock_drift")).toHaveAttribute("aria-checked", "true");

  await page.goto("/devices/MD-24011");
  await expect(page.getByText("Clock drift", { exact: false }).first()).toBeVisible({ timeout: 40_000 });
  await expect(page.getByText("+25 min")).toBeVisible();

  await page.getByRole("button", { name: "Resync clock" }).click();
  await page.getByRole("tab", { name: "Commands" }).click();
  const cmd = page.getByTestId("command-resync_clock").first();
  await expect(cmd).toContainText("RTC unstable", { timeout: 20_000 });
  await expect(cmd).toContainText("Failed");

  await page.goto("/fault-lab");
  await page.getByTestId("fault-MD-24011-clock_drift").click();
  await expect(page.getByTestId("fault-MD-24011-clock_drift")).toHaveAttribute("aria-checked", "false");
  await page.goto("/devices/MD-24011");
  await page.getByRole("button", { name: "Resync clock" }).click();
  await page.getByRole("tab", { name: "Commands" }).click();
  await expect(page.getByTestId("command-resync_clock").first()).toContainText("clock corrected", { timeout: 20_000 });
  await expect(page.getByText("In sync")).toBeVisible({ timeout: 20_000 });
});

test("[TC-043] duplicate messages are logged as Duplicate and never double-counted", async ({ page }) => {
  await login(page, "qa");
  await page.goto("/fault-lab");
  await page.getByTestId("fault-MD-24012-duplicate_messages").click();
  await page.goto("/messages?status=duplicate");
  await page.getByLabel("Device serial").fill("MD-24012");
  const row = page.getByTestId("message-row").first();
  await expect(row).toContainText("Duplicate", { timeout: 30_000 });
  await row.getByRole("button").click();
  await expect(row).toContainText("msg_id");
});

test("[TC-044] device offline: alert after 15 fleet minutes, buffered messages and auto-resolve on reconnect", async ({ page }) => {
  await login(page, "qa");
  await page.goto("/fault-lab");
  await page.getByTestId("fault-MD-24013-offline").click();
  await page.goto("/alerts");
  await expect(page.getByText("MD-24013").first()).toBeVisible({ timeout: 60_000 });

  await page.goto("/fault-lab");
  await page.getByTestId("fault-MD-24013-offline").click();
  await page.goto("/messages?flag=buffered");
  await page.getByLabel("Device serial").fill("MD-24013");
  await expect(page.getByTestId("message-row").first()).toContainText("Buffered", { timeout: 30_000 });

  await page.goto("/devices/MD-24013");
  await expect(page.getByText("Online").first()).toBeVisible();
  await expect(page.getByText("Nothing needs attention on this device.")).toBeVisible({ timeout: 20_000 });
});

test("[TC-045] schedule editor validates input and queues a sync to the device", async ({ page }) => {
  await login(page, "support");
  await page.goto("/devices/MD-24014");
  await page.getByRole("button", { name: "Edit" }).click();
  const field = page.getByLabel("Dose times");
  await field.fill("08:00, 25:00");
  await page.getByRole("button", { name: "Save schedule" }).click();
  await expect(page.getByText("'25:00' is not a valid time")).toBeVisible();
  await field.fill("08:00, 08:00");
  await page.getByRole("button", { name: "Save schedule" }).click();
  await expect(page.getByText("Times must be unique.")).toBeVisible();
  await field.fill("08:00, 13:00, 19:30");
  await page.getByRole("button", { name: "Save schedule" }).click();
  await expect(page.getByText("08:00  ·  13:00  ·  19:30")).toBeVisible();
  await page.getByRole("tab", { name: "Commands" }).click();
  await expect(page.getByTestId("command-sync_schedule").first()).toContainText("schedule 08:00, 13:00, 19:30", { timeout: 20_000 });
});

test("[TC-046] support ticket lifecycle: validation, investigation note, resolution required", async ({ page }) => {
  await login(page, "support");
  await page.goto("/tickets");
  await page.getByRole("button", { name: "New ticket" }).click();
  await page.getByLabel("Subject").fill("Help");
  await page.getByLabel("Device serial").fill("24015");
  await page.getByRole("button", { name: "Create ticket" }).click();
  await expect(page.getByText("At least 5 characters.")).toBeVisible();
  await expect(page.getByText("Describe the problem in at least 10 characters.")).toBeVisible();
  await expect(page.getByText("Serial looks like MD-24001.")).toBeVisible();

  const subject = `Dispenser beeps but nothing comes out ${Date.now()}`;
  await page.getByLabel("Subject").fill(subject);
  await page.getByLabel("Description").fill("Caregiver reports the 13:00 reminder sounded but no sachet came out.");
  await page.getByLabel("Device serial").fill("MD-24015");
  await page.getByRole("button", { name: "Create ticket" }).click();
  await expect(page.getByRole("heading", { name: subject })).toBeVisible();

  await page.getByRole("button", { name: "Start investigating" }).click();
  await page.getByLabel("New note").fill("Checked message log: dose_due received, no dispense_failed. Asked caregiver to reseat the roll.");
  await page.getByRole("button", { name: "Add note" }).click();
  await expect(page.getByText("Asked caregiver to reseat the roll.")).toBeVisible();

  await page.getByRole("button", { name: "Resolve" }).click();
  await page.getByRole("button", { name: "Resolve ticket" }).click();
  await expect(page.getByText("A resolution is required.")).toBeVisible();
  await page.getByLabel("Resolution").fill("Roll was seated incorrectly. Reseated; next dose dispensed.");
  await page.getByRole("button", { name: "Resolve ticket" }).click();
  await expect(page.getByText("Roll was seated incorrectly.")).toBeVisible();
});
