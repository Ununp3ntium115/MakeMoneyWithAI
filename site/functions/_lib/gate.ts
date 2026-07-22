import type { SubClaim } from './cookie';

export function needsReverify(claim: SubClaim, now: number): boolean {
  return now - claim.verified_at > 86400;
}
