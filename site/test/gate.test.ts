import { describe, it, expect } from 'vitest';
import { needsReverify } from '../functions/_lib/gate';

describe('needsReverify', () => {
  it('is false within 24h', () => {
    expect(needsReverify({ email: 'a@b.com', verified_at: 1000 }, 1000 + 86399)).toBe(false);
  });
  it('is true after 24h', () => {
    expect(needsReverify({ email: 'a@b.com', verified_at: 1000 }, 1000 + 86401)).toBe(true);
  });
});
