# 渠道额外设置说明

该配置用于设置一些额外的渠道参数，可以通过 JSON 对象进行配置。主要包含以下三个设置项：

1. force_format
    - 用于标识是否对数据进行强制格式化为 OpenAI 格式
    - 类型为布尔值，设置为 true 时启用强制格式化

2. proxy
    - 用于配置网络代理
    - 类型为字符串，支持 `http`、`https`、`socks5` 和 `socks5h` 协议
    - 保存时必须包含协议和主机；仅允许空路径或根路径 `/`，不允许 query 或 fragment
    - SOCKS 代理未填写端口时，运行时使用默认端口 `1080`

3. thinking_to_content
   - 用于标识是否将思考内容`reasoning_content`转换为`<think>`标签拼接到内容中返回
   - 类型为布尔值，设置为 true 时启用思考内容转换

--------------------------------------------------------------

## JSON 格式示例

以下是一个示例配置，启用强制格式化并设置了代理地址：

```json
{
    "force_format": true,
    "thinking_to_content": true,
    "proxy": "socks5://proxy.example:1080"
}
```

--------------------------------------------------------------

通过调整上述 JSON 配置中的值，可以灵活控制渠道的额外行为，比如是否进行格式化以及使用特定的网络代理。

## 升级兼容性

旧版本会忽略代理地址中的 path、query 和 fragment。为避免升级后中断已有渠道流量，运行时会继续剥离这些遗留后缀，并对同一代理地址每个进程记录一次不含凭证和后缀的警告。该兼容逻辑不会改写数据库；再次保存渠道时必须按上述严格规则修正代理地址。

代理连接使用 30 秒 TCP 拨号超时和 30 秒 KeepAlive；TLS 握手超时为 10 秒。这些超时同样适用于未配置渠道代理的中转请求。

## 代理池与故障切换

渠道可以在保留单代理 `proxy` 的同时启用有序代理池：

```json
{
  "proxy": "socks5://127.0.0.1:1080",
  "proxy_pool_enabled": true,
  "proxy_pool": [
    "socks5://127.0.0.1:1080",
    "http://user:pass@10.0.0.2:8080"
  ],
  "proxy_failover_network_errors": true,
  "proxy_failover_status_codes": [400, 401, 403, 404, 429, 502, 503, 504],
  "proxy_failover_max_attempts": 3,
  "proxy_cooldown_seconds": 60
}
```

- `proxy_pool_enabled`：启用后，新请求按渠道独立轮询代理池。
- `proxy_pool`：有序代理 URL 列表，支持 HTTP、HTTPS、SOCKS5、SOCKS5H；重复地址会在运行时去重。
- `proxy_failover_network_errors`：TCP、TLS、HTTP 代理、SOCKS 等连接错误是否切换代理，默认开启。
- `proxy_failover_status_codes`：命中任一 `400`–`599` 状态码时切换到下一个代理。状态码切换不会把代理标记为故障。
- `proxy_failover_max_attempts`：包含首次请求，默认 `3`，范围 `1`–`10`，且不会超过代理数量。
- `proxy_cooldown_seconds`：网络错误代理的冷却时间，默认 `60` 秒，范围 `0`–`3600`；设为 `0` 表示不冷却。

只有在请求体能够安全重放且响应尚未交给下游时才会切换代理。流式响应一旦进入处理阶段便不会重试。代理池关闭时继续使用原有 `proxy`；两者均为空时使用默认直连客户端。

轮询索引和冷却状态保存在应用进程内。多实例部署时，各实例独立轮询，重启后状态清空。

