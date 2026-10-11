// account-pool: Accounts page for Hermes Desktop.
//
// The desktop half of the account-pool plugin (`hermes account <provider> <action>`).
// It adds Accounts to the sidebar, a status-bar chip and a palette command, and talks
// only to the plugin's own backend (dashboard/plugin_api.py) through ctx.rest.
// Opening the page costs no provider call: usage comes from the history the balance
// timer writes every 5 minutes. Buttons that do call the provider say so.
//
// Plain ESM, no build step: UI is written with createElement, not JSX.

import {
  Badge,
  Button,
  Codicon,
  ConfirmDialog,
  CopyButton,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  ErrorState,
  host,
  Input,
  Loader,
  PALETTE_AREA,
  ROUTES_AREA,
  SegmentedControl,
  SIDEBAR_NAV_AREA,
  STATUSBAR_AREAS,
  StatusDot,
  Switch,
  Tip,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import * as sdk from '@hermes/plugin-sdk'
import { createElement as h, Fragment, useEffect, useState } from 'react'

const ID = 'account-pool'
const ROUTE = '/accounts'
const LIVE_GAP = 120

let rest = null
let storage = null
let openExternal = null

// ── helpers ──────────────────────────────────────────────────────────────────

const get = path => rest(path)
const post = (path, body) => rest(path, { method: 'POST', body, timeoutMs: 180000 })

function errText(error) {
  const msg = String((error && error.message) || error || 'Request failed')
  const m = /^\d{3}:\s*([\s\S]*)$/.exec(msg)
  if (m) {
    try {
      const body = JSON.parse(m[1])
      if (body && body.detail) return String(body.detail)
    } catch {}
    return m[1] || msg
  }
  return msg
}

function notify(kind, message) {
  host.notify({ kind, message })
}

function firstLine(text) {
  return String(text || '').split('\n').find(Boolean) || ''
}

function hhmm(ts) {
  if (!ts) return '–'
  const d = new Date(ts * 1000)
  const opts = { hour: '2-digit', minute: '2-digit' }
  if (Math.abs(ts - Date.now() / 1000) > 20 * 3600) opts.weekday = 'short'
  return d.toLocaleTimeString([], opts)
}

function ago(seconds) {
  if (seconds == null) return ''
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`
  return `${Math.round(seconds / 86400)} d ago`
}

function shortName(label) {
  return String(label || '').split('@')[0]
}

// Tooltip whose label keeps its line breaks. The desktop's tooltip wraps text with
// white-space: normal, which would run "a\nb" into one line.
function MTip({ label, children }) {
  const text = typeof label === 'string' && label.includes('\n') ? h('span', { className: 'hap-ml' }, label) : label
  return h(Tip, { label: text }, children)
}

function fmtTok(n) {
  n = Number(n) || 0
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`
  return String(Math.round(n))
}

// API list price of a token group: "$12.34", "$12.34+" when part of it has no known price.
function fmtCost(t) {
  if (!t || !t.requests || !(t.cost > 0)) return '–'
  return `$${t.cost >= 1000 ? Math.round(t.cost).toLocaleString('en-US') : t.cost.toFixed(2)}${t.unpriced ? '+' : ''}`
}

function tokLines(t) {
  const lines = [
    `input ${fmtTok(t.input)} · output ${fmtTok(t.output)}`,
    `cache read ${fmtTok(t.cache_read)} · cache write ${fmtTok(t.cache_write)}`,
    `${t.requests} request${t.requests === 1 ? '' : 's'}`
  ]
  if (t.cost > 0) lines.push(`${fmtCost(t)} at API list prices${t.unpriced ? ` (${fmtTok(t.unpriced)} tokens have no known price)` : ''}`)
  else if (t.unpriced) lines.push('API price unknown: counted before the tracker recorded the model')
  if (t.model && t.model !== '?') lines.push(`mostly ${t.model}`)
  return lines
}

const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// Day and time, e.g. "Mon 09:00". Not hhmm(): it adds the day itself for times far from now ("Mon Mon 09:00").
function when(ts) {
  if (!ts) return '–'
  const d = new Date(ts * 1000)
  return `${DAY_NAMES[(d.getDay() + 6) % 7]} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
}

// Tokens of one account: last 24 h, with the current usage window in the tip.
function TokensCell({ tokens, window }) {
  if (!tokens || !tokens.day || !tokens.day.requests) return h('span', { className: 'hap-muted' }, '–')
  const lines = [`Last 24 h through Hermes: ${fmtTok(tokens.day.total)}`, ...tokLines(tokens.day)]
  if (tokens.window && tokens.window.requests) {
    lines.push('', `This ${window} window: ${fmtTok(tokens.window.total)} (${tokens.window.requests} requests)`)
  }
  return h(MTip, { label: lines.join('\n') }, h('span', null, fmtTok(tokens.day.total)))
}

// The bot picker for Telegram alerts. The SDK Select follows the Hermes theme;
// a native <select> (older Hermes) is styled as far as Chromium allows.
function Pick({ value, options, disabled, onChange, label }) {
  if (sdk.Select && sdk.SelectTrigger && sdk.SelectContent && sdk.SelectItem && sdk.SelectValue) {
    return h(sdk.Select, { value, disabled, onValueChange: onChange },
      h(sdk.SelectTrigger, { size: 'sm', className: 'hap-select-trigger', 'aria-label': label },
        h(sdk.SelectValue, null)),
      h(sdk.SelectContent, null, options.map(p => h(sdk.SelectItem, { key: p, value: p }, p))))
  }
  return h('select', { className: 'hap-select', value, disabled, 'aria-label': label, onChange: e => onChange(e.target.value) },
    options.map(p => h('option', { key: p, value: p }, p)))
}

function ProfileSelect({ value, profiles, disabled, onChange }) {
  return h(Pick, { value, options: profiles, disabled, onChange, label: 'Profile whose Telegram bot sends the alerts' })
}

const STATE = {
  active: { tone: 'good', text: '' },
  BENCHED: { tone: 'warn', text: 'benched' },
  LIMITED: { tone: 'warn', text: 'rate-limited' },
  COOLING: { tone: 'warn', text: 'cooling down' },
  DEAD: { tone: 'bad', text: 'needs sign-in' },
  PARKED: { tone: 'muted', text: 'parked' }
}

function useInvalidate() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: [ID] })
}

function useNow(active, ms = 5000) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!active) return undefined
    const t = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(t)
  }, [active, ms])
  return now
}

// ── styles (theme variables only) ────────────────────────────────────────────

const CSS = `
.hap-page{display:flex;flex-direction:column;height:100%;overflow:hidden;background:var(--ui-surface-background);color:var(--ui-text-secondary)}
.hap-head{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:8px 16px 6px}
.hap-title{font-size:.875rem;font-weight:600;color:var(--ui-text-primary);margin:0}
.hap-pill{border-radius:999px;background:var(--ui-bg-quaternary);padding:1px 6px;font-size:.625rem;color:var(--ui-text-tertiary);font-variant-numeric:tabular-nums}
.hap-grow{flex:1}
.hap-sub{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:0 16px 8px;font-size:.6875rem;color:var(--ui-text-tertiary)}
.hap-body{flex:1;overflow:auto;padding:2px 16px 28px}
.hap-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;margin:2px 0 6px}
.hap-card{border:1px solid var(--ui-stroke-secondary);border-radius:8px;padding:8px 10px;background:var(--ui-bg-card)}
.hap-card-k{font-size:.6875rem;color:var(--ui-text-tertiary)}
.hap-card-v{font-size:1.05rem;font-weight:600;margin-top:2px;color:var(--ui-text-primary);font-variant-numeric:tabular-nums}
.hap-card-s{font-size:.6875rem;color:var(--ui-text-secondary);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hap-section{display:flex;align-items:center;gap:6px;font-size:.6875rem;font-weight:600;color:var(--ui-text-tertiary);text-transform:uppercase;letter-spacing:.04em;margin:16px 0 4px}
.hap-table{width:100%;border-collapse:collapse;font-size:.75rem}
.hap-table th{text-align:left;font-weight:500;color:var(--ui-text-tertiary);font-size:.6875rem;padding:4px 8px;border-bottom:1px solid var(--ui-stroke-secondary);white-space:nowrap}
.hap-table td{padding:6px 8px;border-bottom:1px solid var(--ui-stroke-tertiary);vertical-align:middle}
.hap-table tr:hover td{background:var(--ui-row-hover-background)}
.hap-num{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.hap-acc{display:flex;align-items:center;gap:7px;color:var(--ui-text-primary);white-space:nowrap}
.hap-usage{display:flex;align-items:center;gap:8px;white-space:nowrap}
.hap-bar{display:inline-block;width:96px;height:6px;border-radius:3px;background:var(--ui-bg-quaternary);overflow:hidden;flex:none}
.hap-bar>i{display:block;height:100%;background:var(--ui-accent)}
.hap-bar.warn>i{background:var(--ui-orange)}
.hap-bar.bad>i{background:var(--ui-red)}
.hap-bar.muted>i{background:var(--ui-text-quaternary)}
.hap-pct{min-width:34px;text-align:right;font-variant-numeric:tabular-nums;color:var(--ui-text-primary)}
.hap-tag{font-size:.625rem;color:var(--ui-text-tertiary);white-space:nowrap}
.hap-spark polyline{fill:none;stroke:var(--ui-text-tertiary);stroke-width:1.2}
.hap-chip{display:inline-block;border:1px solid var(--ui-stroke-secondary);border-radius:999px;padding:0 6px;font-size:.625rem;margin:1px 3px 1px 0;color:var(--ui-text-secondary);white-space:nowrap}
.hap-actions{display:flex;justify-content:flex-end;gap:2px;opacity:.6}
.hap-table tr:hover .hap-actions{opacity:1}
.hap-banner{display:flex;gap:8px;align-items:flex-start;border:1px solid color-mix(in srgb,var(--ui-orange) 45%,transparent);background:color-mix(in srgb,var(--ui-orange) 9%,transparent);border-radius:8px;padding:8px 10px;margin:4px 0 8px;font-size:.75rem;color:var(--ui-text-primary)}
.hap-pre{white-space:pre-wrap;word-break:break-word;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.6875rem;line-height:1.45;background:var(--ui-bg-quaternary);border-radius:6px;padding:8px 10px;max-height:340px;overflow:auto;color:var(--ui-text-secondary);margin:0}
.hap-muted{color:var(--ui-text-tertiary)}
.hap-small{font-size:.6875rem}
.hap-field{display:flex;flex-direction:column;gap:6px;margin-top:10px;font-size:.75rem}
.hap-steps{margin:0;padding-left:18px;font-size:.75rem;line-height:1.5;color:var(--ui-text-secondary)}
.hap-steps b{color:var(--ui-text-primary);font-weight:600}
.hap-code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:1.3rem;letter-spacing:.14em;font-weight:600;color:var(--ui-text-primary)}
.hap-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.hap-link{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.625rem;color:var(--ui-text-tertiary);word-break:break-all;max-height:3.2em;overflow:hidden}
.hap-check{display:flex;gap:9px;align-items:baseline;padding:7px 0;border-bottom:1px solid var(--ui-stroke-tertiary);font-size:.75rem;color:var(--ui-text-primary)}
.hap-empty{display:flex;flex-direction:column;align-items:center;gap:10px;padding:48px 16px;text-align:center;font-size:.75rem;color:var(--ui-text-tertiary)}
.hap-setting{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--ui-stroke-tertiary);font-size:.75rem}
.hap-setting-t{color:var(--ui-text-primary);font-weight:500}
.hap-select{background:var(--ui-bg-input);color:var(--ui-text-primary);border:1px solid var(--ui-stroke-secondary);border-radius:6px;padding:3px 6px;font-size:.75rem;color-scheme:light dark}
.hap-select option{background:var(--ui-bg-elevated,var(--ui-bg-card));color:var(--ui-text-primary)}
.hap-select-trigger{width:auto;min-width:170px}
.hap-ml{white-space:pre-line;display:block}
.hap-mode{border-bottom:1px dotted currentColor;cursor:help}
.hap-ellipsis{display:inline-block;max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:bottom}
.hap-modebtn{display:inline-flex;align-items:center;gap:4px;background:none;border:0;border-bottom:1px dotted currentColor;padding:0;font:inherit;color:inherit;cursor:pointer}
.hap-modebtn:hover{color:var(--ui-text-primary)}
.hap-sharebar{display:inline-block;width:80px;height:5px;border-radius:3px;background:var(--ui-bg-quaternary);overflow:hidden;vertical-align:middle;margin-right:6px}
.hap-sharebar>i{display:block;height:100%;background:var(--ui-accent)}
.hap-heat{display:grid;grid-template-columns:76px repeat(24,minmax(9px,1fr));gap:2px;align-items:center;max-width:760px;margin-top:4px}
.hap-heat>i{display:block;height:16px;border-radius:3px;background:var(--ui-bg-quaternary)}
.hap-heat>i.on{outline:1px solid var(--ui-text-primary)}
.hap-heat-l{font-size:.625rem;color:var(--ui-text-tertiary);white-space:nowrap;font-variant-numeric:tabular-nums}
.hap-heat-read{min-height:1.4em;margin-top:6px}
.hap-days{display:flex;gap:4px;flex-wrap:wrap}
.hap-time{width:76px}
`

// ── small pieces ─────────────────────────────────────────────────────────────

function Spark({ points, now }) {
  if (!points || points.length < 2) return null
  const w = 60
  const ht = 16
  const t0 = now - 5 * 3600
  const pts = points
    .map(([t, p]) => `${(((t - t0) / (5 * 3600)) * w).toFixed(1)},${(ht - 1 - (Math.min(p, 100) / 100) * (ht - 2)).toFixed(1)}`)
    .join(' ')
  return h('svg', { className: 'hap-spark', width: w, height: ht, viewBox: `0 0 ${w} ${ht}`, 'aria-hidden': true },
    h('polyline', { points: pts }))
}

function UsageCell({ usage, parked, now }) {
  if (!usage) return h('span', { className: 'hap-tag' }, 'no data yet')
  if (usage.pct == null) {
    return h(MTip, { label: `The usage window reset after the last reading (${ago(usage.age)}). Live usage or the next timer run shows the new number.` },
      h('span', { className: 'hap-tag' }, 'window reset since'))
  }
  const pct = usage.pct
  const tone = parked ? 'muted' : pct >= 90 ? 'bad' : pct >= 70 ? 'warn' : ''
  const tag = usage.source === 'live' ? `live, ${ago(usage.age)}` : usage.age > 900 ? ago(usage.age) : ''
  return h('div', { className: 'hap-usage' },
    h('span', { className: `hap-bar ${tone}` }, h('i', { style: { width: `${Math.min(100, Math.max(2, pct))}%` } })),
    h('span', { className: 'hap-pct' }, `${Math.round(pct)}%`),
    usage.detail && !usage.detail.startsWith('last known') ? h('span', { className: 'hap-tag' }, usage.detail) : null,
    tag ? h('span', { className: 'hap-tag' }, tag) : null)
}

function IconButton({ icon, label, onClick, disabled }) {
  return h(MTip, { label },
    h(Button, { 'aria-label': label, disabled, onClick, size: 'icon-xs', variant: 'ghost' },
      h(Codicon, { name: icon, size: '0.85rem' })))
}

function Card({ k, v, s, s2 }) {
  return h('div', { className: 'hap-card' },
    h('div', { className: 'hap-card-k' }, k),
    h('div', { className: 'hap-card-v' }, v),
    s ? h('div', { className: 'hap-card-s', title: typeof s === 'string' ? s : undefined }, s) : null,
    s2 ? h('div', { className: 'hap-card-s', title: s2 }, s2) : null)
}

function Sessions({ sessions }) {
  if (!sessions || !sessions.length) return h('span', { className: 'hap-tag' }, 'idle')
  const byProfile = {}
  for (const s of sessions) (byProfile[s.profile] ||= []).push(s)
  return h(Fragment, null, Object.entries(byProfile).map(([profile, list]) =>
    h(MTip, {
      key: profile,
      label: list.map(s => `${s.session} · ${s.platform || '-'} · ${s.model || '?'}\n`
        + `  on this account ${s.since ? `since ${hhmm(s.since)}` : '(start unknown)'}`
        + (s.moved_from ? `, moved from ${shortName(s.moved_from)}` : '')
        + ` · last call ${ago(Date.now() / 1000 - s.last_seen)}`).join('\n')
    }, h('span', { className: 'hap-chip' }, list.length > 1 ? `${profile} ×${list.length}` : profile))))
}

// ── dialogs ──────────────────────────────────────────────────────────────────

// Hermes' rotation strategy per profile (credential_pool_strategies.<provider>). Hermes owns the
// setting; the backend writes it with Hermes' own `config set`, like the CLI's `strategy` action.
const STRATEGIES = ['fill_first', 'round_robin', 'least_used', 'random']

function StrategyDialog({ provider, mode, onClose, onDone }) {
  const [pick, setPick] = useState(() => Object.fromEntries(mode.profiles.map(r => [r.profile, r.strategy])))
  const values = Object.values(pick)
  const all = values.every(v => v === values[0]) ? values[0] : null
  const changed = mode.profiles.filter(r => pick[r.profile] !== r.strategy)
  const risky = values.some(v => v !== 'fill_first')
  return h(ConfirmDialog, {
    open: true,
    onClose,
    title: 'Rotation strategy',
    description: `Which account a new session takes, per profile. This is Hermes' own setting (credential_pool_strategies.${provider} in each profile's config.yaml), saved with Hermes' config writer. New sessions use it at once; running sessions keep their account.`,
    confirmLabel: changed.length ? `Save (${changed.length} profile${changed.length === 1 ? '' : 's'})` : 'Close',
    busyLabel: 'Saving…',
    onConfirm: async () => {
      if (!changed.length) return onClose()
      const groups = {}
      changed.forEach(r => { (groups[pick[r.profile]] = groups[pick[r.profile]] || []).push(r.profile) })
      const out = []
      for (const [value, only] of Object.entries(groups)) {
        const r = await post('/action', { action: 'strategy', provider, target: value, only })
        if (!r.ok) throw new Error(r.output || 'Saving the strategy failed')
        out.push(firstLine(r.output))
      }
      onDone(out.join(' '))
    }
  },
  h('div', { className: 'hap-field' },
    h('span', { className: 'hap-muted' }, 'Every profile'),
    h('div', { className: 'hap-days' }, STRATEGIES.map(s => h(Button, {
      key: s, size: 'sm', variant: all === s ? 'default' : 'outline', 'aria-pressed': all === s,
      onClick: () => setPick(Object.fromEntries(mode.profiles.map(r => [r.profile, s])))
    }, s)))),
  h('table', { className: 'hap-table' },
    h('thead', null, h('tr', null, h('th', null, 'Profile'), h('th', null, 'Now'), h('th', null, 'New sessions take'))),
    h('tbody', null, mode.profiles.map(r => h('tr', { key: r.profile },
      h('td', null, r.profile),
      h('td', { className: 'hap-muted' }, r.strategy),
      h('td', null, h(Pick, {
        value: pick[r.profile], options: STRATEGIES, label: `Rotation strategy of ${r.profile}`,
        onChange: v => setPick({ ...pick, [r.profile]: v })
      })))))),
  h('div', { className: 'hap-small hap-muted hap-ml', style: { marginTop: 8 } }, Object.values(MODES).join('\n')),
  risky
    ? h('div', { className: 'hap-banner', style: { marginTop: 8 } }, h(Codicon, { name: 'warning' }),
      h('span', null, 'round_robin, least_used and random ignore the order balance sets: a new session can start on a nearly full account and wait up to 600 s on a rate limit. Balance is built for fill_first.'))
    : null)
}

