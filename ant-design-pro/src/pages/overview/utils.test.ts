import { describe, expect, it } from 'vitest';
import {
  channelLabel,
  formatDurationMs,
  formatDurationSeconds,
  formatNumber,
  formatPercent,
  formatTime,
} from './utils';

describe('overview utils', () => {
  it('formats numbers', () => {
    expect(formatNumber(1234)).toBe('1,234');
    expect(formatNumber(undefined)).toBe('0');
  });

  it('formats percent from 0-1 and 0-100', () => {
    expect(formatPercent(0.856)).toBe('85.6%');
    expect(formatPercent(85.6)).toBe('85.6%');
    expect(formatPercent(0)).toBe('0.0%');
  });

  it('formats durations', () => {
    expect(formatDurationMs(250)).toBe('250ms');
    expect(formatDurationMs(2500)).toBe('2.50s');
    expect(formatDurationSeconds(45)).toBe('45s');
    expect(formatDurationSeconds(125)).toMatch(/2m/);
  });

  it('formats unix seconds time', () => {
    const text = formatTime(1700000000);
    expect(text).not.toBe('--');
    expect(text).not.toBe('1700000000');
  });

  it('maps channel labels', () => {
    expect(channelLabel('graph_inbox')).toBe('Graph Inbox');
    expect(channelLabel('x', 'Custom')).toBe('Custom');
    expect(channelLabel()).toBe('unknown');
  });
});
