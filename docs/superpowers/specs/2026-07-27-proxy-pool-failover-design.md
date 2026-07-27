# Channel Proxy Pool and Failover Design

Date: 2026-07-27

## 1. Goal

Add a channel-level outbound proxy pool to New API. Each new upstream request selects proxies in round-robin order. When a configured network failure or HTTP response status occurs before the response is exposed to the downstream client, the request may be replayed through the next eligible proxy.

The feature must:

- preserve the existing single `proxy` setting;
- expose structured controls in the channel create/edit interface;
- support HTTP, HTTPS, SOCKS5, and SOCKS5H proxy URLs;
- reuse the existing per-proxy `http.Client` and connection pools;
- avoid retrying after a streaming response has begun;
- avoid treating configurable HTTP application responses as proof that a proxy is unhealthy;
- work without database schema changes.

## 2. Scope

### Included

- Regular HTTP relay requests.
- Streaming HTTP relay requests, but only before the upstream response is returned to the response handling layer.
- Form and task relay requests when their body can be safely replayed.
- Channel test requests.
- Channel create/edit UI and validation.
- Channel-level status-code and retry controls.
- Unit and regression tests for selection, failover, cooldown, validation, and body replay.

### Excluded

- WebSocket proxy pool support. The current WebSocket path uses `websocket.DefaultDialer` and does not use the channel HTTP proxy setting.
- Global proxy pools shared across channels.
- Persistent health state in Redis or the database.
- Active background health checks.
- Automatic proxy acquisition or scraping.
- Retrying after any upstream bytes have been forwarded to the downstream client.

## 3. Configuration Model

The configuration remains inside the existing channel settings JSON. No table migration is required.

```json
{
  "proxy": "socks5://127.0.0.1:1080",
  "proxy_pool_enabled": true,
  "proxy_pool": [
    "socks5://127.0.0.1:1080",
    "http://user:pass@10.0.0.2:8080"
  ],
  "proxy_failover_network_errors": true,
  "proxy_failover_status_codes": [429, 502, 503, 504],
  "proxy_failover_max_attempts": 3,
  "proxy_cooldown_seconds": 60
}
```

### Fields

- `proxy`: existing single-proxy field. It remains unchanged for backward compatibility.
- `proxy_pool_enabled`: enables the pool behavior. Default is `false`.
- `proxy_pool`: ordered proxy URL list. Blank entries are removed during normalization.
- `proxy_failover_network_errors`: switch proxy on eligible transport errors. Default is `true` when the pool is enabled.
- `proxy_failover_status_codes`: HTTP response status codes that trigger replay through the next proxy. Default is `[429, 502, 503, 504]` for newly configured pools. Existing channels receive no behavioral change until the pool is enabled.
- `proxy_failover_max_attempts`: maximum total proxy attempts for one upstream operation, including the first attempt. Default is `3`; minimum `1`; maximum is the number of configured proxies and must also be capped by a small implementation limit such as `10`.
- `proxy_cooldown_seconds`: cooldown for proxies that fail with an eligible network error. Default is `60`; `0` disables cooldown; accepted range is `0` to `3600`.

### Precedence

1. When `proxy_pool_enabled` is true and `proxy_pool` contains at least one valid entry, the proxy pool is used.
2. Otherwise, the existing `proxy` field is used.
3. Otherwise, the normal outbound client is used.

### Validation and normalization

- Every proxy pool entry uses the existing strict proxy URL parser.
- Schemes are limited to HTTP, HTTPS, SOCKS5, and SOCKS5H.
- Duplicate canonical proxy URLs are removed while preserving first occurrence order.
- Proxy credentials are never included in validation errors or logs.
- Status codes must be unique integers from `400` through `599`.
- An enabled proxy pool with no valid proxy entries is rejected on save.
- Maximum attempts is normalized against the number of unique proxy entries at runtime.

## 4. User Interface

Add a structured **Proxy Pool** section to the channel create/edit drawer near the existing proxy-related channel settings.

### Controls

1. **Enable proxy pool** switch.
2. **Proxy addresses** editable list:
   - one URL per row;
   - add and remove actions;
   - preserve displayed order as the round-robin order;
   - inline validation for protocol, host, port, path, query, and fragment;
   - masked password display after loading an existing channel where practical, without corrupting the saved value.