function ResultDialog({ title, text, onClose }) {
  return h(Dialog, { open: true, onOpenChange: open => !open && onClose() },
    h(DialogContent, { style: { maxWidth: 640 } },
      h(DialogHeader, null, h(DialogTitle, null, title)),
      h('pre', { className: 'hap-pre' }, text || '(no output)'),
      h(DialogFooter, null, h(Button, { onClick: onClose, size: 'sm' }, 'Close'))))
}

function ParkDialog({ provider, row, onClose, onDone }) {
  const [mode, setMode] = useState('open')
  const [custom, setCustom] = useState('17:00')
  const until = mode === 'open' ? null : mode === 'custom' ? custom.trim() : mode === '1h' ? '+1h' : '+2h'
  return h(ConfirmDialog, {
    open: true,
    onClose,
    title: `Park ${row.label}?`,
    description: 'Hermes stops using this account. Its login is kept, so Unpark brings it back without a new sign-in.',
    confirmLabel: 'Park',
    busyLabel: 'Parking…',
    onConfirm: async () => {
      const r = await post('/action', { action: 'park', provider, target: row.id, until })
      if (!r.ok) throw new Error(r.output || 'Park failed')
      onDone(firstLine(r.output))
    }
  }, h('div', { className: 'hap-field' },
    h('span', { className: 'hap-muted' }, 'Bring it back'),
    h(SegmentedControl, {
      options: [
        { id: 'open', label: 'When I unpark' },
        { id: '1h', label: 'In 1 hour' },
        { id: '2h', label: 'In 2 hours' },
        { id: 'custom', label: 'At…' }
      ],
      value: mode,
      onChange: setMode
    }),
    mode === 'custom'
      ? h(Input, { value: custom, onChange: e => setCustom(e.target.value), placeholder: '17:00, +90m or 2026-10-11 08:00' })
      : null,
    mode !== 'open'
      ? h('span', { className: 'hap-small hap-muted' }, 'The balance timer returns it on its first run after that time.')
      : null))
}

