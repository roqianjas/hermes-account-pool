// Where the test finds React, jsdom and the rest: the node_modules of a Hermes Agent checkout.
// Override with HERMES_AGENT_DIR=/path/to/hermes-agent.
import { createRequire } from 'node:module'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const dir = process.env.HERMES_AGENT_DIR || path.join(os.homedir(), '.hermes', 'hermes-agent')
export const NM = pathToFileURL(path.join(dir, 'node_modules') + path.sep).href
export const require = createRequire(path.join(dir, 'node_modules') + path.sep)
