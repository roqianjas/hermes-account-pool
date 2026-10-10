// Stand-ins for @hermes/plugin-sdk: plain elements with the same props, so the page
// renders in jsdom. Query hooks are the real @tanstack/react-query.
import { NM, require } from './env.mjs'

const React = require('react')
const h = React.createElement
const RQ = await import(NM + '@tanstack/react-query/build/modern/index.js')
export const { useQuery, useQueryClient } = RQ

export const ROUTES_AREA = 'routes'
export const SIDEBAR_NAV_AREA = 'sidebar.nav'
export const PALETTE_AREA = 'palette'
export const STATUSBAR_AREAS = { left: 'statusBar.left', right: 'statusBar.right' }

export const host = {
  notes: [],
  navigated: [],
  notify(n) { host.notes.push(n) },
  navigate(p) { host.navigated.push(p) }
}

const pass = tag => ({ children, className }) => h(tag, { className }, children)
export const Badge = ({ children, variant }) => h('span', { 'data-badge': variant }, children)
export const Button = ({ children, onClick, disabled, ...p }) =>
  h('button', { onClick, disabled, 'aria-label': p['aria-label'] }, children)
export const Codicon = ({ name }) => h('i', { 'data-icon': name })
export const CopyButton = ({ text, label }) => h('button', { 'data-copy': text }, label || 'copy')
export const Dialog = ({ open, children }) => (open ? h('div', { role: 'dialog' }, children) : null)
export const DialogContent = pass('div')
export const DialogDescription = pass('p')
export const DialogFooter = pass('footer')
export const DialogHeader = pass('header')
export const DialogTitle = pass('h2')
export const ErrorState = ({ title, description }) => h('div', { 'data-error': true }, title, ' ', description)
export const Input = p => h('input', { ...p })
export const Loader = () => h('span', null, 'loading')
export const SegmentedControl = ({ options, value, onChange }) =>
  h('div', { role: 'tablist' }, options.map(o =>
    h('button', { key: o.id, role: 'tab', 'aria-selected': o.id === value, onClick: () => onChange(o.id) }, o.label)))
export const StatusDot = ({ tone }) => h('span', { 'data-tone': tone })
export const Switch = ({ checked, onCheckedChange, disabled }) =>
  h('button', { role: 'switch', 'aria-checked': checked, disabled, onClick: () => onCheckedChange(!checked) })
export const Tip = ({ label, children }) => h('span', { title: typeof label === 'string' ? label : undefined }, children)

export function ConfirmDialog({ open, onClose, onConfirm, title, description, children, confirmLabel = 'Confirm' }) {
  const [err, setErr] = React.useState('')
  if (!open) return null
  return h('div', { role: 'dialog' },
    h('h2', null, title), h('p', null, description), children,
    err ? h('div', { role: 'alert' }, err) : null,
    h('button', { onClick: onClose }, 'Cancel'),
    h('button', {
      onClick: async () => {
        try {
          await onConfirm()
        } catch (e) {
          setErr(String(e.message || e))
        }
      }
    }, confirmLabel))
}
