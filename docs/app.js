var EXPECTED_PACKAGE_NAMES = [
  'unifi-access-mcp',
  'unifi-api-server',
  'unifi-mcp-relay',
  'unifi-network-mcp',
  'unifi-protect-mcp'
];

var copyResetTimers = new WeakMap();

function activateTab(tab) {
  var tabList = tab.closest('[role="tablist"]');
  if (!tabList) return;

  var tabs = Array.from(tabList.querySelectorAll('[role="tab"]'));
  tabs.forEach(function (candidate) {
    var selected = candidate === tab;
    var panelId = candidate.getAttribute('aria-controls');
    var panel = panelId ? document.getElementById(panelId) : null;

    candidate.setAttribute('aria-selected', selected ? 'true' : 'false');
    candidate.tabIndex = selected ? 0 : -1;

    if (panel) {
      panel.hidden = !selected;
      panel.classList.toggle('active', selected);
    }
  });
}

function copyWithTextarea(text) {
  var previouslyFocused = document.activeElement;
  var textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();

  var copied = false;
  try {
    copied = document.execCommand('copy');
  } catch (error) {
    copied = false;
  } finally {
    textarea.remove();
    if (previouslyFocused && previouslyFocused.isConnected && typeof previouslyFocused.focus === 'function') {
      previouslyFocused.focus({ preventScroll: true });
    }
  }

  return copied;
}

function getCopyStatus(button) {
  var status = button.parentElement && button.parentElement.querySelector('[data-copy-status]');
  if (status) return status;

  status = document.createElement('span');
  status.setAttribute('data-copy-status', '');
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  status.style.position = 'absolute';
  status.style.width = '1px';
  status.style.height = '1px';
  status.style.padding = '0';
  status.style.margin = '-1px';
  status.style.overflow = 'hidden';
  status.style.clip = 'rect(0, 0, 0, 0)';
  status.style.whiteSpace = 'nowrap';
  status.style.border = '0';
  button.insertAdjacentElement('afterend', status);
  return status;
}

async function copyPanelCode(button) {
  var panel = button.closest('[data-install-panel]');
  var code = panel && panel.querySelector('code');
  if (!code) return;

  var copied = false;
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    try {
      await navigator.clipboard.writeText(code.innerText);
      copied = true;
    } catch (error) {
      copied = copyWithTextarea(code.innerText);
    }
  } else {
    copied = copyWithTextarea(code.innerText);
  }

  if (!copied) return;

  var status = getCopyStatus(button);
  var previousTimer = copyResetTimers.get(button);
  if (previousTimer) window.clearTimeout(previousTimer);

  button.classList.add('copied');
  status.textContent = 'Copied';
  copyResetTimers.set(button, window.setTimeout(function () {
    button.classList.remove('copied');
    status.textContent = '';
    copyResetTimers.delete(button);
  }, 1800));
}

function isNonNegativeInteger(value) {
  return Number.isInteger(value) && value >= 0;
}

function hasCompletePackageMap(packages) {
  if (!packages || typeof packages !== 'object' || Array.isArray(packages)) return false;

  var names = Object.keys(packages).sort();
  if (names.length !== EXPECTED_PACKAGE_NAMES.length) return false;

  return names.every(function (name, index) {
    return name === EXPECTED_PACKAGE_NAMES[index] && isNonNegativeInteger(packages[name]);
  });
}

function validProjectStats(snapshot) {
  if (!snapshot || typeof snapshot !== 'object' || snapshot.schema_version !== 1) return false;
  if (!snapshot.python || !snapshot.containers || !snapshot.community || !snapshot.github) return false;
  if (!hasCompletePackageMap(snapshot.python.packages)) return false;
  if (!hasCompletePackageMap(snapshot.containers.packages)) return false;
  if (typeof snapshot.generated_at !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(snapshot.generated_at)) {
    return false;
  }

  var generatedAt = new Date(snapshot.generated_at);
  var canonicalGeneratedAt = snapshot.generated_at.slice(0, -1) + '.000Z';
  return !Number.isNaN(generatedAt.getTime()) && generatedAt.toISOString() === canonicalGeneratedAt &&
    isNonNegativeInteger(snapshot.python.total) &&
    isNonNegativeInteger(snapshot.containers.total) &&
    isNonNegativeInteger(snapshot.community.merged_pull_requests) &&
    isNonNegativeInteger(snapshot.community.contributors) &&
    isNonNegativeInteger(snapshot.github.stars);
}

