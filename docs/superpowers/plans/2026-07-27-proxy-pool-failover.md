# Channel Proxy Pool Failover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add channel-level round-robin proxy pools with configurable network/status-code failover and a structured channel administration UI.

**Architecture:** Keep persisted configuration in the existing channel `setting` JSON and preserve the legacy `proxy` field. A focused service owns normalized proxy-pool configuration, process-local round-robin/cooldown state, and per-operation candidate generation; the relay request layer owns safe request replay and response disposal. The frontend exposes the fields through React Hook Form and serializes them into the existing setting JSON.

**Tech Stack:** Go 1.25.1, net/http, Gin, testify; React 19, TypeScript, React Hook Form, Zod, Base UI/Tailwind, Bun/Vitest.

## Global Constraints

- Existing single-proxy channels must behave exactly as before until `proxy_pool_enabled` is true.
- Supported proxy schemes remain `http`, `https`, `socks5`, and `socks5h`.
- HTTP failover status values are unique integers from `400` through `599`.
- Network failures may cool a proxy; HTTP status failover must never cool a proxy.
- Never replay after the upstream response has been returned to the response handler.
- Never retry a request body that cannot produce a fresh reader.
- No database migration and no Redis dependency.
- Backend JSON marshal/unmarshal must use `common` wrappers.
- New Go tests use `testify/require` and `testify/assert`.
- Frontend user-facing strings use `useTranslation()` and locale files.

---

### Task 1: Persisted Settings and Proxy Pool Selector

**Files:**
- Modify: `dto/channel_settings.go`
- Create: `service/proxy_pool.go`
- Create: `service/proxy_pool_test.go`

**Interfaces:**
- Consumes: `common.ParseProxyURLStrict`, `common.ParseProxyURLRuntime`, `dto.ChannelSettings`.
- Produces:
  - `type ProxyPoolAttemptPlan struct`
  - `func PrepareProxyPoolAttempts(channelID int, settings dto.ChannelSettings) (*ProxyPoolAttemptPlan, error)`
  - `func (plan *ProxyPoolAttemptPlan) ShouldFailoverStatus(statusCode int) bool`
  - `func MarkProxyNetworkFailure(channelID int, fingerprint string, proxyURL string, cooldown time.Duration)`
  - `func ValidateChannelProxySettings(settings dto.ChannelSettings) error`

- [ ] **Step 1: Write failing selector and validation tests**

Add deterministic tests for strict URL validation, duplicate canonical URL removal, default values, ordered round-robin, concurrent selection, cooldown skipping/re-entry, all-cooled fallback, configuration fingerprint reset, and status lookup.

```go
func TestPrepareProxyPoolAttemptsRotatesPerChannel(t *testing.T) {
    settings := dto.ChannelSettings{
        ProxyPoolEnabled: true,
        ProxyPool: []string{"http://127.0.0.1:18080", "socks5://127.0.0.1:1080"},
        ProxyFailoverMaxAttempts: 2,
    }

    first, err := PrepareProxyPoolAttempts(101, settings)
    require.NoError(t, err)
    second, err := PrepareProxyPoolAttempts(101, settings)
    require.NoError(t, err)

    assert.Equal(t, []string{"http://127.0.0.1:18080", "socks5://127.0.0.1:1080"}, first.ProxyURLs)
    assert.Equal(t, []string{"socks5://127.0.0.1:1080", "http://127.0.0.1:18080"}, second.ProxyURLs)
}
```

- [ ] **Step 2: Run tests and verify RED**

Run: `go test ./service -run 'Test(PrepareProxyPool|ValidateChannelProxy)' -count=1`

Expected: compilation failure because the new fields and selector interfaces do not exist.

- [ ] **Step 3: Add channel settings fields**

