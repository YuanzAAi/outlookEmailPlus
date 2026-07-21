const fs = require('fs');
const path = require('path');
const { webcrypto } = require('node:crypto');

const repoRoot = path.resolve(__dirname, '../..');

function createStorageArea(initialState = {}) {
  const store = { ...initialState };

  return {
    async get(keys) {
      if (typeof keys === 'string') {
        return { [keys]: store[keys] };
      }
      if (Array.isArray(keys)) {
        return keys.reduce((acc, key) => {
          acc[key] = store[key];
          return acc;
        }, {});
      }
      if (!keys || typeof keys !== 'object') {
        return { ...store };
      }
      return Object.keys(keys).reduce((acc, key) => {
        acc[key] = Object.prototype.hasOwnProperty.call(store, key) ? store[key] : keys[key];
        return acc;
      }, {});
    },

    async set(items) {
      Object.assign(store, items);
    },

    async clear() {
      Object.keys(store).forEach((key) => delete store[key]);
    },

    dump() {
      return JSON.parse(JSON.stringify(store));
    },
  };
}

function loadBrowserScript(relativePath) {
  const fullPath = path.join(repoRoot, relativePath);
  const code = fs.readFileSync(fullPath, 'utf8');
  window.eval(code);
}

function readLexicalBinding(name) {
  const token = `__binding_${name}`;
  window.eval(`window.${token} = typeof ${name} !== 'undefined' ? ${name} : undefined;`);
  const value = window[token];
  delete window[token];
  return value;
}

global.loadBrowserScript = loadBrowserScript;
global.readLexicalBinding = readLexicalBinding;

beforeEach(() => {
  document.documentElement.innerHTML = '<head></head><body></body>';
  jest.restoreAllMocks();
  jest.clearAllMocks();

  global.chrome = {
    storage: {
      local: createStorageArea(),
    },
    permissions: {
      request: jest.fn(async () => true),
    },
    tabs: {
      create: jest.fn(),
    },
  };

  Object.defineProperty(global, 'crypto', {
    value: webcrypto,
    configurable: true,
  });

  Object.defineProperty(navigator, 'clipboard', {
    value: {
      writeText: jest.fn(async () => undefined),
    },
    configurable: true,
  });
});

afterEach(() => {
  delete global.chrome;
  delete global.fetch;
});
