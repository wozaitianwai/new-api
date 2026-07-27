#!/usr/bin/env python3
from __future__ import annotations

from proxy_pool_backend_core import execute_core
from proxy_pool_backend_relay import execute_relay
from proxy_pool_frontend import (
    add_translations,
    apply_frontend_types_and_form,
    write_frontend_tests,
    write_proxy_pool_component,
)
from proxy_pool_frontend_mount import mount_proxy_pool_component
from proxy_pool_patch_utils import gofmt, read, replace_once, repo_path, run, write

COPYRIGHT_HEADER = '''/*
Copyright (C) 2023-2026 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

For commercial licensing, please contact support@quantumnous.com
*/
'''

PROXY_POOL_TEST_PATH = "web/src/features/channels/lib/proxy-pool.test.js"


def apply_replay_reader_isolation() -> None:
    replace_once(
        "relay/common/outbound_body.go",
        '''import (
	"io"
	"net/http"''',
        '''import (
	"bytes"
	"io"
	"net/http"''',
    )
    replace_once(
        "relay/common/outbound_body.go",
        '''func (body *replayableBody) NewRequestBody() (io.ReadCloser, error) {
	if _, err := body.storage.Seek(0, io.SeekStart); err != nil {
		return nil, err
	}
	return io.NopCloser(rootcommon.ReaderOnly(body.storage)), nil
}''',
        '''func (body *replayableBody) NewRequestBody() (io.ReadCloser, error) {
	data, err := body.storage.Bytes()
	if err != nil {
		return nil, err
	}
	return io.NopCloser(bytes.NewReader(data)), nil
}''',
    )
    gofmt("relay/common/outbound_body.go")
    run(
        [
            "go",
            "test",
            "./relay/common",
            "-run",
            "TestOutboundJSONBody",
            "-count=1",
        ]
    )


def prepare_proxy_pool_javascript_test() -> None:
    typescript_path = "web/src/features/channels/lib/proxy-pool.test.ts"
    write_frontend_tests()
    content = read(typescript_path)
    write(PROXY_POOL_TEST_PATH, content)
    repo_path(typescript_path).unlink()


def ensure_proxy_pool_test_header() -> None:
    content = read(PROXY_POOL_TEST_PATH)
    if not content.startswith("/*"):
        write(PROXY_POOL_TEST_PATH, COPYRIGHT_HEADER + content)


def assert_feature_copyright_headers() -> None:
    for path in (
        PROXY_POOL_TEST_PATH,
        "web/src/features/channels/components/proxy-pool-fields.tsx",
    ):
        content = read(path)
        if "Copyright (C) 2023-2026 QuantumNous" not in content[:800]:
            raise RuntimeError(f"missing project copyright header: {path}")


def update_docs() -> None:
    path = "docs/channel/other_setting.md"
    content = read(path)
    if "## 代理池与故障切换" in content:
        return
    appendix = r'''

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
'''
    write(path, content.rstrip() + appendix + "\n")


def execute_frontend() -> None:
    web_root = repo_path("web")
    prepare_proxy_pool_javascript_test()
    ensure_proxy_pool_test_header()
    run(
        ["bun", "test", "src/features/channels/lib/proxy-pool.test.js"],
        cwd=web_root,
        expect_failure=True,
    )
    apply_frontend_types_and_form()
    write_proxy_pool_component()
    mount_proxy_pool_component()
    add_translations()

    changed_files = [
        "src/features/channels/types.ts",
        "src/features/channels/lib/channel-form.ts",
        "src/features/channels/lib/channel-form-errors.ts",
        "src/features/channels/lib/proxy-pool.test.js",
        "src/features/channels/components/proxy-pool-fields.tsx",
        "src/features/channels/components/drawers/channel-mutate-drawer.tsx",
    ]
    changed_files.extend(
        str(path.relative_to(web_root))
        for path in sorted((web_root / "src/i18n/locales").glob("*.json"))
    )
    run(["bun", "x", "oxfmt", "--write", *changed_files], cwd=web_root)
    assert_feature_copyright_headers()
    run(
        ["bun", "test", "src/features/channels/lib/proxy-pool.test.js"],
        cwd=web_root,
    )


def verify_all() -> None:
    web_root = repo_path("web")
    run(
        [
            "go",
            "test",
            "./service",
            "./relay/common",
            "./relay/channel",
            "./model",
            "-count=1",
        ]
    )
    run(["bun", "run", "i18n:sync"], cwd=web_root)
    assert_feature_copyright_headers()
    run(["bun", "run", "format:check"], cwd=web_root)
    run(["bun", "run", "typecheck"], cwd=web_root)
    run(["bun", "run", "lint"], cwd=web_root)
    run(["bun", "run", "build"], cwd=web_root)
    run(["go", "test", "./...", "-count=1"])


def main() -> None:
    print("Applying channel proxy pool implementation")
    execute_core()
    apply_replay_reader_isolation()
    execute_relay()
    execute_frontend()
    update_docs()
    verify_all()
    print("Proxy pool implementation completed and verified")


if __name__ == "__main__":
    main()
