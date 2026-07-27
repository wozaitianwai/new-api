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
import { Plus, Trash2 } from 'lucide-react'
import { useRef, useState } from 'react'
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
  const proxyRowIds = useRef<string[]>([])
  const nextProxyRowId = useRef(0)

  const createProxyRowId = () => {
    const rowId = `proxy-row-${nextProxyRowId.current}`
    nextProxyRowId.current += 1
    return rowId
  }

  while (proxyRowIds.current.length < proxyPool.length) {
    proxyRowIds.current.push(createProxyRowId())
  }
  if (proxyRowIds.current.length > proxyPool.length) {
    proxyRowIds.current.length = proxyPool.length
  }

  const setProxyPool = (nextProxyPool: string[]) => {
    form.setValue('proxy_pool', nextProxyPool, {
      shouldDirty: true,
      shouldValidate: true,
    })
  }

  const addProxy = () => {
    proxyRowIds.current.push(createProxyRowId())
    setProxyPool([...proxyPool, ''])
  }

  const updateProxy = (index: number, value: string) => {
    setProxyPool(
      proxyPool.map((proxyURL, proxyIndex) =>
        proxyIndex === index ? value : proxyURL
      )
    )
  }

  const removeProxy = (index: number) => {
    proxyRowIds.current.splice(index, 1)
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
    if (!Number.isInteger(statusCode) || statusCode < 400 || statusCode > 599) {
      form.setError('proxy_failover_status_codes', {
        type: 'manual',
        message: t('Proxy pool status codes must be integers from 400 to 599'),
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
  const proxyRows = proxyPool.map((proxyURL, index) => ({
    index,
    proxyURL,
    rowKey: proxyRowIds.current[index],
  }))

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
                onClick={addProxy}
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
              {proxyRows.map(({ proxyURL, index, rowKey }) => (
                <div key={rowKey} className='flex items-center gap-2'>
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
                  onChange={(event) =>
                    field.onChange(Number(event.target.value))
                  }
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
                  onChange={(event) =>
                    field.onChange(Number(event.target.value))
                  }
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
