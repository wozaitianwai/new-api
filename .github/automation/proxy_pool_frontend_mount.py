from __future__ import annotations

from proxy_pool_patch_utils import replace_once


def mount_proxy_pool_component() -> None:
    path = "web/src/features/channels/components/drawers/channel-mutate-drawer.tsx"
    replace_once(
        path,
        "import { ModelMappingEditor } from '../model-mapping-editor'\n",
        "import { ModelMappingEditor } from '../model-mapping-editor'\nimport { ProxyPoolFields } from '../proxy-pool-fields'\n",
    )
    replace_once(
        path,
        """  'proxy',
  'pass_through_body_enabled',""",
        """  'proxy',
  'proxy_pool_enabled',
  'proxy_pool',
  'proxy_failover_network_errors',
  'proxy_failover_status_codes',
  'proxy_failover_max_attempts',
  'proxy_cooldown_seconds',
  'pass_through_body_enabled',""",
    )
    replace_once(
        path,
        """    values.proxy?.trim() ||
    values.system_prompt?.trim() ||""",
        """    values.proxy?.trim() ||
    values.proxy_pool_enabled ||
    values.proxy_pool?.some((proxyURL) => proxyURL.trim()) ||
    values.system_prompt?.trim() ||""",
    )
    replace_once(
        path,
        "<FormLabel>{t('Proxy Address')}</FormLabel>",
        "<FormLabel>{t('Single Proxy / Fallback')}</FormLabel>",
    )
    replace_once(
        path,
        "'Network proxy for this channel (supports HTTP, HTTPS, SOCKS5, and SOCKS5H)'",
        "'Used when the proxy pool is disabled or empty. Supports HTTP, HTTPS, SOCKS5, and SOCKS5H.'",
    )
    replace_once(
        path,
        """                            />

                            <FormField
                              control={form.control}
                              name='system_prompt'""",
        """                            />

                            <ProxyPoolFields
                              disabled={sensitiveLocked || isSubmitting}
                            />

                            <FormField
                              control={form.control}
                              name='system_prompt'""",
    )