// Park an account every week at the same hours; the balance timer applies it.
function ScheduleDialog({ provider, row, current, onClose, onDone }) {
  const [days, setDays] = useState(current ? current.days : [0, 1, 2, 3, 4])
  const [from, setFrom] = useState(current ? current.from : '09:00')
  const [to, setTo] = useState(current ? current.to : '17:00')
  const time = /^([01]?\d|2[0-3])[:.][0-5]\d$/
  const valid = days.length && time.test(from.trim()) && time.test(to.trim()) && from.trim() !== to.trim()
  const toggle = d => setDays(days.includes(d) ? days.filter(x => x !== d) : [...days, d].sort())
  return h(ConfirmDialog, {
    open: true,
    onClose,
    title: `Park ${row.label} on a schedule`,
    description: 'The balance timer parks it when a window starts and brings it back when it ends. Unparking it by hand inside a window keeps it in rotation until the next window.',
    confirmLabel: current ? 'Save schedule' : 'Add schedule',
    busyLabel: 'Saving…',
    onConfirm: async () => {
      if (!valid) throw new Error('Pick at least one day and two different times (HH:MM).')
      const every = `${days.map(d => DAY_NAMES[d].toLowerCase()).join(',')} ${from.trim()}-${to.trim()}`
      const r = await post('/action', { action: 'schedule', provider, target: row.id, every })
      if (!r.ok) throw new Error(r.output || 'Saving the schedule failed')
      onDone(firstLine(r.output))
    }
  },
  h('div', { className: 'hap-field' },
    h('span', { className: 'hap-muted' }, 'Days'),
    h('div', { className: 'hap-days' }, DAY_NAMES.map((name, d) => h(Button, {
      key: name, size: 'sm', variant: days.includes(d) ? 'default' : 'outline', 'aria-pressed': days.includes(d), onClick: () => toggle(d)
    }, name)))),
  h('div', { className: 'hap-field' },
    h('span', { className: 'hap-muted' }, 'Parked from … to'),
    h('div', { className: 'hap-row' },
      h(Input, { className: 'hap-time', value: from, onChange: e => setFrom(e.target.value), placeholder: '09:00', 'aria-label': 'Parked from' }),
      h('span', { className: 'hap-muted' }, 'to'),
      h(Input, { className: 'hap-time', value: to, onChange: e => setTo(e.target.value), placeholder: '17:00', 'aria-label': 'Parked until' }),
      h('span', { className: 'hap-small hap-muted' }, 'local time; an end before the start runs past midnight'))),
  valid ? null : h('span', { className: 'hap-small', style: { color: 'var(--ui-orange)' } }, 'Pick at least one day and two different times (HH:MM).'))
}

function SignInDialog({ provider, mode, row, verify, onClose }) {
  const invalidate = useInvalidate()
  const [email, setEmail] = useState('')
  const [flow, setFlow] = useState(null)
  const [code, setCode] = useState('')
  const [phase, setPhase] = useState('intro')      // intro | starting | code | device | finishing | done | rejected
  const [error, setError] = useState('')
  const [output, setOutput] = useState('')
  const label = mode === 'add' ? email.trim() : row.label
  const finished = phase === 'done' || phase === 'rejected'

  const handle = r => {
    if (r.status === 'pending') return
    if (r.status === 'error') {
      setError(r.message)
      setPhase(flow && flow.kind === 'device' ? 'device' : 'code')
      return
    }
    setOutput(r.output || '')
    setPhase(r.status === 'done' ? 'done' : 'rejected')
    invalidate()
  }

  const start = async () => {
    setError('')
    setPhase('starting')
    try {
      const r = await post('/signin/start', { provider, mode, target: mode === 'add' ? label : row.id })
      setFlow(r)
      setPhase(r.kind === 'device' ? 'device' : 'code')
    } catch (e) {
      setError(errText(e))
      setPhase('intro')
    }
  }

  const finish = async () => {
    setError('')
    setPhase('finishing')
    try {
      handle(await post('/signin/step', { flow: flow.flow, code: code.trim() }))
    } catch (e) {
      setError(errText(e))
      setPhase('code')
    }
  }

  useEffect(() => {
    if (phase !== 'device' || !flow) return undefined
    let stop = false
    const t = setInterval(async () => {
      try {
        const r = await post('/signin/step', { flow: flow.flow })
        if (!stop) handle(r)
      } catch (e) {
        if (!stop) setError(errText(e))
      }
    }, 4000)
    return () => {
      stop = true
      clearInterval(t)
    }
  }, [phase, flow])

  const close = () => {
    if (flow && !finished) post('/signin/cancel', { flow: flow.flow }).catch(() => {})
    onClose()
  }

  const title = mode === 'add' ? 'Add account' : `Sign in again: ${row.label}`
  const steps = flow && flow.kind === 'device'
    ? h('ol', { className: 'hap-steps' },
      h('li', null, 'Open the page below in a browser that is signed in as ', h('b', null, label),
        ' (its own browser profile, or a private window).'),
      h('li', null, 'Enter this code:'),
      h('li', null, 'This window finishes by itself once you confirm.'))
    : h('ol', { className: 'hap-steps' },
      h('li', null, 'Open the sign-in link in a browser that is signed in as ', h('b', null, label || 'this account'),
        ': its own browser profile, or a private window. Copy the link for that.'),
      h('li', null, 'Check that the page says ', h('b', null, `Logged in as ${label || '…'}`),
        '. "Sign in again to continue" is normal when that browser login is old.'),
      h('li', null, 'Authorize, copy the code and paste it here.'))

  let body
  if (phase === 'intro' || phase === 'starting') {
    body = h(Fragment, null,
      mode === 'add'
        ? h('div', { className: 'hap-field' },
          h('span', null, 'Account email'),
          h(Input, {
            autoFocus: true, value: email, placeholder: 'name@example.com',
            onChange: e => setEmail(e.target.value),
            onKeyDown: e => e.key === 'Enter' && label && start()
          }))
        : null,
      h('div', { className: 'hap-field' }, steps),
      h('p', { className: 'hap-small hap-muted', style: { marginTop: 10 } },
        verify
          ? (mode === 'add'
            ? 'The account is kept only if the sign-in really is this email and not one already in the pool.'
            : 'The old login is replaced only if the new sign-in really is this account. Its place in the order stays.')
          : 'This provider cannot report the account email, so the sign-in is not verified.'))
  } else if (phase === 'code' || phase === 'finishing') {
    body = h(Fragment, null,
      h('div', { className: 'hap-field' }, steps),
      h('div', { className: 'hap-field' },
        h('div', { className: 'hap-row' },
          h(CopyButton, { text: flow.url, label: 'Copy link', showLabel: true, buttonSize: 'sm', buttonVariant: 'outline' }),
          h(Button, { size: 'sm', variant: 'ghost', onClick: () => openExternal(flow.url) },
            h(Codicon, { name: 'link-external', size: '0.8rem' }), 'Open in default browser')),
        h('div', { className: 'hap-link' }, flow.url)),
      h('div', { className: 'hap-field' },
        h('span', null, 'Code'),
        h(Input, {
          autoFocus: true, value: code, placeholder: 'Paste the whole code, including the part after #',
          onChange: e => setCode(e.target.value),
          onKeyDown: e => e.key === 'Enter' && code.trim() && finish()
        })))
  } else if (phase === 'device') {
    body = h(Fragment, null,
      h('div', { className: 'hap-field' }, steps),
      h('div', { className: 'hap-field' },
        h('div', { className: 'hap-row' },
          h('span', { className: 'hap-code' }, flow.user_code),
          h(CopyButton, { text: flow.user_code, appearance: 'icon' })),
        h('div', { className: 'hap-row' },
          h(CopyButton, { text: flow.url, label: 'Copy page link', showLabel: true, buttonSize: 'sm', buttonVariant: 'outline' }),
          h(Button, { size: 'sm', variant: 'ghost', onClick: () => openExternal(flow.url) },
            h(Codicon, { name: 'link-external', size: '0.8rem' }), 'Open in default browser')),
        h('div', { className: 'hap-row hap-muted' }, h(Loader, { type: 'lemniscate-bloom' }), 'Waiting for you to confirm…')))
  } else {
    body = h(Fragment, null,
      h('div', { className: 'hap-row', style: { marginBottom: 8 } },
        h(StatusDot, { tone: phase === 'done' ? 'good' : 'bad' }),
        h('span', null, phase === 'done' ? 'Done.' : 'The sign-in was not kept.')),
      h('pre', { className: 'hap-pre' }, output || '(no output)'))
  }

  const footer = finished
    ? h(Button, { size: 'sm', onClick: onClose }, 'Close')
    : h(Fragment, null,
      h(Button, { size: 'sm', variant: 'ghost', onClick: close }, 'Cancel'),
      phase === 'intro' || phase === 'starting'
        ? h(Button, { size: 'sm', disabled: phase === 'starting' || !label, onClick: start },
          phase === 'starting' ? 'Starting…' : 'Start sign-in')
        : phase === 'code' || phase === 'finishing'
          ? h(Button, { size: 'sm', disabled: phase === 'finishing' || !code.trim(), onClick: finish },
            phase === 'finishing' ? 'Checking…' : 'Finish')
          : null)

  return h(Dialog, { open: true, onOpenChange: open => !open && close() },
    h(DialogContent, { style: { maxWidth: 560 } },
      h(DialogHeader, null,
        h(DialogTitle, null, title),
        h(DialogDescription, null, provider)),
      body,
      error ? h('div', { className: 'hap-banner', style: { marginTop: 10 } }, h(Codicon, { name: 'warning' }), h('span', null, error)) : null,
      h(DialogFooter, null, footer)))
}

