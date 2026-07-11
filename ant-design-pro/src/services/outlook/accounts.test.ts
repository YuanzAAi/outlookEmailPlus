import { describe, expect, it } from 'vitest';
import {
  getResponseHeader,
  isHttpOk,
  parseContentDispositionFilename,
  parseSseDataLines,
} from './accounts';

describe('parseSseDataLines', () => {
  it('parses complete SSE data lines and keeps partial carry', () => {
    const first = parseSseDataLines(
      'data: {"type":"start","total":2,"skipped_count":1}\n\ndata: {"type":"progress","current":1',
    );
    expect(first.events).toEqual([
      { type: 'start', total: 2, skipped_count: 1 },
    ]);
    expect(first.rest.startsWith('data: {"type":"progress"')).toBe(true);

    const second = parseSseDataLines(
      ',"total":2,"result":"success"}\n\ndata: {"type":"complete","total":2,"success_count":2,"failed_count":0}\n\n',
      first.rest,
    );
    expect(second.events.map((e) => e.type)).toEqual([
      'progress',
      'complete',
    ]);
    expect(second.rest).toBe('');
  });

  it('ignores malformed JSON lines', () => {
    const parsed = parseSseDataLines(
      'data: not-json\ndata: {"type":"delay","seconds":1.5}\n',
    );
    expect(parsed.events).toEqual([{ type: 'delay', seconds: 1.5 }]);
  });
});

describe('export response helpers', () => {
  it('isHttpOk supports fetch Response.ok and axios status', () => {
    expect(isHttpOk({ ok: true, status: 200 })).toBe(true);
    expect(isHttpOk({ ok: false, status: 500 })).toBe(false);
    expect(isHttpOk({ status: 200 })).toBe(true);
    expect(isHttpOk({ status: 404 })).toBe(false);
    expect(isHttpOk(undefined)).toBe(false);
    expect(isHttpOk({ headers: {}, data: new Blob() })).toBe(true);
  });

  it('getResponseHeader supports Headers.get and plain object', () => {
    const headers = new Headers({
      'Content-Disposition':
        "attachment; filename*=UTF-8''accounts_export_selected_20260711.txt",
    });
    expect(getResponseHeader({ headers }, 'Content-Disposition')).toContain(
      'accounts_export_selected_20260711.txt',
    );

    expect(
      getResponseHeader(
        {
          headers: {
            'content-disposition':
              'attachment; filename="plain_export.txt"',
          },
        },
        'Content-Disposition',
      ),
    ).toBe('attachment; filename="plain_export.txt"');
  });

  it('parseContentDispositionFilename handles UTF-8 and plain forms', () => {
    expect(
      parseContentDispositionFilename(
        "attachment; filename*=UTF-8''accounts_export_selected_20260711.txt",
        'fallback.txt',
      ),
    ).toBe('accounts_export_selected_20260711.txt');

    expect(
      parseContentDispositionFilename(
        'attachment; filename="plain_export.txt"',
        'fallback.txt',
      ),
    ).toBe('plain_export.txt');

    expect(parseContentDispositionFilename(null, 'fallback.txt')).toBe(
      'fallback.txt',
    );
  });
});
