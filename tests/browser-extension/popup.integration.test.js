'use strict';

const fs = require('fs');
const path = require('path');

const popupHtmlPath = path.resolve(__dirname, '../../browser-extension/popup.html');

function loadPopupDocument() {
  const html = fs.readFileSync(popupHtmlPath, 'utf8')
    .replace(/<!DOCTYPE html>/i, '')
    .replace(/<html[^>]*>/i, '')
    .replace(/<\/html>/i, '');
  document.documentElement.innerHTML = html;
}

async function bootstrapPopup(initialStorage = {}) {
  await chrome.storage.local.set(initialStorage);
  localStorage.clear();
  loadPopupDocument();
  document.dispatchEvent(new Event('DOMContentLoaded'));
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

function byId(id) {
  return document.getElementById(id);
}

describe('browser-extension/popup integration', () => {
  beforeAll(() => {
    loadBrowserScript('browser-extension/storage.js');
    loadBrowserScript('browser-extension/profile-data-us.js');
    loadBrowserScript('browser-extension/profile-generator.js');
    loadBrowserScript('browser-extension/popup.js');
  });

  test('side navigation switches between mailbox and profile pages', async () => {
    await bootstrapPopup();

    expect(byId('page-mail').classList.contains('active')).toBe(true);
    expect(byId('page-profile').classList.contains('active')).toBe(false);

    byId('nav-profile').click();

    expect(byId('page-profile').classList.contains('active')).toBe(true);
    expect(byId('page-mail').classList.contains('active')).toBe(false);

    byId('nav-mail').click();

    expect(byId('page-mail').classList.contains('active')).toBe(true);
    expect(byId('page-profile').classList.contains('active')).toBe(false);
  });

  test('profile fields are readonly and copy value on click with feedback', async () => {
    await bootstrapPopup();

    byId('nav-profile').click();
    byId('btn-generate-profile').click();

    await new Promise((resolve) => setTimeout(resolve, 0));

    const fieldIds = [
      'profile-first-name',
      'profile-last-name',
      'profile-full-name',
      'profile-username',
      'profile-password',
      'profile-email',
      'profile-phone',
      'profile-company',
      'profile-country',
      'profile-state',
      'profile-city',
      'profile-postal',
      'profile-address1',
      'profile-address2',
    ];

    fieldIds.forEach((fieldId) => {
      expect(byId(fieldId).readOnly).toBe(true);
    });

    const firstNameInput = byId('profile-first-name');
    const firstName = firstNameInput.value;
    firstNameInput.click();

    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(firstName);
    expect(firstNameInput.classList.contains('copied')).toBe(true);
    expect(byId('message-bar').textContent).toContain('已复制');
    expect(byId('message-bar').className).toContain('message-success');
  });

  test('profile generation can reuse the currently claimed mailbox email', async () => {
    await bootstrapPopup({
      currentTask: {
        email: 'claimed@example.com',
        taskId: 'task-1',
        claimedAt: '2026-04-20T00:00:00.000Z',
      },
    });

    byId('nav-profile').click();

    expect(byId('profile-use-claimed-email').disabled).toBe(false);
    expect(byId('profile-claimed-email-hint').textContent).toContain('claimed@example.com');

    byId('profile-use-claimed-email').checked = true;
    byId('profile-password-length').value = '14';
    byId('btn-generate-profile').click();

    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(byId('profile-email').value).toBe('claimed@example.com');
    expect(byId('profile-password').value).toHaveLength(14);
    expect(byId('profile-full-name').value).toMatch(/\S+\s+\S+/);
  });

  test('verification request carries claim token and retries a temporary miss', async () => {
    await bootstrapPopup({
      config: {
        serverUrl: 'http://localhost:5001',
        apiKey: 'test-key',
        defaultProjectKey: '',
      },
      currentTask: {
        email: 'claimed@example.com',
        taskId: 'task-1',
        claimToken: 'clm_test_token',
        claimedAt: '2026-04-20T00:00:00.000Z',
      },
    });

    let calls = 0;
    global.fetch = jest.fn(async () => {
      calls += 1;
      if (calls === 1) {
        return {
          ok: false,
          status: 404,
          json: async () => ({
            success: false,
            code: 'VERIFICATION_CODE_NOT_FOUND',
            message: '未找到验证码',
          }),
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          data: { verification_code: '123456' },
        }),
      };
    });

    jest.useFakeTimers();
    try {
      byId('btn-get-code').click();
      await Promise.resolve();
      await Promise.resolve();
      await jest.advanceTimersByTimeAsync(2000);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    } finally {
      jest.useRealTimers();
    }

    expect(global.fetch).toHaveBeenCalledTimes(2);
    const firstUrl = global.fetch.mock.calls[0][0];
    expect(firstUrl).toContain('claim_token=clm_test_token');
    expect(firstUrl).toContain('email=claimed%40example.com');
    expect(byId('result-value').textContent).toBe('123456');
  });
});
