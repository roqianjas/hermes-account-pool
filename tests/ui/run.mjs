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
// The hour chart of the Report tab: 7 days x 24 hours, busy from 09:00 to 21:00.
function chart(window, busy) {
  const days = []
  for (let back = 6; back >= 0; back--) {
    const d = new Date()
    d.setHours(0, 0, 0, 0)
    d.setDate(d.getDate() - back)
    const used = Array.from({ length: 24 }, (_, hr) => (busy && hr >= 9 && hr < 21 ? ((hr * 7 + back * 13) % 40) + 5 : 0))
    days.push({
      start: d.getTime() / 1000, date: `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`,
      dow: d.toLocaleDateString('en-US', { weekday: 'short' }), used, tokens: used.map(v => v * 90000), requests: used.map(v => v)
    })
  }
  return { window, has_usage: true, days }
}
for (const [path, rep] of Object.entries(fx)) {
  if (path.startsWith('/report?')) rep.chart = chart(rep.window, rep.snapshots > 0)
}
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
ok(document.querySelector('[data-card="forecast"]')?.textContent.includes('Every account ≥ 90%')
  && /~\d\d:\d\d/.test(document.querySelector('[data-card="forecast"]').textContent), 'forecast card with the time')
ok(screen.getByText(/New sessions start on #1/), 'rotation table explains where new sessions start')
ok(!screen.queryByText(/Hermes rotation is not fill_first/), 'no rotation banner while every profile uses fill_first')
ok(screen.getByText(/at API prices$/) && screen.getAllByText(/^\d+ requests$/).length, 'tokens card shows the API price and the requests on two lines')
ok(within(rows[1]).getByText(/Mon-Fri 09:00-17:00/), 'schedule chip on the scheduled account')
const schedTable = document.querySelector('[data-table="schedules"]')
ok(schedTable && schedTable.querySelectorAll('tbody tr').length === status.schedules.length, 'schedules table lists every schedule')
ok(within(schedTable).getByText('not in the pool'), 'a schedule for an account no longer in the pool is flagged')

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

// park schedule: a new one, with Saturday added and a window past midnight
await click(within(rows[0]).getByLabelText('Park on a schedule'))
ok(screen.getByText(`Park ${status.rotation[0].label} on a schedule`), 'schedule dialog opens')
await click(screen.getByText('Sat'))
await act(async () => { fireEvent.change(document.querySelector('input[aria-label="Parked from"]'), { target: { value: '22:00' } }) })
await act(async () => { fireEvent.change(document.querySelector('input[aria-label="Parked until"]'), { target: { value: '06:00' } }) })
await click(screen.getByText('Add schedule'))
await waitFor(() => {
  const b = lastPost('/action')?.body
  ok(b.action === 'schedule' && b.target === status.rotation[0].id && b.every === 'mon,tue,wed,thu,fri,sat 22:00-06:00', 'schedule posts the id, days and hours')
})
// an existing schedule opens for editing; a bad time is flagged and not sent
await click(within(rows[1]).getByLabelText('Park on a schedule'))
ok(screen.getByText('Save schedule'), 'an existing schedule opens for editing')
const before = calls.length
await act(async () => { fireEvent.change(document.querySelector('input[aria-label="Parked from"]'), { target: { value: '25:00' } }) })
ok(screen.getAllByText(/Pick at least one day and two different times/).length, 'an invalid time is flagged')
await click(screen.getByText('Save schedule'))
ok(calls.length === before, 'an invalid schedule is not posted')
await click(screen.getByText('Cancel'))
// remove a schedule
await click(within(document.querySelector('[data-table="schedules"] tbody tr')).getByLabelText('Remove schedule'))
await click(screen.getAllByText('Remove schedule').find(b => b.tagName === 'BUTTON' && !b.getAttribute('aria-label')))
await waitFor(() => ok(lastPost('/action')?.body.action === 'unschedule' && lastPost('/action').body.target === status.schedules[0].label, 'unschedule posts the label'))

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
const rep24 = fx['/report?provider=anthropic&hours=24']
ok(document.querySelectorAll('[data-table="accounts"] tbody tr').length === rep24.accounts.length, 'report rows match')
ok(document.querySelectorAll('[data-table="bots"] tbody tr').length === rep24.by_profile.filter(r => r.requests).length, 'tokens per profile (bot) listed')
ok(document.querySelectorAll('[data-table="models"] tbody tr').length === rep24.by_model.filter(r => r.requests).length, 'tokens per model listed')
ok(screen.getAllByText('no name (older tracker)').length === 2, 'tokens counted by a tracker older than 1.3.0 are labelled')
ok(screen.getByText('At API list prices') && screen.getByText(/^\$[\d,.]+\+$/), 'API price card with the unpriced marker')
const cells = document.querySelectorAll('.hap-heat > i')
ok(cells.length === 7 * 24, 'hour chart has 7 x 24 cells')
await act(async () => { fireEvent.mouseEnter(cells[6 * 24 + 9]) })
ok(document.querySelector('.hap-heat-read').textContent.includes('09:00-10:00: quota used'), 'hovering a cell shows its numbers')
const srows = document.querySelectorAll('[data-table="sessions"] tbody tr')
ok(srows.length === 2 && srows[0].textContent.includes('Shipping: admin page for limits') && srows[0].textContent.includes('t_5f2e91')
  && srows[0].textContent.includes('$18.90'), 'sessions table: title, task and API price')
ok(screen.getByText('3 more session(s): 0 tokens, $0.00.'), 'sessions table: the rest')
await click(screen.getByText('Tokens', { selector: 'button' }))
ok(document.querySelector('[data-chart="tokens"]'), 'chart switches to tokens')
await click(screen.getByText('7 days'))
await waitFor(() => ok(calls.some(c => c.path === '/report?provider=anthropic&hours=168'), 'report 7 days fetched'))

// activity
await click(screen.getByText('Activity'))
await waitFor(() => ok(document.querySelectorAll('[data-table="activity"] tbody tr').length === 3, 'activity events listed'))
ok(document.querySelector('[data-table="activity"]').textContent.includes('timerbench alice@example.com (91% >= 90%)'), 'activity shows who and what')
await click(screen.getByText('3 days'))
await waitFor(() => ok(calls.some(c => c.path === '/activity?provider=anthropic&hours=72'), 'activity 3 days fetched'))

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
ok(screen.getByText('Daily summary'), 'daily summary setting shown')
await click(screen.getAllByRole('switch')[2])
await waitFor(() => ok(lastPost('/action')?.body.target === 'daily=08:00', 'daily summary switch posts daily=08:00'))
ok(document.querySelector('[data-setting="bots"]'), 'bot alert setting shown')
const botInput = screen.getByLabelText('Dollars per hour for a bot alert')
await act(async () => { fireEvent.change(botInput, { target: { value: '25' } }) })
await act(async () => { fireEvent.blur(botInput) })
await waitFor(() => ok(lastPost('/action')?.body.target === 'bots=25', 'bot alert amount posts bots=25'))
await click(screen.getAllByRole('switch')[3])
await waitFor(() => ok(lastPost('/action')?.body.target === 'bots-off', 'bot alert switch posts bots-off'))
await click(screen.getByText('Send the summary now').closest('button'))
await waitFor(() => ok(lastPost('/action')?.body.target === 'summary', 'send the summary now posts summary'))
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
await click(screen.getByText('Use fill_first', { selector: 'button' }))
ok(screen.getByText('Use fill_first in worker-3?'), 'banner button asks before it changes the strategy')
await click(screen.getAllByText('Use fill_first').filter(b => b.tagName === 'BUTTON').pop())
await waitFor(() => {
  const b = lastPost('/action')?.body
  ok(b.action === 'strategy' && b.target === 'fill_first' && JSON.stringify(b.only) === '["worker-3"]', 'banner fix posts fill_first for that profile only')
})
// the strategy dialog: one Select per profile; changes are grouped per value
await click(screen.getByLabelText('Change the rotation strategy'))
ok(screen.getByText('Rotation strategy') && screen.getByText('New sessions take'), 'header opens the strategy dialog')
const sels = [...document.querySelectorAll('[role="dialog"] select')]
ok(sels.length === rr.length && sels[rr.findIndex(r => r.profile === 'worker-3')].value === 'round_robin', 'one strategy picker per profile, showing the current value')
ok(screen.getByText(/ignore the order balance sets/), 'warning while a profile is not on fill_first')
await click(screen.getByText('fill_first', { selector: 'button' }))
ok(!screen.queryByText(/ignore the order balance sets/) && screen.getByText('Save (1 profile)'), '"every profile" button sets them all; only real changes count')
await act(async () => { fireEvent.change(sels[0], { target: { value: 'random' } }) })
await click(screen.getByText('Save (2 profiles)'))
await waitFor(() => {
  const posts = calls.filter(c => c.method === 'POST' && c.path === '/action').slice(-2).map(c => c.body)
  ok(posts.some(b => b.target === 'random' && JSON.stringify(b.only) === JSON.stringify([rr[0].profile]))
    && posts.some(b => b.target === 'fill_first' && JSON.stringify(b.only) === '["worker-3"]'), 'strategy dialog posts one change per value')
})
fx['/status?provider=anthropic'].rotation_mode = savedMode
cleanup()

// processes that still run an older session tracker -> one info banner with the fixes
const savedTracker = fx['/status?provider=anthropic'].tracker
mount('page')
await screen.findByText('Next session starts on')
ok(!document.querySelector('[data-banner="tracker"]'), 'no tracker banner while every process is current')
cleanup()
fx['/status?provider=anthropic'].tracker = { version: '1.4.0', unnamed_since: null, stale: [
  { kind: 'gateway', pid: null, profiles: ['worker-2'], platforms: ['telegram'], tracker: 'older than 1.4.0', last_seen: 0, fix: 'hermes gateway restart (it serves the Telegram bots and cron jobs)' },
  { kind: 'desktop', pid: 7, profiles: ['default'], platforms: ['desktop'], tracker: '1.3.9', last_seen: 0, fix: 'restart Hermes Desktop' }] }
mount('page')
await waitFor(() => ok(document.querySelector('[data-banner="tracker"]'), 'tracker banner shown'))
const tb = document.querySelector('[data-banner="tracker"]').textContent
ok(/the gateway \(worker-2\), Hermes Desktop \(default\) still run an older session tracker than 1\.4\.0/.test(tb)
  && tb.includes('Fix: hermes gateway restart') && tb.includes('restart Hermes Desktop'), 'tracker banner names the processes and the fixes')
cleanup()
fx['/status?provider=anthropic'].tracker = { version: '1.4.0', stale: [], unnamed_since: Math.floor(Date.now() / 1000) - 600 }
mount('page')
await waitFor(() => ok(/without a bot name until/.test(document.querySelector('[data-banner="tracker"]')?.textContent || ''), 'tracker banner for tokens without a bot name'))
fx['/status?provider=anthropic'].tracker = savedTracker
cleanup()

// a bot that uses far more than usual -> banner with a shortcut to the sessions
const savedAlerts = fx['/status?provider=anthropic'].alerts
fx['/status?provider=anthropic'].alerts = [{ key: 'anthropic:bot:worker-1', since: Math.floor(Date.now() / 1000) - 300, kind: 'bot', profile: 'worker-1',
  text: 'worker-1 is using far more than usual: $20.00 and 100 requests in the last hour (20x its usual hour). Busiest session: Shipping: admin page for limits.' }]
mount('page')
await waitFor(() => ok(document.querySelector('[data-alert="bot"]')?.textContent.includes('worker-1 is using far more than usual'), 'bot alert banner'))
await click(screen.getByText('See sessions', { selector: 'button' }))
await screen.findByText('Busiest hours')
ok(document.querySelector('[data-table="sessions"]'), 'See sessions opens the report')
fx['/status?provider=anthropic'].alerts = savedAlerts
store.view = 'accounts'
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
