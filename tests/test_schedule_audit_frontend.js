"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function runAuditFrontendTests() {
  const root = path.resolve(__dirname, "..");
  const context = vm.createContext({console});
  for (const file of ["subject-catalog.js", "audit/data.js", "audit/workload.js", "audit/saved-limits.js"]) {
    new vm.Script(fs.readFileSync(path.join(root, "app/static", file), "utf8"), {filename:file})
      .runInContext(context);
  }
  const names = ["Nguyễn Văn An", "Nguyễn Văn Ân"];
  const cells = names.map((name, i) => ({draft_id:i+1, slot:i, class_id:1,
    class_name:"6A1", subject_name:"Toán", teacher_name:name}));
  const report = {viewer:{classes:[{id:1, name:"6A1"}], cells}};
  const saved = {class_subject:[], assignments:names.map((teacher, i) =>
    ({teacher, class_name:"6A1", subject:"Toán", periods:i+1}))};
  let passed = 0;
  const check = (name, callback) => {callback(); passed++;};

  check("draft keeps distinct teacher identities", () => {
    assert.equal(context.weeklyMakeLimitDraft(report).assignments.length, 2);
  });
  check("catalog keeps both names", () => {
    assert.equal(context.weeklyCatalogFromReport(report).teachers.length, 2);
  });
  check("saved assignment keys do not collide", () => {
    assert.notEqual(context.weeklyRowKey("assignments", saved.assignments[0]),
      context.weeklyRowKey("assignments", saved.assignments[1]));
  });
  check("matrix counts remain separate", () => {
    context.scheduleAuditLastReport = report;
    const counts = context.weeklyMatrixActualCounts();
    assert.equal(counts.size, 2);
    assert.ok([...counts.values()].every(value => value === 1));
  });
  check("restoring saved limits retains both quotas", () => {
    const catalog = context.weeklyCatalogFromReport(report);
    const merged = context.weeklyMergeLimits(saved, context.weeklyMakeLimitDraft(report), catalog, true);
    assert.equal(merged.assignments.length, 2);
    assert.equal(merged.assignments[0].periods, 1);
    assert.equal(merged.assignments[1].periods, 2);
  });
  check("catalog detects replacing one teacher with the other", () => {
    const changes = context.weeklyCatalogChanges({teachers:[names[0]]}, {teachers:[names[1]]});
    assert.equal(changes.teachers.removed[0], names[0]);
    assert.equal(changes.teachers.added[0], names[1]);
  });
  check("Unicode composition and casing still identify the same teacher", () => {
    assert.equal(context.scheduleAuditIdentityKey(names[1]),
      context.scheduleAuditIdentityKey(names[1].normalize("NFD").toUpperCase()));
  });
  return `${passed} file-audit frontend checks passed.`;
}

if (require.main === module) {
  console.log(runAuditFrontendTests());
  require("./test_schedule_audit_requests.js").runAuditRequestTests().then(console.log).catch(error => {
    console.error(error); process.exitCode = 1;
  });
}
module.exports = {runAuditFrontendTests};
