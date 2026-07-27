from __future__ import annotations

import json

from proxy_pool_patch_utils import repo_path, replace_once, run, write


def write_frontend_tests() -> None:
    write(
        "web/src/features/channels/lib/proxy-pool.test.ts",
        r'''import { describe, expect, test } from 'bun:test'

import { channelSchema } from '../types'
import {
  CHANNEL_FORM_DEFAULT_VALUES,
  channelFormSchema,
  transformChannelToFormDefaults,
  transformFormDataToCreatePayload,
} from './channel-form'

describe('channel proxy pool form', () => {
  test('uses safe proxy pool defaults', () => {
    expect(CHANNEL_FORM_DEFAULT_VALUES.proxy_pool_enabled).toBe(false)
    expect(CHANNEL_FORM_DEFAULT_VALUES.proxy_pool).toEqual([])
    expect(CHANNEL_FORM_DEFAULT_VALUES.proxy_failover_network_errors).toBe(true)
    expect(CHANNEL_FORM_DEFAULT_VALUES.proxy_failover_status_codes).toEqual([
      429, 502, 503, 504,
    ])
    expect(CHANNEL_FORM_DEFAULT_VALUES.proxy_failover_max_attempts).toBe(3)
    expect(CHANNEL_FORM_DEFAULT_VALUES.proxy_cooldown_seconds).toBe(60)
  })

  test('requires a proxy when pool is enabled', () => {
    const result = channelFormSchema.safeParse({
      ...CHANNEL_FORM_DEFAULT_VALUES,
      proxy_pool_enabled: true,
      proxy_pool: [],
    })
    expect(result.success).toBe(false)
  })

  test('rejects invalid proxy pool values', () => {
    const result = channelFormSchema.safeParse({
      ...CHANNEL_FORM_DEFAULT_VALUES,
      proxy_pool_enabled: true,
      proxy_pool: ['ftp://127.0.0.1:21'],
      proxy_failover_status_codes: [399],
      proxy_failover_max_attempts: 11,
      proxy_cooldown_seconds: 3601,
    })
    expect(result.success).toBe(false)
  })

  test('serializes proxy pool settings into channel setting JSON', () => {
    const payload = transformFormDataToCreatePayload({
      ...CHANNEL_FORM_DEFAULT_VALUES,
      name: 'proxy pool',
      models: 'gpt-test',
      key: 'secret',
      proxy_pool_enabled: true,
      proxy_pool: [
        ' http://127.0.0.1:18080 ',
        '',
        'socks5://127.0.0.1:1080',
      ],
      proxy_failover_network_errors: false,
      proxy_failover_status_codes: [400, 401, 429],
      proxy_failover_max_attempts: 2,
      proxy_cooldown_seconds: 0,
    })

    const setting = JSON.parse(String(payload.channel.setting))
    expect(setting.proxy_pool_enabled).toBe(true)
    expect(setting.proxy_pool).toEqual([
      'http://127.0.0.1:18080',
      'socks5://127.0.0.1:1080',
    ])
    expect(setting.proxy_failover_network_errors).toBe(false)
    expect(setting.proxy_failover_status_codes).toEqual([400, 401, 429])
    expect(setting.proxy_failover_max_attempts).toBe(2)
    expect(setting.proxy_cooldown_seconds).toBe(0)
  })

  test('loads saved values and preserves them while disabled', () => {
    const channel = channelSchema.parse({
      id: 1,
      type: 1,
      key: '',
      status: 1,
      name: 'saved',
      created_time: 0,
      test_time: 0,
      response_time: 0,
      balance_updated_time: 0,
      setting: JSON.stringify({
        proxy: 'http://127.0.0.1:8080',
        proxy_pool_enabled: false,
        proxy_pool: ['http://127.0.0.1:18080'],
        proxy_failover_network_errors: true,
        proxy_failover_status_codes: [403, 429],
        proxy_failover_max_attempts: 1,
        proxy_cooldown_seconds: 0,
      }),
    })

    const values = transformChannelToFormDefaults(channel)
    expect(values.proxy_pool_enabled).toBe(false)
    expect(values.proxy_pool).toEqual(['http://127.0.0.1:18080'])
    expect(values.proxy_failover_status_codes).toEqual([403, 429])
    expect(values.proxy_cooldown_seconds).toBe(0)

    const setting = JSON.parse(
      String(
        transformFormDataToCreatePayload({ ...values, key: 'secret' }).channel
          .setting
      )
    )
    expect(setting.proxy_pool).toEqual(['http://127.0.0.1:18080'])
  })
})
''',
    )