// ── views ────────────────────────────────────────────────────────────────────

function SchedChip({ s }) {
  if (!s) return null
  return h(MTip, { label: `Parked ${s.every} by the balance timer.` + (s.next ? `\nNext window: ${when(s.next)}` : '') },
    h('span', { className: 'hap-chip' }, h(Codicon, { name: 'calendar', size: '0.65rem' }), ` ${s.every}`))
}

function AccountsView({ data, provider, openDialog }) {
  const now = data.now
  const schedules = data.schedules || []
  const schedOf = label => schedules.find(s => s.label.toLowerCase() === String(label).toLowerCase())
  const active = data.rotation.filter(r => r.state === 'active')
  const next = active[0]
  const known = data.rotation.filter(r => r.usage && r.usage.pct != null)
  const top = known.reduce((a, r) => (!a || r.usage.pct > a.usage.pct ? r : a), null)

  if (!data.rotation.length && !data.parked.length) {
    return h('div', { className: 'hap-empty' },
      h(Codicon, { name: 'account', size: '1.4rem' }),
      h('div', null, `No ${provider} accounts yet.`),
      data.web_signin
        ? h(Button, { size: 'sm', onClick: () => openDialog({ type: 'add' }) }, h(Codicon, { name: 'add', size: '0.8rem' }), 'Add account')
        : h('code', null, `hermes account ${provider} add <email>`),
      h('div', { className: 'hap-small' }, 'Using this provider in a profile is a Hermes setting; this page only manages its accounts.'))
  }

  return h(Fragment, null,
    h('div', { className: 'hap-cards' },
      h(Card, { k: 'In rotation', v: `${active.length} / ${data.rotation.length}`, s: active.length === data.rotation.length ? 'all usable' : `${data.rotation.length - active.length} benched or blocked` }),
      h(Card, { k: 'Parked', v: String(data.parked.length), s: data.parked.length ? data.parked.map(p => shortName(p.label)).join(', ') : 'none' }),
      h(Card, {
        k: 'Next session starts on',
        v: next ? (next.usage && next.usage.pct != null ? `${Math.round(next.usage.pct)}%` : '–') : '–',
        s: next ? next.label : 'no usable account'
      }),
      h(Card, {
        k: `Sessions, last ${data.who_minutes} min`,
        v: String(data.sessions_active),
        s: top ? `highest: ${shortName(top.label)} ${Math.round(top.usage.pct)}%` : ''
      }),
      h(Card, {
        k: 'Tokens, last 24 h',
        v: data.tokens && data.tokens.day.requests ? fmtTok(data.tokens.day.total) : '–',
        s: data.tokens && data.tokens.day.requests
          ? (data.tokens.day.cost > 0 ? `${fmtCost(data.tokens.day)} at API prices` : `${fmtTok(data.tokens.day.output)} output`)
          : data.tokens && data.tokens.since ? 'none in 24 h' : 'counting starts with the next request',
        s2: data.tokens && data.tokens.day.requests ? `${data.tokens.day.requests} requests` : null
      }),
      data.forecast && data.forecast.status !== 'no-data'
        ? h(MTip, { label: `${data.forecast.text}\n\nFrom the balance timer's history: the pace is what the pool used in the last hour. It assumes accounts of the same plan and the least-used account taking the load, as balance does.` },
          h('div', { 'data-card': 'forecast' }, h(Card, {
            k: `Every account ≥ ${data.forecast.threshold}%`,
            v: data.forecast.full_at ? `~${hhmm(data.forecast.full_at)}` : data.forecast.status === 'idle' ? 'idle' : `> ${data.forecast.horizon_h} h`,
            s: data.forecast.full_at ? `back ~${hhmm(data.forecast.back_at)} · pace ${Math.round(data.forecast.pace)}%/h`
              : data.forecast.status === 'idle' ? 'no load in the last hour' : `at the last hour's pace, ${Math.round(data.forecast.pace)}%/h`
          })))
        : null),

    h('div', { className: 'hap-section' }, 'In rotation',
      h('span', { className: 'hap-pill' }, data.rotation.length),
      h('span', { className: 'hap-grow' }),
      h('span', { className: 'hap-tag', style: { textTransform: 'none', letterSpacing: 0, fontWeight: 400 } },
        h(MTip, {
          label: 'Hermes starts each new session on the first usable account (fill_first), and balance moves the least-used account to the top every 5 minutes.\n\n'
            + 'A running session stays on its account until that account hits a limit, then Hermes moves it to the next one. '
            + 'Moving it earlier would throw away its prompt cache, and resending the context costs more quota than it saves.\n\n'
            + '/reset, a new chat or a restart picks the account again.'
        }, h('span', { className: 'hap-mode' }, 'New sessions start on #1. Running sessions keep their account until it hits a limit.')))),
    h('table', { className: 'hap-table' },
      h('thead', null, h('tr', null,
        h('th', { style: { width: 28 } }, '#'), h('th', null, 'Account'),
        h('th', null, data.has_usage ? `${data.window} usage` : 'Usage'), h('th', null, ''),
        h('th', null, 'Resets'),
        h('th', { className: 'hap-num' }, h(MTip, { label: 'Tokens Hermes sent and received on this account in the last 24 hours (input, output and cache). Other apps signed in to the same account are not counted.' }, h('span', null, 'Tokens, 24 h'))),
        h('th', null, h(MTip, { label: `Profiles with a session on this account in the last ${data.who_minutes} minutes. Hover a profile for its sessions.` }, h('span', null, 'Used by'))),
        h('th', { style: { width: 96 } }, ''))),
      h('tbody', null, data.rotation.map(r => {
        const st = STATE[r.state] || STATE.active
        return h('tr', { key: r.id },
          h('td', { className: 'hap-num hap-muted' }, r.pos),
          h('td', null, h('div', { className: 'hap-acc' },
            h(StatusDot, { tone: st.tone }),
            h('span', null, r.label),
            st.text ? h(MTip, { label: (r.problems || []).join('\n') || st.text },
              h(Badge, { variant: r.state === 'DEAD' ? 'destructive' : 'warn' }, st.text)) : null,
            h(SchedChip, { s: schedOf(r.label) }))),
          h('td', null, h(UsageCell, { usage: r.usage, now })),
          h('td', null, h(Spark, { points: r.spark, now })),
          h('td', { className: 'hap-num' },
            r.back_at ? h(MTip, { label: 'Back in rotation at this time' }, h('span', null, `back ${hhmm(r.back_at)}`))
              : hhmm(r.usage && r.usage.pct != null ? r.usage.reset : null)),
          h('td', { className: 'hap-num' }, h(TokensCell, { tokens: r.tokens, window: data.window })),
          h('td', null, h(Sessions, { sessions: r.sessions })),
          h('td', null, h('div', { className: 'hap-actions' },
            r.auth === 'oauth' && data.web_signin
              ? h(IconButton, { icon: 'key', label: 'Sign in again', onClick: () => openDialog({ type: 'relogin', row: r }) })
              : null,
            h(IconButton, { icon: 'debug-pause', label: 'Park (take out of rotation)', onClick: () => openDialog({ type: 'park', row: r }) }),
            h(IconButton, { icon: 'calendar', label: 'Park on a schedule', onClick: () => openDialog({ type: 'schedule', row: r, current: schedOf(r.label) }) }),
            h(IconButton, { icon: 'trash', label: 'Remove', onClick: () => openDialog({ type: 'remove', row: r }) }))))
      }))),

    data.parked.length
      ? h(Fragment, null,
        h('div', { className: 'hap-section' }, 'Parked', h('span', { className: 'hap-pill' }, data.parked.length),
          h('span', { className: 'hap-grow' }),
          h('span', { className: 'hap-tag', style: { textTransform: 'none', letterSpacing: 0, fontWeight: 400 } },
            'Not used by Hermes. The login is kept.')),
        h('table', { className: 'hap-table' },
          h('thead', null, h('tr', null,
            h('th', { style: { width: 28 } }, ''), h('th', null, 'Account'), h('th', null, 'Last known usage'),
            h('th', null, ''), h('th', null, 'Parked'), h('th', { className: 'hap-num' }, 'Tokens, 24 h'), h('th', null, 'Returns'), h('th', { style: { width: 96 } }, ''))),
          h('tbody', null, data.parked.map(p => h('tr', { key: p.id },
            h('td', null, ''),
            h('td', null, h('div', { className: 'hap-acc' },
              h(StatusDot, { tone: p.dead ? 'bad' : 'muted' }), h('span', null, p.label),
              p.dead ? h(MTip, { label: 'Its sign-in expired while parked: remove it, then add it again.' },
                h(Badge, { variant: 'destructive' }, 'sign-in expired')) : null,
              h(SchedChip, { s: schedOf(p.label) }))),
            h('td', null, h(UsageCell, { usage: p.usage, parked: true, now })),
            h('td', null, h(Spark, { points: p.spark, now })),
            h('td', { className: 'hap-num' }, hhmm(p.since)),
            h('td', { className: 'hap-num' }, h(TokensCell, { tokens: p.tokens, window: data.window })),
            h('td', { className: 'hap-num' }, p.until
              ? (p.by === 'schedule' ? h(MTip, { label: 'Parked by its schedule; returns when the window ends.' }, h('span', null, `${hhmm(p.until)} (schedule)`)) : hhmm(p.until))
              : h('span', { className: 'hap-tag' }, 'when unparked')),
            h('td', null, h('div', { className: 'hap-actions' },
              h(IconButton, { icon: 'debug-start', label: 'Unpark (back into rotation)', onClick: () => openDialog({ type: 'unpark', row: p }) }),
              h(IconButton, { icon: 'calendar', label: 'Park on a schedule', onClick: () => openDialog({ type: 'schedule', row: p, current: schedOf(p.label) }) }),
              h(IconButton, { icon: 'trash', label: 'Remove', onClick: () => openDialog({ type: 'remove', row: p, parked: true }) }))))))))
      : null,

    schedules.length
      ? h(Fragment, null,
        h('div', { className: 'hap-section' }, 'Park schedules', h('span', { className: 'hap-pill' }, schedules.length),
          h('span', { className: 'hap-grow' }),
          h('span', { className: 'hap-tag', style: { textTransform: 'none', letterSpacing: 0, fontWeight: 400 } },
            'Applied by the balance timer: parked when a window starts, back when it ends.')),
        h('table', { className: 'hap-table', 'data-table': 'schedules' },
          h('thead', null, h('tr', null, h('th', null, 'Account'), h('th', null, 'Parked'), h('th', null, 'Now'), h('th', { style: { width: 96 } }, ''))),
          h('tbody', null, schedules.map(sc => h('tr', { key: sc.label },
            h('td', { style: { color: 'var(--ui-text-primary)' } }, sc.label),
            h('td', null, sc.every),
            h('td', null, !sc.found ? h('span', { style: { color: 'var(--ui-orange)' } }, 'not in the pool')
              : sc.in_window && sc.parked ? (sc.until ? `parked, back ${hhmm(sc.until)}` : 'parked by hand')
                : sc.in_window ? h(MTip, { label: 'Unparked by hand inside the window, or parking was refused (the last working account is never parked). The next window parks it again.' }, h('span', null, 'in rotation'))
                  : h('span', { className: 'hap-muted' }, `next ${when(sc.next)}`)),
            h('td', null, h('div', { className: 'hap-actions' },
              sc.found ? h(IconButton, { icon: 'edit', label: 'Change schedule', onClick: () => openDialog({ type: 'schedule', row: { label: sc.label, id: sc.id || sc.label }, current: sc }) }) : null,
              h(IconButton, { icon: 'close', label: 'Remove schedule', onClick: () => openDialog({ type: 'unschedule', row: sc }) }))))))))
      : null,

    data.other_sessions.length
      ? h('p', { className: 'hap-small hap-muted', style: { marginTop: 12 } },
        `${data.other_sessions.length} session(s) ran on accounts that are no longer in the pool.`)
      : null)
}

