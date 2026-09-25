// Drive the candidate calendar through visible controls, including mobile.
import assert from 'node:assert/strict';
export async function selectDateRange(page, startId, endId, start, end) {
  await page.locator(startId).click();
  const dialog = page.locator('.go-date-range[role=dialog]');
  await dialog.waitFor();
  for (const value of [start, end]) {
    const day = value.slice(0, 10);
    for (let months = 0; months < 13; months++) {
      if (await dialog.locator(`[data-day="${day}"]`).count()) break;
      await dialog.locator('[data-next]').click();
    }
    await dialog.locator(`[data-day="${day}"]`).click();
  }
  if (start.includes('T')) {
    await dialog.locator('[data-start-time]').fill(start.slice(11, 16));
    await dialog.locator('[data-end-time]').fill(end.slice(11, 16));
  }
  await dialog.locator('[data-confirm]').click();
  await dialog.waitFor({state:'detached'});
  assert.equal(await page.locator(startId).inputValue(), start);
  assert.equal(await page.locator(endId).inputValue(), end);
}