3. **Switch on network errors** switch.
4. **HTTP statuses that switch proxy** multi-select/tag input:
   - quick options: `400`, `401`, `403`, `404`, `408`, `409`, `429`, `500`, `502`, `503`, `504`;
   - allow custom status values from `400` through `599`;
   - allow an empty list.
5. **Maximum attempts** numeric input.
6. **Network-error cooldown** numeric input in seconds.
7. Read-only summary showing the number of unique valid proxies.

### UI behavior

- Pool-dependent controls are disabled when the pool switch is off.
- Saving validates every proxy and every status code before submitting.
- Turning the pool off does not delete its saved values, allowing temporary rollback to the existing single proxy.
- Existing `proxy` remains visible as **Single proxy / fallback** to preserve compatibility.
- All user-facing strings use the existing i18n pattern and are added to every supported locale through the repository sync workflow.

## 5. Runtime Architecture

### 5.1 Parsed proxy pool configuration

Introduce a normalized runtime representation derived from `ChannelSettings`:

- canonical ordered proxy URLs;
- network-error failover flag;
- status-code lookup set;
- effective maximum attempts;
- cooldown duration.

Configuration parsing must not mutate the persisted channel value.

### 5.2 Process-local selector state

Add a service-level proxy pool selector keyed by channel ID and a stable configuration fingerprint.

Each selector stores:

- an atomic or mutex-protected round-robin cursor;
- a cooldown-until timestamp per canonical proxy URL;
- the configuration fingerprint used to invalidate stale state.

State is intentionally process-local:

- different application instances rotate independently;
- restart clears cursor and cooldown state;
- no database writes occur per request;
- no Redis dependency is introduced.

When a channel configuration changes, the changed fingerprint causes a fresh selector state to replace the old one.

### 5.3 Selection algorithm

For each new upstream operation:

1. Calculate the starting index by advancing the channel selector cursor once.
2. Walk proxies circularly from that index.
3. Skip proxies whose network-error cooldown has not expired.
4. Do not use the same proxy twice within one operation.
5. If every proxy is cooling down, select the proxy with the earliest cooldown expiry rather than failing immediately. This keeps the channel usable when the entire pool is temporarily marked unhealthy.
6. Limit the returned candidates to the effective maximum attempts.

Round-robin selection occurs at operation level, not per TCP connection. Existing cached clients preserve independent keep-alive pools for each proxy.

## 6. Failover Semantics

### 6.1 Network errors

Eligible transport errors include errors produced before an HTTP response is available, such as:

- TCP dial failure;
- connection timeout;
- HTTP proxy connect failure;
- SOCKS handshake failure;
- TLS handshake failure;
- connection reset before a response is received;
- other `net.Error` or `url.Error` failures originating from `http.Client.Do`.

When network-error failover is enabled:

1. mark the attempted proxy in cooldown;
2. rebuild the request with a fresh body reader;
3. try the next candidate proxy;
4. return the final normalized upstream error if no candidate succeeds.

Context cancellation and request deadline expiration caused by the downstream caller are terminal and must not trigger another proxy attempt.

### 6.2 HTTP status codes

When an upstream response status is present in `proxy_failover_status_codes`:

1. the response body is closed without exposing it downstream;
2. the proxy is not marked unhealthy and receives no cooldown;
3. the request is rebuilt and replayed through the next candidate;
4. if attempts are exhausted, the last response is returned unchanged to the existing response handling path.

This allows operators to opt into switching for `400`, `401`, `403`, `404`, or `429`, while acknowledging that these usually describe the request, API key, account, endpoint, or upstream limits rather than proxy health.

### 6.3 Successful and non-configured responses

Any HTTP response whose status is not configured for failover is returned immediately. This includes `2xx`, redirects after the existing redirect policy, and unconfigured `4xx` or `5xx` responses.

### 6.4 Streaming safety

The proxy decision and any failover happen inside the outbound request function before the returned response is consumed. Once the response is returned to the relay response handler, no further proxy retry is permitted.

## 7. Request Replay

Every additional attempt requires a fresh `http.Request` body.

### Replayable bodies

- Marshaled JSON bodies backed by the existing `BodyStorage` are replayable because the storage implements `io.ReadSeeker`.
- Empty bodies are replayable.
- Form or task bodies are replayable only when the caller supplies a correct `GetBody` function or a seekable stored body.

### Implementation rule