def apply_frontend_types_and_form() -> None:
    replace_once(
        "web/src/features/channels/types.ts",
        '''  proxy?: string
  pass_through_body_enabled?: boolean''',
        '''  proxy?: string
  proxy_pool_enabled?: boolean
  proxy_pool?: string[]
  proxy_failover_network_errors?: boolean
  proxy_failover_status_codes?: number[]
  proxy_failover_max_attempts?: number
  proxy_cooldown_seconds?: number
  pass_through_body_enabled?: boolean''',
    )

    replace_once(
        "web/src/features/channels/lib/channel-form.ts",
        '''    proxy: z
      .string()
      .optional()
      .refine(isOptionalProxyURL, ERROR_MESSAGES.INVALID_PROXY),
    pass_through_body_enabled: z.boolean().optional(),''',
        '''    proxy: z
      .string()
      .optional()
      .refine(isOptionalProxyURL, ERROR_MESSAGES.INVALID_PROXY),
    proxy_pool_enabled: z.boolean().optional(),
    proxy_pool: z
      .array(
        z.string().refine(isOptionalProxyURL, ERROR_MESSAGES.INVALID_PROXY)
      )
      .optional(),
    proxy_failover_network_errors: z.boolean().optional(),
    proxy_failover_status_codes: z
      .array(z.number().int().min(400).max(599))
      .refine(
        (statusCodes) => new Set(statusCodes).size === statusCodes.length,
        'Proxy failover status codes must be unique'
      )
      .optional(),
    proxy_failover_max_attempts: z.number().int().min(1).max(10).optional(),
    proxy_cooldown_seconds: z.number().int().min(0).max(3600).optional(),
    pass_through_body_enabled: z.boolean().optional(),''',
    )

    replace_once(
        "web/src/features/channels/lib/channel-form.ts",
        '''  .superRefine((data, ctx) => {
    if ([3, 8, 36, 45].includes(data.type) && !data.base_url?.trim()) {''',
        '''  .superRefine((data, ctx) => {
    if (
      data.proxy_pool_enabled &&
      !(data.proxy_pool || []).some((proxyURL) => proxyURL.trim())
    ) {
      addRequiredIssue(
        ctx,
        'proxy_pool',
        'Proxy pool requires at least one proxy address'
      )
    }

    if ([3, 8, 36, 45].includes(data.type) && !data.base_url?.trim()) {''',
    )

    replace_once(
        "web/src/features/channels/lib/channel-form.ts",
        '''  proxy: '',
  pass_through_body_enabled: false,''',
        '''  proxy: '',
  proxy_pool_enabled: false,
  proxy_pool: [],
  proxy_failover_network_errors: true,
  proxy_failover_status_codes: [429, 502, 503, 504],
  proxy_failover_max_attempts: 3,
  proxy_cooldown_seconds: 60,
  pass_through_body_enabled: false,''',
    )

    replace_once(
        "web/src/features/channels/lib/channel-form.ts",
        '''    proxy: '',
    pass_through_body_enabled: false,''',
        '''    proxy: '',
    proxy_pool_enabled: false,
    proxy_pool: [] as string[],
    proxy_failover_network_errors: true,
    proxy_failover_status_codes: [429, 502, 503, 504] as number[],
    proxy_failover_max_attempts: 3,
    proxy_cooldown_seconds: 60,
    pass_through_body_enabled: false,''',
    )

    replace_once(
        "web/src/features/channels/lib/channel-form.ts",
        '''        proxy: parsed.proxy || '',
        pass_through_body_enabled: parsed.pass_through_body_enabled || false,''',
        '''        proxy: parsed.proxy || '',
        proxy_pool_enabled: parsed.proxy_pool_enabled === true,
        proxy_pool: Array.isArray(parsed.proxy_pool)
          ? parsed.proxy_pool.filter(
              (value: unknown): value is string => typeof value === 'string'
            )
          : [],
        proxy_failover_network_errors:
          parsed.proxy_failover_network_errors !== false,
        proxy_failover_status_codes: Array.isArray(
          parsed.proxy_failover_status_codes
        )
          ? parsed.proxy_failover_status_codes.filter(
              (value: unknown): value is number =>
                Number.isInteger(value) &&
                Number(value) >= 400 &&
                Number(value) <= 599
            )
          : [429, 502, 503, 504],
        proxy_failover_max_attempts: Number.isInteger(
          parsed.proxy_failover_max_attempts
        )
          ? parsed.proxy_failover_max_attempts
          : 3,
        proxy_cooldown_seconds: Number.isInteger(parsed.proxy_cooldown_seconds)
          ? parsed.proxy_cooldown_seconds
          : 60,
        pass_through_body_enabled: parsed.pass_through_body_enabled || false,''',
    )

    replace_once(
        "web/src/features/channels/lib/channel-form.ts",
        '''    proxy: formData.proxy?.trim() || '',
    pass_through_body_enabled: formData.pass_through_body_enabled || false,''',
        '''    proxy: formData.proxy?.trim() || '',
    proxy_pool_enabled: formData.proxy_pool_enabled === true,
    proxy_pool: [
      ...new Set(
        (formData.proxy_pool || [])
          .map((proxyURL) => proxyURL.trim())
          .filter(Boolean)
      ),
    ],
    proxy_failover_network_errors:
      formData.proxy_failover_network_errors !== false,
    proxy_failover_status_codes: [
      ...new Set(formData.proxy_failover_status_codes || []),
    ],
    proxy_failover_max_attempts: formData.proxy_failover_max_attempts || 3,
    proxy_cooldown_seconds: formData.proxy_cooldown_seconds ?? 60,
    pass_through_body_enabled: formData.pass_through_body_enabled || false,''',
    )

    replace_once(
        "web/src/features/channels/lib/channel-form-errors.ts",
        '''  'proxy',
  'system_prompt',''',
        '''  'proxy',
  'proxy_pool_enabled',
  'proxy_pool',
  'proxy_failover_network_errors',
  'proxy_failover_status_codes',
  'proxy_failover_max_attempts',
  'proxy_cooldown_seconds',
  'system_prompt',''',
    )


