"use strict";
// Same 16-row school subject catalog used for import, quotas, and automatic setup.
// Keep generic KHTN/LSĐL independent of their respective components.
const schoolSubjectCatalog = (() => {
  const order = [
    ["nvan", "N. Văn", ["van", "nguvan"]],
    ["toan", "Toán", []],
    ["tanh", "T.Anh", ["anh", "tienganh", "ngoaingutanh"]],
    ["gdcd", "GDCD", ["giaoduccongdan"]],
    ["lsdls", "LSĐL (S)", ["lsdlsu", "lsdllichsu", "su", "lichsu", "lichsuvadialilichsu", "lichsuvadialylichsu", "lichsuvadialysu"]],
    ["lsdld", "LSĐL (Đ)", ["lsdldia", "lsdldiali", "lsdldialy", "dia", "diali", "dialy", "lichsuvadialidia", "lichsuvadialidiali", "lichsuvadialydia", "lichsuvadialydiali"]],
    ["khtnl", "KHTN (L)", ["khtnli", "khtnly", "khtnvatli", "khtnvatly", "li", "ly", "vatli", "vatly", "khoahoctunhienvatli", "khoahoctunhienvatly"]],
    ["khtnh", "KHTN (H)", ["khtnhoa", "khtnhoahoc", "hoa", "hoahoc", "khoahoctunhienhoa", "khoahoctunhienhoahoc"]],
    ["khtns", "KHTN (S)", ["khtnsinh", "khtnsinhhoc", "sinh", "sinhhoc", "khoahoctunhiensinh", "khoahoctunhiensinhhoc"]],
    ["congnghe", "C.Nghệ", ["cnghe", "cn"]],
    ["tin", "Tin", ["tinhoc"]],
    ["gdtc", "GDTC", ["giaoducthechat", "theduc"]],
    ["ntnhac", "NT (Nhạc)", ["amnhac", "nghethuatamnhac", "gdnthamnhac"]],
    ["ntmythuat", "NT (MT)", ["ntmt", "ntmithuat", "mithuat", "mythuat", "nghethuatmithuat", "nghethuatmythuat"]],
    ["hdtnhn", "HĐTNHN", ["hdtnhuongnghiep", "hoatdongtrainghiemhuongnghiep"]],
    ["gddp", "GDĐP", ["giaoducdiaphuong"]],
  ];
  const alias = new Map(), names = new Map(), ranks = new Map();
  order.forEach(([code, name, alternatives], index) => {
    names.set(code, name); ranks.set(code, index);
    for (const key of [code, ...alternatives]) alias.set(key, code);
  });
  alias.set("khtn", "khtn"); alias.set("khoahoctunhien", "khtn");
  for (const extra of ["lsdl", "lichsuvadiali", "lichsuvadialy"]) alias.set(extra, "lsdl");
  function key(value) {
    const label = String(value ?? "").normalize("NFC").trim().toLocaleLowerCase("vi-VN");
    const token = label.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .replace(/đ/g, "d").replace(/[^a-z0-9]/g, "");
    return alias.get(token) || token || label;
  }
  function canonical(value) {
    const label = String(value ?? "").normalize("NFC").trim();
    return names.get(key(label)) || label;
  }
  function rank(value) {return ranks.get(key(value)) ?? order.length;}
  function compare(a, b) {
    return rank(a) - rank(b) || canonical(a).localeCompare(canonical(b), "vi", {numeric:true});
  }
  return Object.freeze({key, canonical, rank, compare, order:Object.freeze(order.map(x => x[1]))});
})();