The outbound layer must not reuse a consumed `http.Request`. It should either:

- build the initial request with `GetBody` and clone the request for each attempt; or
- use a small request factory closure that creates a new request with a fresh reader and copied headers for each attempt.

A request that cannot produce a fresh body reader is attempted once. Its failure is returned without unsafe replay.

Each discarded response body is closed. Each attempt uses the original context so downstream cancellation stops all work.

## 8. Logging and Security

Log at debug or warning level:

- channel ID;
- attempt number and maximum attempts;
- sanitized proxy scheme and host;
- network failure category or triggering HTTP status;
- whether another proxy will be attempted.

Never log:

- proxy passwords;
- full proxy URLs containing credentials;
- API keys;
- request bodies.

The final user-facing error continues through the existing error normalization and hidden-error behavior.

## 9. Component Changes

Expected change areas:

- `relaykit/dto/channel_settings.go` or the current channel settings DTO location: add fields and normalization helpers.
- `common/proxy_url.go`: reuse strict/runtime URL normalization; add list validation only if it represents a stable shared concept.
- `service/http_client.go`: continue providing cached per-proxy clients; do not put channel rotation policy into the client cache.
- New focused service file such as `service/proxy_pool.go`: selector state, cooldown, candidate generation, and invalidation by fingerprint.
- `relay/channel/api_request.go`: request replay loop and response-status failover before returning a response.
- Channel controller validation: reject malformed pool settings on create/update.
- Channel form state, validation, drawer components, types, and i18n locale files: structured proxy pool UI.
- `docs/channel/other_setting.md`: document new settings and backward compatibility.

The selector and HTTP client cache remain separate responsibilities:

- selector decides which proxy to try;
- HTTP client cache creates and reuses transports for a selected proxy;
- relay request code controls replay and response disposal.

## 10. Tests

### Backend DTO and validation

- Existing single proxy remains valid and unchanged.
- Enabled pool requires at least one proxy.
- Invalid scheme, host, port, path, query, and fragment are rejected.
- Canonical duplicates are removed.
- Status codes outside `400–599` are rejected.
- Duplicate status codes normalize to one value.
- Attempt and cooldown bounds are enforced.

### Selector

- Sequential requests rotate in configured order.
- Concurrent selection is race-safe.
- One operation never repeats the same proxy.
- Cooled proxies are skipped.
- Expired proxies re-enter selection.
- All-cooled behavior chooses the earliest-expiring proxy.
- Configuration fingerprint changes reset stale state.

### Request failover

- Network error switches proxy when enabled.
- Network error does not switch when disabled.
- Downstream context cancellation does not switch.
- Configured `400`, `401`, `403`, `404`, and `429` can switch.
- Unconfigured status codes do not switch.
- Configured `502`, `503`, and `504` switch.
- HTTP-status failover does not put the proxy into cooldown.
- Network failure does put the proxy into cooldown.
- Last configured response is returned when attempts are exhausted.
- Discarded response bodies are closed.
- JSON request bodies are identical on every attempt.
- Non-replayable bodies receive only one attempt.
- Streaming responses are never retried after being returned.

### Frontend

- Existing channel settings populate correctly.
- Pool values round-trip without deleting unrelated channel settings.
- Proxy and status validation block invalid submission.
- Disabling the pool preserves entered values.
- Custom status tags accept only `400–599`.
- Maximum attempts and cooldown bounds display actionable errors.

## 11. Compatibility and Rollout

- Default behavior remains unchanged for every existing channel.
- No database migration is required.
- The existing `proxy` value continues to work.
- Operators can disable the pool instantly and fall back to `proxy` or direct access.
- Process-local health state means horizontally scaled instances may choose different proxies. This is acceptable for the first implementation and avoids adding distributed coordination to a request-path feature.

## 12. Acceptance Criteria

The feature is complete when:

1. An administrator can configure an ordered proxy list and failover rules entirely from the channel UI.
2. New requests rotate across eligible proxies per channel.
3. Network failures switch and temporarily cool the failed proxy when enabled.
4. Any administrator-selected HTTP status from `400` through `599` can trigger a proxy switch without cooling the proxy.
5. Requests are replayed only when the body is safely reproducible.
6. Existing single-proxy channels behave exactly as before.
7. Backend and frontend tests cover the stated contracts.
8. Go tests, frontend checks, and production builds pass.
