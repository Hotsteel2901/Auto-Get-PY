/**
 * Agents: the integration surface, in the UI.
 *
 * Lists every supported tool, its URL alias, the files it reads, and gives a
 * copy-ready snippet so wiring a new agent up takes seconds.
 */

import {
  $, banner, codeBlock, copyText, emptyState, h, icon, kvRow, modal, skeletonList,
} from '../core.js';
import { api } from '../api.js';
import { t } from '../i18n.js';

let agents = [];

export const agentsPage = {
  id: 'agents',
  titleKey: 'agents.title',
  subtitleKey: 'agents.subtitle',
  icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M12 8V4M9 14h.01M15 14h.01M8 20v2M16 20v2"/></svg>',

  async mount(container) {
    container.append(
      h('div#agents-intro'),
      h('div#agents-body', skeletonList(4)),
    );
    await load();
  },
};

async function load() {
  const body = $('#agents-body');
  const intro = $('#agents-intro');
  if (!body) return;

  try {
    const [manifest, list] = await Promise.all([
      api.agents.manifest(),
      api.agents.list(),
    ]);
    agents = list.agents || [];

    intro?.replaceChildren(banner({
      tone: 'info',
      title: t('agents.intro.title'),
      message: t('agents.intro.message', { prefix: manifest.canonical_prefix }),
    }));

    render(manifest);
  } catch (error) {
    body.replaceChildren(emptyState({
      iconName: 'alert',
      title: t('agents.error.title'),
      message: error.message,
    }));
  }
}

function render(manifest) {
  const body = $('#agents-body');
  if (!body) return;

  body.replaceChildren(
    h('div.card', [
      h('div.card-head', [
        h('h2', t('agents.mcp')),
        h('span.card-sub', t('agents.mcp.hint')),
      ]),
      h('p', { style: { fontSize: '13px', color: 'var(--text-soft)' } }, t('agents.mcp.desc')),
      codeBlock(JSON.stringify({
        mcpServers: {
          'auto-get-py': {
            command: 'python',
            args: ['mcp_server.py'],
            env: { AUTO_GET_BASE_URL: location.origin },
          },
        },
      }, null, 2), { language: 'json' }),
    ]),

    h('div.card', [
      h('div.card-head', [
        h('h2', t('agents.quickstart')),
        h('span.card-sub', t('agents.quickstart.hint')),
      ]),
      h('div.steps', [
        step(1, t('agents.step1.title'), t('agents.step1.desc'),
          codeBlock(`curl ${location.origin}/api/health`)),
        step(2, t('agents.step2.title'), t('agents.step2.desc'),
          codeBlock(`curl -s ${location.origin}/api/agent/quick \\
  -H 'Content-Type: application/json' \\
  -d '{"url":"https://example.com","crawl_depth":2}'`)),
        step(3, t('agents.step3.title'), t('agents.step3.desc'),
          codeBlock(`curl -s ${location.origin}/api/agent/scrape \\
  -H 'Content-Type: application/json' \\
  -d '{"url":"https://example.com","wait":true,"crawl_depth":2}'`)),
      ]),
    ]),

    h('div.card.flush', [
      h('div.card-head', [
        h('h2', t('agents.supported', { n: agents.length })),
        h('span.card-sub', t('agents.supported.hint')),
      ]),
      h('div.table-wrap', h('table', [
        h('thead', h('tr', [
          h('th', t('agents.col.tool')),
          h('th', t('agents.col.vendor')),
          h('th', t('agents.col.alias')),
          h('th', t('agents.col.config')),
          h('th.actions', ''),
        ])),
        h('tbody', agents.map(buildRow)),
      ])),
    ]),

    h('div.card', [
      h('div.card-head', [h('h2', t('agents.manifest'))]),
      h('p', {
        style: { fontSize: '12.5px', color: 'var(--text-muted)', marginBottom: 'var(--s3)' },
      }, t('agents.manifest.hint')),
      h('div.chip-group', (manifest.capabilities || []).map((capability) =>
        h('span.tag', capability))),
      h('div.btn-row', { style: { marginTop: 'var(--s4)' } }, [
        h('a.btn', {
          href: '/api/agent/manifest', target: '_blank', rel: 'noopener noreferrer',
        }, [icon('external'), t('agents.openManifest')]),
        h('a.btn.btn-ghost', {
          href: '/docs', target: '_blank', rel: 'noopener noreferrer',
        }, [icon('code'), t('agents.openApi')]),
      ]),
    ]),
  );
}