def write_proxy_pool_component() -> None:
    write(
        "web/src/features/channels/components/proxy-pool-fields.tsx",
        r'''/*
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
import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useFormContext, useWatch } from 'react-hook-form'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'

import type { ChannelFormValues } from '../lib'

const QUICK_STATUS_CODES = [
  400, 401, 403, 404, 408, 409, 429, 500, 502, 503, 504,
]

type ProxyPoolFieldsProps = {
  disabled?: boolean
}

export function ProxyPoolFields(props: ProxyPoolFieldsProps) {
  const { t } = useTranslation()
  const form = useFormContext<ChannelFormValues>()
  const [customStatusCode, setCustomStatusCode] = useState('')
  const enabled =
    useWatch({ control: form.control, name: 'proxy_pool_enabled' }) === true
  const proxyPool =
    useWatch({ control: form.control, name: 'proxy_pool' }) || []
  const statusCodes =
    useWatch({
      control: form.control,
      name: 'proxy_failover_status_codes',
    }) || []
  const controlsDisabled = props.disabled || !enabled

  const setProxyPool = (nextProxyPool: string[]) => {
    form.setValue('proxy_pool', nextProxyPool, {
      shouldDirty: true,
      shouldValidate: true,
    })
  }

  const updateProxy = (index: number, value: string) => {
    setProxyPool(
      proxyPool.map((proxyURL, proxyIndex) =>
        proxyIndex === index ? value : proxyURL
      )
    )
  }

  const removeProxy = (index: number) => {
    setProxyPool(proxyPool.filter((_, proxyIndex) => proxyIndex !== index))
  }

  const toggleStatusCode = (statusCode: number) => {
    const next = statusCodes.includes(statusCode)
      ? statusCodes.filter((value) => value !== statusCode)
      : [...statusCodes, statusCode].sort((left, right) => left - right)
    form.setValue('proxy_failover_status_codes', next, {
      shouldDirty: true,
      shouldValidate: true,
    })
  }

  const addCustomStatusCode = () => {
    const statusCode = Number(customStatusCode)
    if (
      !Number.isInteger(statusCode) ||
      statusCode < 400 ||
      statusCode > 599
    ) {
      form.setError('proxy_failover_status_codes', {
        type: 'manual',
        message: t(
          'Proxy pool status codes must be integers from 400 to 599'
        ),
      })
      return
    }
    if (!statusCodes.includes(statusCode)) {
      form.setValue(
        'proxy_failover_status_codes',
        [...statusCodes, statusCode].sort((left, right) => left - right),
        { shouldDirty: true, shouldValidate: true }
      )
    }
    form.clearErrors('proxy_failover_status_codes')
    setCustomStatusCode('')
  }

  const uniqueProxyCount = new Set(
    proxyPool.map((proxyURL) => proxyURL.trim()).filter(Boolean)
  ).size

  return (
    <div className='border-border/60 space-y-4 rounded-lg border p-4'>
      <FormField
        control={form.control}
        name='proxy_pool_enabled'
        render={({ field }) => (
          <FormItem className='flex items-center justify-between gap-4'>
            <div className='space-y-0.5'>
              <FormLabel>{t('Enable proxy pool')}</FormLabel>
              <FormDescription>
                {t('Rotate outbound requests across multiple channel proxies.')}
              </FormDescription>
            </div>
            <FormControl>
              <Switch
                checked={field.value === true}
                onCheckedChange={field.onChange}
                disabled={props.disabled}
              />
            </FormControl>
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name='proxy_pool'
        render={() => (
          <FormItem>
            <div className='flex items-center justify-between gap-3'>
              <div>
                <FormLabel>{t('Proxy addresses')}</FormLabel>
                <FormDescription>
                  {t(
                    'One proxy URL per row. Requests start from the next proxy in order.'
                  )}
                </FormDescription>
              </div>
              <Button
                type='button'
                variant='outline'
                size='sm'
                disabled={controlsDisabled}
                onClick={() => setProxyPool([...proxyPool, ''])}
              >
                <Plus className='mr-2 h-4 w-4' aria-hidden='true' />
                {t('Add proxy')}
              </Button>
            </div>

            <div className='space-y-2'>
              {proxyPool.length === 0 && (
                <p className='text-muted-foreground text-xs'>
                  {t('No proxies configured.')}
                </p>
              )}
              {proxyPool.map((proxyURL, index) => (
                <div key={`${index}-${proxyURL}`} className='flex items-center gap-2'>
                  <Input
                    value={proxyURL}
                    placeholder='socks5://user:pass@host:port'
                    disabled={controlsDisabled}
                    aria-label={t('Proxy address {{index}}', {
                      index: index + 1,
                    })}
                    onChange={(event) => updateProxy(index, event.target.value)}
                  />
                  <Button
                    type='button'
                    variant='ghost'
                    size='sm'
                    disabled={controlsDisabled}
                    aria-label={t('Remove proxy')}
                    onClick={() => removeProxy(index)}
                  >
                    <Trash2 className='h-4 w-4' aria-hidden='true' />
                  </Button>
                </div>
              ))}
            </div>

            <p className='text-muted-foreground text-xs'>
              {t('{{count}} unique proxies', { count: uniqueProxyCount })}
            </p>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name='proxy_failover_network_errors'
        render={({ field }) => (
          <FormItem className='flex items-center justify-between gap-4'>
            <div className='space-y-0.5'>
              <FormLabel>{t('Switch on network errors')}</FormLabel>
              <FormDescription>
                {t(
                  'TCP, TLS, HTTP proxy, and SOCKS connection failures switch to the next proxy.'
                )}
              </FormDescription>
            </div>
            <FormControl>
              <Switch
                checked={field.value !== false}
                onCheckedChange={field.onChange}
                disabled={controlsDisabled}
              />
            </FormControl>
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name='proxy_failover_status_codes'
        render={() => (
          <FormItem>
            <FormLabel>{t('HTTP statuses that switch proxy')}</FormLabel>
            <FormDescription>
              {t(
                'Selected statuses retry through the next proxy without marking the proxy unhealthy.'
              )}
            </FormDescription>
            <div className='flex flex-wrap gap-2'>
              {QUICK_STATUS_CODES.map((statusCode) => {
                const selected = statusCodes.includes(statusCode)
                return (
                  <Button
                    key={statusCode}
                    type='button'
                    size='sm'
                    variant={selected ? 'default' : 'outline'}
                    disabled={controlsDisabled}
                    className={cn('font-mono', selected && 'shadow-sm')}
                    onClick={() => toggleStatusCode(statusCode)}
                  >
                    {statusCode}
                  </Button>
                )
              })}
            </div>
            <div className='flex gap-2'>
              <Input
                type='number'
                min={400}
                max={599}
                value={customStatusCode}
                disabled={controlsDisabled}
                placeholder={t('Custom status code')}
                onChange={(event) => setCustomStatusCode(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    addCustomStatusCode()
                  }
                }}
              />
              <Button
                type='button'
                variant='outline'
                disabled={controlsDisabled || customStatusCode.length === 0}
                onClick={addCustomStatusCode}
              >
                {t('Add status')}
              </Button>
            </div>
            <FormMessage />
          </FormItem>
        )}
      />

      <div className='grid gap-4 sm:grid-cols-2'>
        <FormField
          control={form.control}
          name='proxy_failover_max_attempts'
          render={({ field }) => (
            <FormItem>
              <FormLabel>{t('Maximum attempts')}</FormLabel>
              <FormControl>
                <Input
                  type='number'
                  min={1}
                  max={10}
                  value={field.value ?? 3}
                  disabled={controlsDisabled}
                  onChange={(event) => field.onChange(Number(event.target.value))}
                />
              </FormControl>
              <FormDescription>
                {t(
                  'Includes the first proxy attempt and is capped by the proxy count.'
                )}
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name='proxy_cooldown_seconds'
          render={({ field }) => (
            <FormItem>
              <FormLabel>{t('Network-error cooldown (seconds)')}</FormLabel>
              <FormControl>
                <Input
                  type='number'
                  min={0}
                  max={3600}
                  value={field.value ?? 60}
                  disabled={controlsDisabled}
                  onChange={(event) => field.onChange(Number(event.target.value))}
                />
              </FormControl>
              <FormDescription>
                {t(
                  'Only network failures cool a proxy. HTTP status failover does not.'
                )}
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
      </div>
    </div>
  )
}
''',
    )