// Load per local hour for the last 7 days: quota used (from the balance timer) or tokens (from the tracker).
function HourChart({ chart }) {
  const [metric, setMetric] = useState(chart.has_usage ? 'used' : 'tokens')
  const [hover, setHover] = useState(null)
  const values = chart.days.flatMap(d => d[metric])
  const top = Math.max(0, ...values)
  const fmt = v => metric === 'tokens' ? `${fmtTok(v)} tokens` : `${Math.round(v)} (${chart.window}-window %)`
  const cell = (d, hr) => {
    const v = d[metric][hr]
    const on = hover && hover.d === d && hover.hr === hr
    return h('i', {
      key: `${d.date}-${hr}`,
      className: on ? 'on' : undefined,
      style: v ? { background: `color-mix(in srgb, var(--ui-accent) ${Math.round(20 + 80 * v / (top || 1))}%, transparent)` } : undefined,
      onMouseEnter: () => setHover({ d, hr }),
      'data-v': v
    })
  }
  let read = `Darker = more. Busiest hour: ${top ? fmt(top) : 'none yet'}. Hover a cell for its numbers.`
  if (hover) {
    const { d, hr } = hover
    read = `${d.dow} ${d.date}, ${String(hr).padStart(2, '0')}:00-${String((hr + 1) % 24).padStart(2, '0')}:00: `
      + (chart.has_usage ? `quota used ${Math.round(d.used[hr])}, ` : '')
      + `${fmtTok(d.tokens[hr])} tokens in ${d.requests[hr]} request${d.requests[hr] === 1 ? '' : 's'}`
  }
  return h(Fragment, null,
    h('div', { className: 'hap-section' }, 'Load by hour, last 7 days',
      h('span', { className: 'hap-grow' }),
      chart.has_usage
        ? h(SegmentedControl, { options: [{ id: 'used', label: 'Quota used' }, { id: 'tokens', label: 'Tokens' }], value: metric, onChange: setMetric })
        : null),
    h('div', { className: 'hap-heat', 'data-chart': metric, onMouseLeave: () => setHover(null) },
      h('span', null),
      Array.from({ length: 24 }, (_, hr) => h('span', { key: `h${hr}`, className: 'hap-heat-l' }, hr % 3 ? '' : String(hr).padStart(2, '0'))),
      chart.days.map(d => [h('span', { key: `l${d.date}`, className: 'hap-heat-l' }, `${d.dow} ${d.date}`), ...d[metric].map((_, hr) => cell(d, hr))])),
    h('div', { className: 'hap-small hap-muted hap-heat-read' }, read))
}

function GroupTable({ title, kind, rows, total, extra }) {
  const shown = rows.filter(r => r.requests)
  if (!shown.length) return null
  const name = r => r.name === '?' ? h(MTip, { label: 'Counted by a session tracker older than 1.3.0, which did not record profile and model: before the update, or by a process that kept the old tracker until it restarted (Health > Run doctor names it). These tokens leave the report within 8 days.' }, h('span', { className: 'hap-muted' }, 'no name (older tracker)')) : r.name
  return h(Fragment, null,
    h('div', { className: 'hap-section' }, title, h('span', { className: 'hap-pill' }, shown.length)),
    h('table', { className: 'hap-table', 'data-table': kind },
      h('thead', null, h('tr', null,
        h('th', null, kind === 'bots' ? 'Profile' : 'Model'), h('th', { className: 'hap-num' }, 'Tokens'), h('th', null, 'Share'),
        h('th', { className: 'hap-num' }, 'Requests'), h('th', { className: 'hap-num' }, 'API price'),
        extra ? h('th', null, extra[0]) : null)),
      h('tbody', null, shown.map(r => h('tr', { key: r.name },
        h('td', { style: { color: 'var(--ui-text-primary)' } }, name(r)),
        h('td', { className: 'hap-num' }, h(MTip, { label: tokLines(r).join('\n') }, h('span', null, fmtTok(r.total)))),
        h('td', null, h('span', { className: 'hap-sharebar' }, h('i', { style: { width: `${total ? Math.min(100, r.total / total * 100) : 0}%` } })),
          h('span', { className: 'hap-tag' }, `${total ? Math.round(r.total / total * 100) : 0}%`)),
        h('td', { className: 'hap-num' }, r.requests),
        h('td', { className: 'hap-num' }, fmtCost(r)),
        extra ? h('td', null, extra[1](r)) : null)))))
}

// The sessions (tasks) with the most tokens in the period, from the tracker's per-session buckets.
function SessionTable({ data }) {
  if (!data.since) {
    return h(Fragment, null, h('div', { className: 'hap-section' }, 'By session'),
      h('p', { className: 'hap-small hap-muted' }, 'Session tracker 1.5.0 counts tokens per session from its first API call. Running bots switch to it when they restart.'))
  }
  const rows = data.sessions || []
  const tip = r => [
    r.title, `session ${r.session}` + (r.task ? ` · task ${r.task}` : ''),
    `${r.source}${r.platform && r.platform !== r.source ? ` (${r.platform})` : ''} · ${r.models.join(', ') || '?'}`,
    ...(r.accounts.length ? [`account: ${r.accounts.join(' → ')}`] : []),
    `${hhmm(r.first)}-${hhmm(r.last)}${r.ended ? ', ended' : ''}`, '', ...tokLines(r.tokens)].join('\n')
  return h(Fragment, null,
    h('div', { className: 'hap-section' }, 'By session', h('span', { className: 'hap-pill' }, data.count),
      h('span', { className: 'hap-grow' }),
      h('span', { className: 'hap-tag', style: { textTransform: 'none', letterSpacing: 0, fontWeight: 400 } },
        data.since > Date.now() / 1000 - data.hours * 3600 ? `counted per session since ${when(data.since)}` : 'tokens in this period only')),
    rows.length
      ? h('table', { className: 'hap-table', 'data-table': 'sessions' },
        h('thead', null, h('tr', null, h('th', null, 'Session'), h('th', null, 'Profile'), h('th', null, 'Source'),
          h('th', { className: 'hap-num' }, 'Tokens'), h('th', { className: 'hap-num' }, 'Requests'), h('th', { className: 'hap-num' }, 'API price'))),
        h('tbody', null, rows.map(r => h('tr', { key: `${r.profile}:${r.session}` },
          h('td', { style: { color: 'var(--ui-text-primary)', maxWidth: 380 } },
            h(MTip, { label: tip(r) }, h('span', { className: 'hap-ellipsis' }, r.named ? r.title : h('span', { className: 'hap-muted' }, r.title))),
            r.task ? h('span', { className: 'hap-tag', style: { marginLeft: 6 } }, r.task) : null),
          h('td', null, r.profile), h('td', { className: 'hap-muted' }, r.source),
          h('td', { className: 'hap-num' }, fmtTok(r.tokens.total)), h('td', { className: 'hap-num' }, r.tokens.requests),
          h('td', { className: 'hap-num' }, fmtCost(r.tokens))))))
      : h('p', { className: 'hap-small hap-muted' }, 'No session in this period.'),
    data.rest && data.rest.count
      ? h('p', { className: 'hap-small hap-muted' }, `${data.rest.count} more session(s): ${fmtTok(data.rest.total)} tokens, $${data.rest.cost.toFixed(2)}.`)
      : null)
}

