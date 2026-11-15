"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function environment() {
  const nodes = new Map();
  for (const name of ["scheduleAuditFile", "scheduleAuditButton", "scheduleAuditAiButton",
    "scheduleAuditDropzone", "scheduleAuditResult", "scheduleAuditAiResult", "scheduleAuditFileName",
    "scheduleAuditFileActions", "scheduleAuditFormatGuide"]) {
    const classes = new Set();
    nodes.set(name, {disabled:false, textContent:"", innerHTML:"", hidden:false,
      files:[], value:"", setAttribute() {}, classList:{
        add(...names) {names.forEach(name => classes.add(name));},
        remove(...names) {names.forEach(name => classes.delete(name));},
        contains(name) {return classes.has(name);},
        toggle(name, enabled) {if (enabled) classes.add(name); else classes.delete(name);},
      }});
  }
  const pending = [];
  const context = vm.createContext({console,
    document:{querySelector: selector => nodes.get(selector.slice(1)) || null,
      getElementById: id => nodes.get(id) || null},
    window:{confirm:()=>true}, FormData:class {append() {}},
    fetch:()=>new Promise(resolve => pending.push(resolve)),
  });
  const root = path.resolve(__dirname, "..", "app", "static");
  for (const file of ["subject-catalog.js", "schedule-audit.js", "audit/data.js", "audit/workload.js",
    "audit/saved-limits.js", "audit/upload.js", "audit/editing.js", "audit/requests.js"]) {
    new vm.Script(fs.readFileSync(path.join(root, file), "utf8"), {filename:file}).runInContext(context);
  }
  Object.assign(context, {
    scheduleAuditAiIsEnabled:()=>true, hideScheduleAuditBottomScroller() {},
    renderScheduleAudit() {}, renderScheduleAuditAiLoading() {}, renderScheduleAuditAiResult() {},
    renderScheduleAuditAiError() {}, renderScheduleAuditError() {},
    renderScheduleAuditWifiLoader:()=>"loading", restoreSavedWeeklyLimits:async()=>{},
  });
  const report = {ok:true, viewer:{days:1, sessions:1, periods:5,
    classes:[{id:1,name:"6A1"}], cells:[{draft_id:1, slot:0, class_id:1,
      class_name:"6A1", subject_name:"Toán", teacher_name:"An"}]}, issues:[]};
  context.fixture = report;
  vm.runInContext("scheduleAuditSelectedFile = {name:'first.csv',size:1}; scheduleAuditLastReport = fixture;", context);
  const respond = data => pending.shift()({ok:true, status:200, text:async()=>JSON.stringify(data)});
  return {context, nodes, report, respond};
}

async function runAuditRequestTests() {
  {
    const {context, nodes, report, respond} = environment();
    const request = context.runScheduleAuditAI();
    assert.equal(nodes.get("scheduleAuditAiButton").disabled, true);
    context.selectScheduleAuditFile({name:"second.csv",size:1}, {autoRun:false});
    assert.equal(nodes.get("scheduleAuditAiButton").disabled, false);
    assert.equal(nodes.get("scheduleAuditAiButton").classList.contains("is-loading"), false);
    respond({ok:true, report, ai:{overview:"old result"}});
    await request;
    assert.equal(vm.runInContext("scheduleAuditLastReport", context), null);
  }
  {
    const {context, report, respond} = environment();
    const original = JSON.parse(JSON.stringify(report));
    const request = context.runScheduleAuditAI();
    assert.equal(context.applyScheduleAuditCellRename("teacher_name", 1, "Mai"), true);
    respond({ok:true, report:original, ai:{overview:"computed before edit"}});
    await request;
    assert.equal(vm.runInContext("scheduleAuditLastReport.viewer.cells[0].teacher_name", context), "Mai");
    assert.equal(vm.runInContext("scheduleAuditAiAnalysis", context), null);
  }
  {
    const {context, nodes, report, respond} = environment();
    const request = context.runScheduleAudit();
    context.selectScheduleAuditFile({name:"second.csv",size:1}, {autoRun:false});
    assert.equal(nodes.get("scheduleAuditButton").disabled, false);
    respond(report);
    await request;
    assert.equal(vm.runInContext("scheduleAuditLastReport", context), null);
  }
  return "3 file-audit request race checks passed.";
}

if (require.main === module) runAuditRequestTests().then(console.log).catch(error => {
  console.error(error); process.exitCode = 1;
});
module.exports = {runAuditRequestTests};