function buildRow(agent) {
  return h('tr', [
    h('td', [
      h('div.cell-strong', agent.name),
      agent.docs_url
        ? h('a.cell-mono', {
            href: agent.docs_url, target: '_blank', rel: 'noopener noreferrer',
          }, agent.docs_url.replace(/^https?:\/\//, ''))
        : null,
    ]),
    h('td', { style: { color: 'var(--text-muted)' } }, agent.vendor),
    h('td', h('div', { style: { display: 'flex', flexDirection: 'column', gap: '2px' } },
      (agent.aliases || []).map((alias) => h('span.tag', alias)))),
    h('td', h('div', { style: { display: 'flex', flexDirection: 'column', gap: '2px' } },
      (agent.config_files || []).length
        ? agent.config_files.map((path) => h('span.cell-mono', path))
        : h('span', { style: { color: 'var(--text-faint)' } }, '—'))),
    h('td.actions', h('button.btn.btn-sm', {
      type: 'button', onclick: () => showAgent(agent),
    }, t('action.setup'))),
  ]);
}

function step(number, title, description, code = null) {
  return h('div.step', [
    h('span.step-num', String(number)),
    h('div.step-body', [
      h('h4', title),
      h('p', description),
      code,
    ]),
  ]);
}

function showAgent(agent) {
  // The registry sends `aliases` (tool-specific paths) and `api_prefix` (the
  // canonical one); the snippet should use the tool's own path.
  const alias = agent.aliases?.[0] || agent.api_prefix || '/api/agent';
  const skillUrl = `${location.origin}${alias}/skill?agent=${agent.id}`;

  modal({
    title: agent.name,
    width: 640,
    build: () => h('div', [
      h('div.kv-list', [
        kvRow(t('agents.detail.vendor'), agent.vendor),
        kvRow(t('agents.detail.alias'), h('div', {
          style: { display: 'flex', gap: '6px', flexWrap: 'wrap' },
        }, (agent.aliases || []).map((entry) => h('span.tag', entry)))),
        kvRow(t('agents.detail.canonical'), h('span.tag', '/api/agent')),
        kvRow(t('agents.detail.skill'), h('a.cell-mono', {
          href: skillUrl, target: '_blank', rel: 'noopener noreferrer',
        }, t('agents.detail.open'))),
      ]),
      agent.notes
        ? h('div.banner.banner-info', { style: { marginTop: 'var(--s4)' } },
            [icon('info'), h('div.banner-body', agent.notes)])
        : null,

      h('h3', { style: { margin: 'var(--s5) 0 var(--s2)', fontSize: '13px' } },
        t('agents.detail.setup')),
      h('p', { style: { fontSize: '12.5px', color: 'var(--text-soft)' } },
        agent.install || ''),

      agent.config_files?.length
        ? h('div', [
            h('h3', { style: { margin: 'var(--s5) 0 var(--s2)', fontSize: '13px' } },
              t('agents.detail.files')),
            h('div', { style: { display: 'flex', flexDirection: 'column', gap: '3px' } },
              agent.config_files.map((path) => h('span.cell-mono', path))),
          ])
        : null,

      h('h3', { style: { margin: 'var(--s5) 0 var(--s2)', fontSize: '13px' } },
        t('agents.detail.call')),
      codeBlock(`curl -s ${location.origin}${alias}/quick \\
  -H 'Content-Type: application/json' \\
  -d '{"url":"https://example.com","crawl_depth":2}'`),
    ]),
    actions: [
      {
        label: t('agents.detail.copySkill'),
        variant: 'btn-ghost',
        onClick: () => copyText(skillUrl, t('agents.detail.skillCopied')),
      },
      { label: t('action.close'), variant: 'btn-primary' },
    ],
  });
}