function ReportView({ provider }) {
  const [hours, setHours] = useState('24')
  const q = useQuery({
    queryKey: [ID, 'report', provider, hours],
    queryFn: () => get(`/report?provider=${encodeURIComponent(provider)}&hours=${hours}`),
    refetchInterval: 300000
  })
  const d = q.data
  const tt = d && d.tokens_total
  const counted = tt && tt.requests
  const since = d && d.tokens_since && d.tokens_since > (d.start || 0)
    ? `, since ${new Date(d.tokens_since * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}` : ''
  const usage = d && d.available && d.snapshots >= 2
  return h(Fragment, null,
    h('div', { className: 'hap-row', style: { margin: '4px 0 10px' } },
      h(SegmentedControl, {
        options: [{ id: '24', label: '24 hours' }, { id: '72', label: '3 days' }, { id: '168', label: '7 days' }],
        value: hours, onChange: setHours
      }),
      h('span', { className: 'hap-small hap-muted' }, 'From the history the balance timer records and the tokens the session tracker counts. No provider call.')),
    q.isLoading ? h(Loader, { type: 'lemniscate-bloom' })
      : q.error ? h(ErrorState, { title: errText(q.error) })
        : !d.available ? h('p', { className: 'hap-muted hap-small' }, d.message)
          : h(Fragment, null,
            h('div', { className: 'hap-cards' },
              usage ? h(Card, { k: 'Load', v: `${Math.round(d.total)}`, s: `100 = one full ${d.window} window` }) : null,
              usage ? h(Card, { k: 'Covered', v: `${d.span_h.toFixed(1)} h`, s: `${d.snapshots} snapshots` }) : null,
              usage ? h(Card, { k: 'Every account ≥ 90%', v: `${Math.round(d.full_min)} min`, s: d.full_min ? 'the pool ran out of headroom' : 'never' }) : null,
              usage ? h(Card, {
                k: 'Busiest hours', v: d.busiest.length ? `${String(d.busiest[0][0]).padStart(2, '0')}:00` : '–',
                s: d.busiest.map(([hr, v]) => `${String(hr).padStart(2, '0')}:00 (${Math.round(v)})`).join(', ')
              }) : null,
              h(Card, {
                k: 'Tokens through Hermes',
                v: counted ? fmtTok(tt.total) : '–',
                s: counted ? `${fmtTok(tt.input)} in · ${fmtTok(tt.output)} out · ${fmtTok(tt.cache_read)} cache read` : 'none counted yet'
              }),
              h(Card, {
                k: 'At API list prices',
                v: counted ? fmtCost(tt) : '–',
                s: !counted ? 'no tokens yet' : tt.unpriced ? `+ ${fmtTok(tt.unpriced)} tokens with no known price` : 'what the tokens would cost through the API'
              })),
            usage ? null : h('p', { className: 'hap-muted hap-small' }, `Not enough usage history yet (${d.snapshots} snapshot(s)). The timer records one every 5 minutes.`),
            usage && d.advice ? h('div', { className: 'hap-banner' }, h(Codicon, { name: 'lightbulb' }), h('span', null, d.advice)) : null,
            usage ? h('table', { className: 'hap-table', 'data-table': 'accounts' },
              h('thead', null, h('tr', null,
                h('th', null, 'Account'), h('th', { className: 'hap-num' }, 'Used'), h('th', null, 'Share'),
                h('th', { className: 'hap-num' }, 'Peak'), h('th', { className: 'hap-num' }, 'Time ≥ 90%'),
                h('th', { className: 'hap-num' }, 'Tokens'), h('th', { className: 'hap-num' }, 'API price'))),
              h('tbody', null, d.accounts.map(a => h('tr', { key: a.label },
                h('td', { style: { color: 'var(--ui-text-primary)' } }, a.label),
                h('td', { className: 'hap-num' }, Math.round(a.used)),
                h('td', null, h('span', { className: 'hap-sharebar' }, h('i', { style: { width: `${Math.min(100, a.share)}%` } })),
                  h('span', { className: 'hap-tag' }, `${Math.round(a.share)}%`)),
                h('td', { className: 'hap-num' }, `${Math.round(a.peak)}%`),
                h('td', { className: 'hap-num' }, `${Math.round(a.hot_min)} min`),
                h('td', { className: 'hap-num' }, a.tokens && a.tokens.requests
                  ? h(MTip, { label: tokLines(a.tokens).join('\n') }, h('span', null, fmtTok(a.tokens.total)))
                  : h('span', { className: 'hap-muted' }, '–')),
                h('td', { className: 'hap-num' }, fmtCost(a.tokens)))))) : null,
            h(GroupTable, {
              title: 'By profile (bot)', kind: 'bots', rows: d.by_profile || [], total: tt && tt.total,
              extra: ['Mostly', r => r.model && r.model !== '?' ? `${r.model}${r.accounts > 1 ? ` · ${r.accounts} accounts` : ''}` : '–']
            }),
            h(GroupTable, { title: 'By model', kind: 'models', rows: d.by_model || [], total: tt && tt.total }),
            d.sessions ? h(SessionTable, { data: d.sessions }) : null,
            d.chart ? h(HourChart, { chart: d.chart }) : null,
            h('p', { className: 'hap-small hap-muted', style: { marginTop: 8 } },
              (usage ? 'Used and Peak come from the provider\'s usage percentages. ' : '')
              + `Tokens count only what Hermes sent and received on this computer${since}. `
              + 'API price is what those tokens would cost at the provider\'s list prices; a subscription is billed flat, so it shows what the use is worth, not a bill.')))
}

const KIND_ICON = { balance: 'arrow-swap', alert: 'bell', park: 'debug-pause', unpark: 'debug-start', schedule: 'calendar',
  unschedule: 'calendar', strategy: 'settings-gear', notify: 'bell', add: 'add', remove: 'trash', relogin: 'key',
  setup: 'tools' }

function ActivityView({ provider }) {
  const [hours, setHours] = useState('24')
  const q = useQuery({
    queryKey: [ID, 'activity', provider, hours],
    queryFn: () => get(`/activity?provider=${encodeURIComponent(provider)}&hours=${hours}`),
    refetchInterval: 60000
  })
  const d = q.data
  return h(Fragment, null,
    h('div', { className: 'hap-row', style: { margin: '4px 0 10px' } },
      h(SegmentedControl, {
        options: [{ id: '24', label: '24 hours' }, { id: '72', label: '3 days' }, { id: '168', label: '7 days' }],
        value: hours, onChange: setHours
      }),
      h('span', { className: 'hap-small hap-muted' }, 'What the balance timer, the hermes account command and this page changed. Kept 30 days.')),
    q.isLoading ? h(Loader, { type: 'lemniscate-bloom' })
      : q.error ? h(ErrorState, { title: errText(q.error) })
        : !d.events.length ? h('p', { className: 'hap-muted hap-small' }, 'Nothing recorded in this period.')
          : h('table', { className: 'hap-table', 'data-table': 'activity' },
            h('thead', null, h('tr', null, h('th', { style: { width: 110 } }, 'When'), h('th', { style: { width: 64 } }, 'By'), h('th', null, 'What happened'))),
            h('tbody', null, d.events.map((e, i) => h('tr', { key: `${e.ts}-${i}` },
              h('td', { className: 'hap-num hap-muted' }, when(e.ts)),
              h('td', null, h('span', { className: 'hap-tag' }, e.by)),
              h('td', null, h('span', { className: 'hap-acc' }, h(Codicon, { name: KIND_ICON[e.kind] || 'circle-small', size: '0.8rem' }), h('span', null, e.text))))))))
}

function HealthView({ provider, data, openResult }) {
  const [checks, setChecks] = useState(null)
  const [busy, setBusy] = useState('')
  const run = async () => {
    setBusy('doctor')
    try {
      setChecks(await post('/doctor', { provider }))
    } catch (e) {
      notify('error', errText(e))
    } finally {
      setBusy('')
    }
  }
  const check = async () => {
    setBusy('check')
    try {
      const r = await post('/action', { action: 'check', provider })
      openResult('Account check', r.output)
    } catch (e) {
      notify('error', errText(e))
    } finally {
      setBusy('')
    }
  }
  const t = data.timer || {}
  const tone = { ok: 'good', warn: 'warn', fail: 'bad' }
  return h(Fragment, null,
    h('div', { className: 'hap-cards' },
      h(Card, { k: 'Balance timer', v: t.active ? 'active' : 'off', s: t.active ? `last ${t.running ? 'running now' : hhmm(t.last_ts)} · next ${t.next || '–'}` : 'systemctl --user enable --now hermes-account-balance.timer' }),
      h(Card, { k: 'Usage history', v: data.snapshot.ts ? ago(data.now - data.snapshot.ts) : 'none', s: `${data.snapshot.count} snapshot(s) in 24 h` }),
      h(Card, { k: 'Active alerts', v: String(data.alerts.length), s: data.alerts.map(a => a.text).join(' · ') || 'none' })),
    h('div', { className: 'hap-row', style: { margin: '10px 0' } },
      h(Button, { size: 'sm', disabled: !!busy, onClick: run }, h(Codicon, { name: 'pulse', size: '0.8rem' }), busy === 'doctor' ? 'Checking…' : 'Run doctor'),
      h(Button, { size: 'sm', variant: 'outline', disabled: !!busy, onClick: check }, h(Codicon, { name: 'verified', size: '0.8rem' }), busy === 'check' ? 'Checking…' : 'Check accounts'),
      h('span', { className: 'hap-small hap-muted' }, 'Doctor reads the usage endpoint once; Check accounts asks the provider who each login really is.')),
    checks
      ? (checks.empty
        ? h('p', { className: 'hap-muted hap-small' }, `No ${provider} accounts: nothing to check.`)
        : h('div', null, checks.checks.map((c, i) => h('div', { className: 'hap-check', key: i },
          h(StatusDot, { tone: tone[c.level] || 'muted' }), h('span', null, c.text)))))
      : null)
}

