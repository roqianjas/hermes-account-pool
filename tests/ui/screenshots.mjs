// Screenshots of the Accounts page for docs/screenshots/, taken from a real Hermes Desktop that shows
// made-up data (tests/ui/fixtures.json through tests/ui/fixture_api.py). Nothing touches your own Hermes.
//
// 1. A throwaway Hermes home with a copy of the plugin whose backend is the fixture backend:
//      SB=$(mktemp -d -p ~/.cache hap-sandbox.XXXX); mkdir -p $SB/plugins $SB/ud
//      cp -a plugins/account-pool $SB/plugins/
//      cp tests/ui/fixture_api.py $SB/plugins/account-pool/dashboard/plugin_api.py
//      cp tests/ui/fixtures.json $SB/plugins/account-pool/dashboard/
//      printf 'plugins:\n  enabled:\n    - account-pool\n' > $SB/config.yaml
// 2. Its backend on a port of its own, with a session token made up for this run:
//      HERMES_HOME=$SB HERMES_DASHBOARD_SESSION_TOKEN=<random> hermes serve --host 127.0.0.1 --port 9441 --skip-build
// 3. A second Hermes Desktop with its own profile directory and debugging port, on a virtual screen:
//      env -u WAYLAND_DISPLAY LANG=en_GB.UTF-8 HERMES_HOME=$SB xvfb-run -a -s "-screen 0 1440x900x24" \
//        <Hermes Desktop binary> --no-sandbox --ozone-platform=x11 --lang=en-GB --user-data-dir=$SB/ud \
//        --remote-debugging-port=9339
//    Connect it once: Gateway settings > Remote gateway, http://127.0.0.1:9441 and the token. Skip the
//    provider choice. Then switch on the Desktop half of account-pool (Capabilities > Plugins).
//    After changing plugin.js, restart this Desktop: it copies the page when it starts.
// 4. node tests/ui/screenshots.mjs [port=9339] [out=docs/screenshots]
// 5. Stop both processes and remove $SB.
import fs from 'node:fs'
import path from 'node:path'

const PORT = process.argv[2] || '9339'
const OUT = process.argv[3] || new URL('../../docs/screenshots/', import.meta.url).pathname
const WIDTH = 1400
const HEIGHT = 900
const STATUS_BAR = 22 // the Desktop's status bar is left out: it shows the sandbox's own backend state
const sleep = ms => new Promise(r => setTimeout(r, ms))

const targets = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()
const page = targets.find(t => t.type === 'page' && !t.url.startsWith('devtools'))
if (!page) throw new Error(`no Hermes Desktop page on port ${PORT}`)
const ws = new WebSocket(page.webSocketDebuggerUrl)
await new Promise((resolve, reject) => { ws.addEventListener('open', resolve); ws.addEventListener('error', reject) })
let seq = 0
const pending = new Map()
ws.addEventListener('message', e => {
  const m = JSON.parse(e.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
})
const send = (method, params = {}) => new Promise(resolve => {
  const id = ++seq
  pending.set(id, resolve)
  ws.send(JSON.stringify({ id, method, params }))
})
async function js(expression) {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || expression)
  return r.result?.result?.value
}
async function waitFor(expression, what, ms = 15000) {
  for (const end = Date.now() + ms; Date.now() < end; await sleep(250)) {
    if (await js(expression)) return
  }
  throw new Error(`timed out waiting for ${what}`)
}
const visible = 'e => e.offsetParent !== null'
const click = (scope, text) => js(`(() => {
  const el = [...document.querySelectorAll(${JSON.stringify(scope)})].filter(${visible})
    .find(e => e.textContent.trim() === ${JSON.stringify(text)})
  if (!el) throw new Error('nothing to click: ' + ${JSON.stringify(text)})
  el.click(); return true })()`)
const hasText = text => `document.body.innerText.toLowerCase().includes(${JSON.stringify(text.toLowerCase())})`
const type = (selector, value) => js(`(() => {
  const el = [...document.querySelectorAll(${JSON.stringify(selector)})].filter(${visible}).pop()
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, ${JSON.stringify(value)})
  el.dispatchEvent(new Event('input', { bubbles: true })); return true })()`)

async function shot(name) {
  await sleep(700)
  const r = await send('Page.captureScreenshot', {
    format: 'png', captureBeyondViewport: false,
    clip: { x: 0, y: 0, width: WIDTH, height: HEIGHT - STATUS_BAR, scale: 1 }
  })
  const file = path.join(OUT, `${name}.png`)
  fs.writeFileSync(file, Buffer.from(r.result.data, 'base64'))
  console.log('saved', file)
}

fs.mkdirSync(OUT, { recursive: true })
await send('Emulation.setDeviceMetricsOverride', { width: WIDTH, height: HEIGHT, deviceScaleFactor: 2, mobile: false })
await js(`(() => { document.activeElement && document.activeElement.blur(); return true })()`)
await click('aside a, aside button, nav a, button', 'Accounts')
await waitFor(hasText('alice@example.com'), 'the Accounts page')
await click('.hap-sub button', 'Accounts')
await waitFor(hasText('In rotation'), 'the rotation table')
await shot('accounts')

await click('.hap-sub button', 'Report')
await waitFor(hasText('By model'), 'the Report tab')
await js(`(() => { const b = document.querySelector('.hap-body'); if (b) b.scrollTop = 0; return true })()`)
await shot('report')
const scrolled = await js(`(() => {
  const h = [...document.querySelectorAll('*')].filter(${visible})
    .filter(e => /^By session/i.test(e.textContent.trim()) && e.textContent.length < 60).pop()
  const body = h && h.closest('.hap-body')
  if (!body) return false
  body.scrollTop += h.getBoundingClientRect().top - body.getBoundingClientRect().top - 8
  return true })()`)
if (!scrolled) throw new Error('no By session table to scroll to')
await shot('sessions')

await click('.hap-sub button', 'Activity')
await waitFor(hasText('timer') + ' && ' + hasText('page'), 'the Activity tab')
await shot('activity')

await click('.hap-sub button', 'Alerts')
await waitFor(hasText('Telegram'), 'the Alerts tab')
await shot('alerts')

await click('.hap-sub button', 'Accounts')
await waitFor(hasText('alice@example.com'), 'the Accounts tab')
await click('button', 'Add account')
await waitFor(hasText('Start sign-in'), 'the Add account dialog')
await type('[role=dialog] input', 'judy@example.com')
await click('[role=dialog] button', 'Start sign-in')
await waitFor(hasText('Copy link'), 'the sign-in step')
await shot('add-account')
await click('[role=dialog] button', 'Cancel').catch(() => {})

// Codex: the browser sign-in waiting for the browser to come back to localhost:1455
await js(`(() => {
  const el = [...document.querySelectorAll('button')].filter(${visible})
    .find(e => e.textContent.trim().startsWith('openai-codex'))
  if (!el) throw new Error('no openai-codex provider button')
  el.click(); return true })()`)
await waitFor(hasText('No openai-codex accounts yet'), 'the empty Codex page')
await click('button', 'Add account')
await waitFor(hasText('Browser on this computer'), 'the Codex Add account dialog')
await type('[role=dialog] input', 'judy@example.com')
await click('[role=dialog] button', 'Start sign-in')
await waitFor(hasText('Waiting for the browser'), 'the browser sign-in step')
await shot('add-account-codex')
await click('[role=dialog] button', 'Cancel').catch(() => {})

ws.close()
