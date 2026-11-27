/**
 * OreBOGAO Progressive TypeScript Core Entry & Legacy Global Bridge.
 *
 * Compiled to CSP-safe IIFE `geological_agent/team/web/bundles/core-bridge.js`
 * exposing `window.OreBogaoCore`, while remaining importable as standard ES modules
 * during incremental migration of the legacy vanilla JS scripts.
 */

export * from './types/api';
export { ApiError, createApiClient, type ApiClientHooks, type ApiRequestOptions } from './api/client';
export { latestRequest, presentationStateApi, type LatestRequestGuard } from './modules/presentationState';
export { createDraftsStore, type DraftsApi, type DraftsOptions } from './modules/drafts';
export {
  RECOVERY_SPECS,
  createRecoveryController,
  describeRecovery,
  type RecoveryController,
  type RecoveryHooks,
  type RecoveryRunUi,
  type RecoveryView,
} from './modules/recovery';
export {
  DEFAULT_RESEARCH_PLAN,
  PLAN_ACCEPTANCE_MAX_ITEMS,
  PLAN_ACCEPTANCE_MAX_LENGTH,
  PLAN_DEFINITIONS,
  PLAN_TEXT_LIMITS,
  renderPlanReceipt,
  validateResearchPlan,
  type PlanTextField,
  type ResearchPlanValidationResult,
} from './modules/researchPlan';

import { createApiClient } from './api/client';
import { createDraftsStore } from './modules/drafts';
import { latestRequest } from './modules/presentationState';
import { createRecoveryController, describeRecovery } from './modules/recovery';
import { renderPlanReceipt, validateResearchPlan } from './modules/researchPlan';

export const CORE_VERSION = '0.32.0-p2-3';

export interface InstallLegacyGlobalsOptions {
  force?: boolean;
}

/**
 * Optionally binds TypeScript-compiled modules onto legacy window globals.
 * By default (`force = false`) it never overwrites globals already registered
 * by legacy scripts, ensuring zero-risk progressive rollout.
 */
export function installLegacyGlobals(options: InstallLegacyGlobalsOptions = {}): string[] {
  if (typeof window === 'undefined') return [];
  const force = options.force === true;
  const win = window as unknown as Record<string, unknown>;
  const installed: string[] = [];

  if (force || !win.GeoPresentationState) {
    win.GeoPresentationState = { latestRequest };
    installed.push('GeoPresentationState');
  }
  if (force || !win.OreSageDrafts) {
    win.OreSageDrafts = createDraftsStore();
    installed.push('OreSageDrafts');
  }
  if (force || !win.GeoAgentRecovery) {
    win.GeoAgentRecovery = createRecoveryController();
    installed.push('GeoAgentRecovery');
  }
  return installed;
}

export const OreBogaoCore = {
  version: CORE_VERSION,
  createApiClient,
  latestRequest,
  createDraftsStore,
  createRecoveryController,
  describeRecovery,
  validateResearchPlan,
  renderPlanReceipt,
  installLegacyGlobals,
};

if (typeof window !== 'undefined') {
  (window as unknown as Record<string, unknown>).OreBogaoCore = OreBogaoCore;
}
