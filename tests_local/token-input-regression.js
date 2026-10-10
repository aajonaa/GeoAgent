'use strict';
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../geological_agent/team/web/app.js'), 'utf8');
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(source.slice(source.indexOf('function parseTokenValue('), source.indexOf("for (const id of ['model-context-window', 'model-max-output'])")), sandbox);
for (const [text, number] of [['1,000,000',1000000],['128,000',128000],['1000000',1000000],[' 128,000 ',128000],['9,007,199,254,740,991',Number.MAX_SAFE_INTEGER]]) {
  assert.equal(sandbox.parseTokenValue(text), number);
  assert.equal(sandbox.parseTokenValue(sandbox.formatTokenValue(number)), number);
}
for (const text of ['', '0', '-1', '1.5', '1e6', '1,00,000', '128,00', '1,,000', '1 000', 'NaN', 'Infinity', '9,007,199,254,740,992']) assert(Number.isNaN(sandbox.parseTokenValue(text)), text);
assert.equal(sandbox.formatTokenValue(1000000), '1,000,000');
assert.equal(sandbox.formatTokenValue(128000), '128,000');
const events = {}, field = {value:'128000', addEventListener:(event, fn) => {events[event] = fn;}};
sandbox.bindTokenInput(field); assert.equal(field.type, 'text'); assert.equal(field.inputMode, 'numeric');
events.blur(); assert.equal(field.value, '128,000');
field.value = '128,00'; events.blur(); assert.equal(field.value, '128,00', 'Invalid grouping stays invalid rather than changing a budget');
assert.equal(JSON.stringify({max_output_tokens:sandbox.parseTokenValue('128,000')}), '{"max_output_tokens":128000}');
console.log('Grouped token display, strict integer parsing, blur formatting and numeric JSON payload passed');
