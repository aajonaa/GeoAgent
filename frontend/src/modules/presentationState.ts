/**
 * Monotonic request sequence guard matching `window.GeoPresentationState`.
 */

export interface LatestRequestGuard {
  begin: () => number;
  current: (token: number) => boolean;
}

export function latestRequest(): LatestRequestGuard {
  let sequence = 0;
  return {
    begin: () => ++sequence,
    current: (token: number) => token === sequence,
  };
}

export const presentationStateApi = { latestRequest };