function setText(selector, text) {
  document.querySelectorAll(selector).forEach(function (node) {
    node.textContent = text;
  });
}

function formatStars(value) {
  return '★ ' + new Intl.NumberFormat().format(value);
}

function renderProjectStats(snapshot) {
  if (!validProjectStats(snapshot)) return;

  var numberFormat = new Intl.NumberFormat();
  var generatedAt = new Date(snapshot.generated_at);
  var dateText = new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC'
  }).format(generatedAt);

  setText('[data-stat="python"]', numberFormat.format(snapshot.python.total));
  setText('[data-stat="containers"]', numberFormat.format(snapshot.containers.total));
  setText('[data-stat="community"]', numberFormat.format(snapshot.community.merged_pull_requests));
  setText('[data-stat="contributors"]', numberFormat.format(snapshot.community.contributors));
  setText('[data-stat="updated"]', dateText);
  setText('[data-stars]', formatStars(snapshot.github.stars));
}

async function fetchJSON(url) {
  try {
    var response = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!response.ok) return null;
    return await response.json();
  } catch (error) {
    return null;
  }
}

async function refreshStars(fallback) {
  if (isNonNegativeInteger(fallback)) setText('[data-stars]', formatStars(fallback));

  var repository = await fetchJSON('https://api.github.com/repos/sirkirby/unifi-mcp');
  if (repository && isNonNegativeInteger(repository.stargazers_count)) {
    setText('[data-stars]', formatStars(repository.stargazers_count));
  }
}

async function refreshPackageVersions() {
  if (!document.querySelector('[data-pkg-version], [data-npm-version]')) return;

  var pythonPackages = [
    'unifi-network-mcp',
    'unifi-protect-mcp',
    'unifi-access-mcp',
    'unifi-api-server',
    'unifi-mcp-relay'
  ];

  var requests = pythonPackages.map(async function (packageName) {
    var result = await fetchJSON('https://pypi.org/pypi/' + packageName + '/json');
    if (result && result.info && typeof result.info.version === 'string' && result.info.version) {
      setText('[data-pkg-version="' + packageName + '"]', 'v' + result.info.version);
    }
  });

  requests.push((async function () {
    var result = await fetchJSON('https://registry.npmjs.org/unifi-mcp-worker/latest');
    if (result && typeof result.version === 'string' && result.version) {
      setText('[data-npm-version="unifi-mcp-worker"]', 'v' + result.version);
    }
  })());

  await Promise.all(requests);
}

document.querySelectorAll('[data-install-tab]').forEach(function (tab) {
  tab.addEventListener('click', function () {
    activateTab(tab);
  });

  tab.addEventListener('keydown', function (event) {
    var tabs = Array.from(tab.closest('[role="tablist"]').querySelectorAll('[role="tab"]'));
    var index = tabs.indexOf(tab);
    var target = null;

    if (event.key === 'ArrowRight') target = tabs[(index + 1) % tabs.length];
    if (event.key === 'ArrowLeft') target = tabs[(index - 1 + tabs.length) % tabs.length];
    if (event.key === 'Home') target = tabs[0];
    if (event.key === 'End') target = tabs[tabs.length - 1];
    if (event.key === 'Enter' || event.key === ' ') target = tab;
    if (!target) return;

    event.preventDefault();
    activateTab(target);
    target.focus();
  });
});

document.querySelectorAll('[data-copy]').forEach(function (button) {
  button.addEventListener('click', function () {
    copyPanelCode(button);
  });
});

(async function loadProjectStats() {
  var snapshot = await fetchJSON('/data/project-stats.json');
  var fallbackStars = null;

  if (validProjectStats(snapshot)) {
    renderProjectStats(snapshot);
    fallbackStars = snapshot.github.stars;
  }

  await refreshStars(fallbackStars);
})();

refreshPackageVersions();