```go
type ChannelSettings struct {
    ForceFormat                 bool    `json:"force_format,omitempty"`
    ThinkingToContent           bool    `json:"thinking_to_content,omitempty"`
    Proxy                       string  `json:"proxy"`
    ProxyPoolEnabled            bool    `json:"proxy_pool_enabled,omitempty"`
    ProxyPool                   []string `json:"proxy_pool,omitempty"`
    ProxyFailoverNetworkErrors  *bool   `json:"proxy_failover_network_errors,omitempty"`
    ProxyFailoverStatusCodes    []int   `json:"proxy_failover_status_codes,omitempty"`
    ProxyFailoverMaxAttempts    int     `json:"proxy_failover_max_attempts,omitempty"`
    ProxyCooldownSeconds        int     `json:"proxy_cooldown_seconds,omitempty"`
    PassThroughBodyEnabled      bool    `json:"pass_through_body_enabled,omitempty"`
    SystemPrompt                string  `json:"system_prompt,omitempty"`
    SystemPromptOverride        bool    `json:"system_prompt_override,omitempty"`
}
```

Use `*bool` so an omitted value defaults to enabled while an explicit `false` remains representable.

- [ ] **Step 4: Implement minimal normalized selector**

`PrepareProxyPoolAttempts` returns `nil, nil` when the pool is disabled or empty so callers keep the legacy path. Normalize URLs with runtime-compatible parsing, deduplicate canonical strings, cap attempts to `min(configured, len(proxies), 10)`, default attempts to `3`, and default cooldown to `60s`. Use a mutex-protected state keyed by channel ID with a stable SHA-256 configuration fingerprint.

- [ ] **Step 5: Run selector tests and verify GREEN**

Run: `go test ./service -run 'Test(PrepareProxyPool|ValidateChannelProxy)' -count=1`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dto/channel_settings.go service/proxy_pool.go service/proxy_pool_test.go
git commit -m "feat: add channel proxy pool selector"
```

---

### Task 2: Replayable Outbound Request Bodies

**Files:**
- Modify: `relay/common/outbound_body.go`
- Create: `relay/common/outbound_body_test.go`

**Interfaces:**
- Produces:
  - `type RequestBodyReplayer interface { NewRequestBody() (io.ReadCloser, error) }`
  - `func AttachRequestBodyReplay(req *http.Request, body io.Reader)`

- [ ] **Step 1: Write failing body replay tests**

```go
func TestOutboundJSONBodyCanReplayIdenticalBytes(t *testing.T) {
    payload := []byte(`{"model":"test","value":0}`)
    body, _, closer, err := NewOutboundJSONBody(payload)
    require.NoError(t, err)
    defer closer.Close()

    req, err := http.NewRequest(http.MethodPost, "http://example.test", body)
    require.NoError(t, err)
    AttachRequestBodyReplay(req, body)
    require.NotNil(t, req.GetBody)

    first, err := io.ReadAll(req.Body)
    require.NoError(t, err)
    replay, err := req.GetBody()
    require.NoError(t, err)
    second, err := io.ReadAll(replay)
    require.NoError(t, err)
    assert.Equal(t, first, second)
}
```

- [ ] **Step 2: Run test and verify RED**

Run: `go test ./relay/common -run TestOutboundJSONBodyCanReplayIdenticalBytes -count=1`

Expected: compilation failure because `AttachRequestBodyReplay` does not exist.

- [ ] **Step 3: Implement replay wrapper**

Wrap the existing `BodyStorage` in a reader that seeks to offset zero when `NewRequestBody()` is called. The returned `io.ReadCloser` must close only its wrapper, not the underlying storage; the existing caller-owned closer remains responsible for final cleanup.

- [ ] **Step 4: Run test and verify GREEN**

Run: `go test ./relay/common -run TestOutboundJSONBodyCanReplayIdenticalBytes -count=1`

Expected: PASS for in-memory and disk-backed table cases.

- [ ] **Step 5: Commit**

```bash
git add relay/common/outbound_body.go relay/common/outbound_body_test.go
git commit -m "feat: make outbound bodies safely replayable"
```

---

### Task 3: Relay Failover Loop

**Files:**
- Modify: `relay/channel/api_request.go`
- Create: `relay/channel/api_request_proxy_pool_test.go`

**Interfaces:**
- Consumes: Task 1 `PrepareProxyPoolAttempts`, `MarkProxyNetworkFailure`; Task 2 `AttachRequestBodyReplay`.

- [ ] **Step 1: Write failing HTTP proxy integration tests**

Use local `httptest.Server` instances as HTTP proxies. Record request bodies and return controlled responses.

Cover:

- configured `400`, `401`, `403`, `404`, and `429` switch to the next proxy;
- unconfigured status returns immediately;
- `502`, `503`, and `504` switch when configured;
- network connection failure switches and cools the failed proxy;
- disabled network failover returns the first error;
- downstream context cancellation is terminal;
- discarded response bodies are closed;
- attempts stop at the configured cap;
- non-replayable body receives one attempt;
- replayed JSON body bytes are identical.

- [ ] **Step 2: Run tests and verify RED**

Run: `go test ./relay/channel -run TestDoRequestProxyPool -count=1`

Expected: FAIL because `doRequest` still selects only `ChannelSetting.Proxy`.

- [ ] **Step 3: Attach replay support at request creation**

Call `relaycommon.AttachRequestBodyReplay(req, requestBody)` in `DoApiRequest`, `DoFormRequest`, and `DoTaskApiRequest`. Remove the existing task `GetBody` closure that returns the same consumed reader.

- [ ] **Step 4: Implement minimal failover loop**

For pool-enabled requests:

1. Generate ordered candidates once for the operation.
2. Use the existing cached `service.GetHttpClientWithProxy` for each candidate.
3. For attempts after the first, clone headers/context and call `req.GetBody()`.
4. On caller cancellation/deadline, stop immediately.
5. On eligible network error, mark cooldown and retry only when another candidate and replay body exist.
6. On configured HTTP status, close the response body and retry without cooldown.
7. If attempts are exhausted on an HTTP status, return the final response unchanged.
8. Normalize the final transport error through the existing `types.NewError` behavior.

Legacy single `proxy` and direct-client paths remain unchanged.

- [ ] **Step 5: Run relay tests and verify GREEN**

Run: `go test ./relay/channel -run TestDoRequestProxyPool -count=1`

Expected: PASS.

- [ ] **Step 6: Run backend regression tests**

Run: `go test ./service ./relay/common ./relay/channel ./controller -count=1`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add relay/channel/api_request.go relay/channel/api_request_proxy_pool_test.go
git commit -m "feat: fail over relay requests across proxies"
```

