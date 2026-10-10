// Smoke test of the Accounts page (desktop/plugin.js) in jsdom: every tab, dialog and button.
// Backend calls are answered from fixtures.json and canned replies; nothing reaches Hermes or a provider.
//
//   node tests/ui/run.mjs        (uses React, jsdom and Testing Library from ~/.hermes/hermes-agent/node_modules)
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'

import { NM, require } from './env.mjs'

const { JSDOM } = require('jsdom')
const dom = new JSDOM('<!doctype html><html><head></head><body></body></html>', { url: 'http://localhost/' })
for (const k of ['window', 'document', 'navigator', 'HTMLElement', 'Node', 'Event', 'MouseEvent', 'KeyboardEvent',
  'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'MutationObserver']) {
  if (dom.window[k] !== undefined) {
    const v = typeof dom.window[k] === 'function' && /^[a-z]/.test(k) ? dom.window[k].bind(dom.window) : dom.window[k]
    Object.defineProperty(globalThis, k, { configurable: true, writable: true, value: v })
  }
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const errors = []
console.error = (...a) => { errors.push(a.map(String).join(' ').slice(0, 300)) }

const HERE = new URL('./', import.meta.url)
const PLUGIN = new URL('../../plugins/account-pool/desktop/plugin.js', import.meta.url)
const src = fs.readFileSync(PLUGIN, 'utf8')
  .replaceAll("from '@hermes/plugin-sdk'", `from '${new URL('sdk-stub.mjs', HERE).href}'`)
  .replace("from 'react'", `from '${new URL('react-shim.mjs', HERE).href}'`)
const UNDER_TEST = fileURLToPath(new URL('.plugin.under-test.mjs', HERE))
fs.writeFileSync(UNDER_TEST, src)

const React = require('react')
const h = React.createElement
const { QueryClient, QueryClientProvider } = await import(NM + '@tanstack/react-query/build/modern/index.js')
const { render, screen, fireEvent, waitFor, within, cleanup, act } = require('@testing-library/react')
const sdk = await import(new URL('sdk-stub.mjs', HERE).href)
const plugin = (await import(new URL('.plugin.under-test.mjs', HERE).href)).default
fs.unlinkSync(UNDER_TEST)

const fx = JSON.parse(fs.readFileSync(new URL('fixtures.json', HERE), 'utf8'))
const calls = []
let failNext = null
const store = {}
let stepCount = 0
async function rest(path, opts = {}) {
  const method = opts.method || 'GET'
  calls.push({ method, path, body: opts.body })
  if (failNext) { const e = failNext; failNext = null; throw e }
  if (method === 'GET') {
    if (!(path in fx)) throw new Error(`404: {"detail":"no fixture ${path}"}`)
    return JSON.parse(JSON.stringify(fx[path]))
  }
  const b = opts.body || {}
  if (path === '/live') return { ok: true, ts: Date.now() / 1000, rows: [], message: '' }
  if (path === '/doctor') return { checks: [{ level: 'ok', text: 'balance timer active' }, { level: 'warn', text: 'something to look at' }], empty: false }
  if (path === '/action') {
    if (b.action === 'balance') return { ok: true, rc: 0, output: 'balance: order unchanged.' }
    if (b.action === 'check') return { ok: true, rc: 0, output: 'all logins match' }
    if (b.action === 'notify') return { ok: true, rc: 0, output: b.target === 'test' ? 'Test sent: desktop ok' : 'saved' }
    return { ok: true, rc: 0, output: `${b.action} done for ${b.target}` }
  }
  if (path === '/signin/start') {
    if (b.provider === 'openai-codex' || b.mode === 'relogin')
      return { flow: 'F2', kind: 'device', url: 'https://auth.example/device', user_code: 'ABCD-1234', label: b.target, mode: b.mode, verify: true, expires_in: 900 }
    return { flow: 'F1', kind: 'code', url: 'https://claude.ai/oauth/authorize?x=1', user_code: null, label: b.target, mode: b.mode, verify: true, expires_in: 900 }
  }
  if (path === '/signin/step') {
    if (b.flow === 'F1') return b.code === 'bad' ? { status: 'error', message: 'Token exchange failed: bad code' } : { status: 'done', output: 'Added user9@example.com.' }
    stepCount += 1
    return stepCount < 2 ? { status: 'pending' } : { status: 'done', output: 'Signed in again.' }
  }
  if (path === '/signin/cancel') return { ok: true }
  throw new Error('unexpected ' + path)
}

const regs = []
const ctx = {
  rest,
  storage: { get: (k, d) => (k in store ? store[k] : d), set: (k, v) => { store[k] = v }, remove: k => { delete store[k] } },
  os: { openExternal: async () => true },
  onDispose: () => {},
  registerMany: cs => { regs.push(...cs); return () => {} }
}
plugin.register(ctx)
const areas = regs.map(r => r.area).sort()
console.log('registered areas:', areas.join(', '))
if (!document.querySelector('style[data-plugin="account-pool"]')) throw new Error('style not injected')

let qc
function mount(id) {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const reg = regs.find(r => r.id === id)
  return render(h(QueryClientProvider, { client: qc }, reg.render()))
}
const lastPost = path => [...calls].reverse().find(c => c.method === 'POST' && c.path === path)
const ok = (cond, msg) => { if (!cond) throw new Error('FAILED: ' + msg); console.log('ok -', msg) }
const click = el => act(async () => { fireEvent.click(el) })

const status = fx['/status?provider=anthropic']

// ── accounts view ──
mount('page')
await waitFor(() => { if (!document.querySelector('.hap-table')) throw new Error('no table yet') }, { timeout: 4000 })
const rows = document.querySelectorAll('.hap-table')[0].querySelectorAll('tbody tr')
ok(rows.length === status.rotation.length, `rotation table has ${rows.length} rows`)
const parkedRows = document.querySelectorAll('.hap-table')[1]?.querySelectorAll('tbody tr') || []
ok(parkedRows.length === status.parked.length, `parked table has ${parkedRows.length} rows`)
ok(within(rows[0]).getByText(status.rotation[0].label), 'first account label shown')
ok(document.querySelectorAll('.hap-bar').length >= status.rotation.filter(r => r.usage && r.usage.pct != null).length, 'usage bars drawn')
ok(document.querySelectorAll('svg.hap-spark').length > 0, 'sparklines drawn')
ok(screen.getByText('Tokens, last 24 h') && screen.getByText('Tokens, 24 h', { selector: 'span' }), 'tokens card and column shown')
ok(rows[0].textContent.includes('1.2M'), 'tokens of the first account shown compact')
ok(screen.getByText('rotation: fill_first'), 'rotation mode shown in the header')
ok(screen.getByText(/New sessions start on #1/), 'rotation table explains where new sessions start')
ok(!screen.queryByText(/Hermes rotation is not fill_first/), 'no rotation banner while every profile uses fill_first')

// live usage
await click(screen.getByText('Live usage').closest('button'))
await waitFor(() => ok(lastPost('/live'), 'Live usage posts /live'))

// park with "In 2 hours"
await click(within(rows[0]).getByLabelText('Park (take out of rotation)'))
ok(screen.getByText(`Park ${status.rotation[0].label}?`), 'park dialog opens')
await click(screen.getByText('In 2 hours'))
await click(screen.getAllByText('Park').find(b => b.tagName === 'BUTTON'))
await waitFor(() => ok(lastPost('/action')?.body.until === '+2h' && lastPost('/action').body.target === status.rotation[0].id, 'park sends id and until=+2h'))

// park "At…" custom time
await click(within(rows[1]).getByLabelText('Park (take out of rotation)'))
await click(screen.getByText('At…'))
const until = document.querySelector('input[placeholder^="17:00"]')
await act(async () => { fireEvent.change(until, { target: { value: '+90m' } }) })
await click(screen.getAllByText('Park').find(b => b.tagName === 'BUTTON'))
await waitFor(() => ok(lastPost('/action')?.body.until === '+90m', 'custom until sent'))

// remove
await click(within(rows[2]).getByLabelText('Remove'))
ok(screen.getByText(`Remove ${status.rotation[2].label}?`), 'remove dialog opens')
await click(screen.getAllByText('Remove').find(b => b.tagName === 'BUTTON' && !b.getAttribute('aria-label')))
await waitFor(() => ok(lastPost('/action')?.body.action === 'remove', 'remove posted'))

// unpark
if (status.parked.length) {
  await click(within(document.querySelectorAll('.hap-table')[1].querySelector('tbody tr')).getByLabelText('Unpark (back into rotation)'))
  await click(screen.getAllByText('Unpark').find(b => b.tagName === 'BUTTON'))
  await waitFor(() => ok(lastPost('/action')?.body.action === 'unpark', 'unpark posted'))
}

// balance -> result dialog
await click(screen.getByText('Balance now').closest('button'))
await click(screen.getAllByText('Balance now').filter(b => b.tagName === 'BUTTON').pop())
await screen.findByText('balance: order unchanged.')
ok(true, 'balance result shown')
await click(screen.getByText('Close'))

// add account (code flow) incl. an error and a retry
await click(screen.getByText('Add account').closest('button'))
const email = document.querySelector('input[placeholder="name@example.com"]')
ok(screen.getByText('Start sign-in').closest('button').disabled, 'start disabled without email')
await act(async () => { fireEvent.change(email, { target: { value: 'user9@example.com' } }) })
await click(screen.getByText('Start sign-in'))
await screen.findByText('Copy link')
ok(lastPost('/signin/start').body.target === 'user9@example.com', 'signin start posts the email')
const codeIn = document.querySelector('input[placeholder^="Paste the whole code"]')
await act(async () => { fireEvent.change(codeIn, { target: { value: 'bad' } }) })
await click(screen.getByText('Finish'))
await screen.findByText('Token exchange failed: bad code')
ok(true, 'step error shown, dialog stays on the code step')
await act(async () => { fireEvent.change(document.querySelector('input[placeholder^="Paste the whole code"]'), { target: { value: 'abc#def' } }) })
await click(screen.getByText('Finish'))
await screen.findByText('Added user9@example.com.')
ok(screen.getByText('Done.'), 'add finished')
await click(screen.getByText('Close'))

// relogin (device flow, polls every 4 s)
await click(within(rows[0]).getByLabelText('Sign in again'))
await click(screen.getByText('Start sign-in'))
await screen.findByText('ABCD-1234')
ok(screen.getByText('Waiting for you to confirm…'), 'device code shown, waiting')
await waitFor(() => screen.getByText('Signed in again.'), { timeout: 12000 })
ok(true, 'device flow polled to done')
await click(screen.getByText('Close'))

// cancel a started sign-in
await click(screen.getByText('Add account').closest('button'))
await act(async () => { fireEvent.change(document.querySelector('input[placeholder="name@example.com"]'), { target: { value: 'x@example.com' } }) })
await click(screen.getByText('Start sign-in'))
await screen.findByText('Copy link')
await click(screen.getByText('Cancel'))
ok(lastPost('/signin/cancel')?.body.flow === 'F1', 'cancel posts /signin/cancel')

// report
await click(screen.getByText('Report'))
await screen.findByText('Busiest hours')
ok(document.querySelectorAll('.hap-table tbody tr').length === fx['/report?provider=anthropic&hours=24'].accounts.length, 'report rows match')
await click(screen.getByText('7 days'))
await waitFor(() => ok(calls.some(c => c.path === '/report?provider=anthropic&hours=168'), 'report 7 days fetched'))

// health
await click(screen.getByText('Health'))
await click(screen.getByText('Run doctor').closest('button'))
await screen.findByText('something to look at')
ok(true, 'doctor checks listed')
await click(screen.getByText('Check accounts').closest('button'))
await screen.findByText('all logins match')
await click(screen.getByText('Close'))

// alerts
await click(screen.getByText('Alerts'))
await screen.findByText('Desktop notifications')
await click(screen.getAllByRole('switch')[0])
await waitFor(() => ok(lastPost('/action')?.body.target === 'desktop-off', 'desktop switch posts desktop-off'))
ok(document.querySelector('[data-sdk-select]') && !document.querySelector('select.hap-select'), 'telegram picker is the SDK Select, not a native select')
await act(async () => { fireEvent.change(document.querySelector('[data-sdk-select]'), { target: { value: 'worker-2' } }) })
await waitFor(() => ok(lastPost('/action')?.body.target === 'telegram-via=worker-2', 'telegram via posts'))
await click(screen.getByText('Send a test alert').closest('button'))
await screen.findByText('Test sent: desktop ok')
await click(screen.getByText('Close'))

// provider switch -> empty state
await click(screen.getByText('Accounts', { selector: 'button' }))
await click(screen.getByText(/^openai-codex/))
await screen.findByText('No openai-codex accounts yet.')
ok(store.provider === 'openai-codex', 'provider choice stored')
cleanup()

// a profile that does not use fill_first -> banner with the fix
store.provider = 'anthropic'
const savedMode = fx['/status?provider=anthropic'].rotation_mode
const rr = savedMode.profiles.map(r => r.profile === 'worker-3' ? { ...r, strategy: 'round_robin', configured: 'round_robin' } : r)
fx['/status?provider=anthropic'].rotation_mode = { ...savedMode, profiles: rr, other: rr.filter(r => r.strategy !== 'fill_first') }
mount('page')
await screen.findByText(/Hermes rotation is not fill_first in worker-3 \(round_robin\)/)
ok(screen.getByText('rotation: fill_first, 1 profile(s) differ'), 'rotation banner and header warning for a round_robin profile')
fx['/status?provider=anthropic'].rotation_mode = savedMode
cleanup()

// multi-line tooltips keep their line breaks
ok(document.querySelector('style[data-plugin="account-pool"]').textContent.includes('.hap-ml{white-space:pre-line'), 'multi-line tip style present')

// backend missing -> setup hint
store.provider = 'anthropic'
failNext = new Error('404: {"detail":"Not Found"}')
mount('page')
await screen.findByText(/The account-pool backend did not answer/)
ok(screen.getByText(/plugins.enabled/), 'setup hint for a missing backend')
cleanup()

// status bar chip
mount('chip')
const sum = fx['/summary?provider=anthropic']
await screen.findByText(new RegExp(`^${sum.usable}/${sum.rotation}`))
await click(document.querySelector('button'))
ok(sdk.host.navigated.includes('/accounts'), 'chip opens the page')
cleanup()

// palette entry
regs.find(r => r.area === 'palette').data.run()
ok(sdk.host.navigated.length >= 2, 'palette entry navigates')

const real = errors.filter(e => !/not wrapped in act|ReactDOMTestUtils/.test(e))
console.log(`console.error: ${real.length}`)
real.slice(0, 10).forEach(e => console.log('  ', e))
console.log('toasts:', sdk.host.notes.map(n => `${n.kind}: ${n.message}`).join(' | '))
console.log(real.length ? 'UI TEST: CHECK ERRORS' : 'UI TEST PASSED')
process.exit(real.length ? 1 : 0)
