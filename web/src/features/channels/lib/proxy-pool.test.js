/*
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
import { describe, expect, test } from 'bun:test'

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
      proxy_pool: [' http://127.0.0.1:18080 ', '', 'socks5://127.0.0.1:1080'],
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
