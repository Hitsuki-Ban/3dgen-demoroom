import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { parse } from 'jsonc-parser';


export function validateWranglerConfig(configPath) {
  const source = fs.readFileSync(configPath, 'utf8');
  const parseErrors = [];
  const config = parse(source, parseErrors, { allowTrailingComma: true });

  if (parseErrors.length > 0) {
    throw new Error('wrangler config must be valid JSONC');
  }
  if (config.workers_dev !== true) {
    throw new Error('wrangler config must explicitly keep workers_dev enabled');
  }
  if (config.preview_urls !== false) {
    throw new Error('wrangler config must explicitly keep preview URLs disabled');
  }
  const customDomainRoute = config.routes?.[0];
  const customDomainKeys = customDomainRoute && typeof customDomainRoute === 'object'
    ? Object.keys(customDomainRoute).sort()
    : [];
  if (
    !Array.isArray(config.routes)
    || config.routes.length !== 1
    || customDomainRoute?.pattern !== '3dgen.hitsuki.space'
    || customDomainRoute?.custom_domain !== true
    || JSON.stringify(customDomainKeys) !== JSON.stringify(['custom_domain', 'pattern'])
  ) {
    throw new Error('wrangler config must declare only the exact 3dgen.hitsuki.space Custom Domain route');
  }
}


const scriptPath = fileURLToPath(import.meta.url);
if (process.argv[1] && path.resolve(process.argv[1]) === scriptPath) {
  validateWranglerConfig(path.resolve(path.dirname(scriptPath), '..', 'wrangler.jsonc'));
}