def mount_proxy_pool_component() -> None:
    replace_once(
        "web/src/features/channels/components/drawers/channel-mutate-drawer.tsx",
        "import { ModelMappingEditor } from '../model-mapping-editor'\n",
        "import { ModelMappingEditor } from '../model-mapping-editor'\nimport { ProxyPoolFields } from '../proxy-pool-fields'\n",
    )
    replace_once(
        "web/src/features/channels/components/drawers/channel-mutate-drawer.tsx",
        '''  'proxy',
  'pass_through_body_enabled',''',
        '''  'proxy',
  'proxy_pool_enabled',
  'proxy_pool',
  'proxy_failover_network_errors',
  'proxy_failover_status_codes',
  'proxy_failover_max_attempts',
  'proxy_cooldown_seconds',
  'pass_through_body_enabled',''',
    )
    replace_once(
        "web/src/features/channels/components/drawers/channel-mutate-drawer.tsx",
        '''    values.proxy?.trim() ||
    values.system_prompt?.trim() ||''',
        '''    values.proxy?.trim() ||
    values.proxy_pool_enabled ||
    values.proxy_pool?.some((proxyURL) => proxyURL.trim()) ||
    values.system_prompt?.trim() ||''',
    )
    replace_once(
        "web/src/features/channels/components/drawers/channel-mutate-drawer.tsx",
        "<FormLabel>{t('Proxy Address')}</FormLabel>",
        "<FormLabel>{t('Single Proxy / Fallback')}</FormLabel>",
    )
    replace_once(
        "web/src/features/channels/components/drawers/channel-mutate-drawer.tsx",
        "'Network proxy for this channel (supports HTTP, HTTPS, SOCKS5, and SOCKS5H)'",
        "'Used when the proxy pool is disabled or empty. Supports HTTP, HTTPS, SOCKS5, and SOCKS5H.'",
    )
    replace_once(
        "web/src/features/channels/components/drawers/channel-mutate-drawer.tsx",
        '''                            />

                            <FormField
                              control={form.control}
                              name='system_prompt' ''',
        '''                            />

                            <ProxyPoolFields
                              disabled={sensitiveLocked || isSubmitting}
                            />

                            <FormField
                              control={form.control}
                              name='system_prompt' ''',
    )


