import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";


const operatorClient = readFileSync(new URL("./operator.ts", import.meta.url), "utf8");
const operatorPage = readFileSync(
  new URL("../app/operator/page.tsx", import.meta.url),
  "utf8",
);
const apiClient = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
const accountClient = readFileSync(new URL("./auth.ts", import.meta.url), "utf8");


test("browser operator code contains no privileged credential persistence or header", () => {
  for (const forbidden of [
    "aira_operator_key",
    "X-API-Key",
    "getOperatorKey",
    "setOperatorKey",
    "clearOperatorKey",
    "hasOperatorKey",
  ]) {
    assert.equal(operatorClient.includes(forbidden), false, forbidden);
    assert.equal(operatorPage.includes(forbidden), false, forbidden);
  }
});


test("operator page does not ask a browser user for a service credential", () => {
  assert.equal(operatorPage.includes('type="password"'), false);
  assert.equal(operatorPage.includes("placeholder=\"Service key\""), false);
  assert.match(operatorPage, /server-managed/);
});


test("account bearer remains temporary while streaming and uploads carry it", () => {
  assert.match(accountClient, /aira_auth_token/);
  assert.match(accountClient, /localStorage/);
  assert.match(apiClient, /userFetch[\s\S]*currentAuthHeaders\(\)/);
  assert.match(apiClient, /userFetch\(`\$\{API_URL\}\/aira-x\/stream`/);
  assert.match(apiClient, /userFetch\(`\$\{API_URL\}\/upload`/);
});