function AlertsView({ provider, data, openResult }) {
  const invalidate = useInvalidate()
  const q = useQuery({ queryKey: [ID, 'notify', provider], queryFn: () => get(`/notify?provider=${encodeURIComponent(provider)}`) })
  const [busy, setBusy] = useState(false)
  const [dailyAt, setDailyAt] = useState('08:00')
  const savedDaily = q.data && q.data.daily
  useEffect(() => { if (savedDaily) setDailyAt(savedDaily) }, [savedDaily])
  const dailyOk = /^([01]?\d|2[0-3])[:.][0-5]\d$/.test(dailyAt.trim())
  const [botUsd, setBotUsd] = useState('15')
  const savedBot = q.data && q.data.bots && q.data.bots.usd
  useEffect(() => { if (savedBot) setBotUsd(String(savedBot)) }, [savedBot])
  const botOk = /^\$?\d+(\.\d+)?$/.test(botUsd.trim()) && Number(botUsd.replace('$', '')) > 0
  const act = async (target, result) => {
    setBusy(true)
    try {
      const r = await post('/action', { action: 'notify', provider, target })
      if (result) openResult(result, r.output)
      else if (!r.ok) notify('error', r.output)
      invalidate()
    } catch (e) {
      notify('error', errText(e))
    } finally {
      setBusy(false)
    }
  }
  const n = q.data
  if (q.isLoading) return h(Loader, { type: 'lemniscate-bloom' })
  if (q.error) return h(ErrorState, { title: errText(q.error) })
  return h(Fragment, null,
    h('p', { className: 'hap-small hap-muted', style: { margin: '4px 0 6px' } },
      `The balance timer alerts once when every account is above ${n.alert_all_above}%, once when an account needs to sign in again, once when it is fixed, and once when a bot uses far more than usual.`),
    h('div', { className: 'hap-setting' },
      h('div', { className: 'hap-grow' },
        h('div', { className: 'hap-setting-t' }, 'Desktop notifications'),
        h('div', { className: 'hap-small hap-muted' }, n.notify_send ? 'Through notify-send on this computer.' : 'notify-send is not installed.')),
      h(Switch, { checked: n.desktop, disabled: busy, onCheckedChange: v => act(v ? 'desktop-on' : 'desktop-off') })),
    h('div', { className: 'hap-setting' },
      h('div', { className: 'hap-grow' },
        h('div', { className: 'hap-setting-t' }, 'Telegram'),
        h('div', { className: 'hap-small hap-muted' }, 'To your private chat (the first TELEGRAM_ALLOWED_USERS entry), sent by the bot of:')),
      h(ProfileSelect, {
        value: n.via, profiles: n.profiles, disabled: busy || !n.telegram,
        onChange: v => { if (v && v !== n.via) act(`telegram-via=${v}`) }
      }),
      h(Switch, { checked: n.telegram, disabled: busy, onCheckedChange: v => act(v ? 'telegram-on' : 'telegram-off') })),
    h('div', { className: 'hap-setting' },
      h('div', { className: 'hap-grow' },
        h('div', { className: 'hap-setting-t' }, 'Daily summary'),
        h('div', { className: 'hap-small hap-muted' },
          'Tokens, bots, API price and load of the last 24 hours, once a day, to the channels above'
          + (n.daily ? `. Sent by the first timer run after ${n.daily}${n.daily_last ? `; last sent ${n.daily_last}` : ''}.` : '.'))),
      h(Input, {
        className: 'hap-time', value: dailyAt, disabled: busy, 'aria-label': 'Time of the daily summary', placeholder: '08:00',
        onChange: e => setDailyAt(e.target.value),
        onBlur: () => { if (n.daily && dailyOk && dailyAt.trim() !== n.daily) act(`daily=${dailyAt.trim()}`) },
        onKeyDown: e => { if (e.key === 'Enter') e.currentTarget.blur() }
      }),
      h(Switch, { checked: !!n.daily, disabled: busy || (!n.daily && !dailyOk), onCheckedChange: v => act(v ? `daily=${dailyAt.trim()}` : 'daily-off') })),
    n.bots
      ? h('div', { className: 'hap-setting', 'data-setting': 'bots' },
        h('div', { className: 'hap-grow' },
          h('div', { className: 'hap-setting-t' }, 'Bot using far more than usual'),
          h('div', { className: 'hap-small hap-muted' },
            `When a bot's last hour reaches this much at API prices (or ${n.bots.requests} requests) and ${n.bots.factor}x its usual hour: a loop or a runaway task. Names its busiest session.`)),
        h('span', { className: 'hap-small hap-muted' }, '$/h'),
        h(Input, {
          className: 'hap-time', value: botUsd, disabled: busy, 'aria-label': 'Dollars per hour for a bot alert', placeholder: '15',
          onChange: e => setBotUsd(e.target.value),
          onBlur: () => { if (n.bots.on && botOk && Number(botUsd) !== Number(n.bots.usd)) act(`bots=${botUsd.trim()}`) },
          onKeyDown: e => { if (e.key === 'Enter') e.currentTarget.blur() }
        }),
        h(Switch, { checked: !!n.bots.on, disabled: busy, 'aria-label': 'Bot alerts', onCheckedChange: v => act(v ? (botOk ? `bots=${botUsd.trim()}` : 'bots-on') : 'bots-off') }))
      : null,
    h('div', { className: 'hap-row', style: { marginTop: 12 } },
      h(Button, { size: 'sm', variant: 'outline', disabled: busy, onClick: () => act('test', 'Test alert') },
        h(Codicon, { name: 'bell', size: '0.8rem' }), busy ? 'Sending…' : 'Send a test alert'),
      h(Button, { size: 'sm', variant: 'outline', disabled: busy, onClick: () => act('summary', 'Daily summary') },
        h(Codicon, { name: 'graph', size: '0.8rem' }), 'Send the summary now')),
    h('div', { className: 'hap-section' }, 'Active now', h('span', { className: 'hap-pill' }, data.alerts.length)),
    data.alerts.length
      ? data.alerts.map(a => h('div', { className: 'hap-check', key: a.key },
        h(StatusDot, { tone: 'warn' }), h('span', { className: 'hap-grow' }, a.text), h('span', { className: 'hap-tag' }, `since ${hhmm(a.since)}`)))
      : h('p', { className: 'hap-small hap-muted' }, 'None.'))
}

// ── page ─────────────────────────────────────────────────────────────────────

function AccountsPage() {
  const invalidate = useInvalidate()
  const [provider, setProviderState] = useState(() => storage.get('provider', 'anthropic'))
  const [view, setView] = useState(() => storage.get('view', 'accounts'))
  const [dialog, setDialog] = useState(null)
  const [busy, setBusy] = useState('')
  const setProvider = p => {
    storage.set('provider', p)
    setProviderState(p)
  }
  const pickView = v => {
    storage.set('view', v)
    setView(v)
  }

  const q = useQuery({
    queryKey: [ID, 'status', provider],
    queryFn: () => get(`/status?provider=${encodeURIComponent(provider)}`),
    refetchInterval: 30000
  })
  const data = q.data
  const liveWait = data && data.live.ts ? Math.max(0, Math.ceil(data.live.ts + LIVE_GAP - Date.now() / 1000)) : 0
  const now = useNow(liveWait > 0)
  const liveLeft = data && data.live.ts ? Math.max(0, Math.ceil(data.live.ts + LIVE_GAP - now / 1000)) : 0

  const done = message => {
    if (message) notify('success', message)
    invalidate()
    setDialog(null)
  }
  const openResult = (title, text) => setDialog({ type: 'result', title, text })

  const refreshLive = async () => {
    setBusy('live')
    try {
      const r = await post('/live', { provider })
      if (r.ok) notify(r.message ? 'warning' : 'success', r.message || 'Live usage updated.')
      else notify('info', r.message)
      invalidate()
    } catch (e) {
      notify('error', errText(e))
    } finally {
      setBusy('')
    }
  }
  let content
  if (q.isLoading) content = h('div', { className: 'hap-empty' }, h(Loader, { type: 'lemniscate-bloom' }))
  else if (q.error) {
    const msg = errText(q.error)
    content = h('div', { className: 'hap-empty' },
      h(ErrorState, {
        title: 'The account-pool backend did not answer',
        description: /404|not found/i.test(msg)
          ? 'Hermes Desktop loads this backend only for profiles that list account-pool in plugins.enabled, and only when it starts. Run "hermes account anthropic setup" (it lists account-pool in every profile; the command stays in the default profile), then restart Hermes Desktop. "hermes account anthropic doctor" names the profiles that miss it.'
          : msg
      }))
  } else if (view === 'report') content = h(ReportView, { provider })
  else if (view === 'activity') content = h(ActivityView, { provider })
  else if (view === 'health') content = h(HealthView, { provider, data, openResult })
  else if (view === 'alerts') content = h(AlertsView, { provider, data, openResult })
  else content = h(AccountsView, { data, provider, openDialog: setDialog })

  let modal = null
  if (dialog && data) {
    const close = () => setDialog(null)
    if (dialog.type === 'park') modal = h(ParkDialog, { provider, row: dialog.row, onClose: close, onDone: done })
    else if (dialog.type === 'schedule') modal = h(ScheduleDialog, { provider, row: dialog.row, current: dialog.current, onClose: close, onDone: done })
    else if (dialog.type === 'strategy' && data.rotation_mode) modal = h(StrategyDialog, { provider, mode: data.rotation_mode, onClose: close, onDone: done })
    else if (dialog.type === 'strategyfix' && data.rotation_mode) {
      const names = data.rotation_mode.other.map(r => r.profile)
      modal = h(ConfirmDialog, {
        open: true, onClose: close, title: `Use fill_first in ${names.join(', ')}?`, confirmLabel: 'Use fill_first', busyLabel: 'Saving…',
        description: `Sets credential_pool_strategies.${provider} to fill_first there with Hermes' config writer, so new sessions start on the account balance puts first. Running sessions keep their account.`,
        onConfirm: async () => {
          const r = await post('/action', { action: 'strategy', provider, target: 'fill_first', only: names })
          if (!r.ok) throw new Error(r.output || 'Saving the strategy failed')
          done(firstLine(r.output))
        }
      })
    }
    else if (dialog.type === 'unschedule') {
      modal = h(ConfirmDialog, {
        open: true, onClose: close, title: `Remove the schedule of ${dialog.row.label}?`, confirmLabel: 'Remove schedule', busyLabel: 'Removing…',
        description: dialog.row.parked_by_schedule
          ? 'The timer stops parking it. It is parked now and stays parked until the current window ends; unpark it to return it sooner.'
          : 'The timer stops parking it. The account itself is not changed.',
        onConfirm: async () => {
          const r = await post('/action', { action: 'unschedule', provider, target: dialog.row.label })
          if (!r.ok) throw new Error(r.output || 'Removing the schedule failed')
          done(firstLine(r.output))
        }
      })
    }
    else if (dialog.type === 'unpark') {
      modal = h(ConfirmDialog, {
        open: true, onClose: close, title: `Unpark ${dialog.row.label}?`, confirmLabel: 'Unpark', busyLabel: 'Unparking…',
        description: 'It goes back into rotation, then the login is checked.',
        onConfirm: async () => {
          const r = await post('/action', { action: 'unpark', provider, target: dialog.row.id })
          if (!r.ok) throw new Error(r.output || 'Unpark failed')
          done(firstLine(r.output))
        }
      })
    } else if (dialog.type === 'remove') {
      modal = h(ConfirmDialog, {
        open: true, onClose: close, destructive: true, title: `Remove ${dialog.row.label}?`, confirmLabel: 'Remove', busyLabel: 'Removing…',
        description: dialog.parked
          ? 'Its saved login is deleted. To use it again you sign in again with Add account.'
          : 'Its login is deleted. To use it again you sign in again with Add account. To pause it instead, park it.',
        onConfirm: async () => {
          const r = await post('/action', { action: 'remove', provider, target: dialog.row.id })
          if (!r.ok) throw new Error(r.output || 'Remove failed')
          done(r.output.split('\n').pop())
        }
      })
    } else if (dialog.type === 'balance') {
      modal = h(ConfirmDialog, {
        open: true, onClose: close, title: 'Balance now?', confirmLabel: 'Balance now', busyLabel: 'Balancing…',
        description: 'Reads the live usage of every account, puts the least-used first and benches accounts at 90% or more until their window resets. The timer does this every 5 minutes anyway.',
        onConfirm: async () => {
          const r = await post('/action', { action: 'balance', provider })
          if (!r.ok && r.rc === 2) throw new Error(r.output)
          invalidate()
          setDialog({ type: 'result', title: 'Balance', text: r.output })
        }
      })
    } else if (dialog.type === 'add' || dialog.type === 'relogin') {
      modal = h(SignInDialog, { provider, mode: dialog.type, row: dialog.row, verify: data.has_identity, onClose: close })
    } else if (dialog.type === 'result') {
      modal = h(ResultDialog, { title: dialog.title, text: dialog.text, onClose: close })
    }
  }

  const providers = data ? data.providers : [{ name: provider }]
  const t = data && data.timer
  const age = data && data.snapshot.ts ? data.now - data.snapshot.ts : null

  return h('div', { className: 'hap-page' },
    h('header', { className: 'hap-head' },
      h('h1', { className: 'hap-title' }, 'Accounts'),
      data ? h('span', { className: 'hap-pill' }, data.rotation.length + data.parked.length) : null,
      providers.length > 1
        ? h(SegmentedControl, {
          options: providers.map(p => ({ id: p.name, label: p.in_use === false ? `${p.name} (none)` : p.name })),
          value: provider, onChange: setProvider
        })
        : null,
      h('span', { className: 'hap-grow' }),
      data && data.has_usage
        ? h(MTip, { label: liveLeft ? `Available in ${liveLeft}s. The usage endpoint rate-limits per account.` : 'Read live usage of every account now (one request per account).' },
          h('span', null, h(Button, { size: 'sm', variant: 'ghost', disabled: !!busy || liveLeft > 0, onClick: refreshLive },
            h(Codicon, { name: 'refresh', size: '0.8rem', spinning: busy === 'live' }), liveLeft ? `Live (${liveLeft}s)` : 'Live usage')))
        : null,
      data && (data.rotation.length || data.parked.length)
        ? h(Button, { size: 'sm', variant: 'outline', disabled: !!busy, onClick: () => setDialog({ type: 'balance' }) },
          h(Codicon, { name: 'arrow-swap', size: '0.8rem' }), 'Balance now')
        : null,
      data && data.web_signin
        ? h(Button, { size: 'sm', onClick: () => setDialog({ type: 'add' }) }, h(Codicon, { name: 'add', size: '0.8rem' }), 'Add account')
        : null),
    h('div', { className: 'hap-sub' },
      h(SegmentedControl, {
        options: [{ id: 'accounts', label: 'Accounts' }, { id: 'report', label: 'Report' }, { id: 'activity', label: 'Activity' }, { id: 'health', label: 'Health' }, { id: 'alerts', label: 'Alerts' }],
        value: view, onChange: pickView
      }),
      data
        ? h('span', null,
          'Shared pool · ',
          age != null ? `usage from the balance timer, ${ago(age)}` : 'no usage history yet',
          t && t.active ? ` · next run ${t.running ? 'now' : t.next || '–'}` : ' · balance timer off',
          data.rotation_mode ? ' · ' : null,
          data.rotation_mode ? h(RotationMode, { mode: data.rotation_mode, provider: data.provider, onEdit: () => setDialog({ type: 'strategy' }) }) : null)
        : null),
    h('div', { className: 'hap-body' },
      data && data.rotation_mode && data.rotation_mode.other.length && view === 'accounts'
        ? h('div', { className: 'hap-banner' }, h(Codicon, { name: 'warning' }),
          h('span', { className: 'hap-grow' },
            `Hermes rotation is not fill_first in ${data.rotation_mode.other.map(r => `${r.profile} (${r.strategy})`).join(', ')}. `
            + 'Sessions there ignore the balance order.'),
          h(Button, { size: 'xs', variant: 'outline', disabled: !!busy, onClick: () => setDialog({ type: 'strategyfix' }) }, 'Use fill_first'))
        : null,
      data && data.tracker && (data.tracker.stale.length || data.tracker.unnamed_since) && view === 'accounts'
        ? h(TrackerBanner, { tracker: data.tracker })
        : null,
      data && data.alerts.length && view === 'accounts'
        ? data.alerts.map(a => h('div', { className: 'hap-banner', key: a.key, 'data-alert': a.kind }, h(Codicon, { name: a.kind === 'bot' ? 'flame' : 'warning' }),
          h('span', { className: 'hap-grow' }, a.text),
          a.kind === 'bot'
            ? h(Button, { size: 'xs', variant: 'outline', onClick: () => pickView('report') }, 'See sessions')
            : null,
          a.kind === 'dead' && data.web_signin
            ? h(Button, {
              size: 'xs', variant: 'outline',
              onClick: () => setDialog({ type: 'relogin', row: data.rotation.find(r => r.label === a.label) || { label: a.label, id: a.label } })
            }, 'Sign in again')
            : null))
        : null,
      content),
    modal)
}