---

### Task 4: Save-Time Validation

**Files:**
- Modify: `controller/channel.go`
- Modify or create test: `controller/channel_test_internal_test.go`

**Interfaces:**
- Consumes: `service.ValidateChannelProxySettings`.

- [ ] **Step 1: Write failing controller tests**

Test create/update normalization boundaries:

- enabled pool with zero valid entries is rejected;
- invalid proxy protocol/host/port/path/query/fragment is rejected;
- status outside `400–599` is rejected;
- attempts outside `1–10` are rejected when explicitly set;
- cooldown outside `0–3600` is rejected;
- disabled pool preserves saved values but does not require entries;
- existing legacy `proxy` remains valid.

- [ ] **Step 2: Run tests and verify RED**

Run: `go test ./controller -run TestValidateChannelProxySettings -count=1`

Expected: FAIL because channel create/update does not validate pool fields.

- [ ] **Step 3: Validate parsed setting before persistence**

Use the existing setting JSON decode path, call `service.ValidateChannelProxySettings`, and return the controller's normal validation error response. Do not rewrite the stored JSON in the controller.

- [ ] **Step 4: Run controller tests and verify GREEN**

Run: `go test ./controller -run TestValidateChannelProxySettings -count=1`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add controller/channel.go controller/channel_test_internal_test.go
git commit -m "fix: validate channel proxy pool settings"
```

---

### Task 5: Structured Channel UI

**Files:**
- Modify: `web/src/features/channels/types.ts`
- Modify: `web/src/features/channels/lib/channel-form.ts`
- Create: `web/src/features/channels/components/proxy-pool-fields.tsx`
- Modify: `web/src/features/channels/components/drawers/channel-mutate-drawer.tsx`
- Create: `web/src/features/channels/lib/proxy-pool.test.ts`
- Modify: `web/src/i18n/locales/en.json`
- Modify: `web/src/i18n/locales/zh.json`
- Modify: remaining locale files through `bun run i18n:sync`

**Interfaces:**
- Form fields:
  - `proxy_pool_enabled: boolean`
  - `proxy_pool: string[]`
  - `proxy_failover_network_errors: boolean`
  - `proxy_failover_status_codes: number[]`
  - `proxy_failover_max_attempts: number`
  - `proxy_cooldown_seconds: number`

- [ ] **Step 1: Write failing form transformation tests**

Cover defaults, API-to-form parsing, create/update payload round trip, disabled-pool value preservation, proxy validation, status validation, deduplication, and range errors.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd web && bun test src/features/channels/lib/proxy-pool.test.ts`

