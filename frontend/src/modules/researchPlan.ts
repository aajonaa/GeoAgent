import type { ResearchPlan } from '../types/api';

/**
 * Typed research-plan validation and receipt rendering matching `window.GeoAgentPlan`
 * and backend `server_helpers._PLAN_TEXT_LIMITS`.
 */

export type PlanTextField = 'objective' | 'scope' | 'materials' | 'tools' | 'deliverables';

export const PLAN_DEFINITIONS: ReadonlyArray<readonly [PlanTextField, string]> = [
  ['objective', '研究目标'],
  ['scope', '研究范围'],
  ['materials', '资料与数据'],
  ['tools', '工具与技能'],
  ['deliverables', '预期成果'],
];

export const PLAN_TEXT_LIMITS: Readonly<Record<PlanTextField, number>> = {
  objective: 500,
  scope: 1000,
  materials: 1000,
  tools: 500,
  deliverables: 1000,
};

export const PLAN_ACCEPTANCE_MAX_ITEMS = 5;
export const PLAN_ACCEPTANCE_MAX_LENGTH = 300;

export const DEFAULT_RESEARCH_PLAN: Readonly<ResearchPlan> = {
  objective: '',
  scope: '围绕研究问题确定；无额外限制',
  materials: '可使用已上传文件、知识库与公开资料',
  tools: '由 Agent 按需选择技能与工具',
  deliverables: '给出结论、关键证据与结果文件（如适用）',
  acceptance: ['结论回应研究问题', '关键判断引用可追溯来源', '说明数据或方法局限'],
};

export interface ResearchPlanValidationResult {
  valid: boolean;
  message?: string;
  fieldId?: string;
}

export function validateResearchPlan(plan: ResearchPlan): ResearchPlanValidationResult {
  for (const [field, label] of PLAN_DEFINITIONS) {
    const value = typeof plan[field] === 'string' ? plan[field].trim() : '';
    if (!value) {
      return { valid: false, message: `请填写${label}后再确认。`, fieldId: `plan-${field}` };
    }
    const limit = PLAN_TEXT_LIMITS[field];
    if (value.length > limit) {
      return {
        valid: false,
        message: `${label}不能超过 ${limit} 个字符。`,
        fieldId: `plan-${field}`,
      };
    }
  }
  const acceptance = Array.isArray(plan.acceptance)
    ? plan.acceptance.map((item) => String(item).trim()).filter(Boolean)
    : [];
  if (!acceptance.length) {
    return { valid: false, message: '请至少填写一条验收标准。', fieldId: 'plan-acceptance' };
  }
  if (acceptance.length > PLAN_ACCEPTANCE_MAX_ITEMS) {
    return {
      valid: false,
      message: `验收标准请控制在 ${PLAN_ACCEPTANCE_MAX_ITEMS} 条以内。`,
      fieldId: 'plan-acceptance',
    };
  }
  if (acceptance.some((item) => item.length > PLAN_ACCEPTANCE_MAX_LENGTH)) {
    return {
      valid: false,
      message: `每条验收标准不能超过 ${PLAN_ACCEPTANCE_MAX_LENGTH} 个字符。`,
      fieldId: 'plan-acceptance',
    };
  }
  return { valid: true };
}

function createNode<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  text?: string,
  className?: string,
): HTMLElementTagNameMap[K] {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}

export function renderPlanReceipt(plan: ResearchPlan | null | undefined): HTMLDetailsElement | null {
  if (!plan || typeof plan !== 'object' || !Array.isArray(plan.acceptance)) return null;
  const box = createNode('details', undefined, 'run-plan');
  box.dataset.planReceipt = '';
  const summary = createNode('summary', undefined, 'run-plan-summary');
  summary.append(
    createNode('span', '研究计划与验收标准 · 已确认'),
    createNode('small', `验收 ${plan.acceptance.length} 项`),
  );
  const body = createNode('div', undefined, 'run-plan-body');
  const list = createNode('dl');
  for (const [field, label] of PLAN_DEFINITIONS) {
    const value = plan[field];
    if (typeof value !== 'string' || !value) continue;
    const row = createNode('div', undefined, 'run-plan-field');
    row.append(createNode('dt', label), createNode('dd', value));
    list.append(row);
  }
  body.append(list, createNode('h3', '验收标准 · 随结果核对'));
  const acceptance = createNode('ol');
  for (const item of plan.acceptance) {
    if (typeof item === 'string' && item) {
      acceptance.append(createNode('li', item));
    }
  }
  body.append(acceptance);
  box.append(summary, body);
  return box;
}