// Processes that loaded the session tracker before its last update (gateway, Desktop, long sessions).
function TrackerBanner({ tracker }) {
  const name = g => g.kind === 'gateway' ? 'the gateway' : g.kind === 'desktop' ? 'Hermes Desktop' : `a ${g.platforms.join('/')} session`
  const fixes = [...new Set(tracker.stale.map(g => g.fix))]
  const text = tracker.stale.length
    ? `Token counting: ${tracker.stale.map(g => `${name(g)} (${g.profiles.join(', ')})`).join(', ')} still ${tracker.stale.length === 1 ? 'runs' : 'run'} an older session tracker than ${tracker.version}, loaded before the update. Fix: ${fixes.join('; ')}.`
    : `Token counting: a process with session tracker 1.2.0 or older counted tokens without a bot name until ${hhmm(tracker.unnamed_since + 900)}. Fix: hermes gateway restart, restart Hermes Desktop, or end long sessions.`
  return h('div', { className: 'hap-banner', 'data-banner': 'tracker' }, h(Codicon, { name: 'info' }), h('span', { className: 'hap-grow' }, text))
}

// Hermes' own rotation setting (credential_pool_strategies). Hermes owns it; the page shows it and
// changes it through the backend, which uses Hermes' `config set`.
const MODES = {
  fill_first: 'fill_first: every new session takes the first usable account. With the balance timer that is the least-used one.',
  round_robin: 'round_robin: each new session takes the next account in turn and moves it to the end. Rewrites the order balance sets.',
  least_used: 'least_used: each new session takes the account picked least often by this computer, not the one with the most quota left.',
  random: 'random: each new session takes a random usable account.'
}

function RotationMode({ mode, provider, onEdit }) {
  const mixed = mode.other.length > 0
  const label = [
    `Rotation is a Hermes setting, per profile: credential_pool_strategies.${provider}.`,
    '',
    ...Object.values(MODES),
    '',
    'fill_first is the one balance is built for: the order it sets decides where new sessions start.',
    mixed ? `Not fill_first: ${mode.other.map(r => `${r.profile} (${r.strategy})`).join(', ')}.` : `All ${mode.profiles.length} profiles use fill_first.`,
    '',
    'Click to change it per profile.'
  ].join('\n')
  return h(MTip, { label },
    h('button', {
      type: 'button', className: 'hap-modebtn', onClick: onEdit, 'aria-label': 'Change the rotation strategy',
      style: mixed ? { color: 'var(--ui-orange)' } : undefined
    },
    mixed ? `rotation: ${mode.default}, ${mode.other.length} profile(s) differ` : `rotation: ${mode.default}`,
    h(Codicon, { name: 'edit', size: '0.7rem' })))
}

// ── status bar ───────────────────────────────────────────────────────────────

function StatusChip() {
  const provider = storage.get('provider', 'anthropic')
  const { data } = useQuery({
    queryKey: [ID, 'summary', provider],
    queryFn: () => get(`/summary?provider=${encodeURIComponent(provider)}`),
    refetchInterval: 60000,
    retry: false
  })
  if (!data || (!data.rotation && !data.parked)) return null
  const pct = data.next && data.next.pct != null ? ` · ${Math.round(data.next.pct)}%` : ''
  const tip = [
    `${provider}: ${data.usable} of ${data.rotation} usable, ${data.parked} parked`,
    data.next ? `Next session starts on ${data.next.label}${data.next.pct != null ? ` (${Math.round(data.next.pct)}%)` : ''}` : 'No usable account',
    data.max != null ? `Highest usage: ${Math.round(data.max)}%` : '',
    data.alerts ? `${data.alerts} alert(s) active` : ''
  ].filter(Boolean).join('\n')
  return h(MTip, { label: tip },
    h('button', {
      type: 'button',
      className: 'inline-flex h-full items-center gap-1 rounded-none px-1.5 text-[0.6875rem] tabular-nums transition-colors text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground',
      onClick: () => host.navigate(ROUTE)
    },
    h(Codicon, { name: 'account', size: '0.7rem' }),
    h('span', null, `${data.usable}/${data.rotation}${pct}`),
    data.alerts || !data.usable ? h(StatusDot, { tone: data.usable ? 'warn' : 'bad' }) : null))
}

// ── plugin ───────────────────────────────────────────────────────────────────

export default {
  id: ID,
  name: 'Accounts',
  description: 'Credential-pool accounts: usage, who uses which account, park, balance, sign in. Desktop half of the account-pool plugin.',
  defaultEnabled: false,
  register(ctx) {
    rest = ctx.rest
    storage = ctx.storage
    openExternal = url => ctx.os.openExternal(url)

    const style = document.createElement('style')
    style.dataset.plugin = ID
    style.textContent = CSS
    document.head.appendChild(style)
    ctx.onDispose(() => style.remove())

    ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, data: { path: ROUTE }, render: () => h(AccountsPage) },
      { id: 'nav', area: SIDEBAR_NAV_AREA, order: 55, data: { path: ROUTE, label: 'Accounts', codicon: 'account' } },
      { id: 'chip', area: STATUSBAR_AREAS.right, order: 85, render: () => h(StatusChip) },
      {
        id: 'open',
        area: PALETTE_AREA,
        data: {
          id: 'account-pool.open',
          label: 'Accounts: open the account pool',
          keywords: ['accounts', 'pool', 'usage', 'claude', 'park', 'balance', 'credential'],
          run: () => host.navigate(ROUTE)
        }
      }
    ])
  }
}