def add_translations() -> None:
    translations = {
        "Enable proxy pool": {"zh": "启用代理池", "zh-TW": "啟用代理池"},
        "Rotate outbound requests across multiple channel proxies.": {"zh": "在多个渠道代理之间轮询上游请求。", "zh-TW": "在多個渠道代理之間輪詢上游請求。"},
        "Proxy addresses": {"zh": "代理地址列表", "zh-TW": "代理位址列表"},
        "One proxy URL per row. Requests start from the next proxy in order.": {"zh": "每行一个代理地址，新请求按顺序选择下一个代理。", "zh-TW": "每行一個代理位址，新請求按順序選擇下一個代理。"},
        "Add proxy": {"zh": "添加代理", "zh-TW": "新增代理"},
        "Remove proxy": {"zh": "删除代理", "zh-TW": "刪除代理"},
        "No proxies configured.": {"zh": "尚未配置代理。", "zh-TW": "尚未設定代理。"},
        "{{count}} unique proxies": {"zh": "{{count}} 个唯一代理", "zh-TW": "{{count}} 個唯一代理"},
        "Proxy address {{index}}": {"zh": "代理地址 {{index}}", "zh-TW": "代理位址 {{index}}"},
        "Switch on network errors": {"zh": "网络错误时切换代理", "zh-TW": "網路錯誤時切換代理"},
        "TCP, TLS, HTTP proxy, and SOCKS connection failures switch to the next proxy.": {"zh": "TCP、TLS、HTTP 代理或 SOCKS 连接失败时切换到下一个代理。", "zh-TW": "TCP、TLS、HTTP 代理或 SOCKS 連線失敗時切換到下一個代理。"},
        "HTTP statuses that switch proxy": {"zh": "触发代理切换的 HTTP 状态码", "zh-TW": "觸發代理切換的 HTTP 狀態碼"},
        "Selected statuses retry through the next proxy without marking the proxy unhealthy.": {"zh": "命中所选状态码时使用下一个代理重试，但不会将当前代理标记为故障。", "zh-TW": "命中所選狀態碼時使用下一個代理重試，但不會將目前代理標記為故障。"},
        "Custom status code": {"zh": "自定义状态码", "zh-TW": "自訂狀態碼"},
        "Add status": {"zh": "添加状态码", "zh-TW": "新增狀態碼"},
        "Maximum attempts": {"zh": "单次请求最大尝试次数", "zh-TW": "單次請求最大嘗試次數"},
        "Includes the first proxy attempt and is capped by the proxy count.": {"zh": "包含首次代理请求，实际次数不会超过代理数量。", "zh-TW": "包含首次代理請求，實際次數不會超過代理數量。"},
        "Network-error cooldown (seconds)": {"zh": "网络错误冷却时间（秒）", "zh-TW": "網路錯誤冷卻時間（秒）"},
        "Only network failures cool a proxy. HTTP status failover does not.": {"zh": "只有网络失败会使代理进入冷却；HTTP 状态码切换不会。", "zh-TW": "只有網路失敗會使代理進入冷卻；HTTP 狀態碼切換不會。"},
        "Single Proxy / Fallback": {"zh": "单代理 / 回退代理", "zh-TW": "單代理 / 回退代理"},
        "Used when the proxy pool is disabled or empty. Supports HTTP, HTTPS, SOCKS5, and SOCKS5H.": {"zh": "代理池关闭或为空时使用。支持 HTTP、HTTPS、SOCKS5 和 SOCKS5H。", "zh-TW": "代理池關閉或為空時使用。支援 HTTP、HTTPS、SOCKS5 和 SOCKS5H。"},
        "Proxy pool status codes must be integers from 400 to 599": {"zh": "代理池状态码必须是 400 到 599 的整数", "zh-TW": "代理池狀態碼必須是 400 到 599 的整數"},
    }
    locale_dir = repo_path("web/src/i18n/locales")
    for locale_path in sorted(locale_dir.glob("*.json")):
        locale_name = locale_path.stem
        data = json.loads(locale_path.read_text(encoding="utf-8"))
        for key, localized in translations.items():
            data[key] = localized.get(locale_name, data.get(key, key))
        locale_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def execute_frontend() -> None:
    write_frontend_tests()
    run(["bun", "test", "src/features/channels/lib/proxy-pool.test.ts"], cwd=repo_path("web"), expect_failure=True)
    apply_frontend_types_and_form()
    write_proxy_pool_component()
    mount_proxy_pool_component()
    add_translations()
    run(["bun", "x", "oxfmt", "--write", "src/features/channels/types.ts", "src/features/channels/lib/channel-form.ts", "src/features/channels/lib/channel-form-errors.ts", "src/features/channels/lib/proxy-pool.test.ts", "src/features/channels/components/proxy-pool-fields.tsx", "src/features/channels/components/drawers/channel-mutate-drawer.tsx", "src/i18n/locales/*.json"], cwd=repo_path("web"))
    run(["bun", "test", "src/features/channels/lib/proxy-pool.test.ts"], cwd=repo_path("web"))