Expected: compilation/schema failures because proxy-pool form fields do not exist.

- [ ] **Step 3: Extend frontend types and Zod schema**

Use defaults:

```ts
proxy_pool_enabled: false,
proxy_pool: [],
proxy_failover_network_errors: true,
proxy_failover_status_codes: [429, 502, 503, 504],
proxy_failover_max_attempts: 3,
proxy_cooldown_seconds: 60,
```

Validate each proxy with the existing URL rules; validate unique integer statuses `400–599`, attempts `1–10`, and cooldown `0–3600`. Only require a non-empty proxy list when the pool is enabled.

- [ ] **Step 4: Extend setting JSON transformations**

Parse and write all pool fields while retaining existing fields. Trim blank proxies and preserve order. Do not delete pool values when disabled.

- [ ] **Step 5: Add reusable `ProxyPoolFields` component**

Render:

- enable switch;
- ordered proxy rows with add/remove controls;
- network-error switch;
- quick status buttons for `400`, `401`, `403`, `404`, `408`, `409`, `429`, `500`, `502`, `503`, `504`;
- custom status input;
- maximum attempts input;
- cooldown seconds input;
- unique proxy count summary.

Use `useFormContext<ChannelFormValues>()`; disable pool-dependent controls when off; keep values intact.

- [ ] **Step 6: Mount the component below the legacy proxy field**

Label the existing field `Single Proxy / Fallback`. Add every proxy-pool field to sensitive-field detection and advanced-setting configured-state calculations.

- [ ] **Step 7: Add translations and run frontend tests**

Run:

```bash
cd web
bun run i18n:sync
bun test src/features/channels/lib/proxy-pool.test.ts
bun run typecheck
bun run lint
bun run build
```

Expected: all commands PASS.

- [ ] **Step 8: Commit**

```bash
git add web/src/features/channels web/src/i18n/locales
git commit -m "feat(web): add proxy pool channel settings"
```

---

### Task 6: Documentation and Full Verification

**Files:**
- Modify: `docs/channel/other_setting.md`

- [ ] **Step 1: Document configuration and behavior**

Include the JSON example, field defaults/ranges, round-robin behavior, network cooldown, configurable HTTP status failover, safe replay limit, legacy `proxy` fallback, and process-local state caveat.

- [ ] **Step 2: Run formatting and backend verification**

```bash
gofmt -w dto/channel_settings.go service/proxy_pool.go service/proxy_pool_test.go relay/common/outbound_body.go relay/common/outbound_body_test.go relay/channel/api_request.go relay/channel/api_request_proxy_pool_test.go controller/channel.go controller/channel_test_internal_test.go
go test ./... -count=1
```

Expected: PASS.

- [ ] **Step 3: Run frontend verification**

```bash
cd web
bun install --frozen-lockfile
bun run typecheck
bun run lint
bun run build
```

Expected: PASS.

- [ ] **Step 4: Review secrets and logs**

Search changed code for full proxy URL logging and confirm credentials are never emitted.

- [ ] **Step 5: Commit**

```bash
git add docs/channel/other_setting.md
git commit -m "docs: explain channel proxy pool failover"
```
