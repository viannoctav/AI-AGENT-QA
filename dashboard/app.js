/* Dashboard lokal TƎRᗩ (Asisten QA berbasis AI) - semua layar dalam satu file.
   Data diambil dari dashboard.py lewat /api/...; progres live lewat Server-Sent Events. */
"use strict";

const app = document.getElementById("app");
const S = {
  overview: null,      // ringkasan untuk menu samping dan Beranda
  config: null,        // pengaturan saat ini (untuk "percobaan k dari N")
  hasil: { runId: null, run: null, tcs: [], filters: { q: "", mod: "", tek: "", kat: "", flag: false }, page: 0, sel: null },
  live: null,          // status run berjalan, dibangun dari event
  es: null,            // EventSource aktif
  compare: new Set(),  // id run yang dipilih di Riwayat
};
const PAGE = 25;

/* ================================================================= util */
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v) => (v === null || v === undefined || v === "" ? "-" : Number(v).toLocaleString("id-ID"));

async function api(path, opts = {}) {
  const init = { ...opts };
  if (init.body && typeof init.body !== "string") {
    init.body = JSON.stringify(init.body);
    init.headers = { "Content-Type": "application/json" };
  }
  const r = await fetch(path, init);
  let data = null;
  try { data = await r.json(); } catch (e) { /* bukan JSON */ }
  if (!r.ok) {
    const err = new Error((data && data.detail) || `Server menjawab ${r.status}`);
    err.field = data && data.field; // id isian yang salah (validasi server)
    throw err;
  }
  return data;
}

/* ================================================================= VALIDASI
   Aturan sama dengan tools/form_rules.py di server. Error tampil di bawah isian yang salah. */
const V = {
  FORBIDDEN: '\\/:*?"<>|',
  alnum: (s) => (String(s).match(/[\p{L}\p{N}]/gu) || []).length,
  readable: (s) => new Set((String(s).toLowerCase().match(/[\p{L}\p{N}]/gu) || [])).size >= 4,
  fmt: (n) => n.toLocaleString("id-ID"),
  name(value, label = "Nama modul") {
    const raw = String(value ?? "");
    const v = raw.replace(/\s+/g, " ").trim();
    if (!v) return `${label} wajib diisi.`;
    if (/[\r\n\t]/.test(raw.trim())) return `${label} harus satu baris.`;
    if (v.length < 3) return `${label} minimal 3 karakter.`;
    if (v.length > 80) return `${label} maksimal 80 karakter.`;
    if ([...v].some((c) => V.FORBIDDEN.includes(c) || c.charCodeAt(0) < 32)) return `${label} tidak boleh memakai karakter ${[...V.FORBIDDEN].join(" ")}`;
    if (!/\p{L}/u.test(v)) return `${label} harus mengandung huruf, tidak boleh hanya angka atau simbol.`;
    return "";
  },
  notes(value, label = "Catatan QA") {
    const v = String(value ?? "");
    if (!v.trim()) return `${label} wajib diisi.`;
    if (v.length > 200000) return `${label} terlalu panjang (maksimal ${V.fmt(200000)} karakter).`;
    if (V.alnum(v) < 20 || v.trim().split(/\s+/).length < 3) return `${label} terlalu pendek. Minimal 20 huruf/angka dan 3 kata.`;
    if (!V.readable(v)) return `${label} tidak berisi kalimat yang bisa dibaca.`;
    return "";
  },
  optional(value, label) {
    const v = String(value ?? "");
    if (!v.trim()) return "";
    if (v.length > 50000) return `${label} terlalu panjang (maksimal ${V.fmt(50000)} karakter).`;
    if (V.alnum(v) < 10) return `${label} terlalu pendek untuk disusun menjadi aturan (minimal 10 huruf/angka). Kosongkan bila tidak perlu.`;
    if (!V.readable(v)) return `${label} tidak berisi kalimat yang bisa dibaca.`;
    return "";
  },
  image(file) {
    if (!/\.(png|jpe?g|webp)$/i.test(file.name) || (file.type && !/^image\/(png|jpeg|webp)$/.test(file.type))) return `${file.name}: format harus PNG, JPG, atau WEBP.`;
    if (!file.size) return `${file.name}: file kosong.`;
    if (file.size > 40 * 1024 * 1024) return `${file.name}: ukuran file maksimal 40 MB.`;
    return "";
  },
  prd(content) {
    const v = String(content ?? "");
    if (!v.trim()) return "Isi PRD kosong.";
    if (new Blob([v]).size > 2000000) return "PRD terlalu besar (maksimal 2 MB).";
    if (!/^#\s+\S/m.test(v)) return 'PRD harus punya judul di baris paling atas, diawali tanda # (mis. "# Nama Modul").';
    return "";
  },
  md(name, size, text) {
    if (!/\.(md|markdown)$/i.test(name)) return `${name}: format harus .md.`;
    if (size > 2000000) return `${name}: ukuran file maksimal 2 MB.`;
    if (!size || !String(text ?? "").trim()) return `${name}: file kosong.`;
    if (/\u0000/.test(text) || /\uFFFD/.test(String(text).slice(0, 2000))) return `${name}: bukan file teks Markdown yang bisa dibaca.`;
    if (V.alnum(text) < 3) return `${name}: tidak berisi teks yang bisa dijadikan PDF.`;
    return "";
  },
  password(value) {
    const v = String(value ?? "");
    if (!v) return "Password wajib diisi.";
    if (v.length < 8) return "Password minimal 8 karakter.";
    if (v.length > 128) return "Password maksimal 128 karakter.";
    if (v !== v.trim()) return "Password tidak boleh diawali atau diakhiri spasi.";
    if (!/[A-Za-z]/.test(v) || !/\d/.test(v)) return "Password harus berisi huruf dan angka.";
    if (new Set(v.toLowerCase()).size < 4) return "Password terlalu mudah ditebak.";
    return "";
  },
  username(value) {
    const v = String(value ?? "");
    if (!v.trim()) return "Nama pengguna wajib diisi.";
    if (v !== v.trim() || v.includes(" ")) return "Nama pengguna tidak boleh memakai spasi.";
    if (v.length < 3 || v.length > 32) return "Nama pengguna harus 3–32 karakter.";
    if (v !== v.toLowerCase()) return "Nama pengguna memakai huruf kecil semua.";
    if (!/^[a-z][a-z0-9._-]*$/.test(v)) return "Nama pengguna diawali huruf, lalu hanya huruf kecil, angka, titik, garis bawah, atau tanda minus.";
    return "";
  },
  serverUrl(value) {
    const v = String(value ?? "").trim();
    if (!v) return "Alamat server wajib diisi.";
    if (v.length > 200) return "Alamat server terlalu panjang.";
    const m = v.match(/^(https?):\/\/([A-Za-z0-9.-]+)(?::(\d{1,5}))?\/?$/);
    if (!m) return "Format alamat server salah. Contoh: http://100.101.102.103:11500";
    const [, , host, port] = m;
    if (/^[-.]|[-.]$|\.\./.test(host)) return "Nama komputer di alamat server tidak valid.";
    if (port && (Number(port) < 1 || Number(port) > 65535)) return "Nomor port harus di antara 1 dan 65535.";
    if (/^[\d.]+$/.test(host)) { const p = host.split("."); if (p.length !== 4 || p.some((x) => !x || Number(x) > 255)) return "Alamat IP tidak valid."; }
    return "";
  },
  NUM: { "c-bs": ["Skenario per kelompok", 1, 20, false], "c-ma": ["Batas menulis ulang", 1, 10, false],
    "c-mo": ["Jumlah skenario maksimum", 1, 10000, true], "c-ctx": ["Kapasitas teks per permintaan", 2048, 131072, false] },
  number(id, raw) {
    const [label, lo, hi, optional] = V.NUM[id];
    const v = String(raw ?? "").trim();
    if (!v) return optional ? "" : `${label} wajib diisi.`;
    if (!/^-?\d+$/.test(v)) return `${label} harus angka bulat.`;
    const n = Number(v);
    if (n < lo || n > hi) return `${label} harus di antara ${V.fmt(lo)} dan ${V.fmt(hi)}.`;
    if (id === "c-ctx" && n % 1024) return `${label} harus kelipatan 1024 (mis. 4096, 8192, 16384).`;
    return "";
  },
};

function errBox(el) { return el.closest(".field") || el.closest("fieldset") || el; }
function setErr(el, msg) {
  if (!el || !msg) return;
  const box = errBox(el);
  box.classList.add("has-err");
  if (el.matches("input, textarea, select")) el.setAttribute("aria-invalid", "true");
  let m = box.querySelector(":scope > .err-msg");
  if (!m) {
    m = document.createElement("span");
    m.className = "err-msg";
    m.id = `${el.id || "isian"}-err`;
    box.appendChild(m);
  }
  m.textContent = msg;
  const ids = new Set((el.getAttribute("aria-describedby") || "").split(" ").filter(Boolean));
  ids.add(m.id);
  el.setAttribute("aria-describedby", [...ids].join(" "));
}
function clearErr(el) {
  if (!el) return;
  const box = errBox(el);
  box.classList.remove("has-err");
  el.removeAttribute("aria-invalid");
  const m = box.querySelector(":scope > .err-msg");
  if (m) {
    const ids = (el.getAttribute("aria-describedby") || "").split(" ").filter((x) => x && x !== m.id);
    ids.length ? el.setAttribute("aria-describedby", ids.join(" ")) : el.removeAttribute("aria-describedby");
    m.remove();
  }
}
function clearErrs(root = document) { root.querySelectorAll(".has-err").forEach((b) => { const el = b.querySelector("[aria-invalid]") || b; clearErr(el); b.classList.remove("has-err"); b.querySelector(":scope > .err-msg")?.remove(); }); }
// errors: [[elemen, pesan], ...] -> tandai semua, fokus ke yang pertama. true bila tidak ada error.
function report(errors, root) {
  clearErrs(root);
  const list = errors.filter(([el, msg]) => el && msg);
  list.forEach(([el, msg]) => setErr(el, msg));
  if (!list.length) return true;
  const first = list[0][0];
  if (!first.matches("input, textarea, select, button")) first.setAttribute("tabindex", "-1");
  first.focus({ preventScroll: true });
  first.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
  toast(list.length === 1 ? list[0][1] : `Ada ${list.length} isian yang perlu diperbaiki.`, true);
  return false;
}
// error dari server: tampilkan di bawah isian yang disebut server, kalau ada
function serverErr(e) {
  const el = e.field && document.getElementById(e.field);
  if (el) { setErr(el, e.message); el.focus && el.focus({ preventScroll: false }); }
  toast(e.message, true);
}

function toast(msg, isErr) {
  const t = document.createElement("div");
  t.className = "toast" + (isErr ? " err" : "");
  t.setAttribute("role", isErr ? "alert" : "status");
  t.textContent = msg;
  let box = document.getElementById("toasts");
  if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
  while (box.children.length >= 3) box.firstChild.remove(); // maksimal 3 notifikasi bertumpuk
  box.appendChild(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 220); }, isErr ? 7000 : 3500);
}

function fmtDate(ts, withYear) {
  if (!ts) return "-";
  const d = new Date(ts * 1000);
  const opts = { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" };
  if (withYear) opts.year = "numeric";
  return d.toLocaleString("id-ID", opts);
}

function fmtDur(sec) {
  if (sec === null || sec === undefined || !isFinite(sec) || sec < 0) return "-";
  const m = Math.round(sec / 60);
  if (m < 1) return "kurang dari 1 menit";
  if (m < 60) return `${m} menit`;
  const h = Math.floor(m / 60), r = m % 60;
  return r ? `${h} jam ${r} menit` : `${h} jam`;
}

// lama proses = waktu kerja; jeda saat laptop tidur (lebih dari 15 menit tanpa kabar) tidak dihitung
const runDur = (r) => (r && typeof r.active_sec === "number" ? r.active_sec : r && r.started && r.finished ? r.finished - r.started : null);
const pausedNote = (r) => (r && r.paused_sec >= 900 ? ` (tidak termasuk ${fmtDur(r.paused_sec)} saat laptop tidur/terhenti)` : "");
const pct = (a, b) => (b ? Math.round((100 * a) / b) : 0);

function icon(kind) {
  if (kind === "ok") return '<svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="none" stroke="#1E6B45" stroke-width="1.5"/><path d="M6 10.5l2.5 2.5L14 7.5" fill="none" stroke="#1E6B45" stroke-width="1.8"/></svg>';
  if (kind === "err") return '<svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="none" stroke="#B3261E" stroke-width="1.5"/><path d="M7 7l6 6M13 7l-6 6" fill="none" stroke="#B3261E" stroke-width="1.8"/></svg>';
  return '<svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="none" stroke="#8A4B00" stroke-width="1.5"/><path d="M10 5.5v5.5M10 13.5v.5" fill="none" stroke="#8A4B00" stroke-width="1.8"/></svg>';
}

const STATUS = {
  berjalan: ["Sedang berjalan", "info"], selesai: ["Selesai", "ok"], dibatalkan: ["Dihentikan", "grey"],
  gagal: ["Gagal", "err"], terputus: ["Terputus", "err"],
};
const statusChip = (s) => { const [t, c] = STATUS[s] || [s || "-", "grey"]; return `<span class="chip ${c}">${esc(t)}</span>`; };

const SOURCE = { llm: "Lolos pemeriksaan otomatis", "llm-unverified": "Perlu dicek manusia", template: "Dibuat dari pola bawaan", skeleton: "Kerangka otomatis" };

/* ================================================================= alasan "perlu dicek" */
const GROUPS = [
  { key: "jelas", title: "Hasil yang diharapkan kurang jelas", chip: "Kurang jelas",
    desc: "Penguji tidak bisa memastikan lulus atau gagal dari kalimat ini. Tulis ulang dengan hasil yang bisa dilihat." },
  { key: "ragu", title: "AI pemeriksa ragu", chip: "AI ragu",
    desc: "AI kedua tidak yakin test case ini sesuai PRD. Baca dan pastikan isinya." },
  { key: "pola", title: "Dibuat dari pola bawaan", chip: "Pola bawaan",
    desc: "Tulisan AI tidak lolos pemeriksaan, jadi test case dibuat dari pola standar. Isinya benar tapi kaku." },
  { key: "ditebak", title: "PRD tidak menyebut hasilnya", chip: "Hasil ditebak",
    desc: "Hasilnya ditebak dari aturan lain di PRD. Pastikan ke Product Owner, terutama yang berasal dari tabel keputusan." },
  { key: "kondisi", title: "Kondisi perlu dipastikan", chip: "Kondisi",
    desc: "Sebagian kondisi tidak disebut jelas di PRD (misalnya pemicu perpindahan status)." },
  { key: "status", title: "Perpindahan status hasil tebakan", chip: "Status ditebak",
    desc: "Perpindahan status yang tidak disebut di PRD dianggap tidak boleh. Pastikan memang begitu." },
  { key: "lain", title: "Lainnya", chip: "Perlu dicek", desc: "Ditandai untuk dibaca sebelum dipakai." },
];
const GROUP = Object.fromEntries(GROUPS.map((g) => [g.key, g]));

function explainFlag(part) {
  const p = part.trim();
  const after = (s) => { const i = s.indexOf(":"); return i >= 0 ? s.slice(i + 1).trim() : ""; };
  if (/juri/i.test(p)) {
    if (/CONTRADICTS/.test(p)) return ["ragu", "AI pemeriksa menilai hasilnya bertentangan dengan PRD" + (after(p) ? `: ${after(p)}` : "")];
    if (/UNRELATED|kurang relevan/i.test(p)) return ["ragu", "AI pemeriksa menilai test case ini kurang relevan dengan aturannya"];
    return ["ragu", "AI pemeriksa ragu" + (after(p) ? `: ${after(p)}` : "")];
  }
  if (/^Template otomatis/.test(p)) return ["pola", "Tulisan AI tidak lolos pemeriksaan, jadi dibuat dari pola bawaan"];
  if (/^Ekspektasi disimpulkan/.test(p)) return ["ditebak", "PRD tidak menyebut hasilnya; hasil ditebak dari aturan lain"];
  if (/^Diturunkan otomatis/.test(p)) return ["status", "Perpindahan status ini tidak disebut di PRD dan dianggap tidak boleh"];
  if (/N\/A/.test(p)) return ["kondisi", "Sebagian kondisi tidak berlaku (N/A) karena bergantung pada kondisi lain"];
  if (/pemicu/i.test(p)) return ["kondisi", "PRD tidak menyebut pemicu perpindahan status"];
  if (/di Test Steps tidak ada di PRD/.test(p)) return ["jelas", "Ada angka di Test Steps yang tidak tercantum di PRD"];
  if (/PERLU REVIEW/.test(p)) {
    if (/generik/.test(p)) return ["jelas", "Kalimat hasil yang diharapkan terlalu umum"];
    if (/terpotong/.test(p)) return ["jelas", "Kalimat hasil yang diharapkan terpotong"];
    if (/bertentangan/.test(p)) return ["jelas", "Kalimat hasil bertentangan (berhasil tetapi juga menolak)"];
    if (/angka/.test(p)) return ["jelas", "Ada angka yang tidak tercantum di PRD"];
    if (/precondition|prekondisi/i.test(p)) return ["jelas", "Kondisi awal perlu dirapikan"];
    if (/steps/.test(p)) return ["jelas", "Langkah uji belum lengkap"];
    if (/placeholder/.test(p)) return ["jelas", "Data uji belum berupa nilai yang bisa dipakai"];
    if (/title|judul|frasa|Inggris/i.test(p)) return ["jelas", "Judul belum sesuai skenarionya"];
    return ["jelas", "Belum lolos pemeriksaan otomatis"];
  }
  return ["lain", p];
}

function flagInfo(flag) {
  if (!flag) return [];
  return String(flag).split(" | ").filter((x) => x.trim()).map(explainFlag);
}
const flagChips = (flag) => [...new Set(flagInfo(flag).map(([k]) => k))]
  .map((k) => `<span class="chip">${esc(GROUP[k].chip)}</span>`).join(" ");

function friendlyDrop(reason) {
  const r = String(reason || "");
  if (/polaritas/.test(r)) return "Hasil yang ditulis AI berlawanan dengan yang seharusnya";
  if (/tidak dikembalikan|tidak terbentuk/.test(r)) return "AI tidak mengembalikan test case untuk skenario ini";
  if (/angka/.test(r)) return "AI memakai angka yang tidak ada di PRD";
  if (/generik|terpotong/.test(r)) return "Kalimat hasil yang diharapkan belum jelas";
  return r;
}
const cleanScenario = (s) => String(s || "").replace(/^(Aturan|Alur utama berjalan normal|Edge case)\s*:\s*/i, "");
const cleanTitle = (s) => String(s || "").replace(/\s*\|\s*Expected:.*$/i, "");

/* ================================================================= log & tahapan yang mudah dibaca */
const STAGES = [
  ["atomize", "Membaca PRD"], ["design", "Menyusun skenario uji"], ["generate", "Menulis dan memeriksa"],
  ["coverage", "Merapikan hasil"], ["export", "Menyimpan ke Excel"],
];

function humanLog(tag, msg) {
  let m;
  msg = String(msg || "");
  if (tag === "verifier" && (m = msg.match(/^(\d+) TC dikembalikan/))) return [`${m[1]} test case ditulis ulang karena belum lolos pemeriksaan`, ""];
  if (tag === "verifier" && /tidak menghasilkan TC/.test(msg)) return ["1 skenario gagal dibuatkan test case (tercatat di Perlu dicek)", "err"];
  if (tag === "judge" && (m = msg.match(/diperiksa (\d+)\/(\d+)/))) return [`AI pemeriksa: ${m[1]} dari ${m[2]} test case sudah diperiksa ulang`, ""];
  if (tag === "judge") return ["1 test case ditandai Perlu dicek karena AI pemeriksa ragu", "warn"];
  if (tag === "designer" && (m = msg.match(/max_obligations=(\d+) dari (\d+)/))) return [`Jumlah skenario dibatasi ${m[1]} dari ${m[2]}`, "warn"];
  if (tag === "designer" && (m = msg.match(/^obligations=(\d+)/))) return [`${m[1]} skenario uji disusun`, ""];
  if (tag === "designer" && /,\s*0 \(decision\/edge\)/.test(msg)) return ["Semua skenario ditulis oleh AI penulis utama", ""];
  if (tag === "designer" && (m = msg.match(/,\s*(\d+) \(decision\/edge\)/))) return [`${m[1]} skenario rumit akan ditulis oleh AI yang lebih besar di akhir`, ""];
  if (tag === "atomizer" && (m = msg.match(/atoms=(\d+)/))) return [`PRD dibaca: ${m[1]} aturan ditemukan`, ""];
  if (tag === "expander" && (m = msg.match(/draft (\d+)\/(\d+)/))) return [`AI baru mengembalikan ${m[1]} dari ${m[2]} test case, sisanya diminta ulang`, ""];
  if (tag === "coverage") return ["Hasil dirapikan: test case kembar digabung dan prioritas diisi", ""];
  if (tag === "export" && /menyalin/.test(msg)) return ["Excel tidak bisa disalin ke folder outputs karena file lamanya sedang dibuka. Unduh dari halaman Hasil.", "warn"];
  if (tag === "export") return /gagal/.test(msg) ? ["Gagal menyimpan data lengkap (JSON)", "err"] : ["Hasil disimpan ke Excel", ""];
  if (tag === "llm") return ["Gagal menghubungi AI lokal, mencoba lagi", "err"];
  return [msg, ""];
}

function stageDetail(key, st, live) {
  const d = st.detail || "";
  let m;
  if (st.state === "pending") return live.status === "berjalan" ? "Menunggu" : "Tidak dijalankan";
  if (st.state === "running" && live.status !== "berjalan") return live.status === "gagal" ? "Gagal di tahap ini" : "Dihentikan di tahap ini";
  if (key === "atomize" && (m = d.match(/(\d+) atom/))) return `${m[1]} aturan ditemukan`;
  if (key === "design" && (m = d.match(/(\d+) obligation/))) return `${m[1]} skenario uji`;
  if (key === "generate") return st.state === "done" ? `${live.done} skenario selesai` : "Sedang dikerjakan";
  if (key === "coverage" && (m = d.match(/(\d+) TC, (\d+) duplikat/))) return `${m[1]} test case, ${m[2]} kembar digabung`;
  if (key === "export" && st.state === "done") return "Excel tersimpan";
  return st.state === "done" ? "Selesai" : "Sedang dikerjakan";
}

function newLive(run) {
  return {
    runId: run.id, run, status: "berjalan", stages: Object.fromEntries(STAGES.map(([k]) => [k, { state: "pending", detail: "" }])),
    total: 0, done: 0, retry: 0, dropped: 0, judged: 0, sources: {}, batch: null, logs: [], firstTime: null, error: null,
  };
}

function reduce(L, e) {
  if (!L.firstTime && e.time) L.firstTime = e.time;
  const order = STAGES.map(([k]) => k);
  switch (e.type) {
    case "stage": {
      const i = order.indexOf(e.key);
      if (i < 0) break;
      order.slice(0, i).forEach((k) => { L.stages[k].state = "done"; });
      if (L.stages[e.key].state !== "done") L.stages[e.key].state = "running";
      if (e.detail) L.stages[e.key].detail = e.detail;
      break;
    }
    case "stage_done":
      if (L.stages[e.key]) { L.stages[e.key].state = "done"; if (e.detail) L.stages[e.key].detail = e.detail; }
      break;
    case "total": L.total = e.total; break;
    case "batch_start": L.batch = { n: (e.ids || []).length, attempt: e.attempt }; break;
    case "progress":
      Object.assign(L, { done: e.done, total: e.total || L.total, retry: e.retry, dropped: e.dropped, judged: e.judged, sources: e.sources || {} });
      L.eta = typeof e.eta === "number" ? e.eta : null;
      L.etaAt = e.time;
      break;
    case "log": {
      if (typeof e.eta === "number") { L.eta = e.eta; L.etaAt = e.time; }
      if (e.tag === "designer" && /judge_planned=/.test(e.msg || "")) break; // catatan internal untuk perkiraan waktu
      const [text, cls] = humanLog(e.tag, e.msg);
      L.logs.unshift({ time: e.time, text, cls });
      if (L.logs.length > 200) L.logs.pop();
      break;
    }
    case "done": L.status = "selesai"; L.report = e.report; STAGES.forEach(([k]) => { L.stages[k].state = "done"; }); break;
    case "cancelled": L.status = "dibatalkan"; break;
    case "error": L.status = "gagal"; L.error = e.message; break;
    default: break;
  }
}

/* ================================================================= menu samping */
const SEEN_KEY = "aiqa-cek-dilihat";
function seenReview() { try { return localStorage.getItem(SEEN_KEY); } catch (e) { return S.seenMem || null; } }
function markReviewSeen(runId) {
  S.seenMem = runId;
  try { localStorage.setItem(SEEN_KEY, runId); } catch (e) { /* mode privat: cukup di memori */ }
  const b = document.getElementById("nav-badge");
  if (b && S.overview && S.overview.last && S.overview.last.id === runId) b.hidden = true;
}

async function refreshNav() {
  try {
    S.overview = await api("/api/overview");
  } catch (e) {
    setNavStatus("TƎRᗩ tidak terhubung", "Jendela PowerShell TƎRᗩ harus tetap terbuka");
    return;
  }
  const o = S.overview, pf = o.preflight;
  document.getElementById("nav-dot").hidden = !o.active;
  // titik di menu Perlu dicek: hanya untuk hasil terbaru yang belum dibuka halamannya
  const badge = document.getElementById("nav-badge");
  const nr = o.last && o.last.report ? o.last.report.needs_review : 0;
  badge.hidden = !(nr && o.last.id !== seenReview());
  // kotak status hanya muncul bila ada masalah; saat semuanya siap, sidebar bersih
  setNavVersion(pf.source);
  if (!pf.ollama) { const [, t, sub] = aiStatus(pf); setNavStatus(t, sub); }
  else if (pf.missing.length) setNavStatus("AI belum lengkap", "Cek menu Pengaturan");
  else setNavStatus(null);
}

// [ok, judul, keterangan] untuk status AI, sesuai sumber AI (laptop ini / Server AI bersama)
function aiStatus(pf) {
  const src = pf.source || { mode: "lokal" };
  if (src.mode !== "server") {
    return pf.ollama ? ["ok", "Mesin AI lokal menyala", "Berjalan di laptop ini"]
      : ["err", "Mesin AI lokal belum menyala", "Buka aplikasi Ollama, lalu klik Periksa ulang"];
  }
  if (pf.ollama) return ["ok", "Server AI bersama terhubung", `Masuk sebagai ${src.username}`];
  if (src.problem === "login") return ["err", src.logged_in ? "Sesi login Server AI habis" : "Belum masuk ke Server AI bersama", src.logged_in ? "Masuk lagi di Pengaturan, bagian Sumber AI. Bila tetap ditolak, hubungi pemilik server" : "Masuk di Pengaturan, bagian Sumber AI"];
  if (src.problem === "versi") return ["err", "Versi TƎRᗩ terlalu lama untuk Server AI ini", `Server mewajibkan minimal versi ${src.min_version || "terbaru"}. Minta folder TƎRᗩ terbaru ke pemilik server`];
  if (src.problem === "ditolak") return ["err", "Server AI bersama menolak laptop ini", "Pastikan Tailscale menyala dan sudah masuk"];
  return ["err", "Server AI bersama tidak terhubung", "Pastikan Tailscale menyala dan Server AI temanmu sedang berjalan"];
}
function pullHint(pf, name) { return (pf.source || {}).mode === "server" ? `Minta pemilik server mengunduh ${name}` : `Unduh dengan: ollama pull ${name}`; }

/* ---------- versi aplikasi */
function setNavVersion(src) {
  const a = document.getElementById("nav-version");
  if (!a || !src || !src.version) return;
  const gh = S.update && S.update.available && !S.update.dev;
  const fresh = src.update_available || src.too_old || gh;
  a.innerHTML = `<span class="lbl">TƎRᗩ versi</span>${esc(src.version)}${fresh ? `<span class="nav-ver-new">${src.too_old ? "Perlu update" : "Ada versi baru"}</span>` : ""}`;
  a.title = gh ? `Versi ${S.update.latest} tersedia. Klik untuk memperbarui` : fresh ? `Server AI bersama memakai versi ${src.server_version}` : "Lihat apa yang baru";
  S.navSrc = src;
}

/* ---------- pembaruan dari GitHub */
async function checkUpdate(force) {
  try { S.update = await api(`/api/update${force ? "?cek=1" : ""}`); } catch (e) { S.update = { error: e.message }; }
  if (S.navSrc) setNavVersion(S.navSrc);
  return S.update;
}

function updateCardHtml(u) {
  if (!u) return "";
  let body;
  if (u.dev) body = `<p class="small">Folder ini salinan pengembang (terhubung ke Git), jadi tidak ditimpa otomatis. Versi di GitHub: <b class="num">${esc(u.latest || "-")}</b>. Untuk mengambil perubahan, pakai <span class="mono">git pull</span>.</p>`;
  else if (u.error) body = `<p class="small" style="color:var(--warn)">${esc(u.error)}</p>`;
  else if (u.available) body = `<p class="small"><strong>Versi ${esc(u.latest)} tersedia</strong> (laptop ini versi ${esc(u.current)}). Yang diperbarui hanya file program. Hasil kerja, dokumen PRD, akun, dan pengaturanmu tidak diubah, dan file program lama dicadangkan dulu.</p>
      ${(parseChangelog(u.changelog).filter((r) => verOlder(u.current, r.version)).slice(0, 3)).map((r) => `<div><h3 class="rel-group">Baru di versi ${esc(r.version)}</h3><ul class="rel-list">${r.groups.flatMap((g) => g.items).slice(0, 8).map((i) => `<li>${inlineMd(i)}</li>`).join("")}</ul></div>`).join("")}`;
  else body = `<p class="small">${icon("ok")} TƎRᗩ di laptop ini sudah versi terbaru (${esc(u.current)}).</p>`;
  return `<section class="card" aria-labelledby="upd-h"><div class="card-head"><h2 id="upd-h">Pembaruan</h2>
      <div class="actions">${u.available && !u.dev ? `<button type="button" class="btn btn-primary" data-action="upd-apply">Perbarui sekarang</button>` : ""}
        <button type="button" class="btn btn-small" data-action="upd-check">Periksa pembaruan</button></div></div>
    ${body}
    <p class="tiny muted">Pembaruan diambil dari GitHub${u.repo ? ` (${esc(u.repo)})` : ""}, jadi butuh internet. Bisa juga lewat file <span class="mono">Perbarui_Tera.bat</span> saat TƎRᗩ ditutup.</p></section>`;
}
function verOlder(a, b) {
  const p = (v) => (/^\d+\.\d+\.\d+$/.test(v || "") ? v.split(".").map(Number) : null), x = p(a), y = p(b);
  if (!y) return false; if (!x) return true;
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] < y[i];
  return false;
}

async function updateApply(btn) {
  btn.disabled = true; btn.innerHTML = `<span class="spinner" aria-hidden="true"></span>Mengunduh dan memasang...`;
  try {
    const r = await api("/api/update/apply", { method: "POST", body: {} });
    S.update = null;
    if (!r.updated) { toast(r.message); return viewVersi(true); }
    app.innerHTML = `<header class="page-head"><div><h1>TƎRᗩ diperbarui ke versi ${esc(r.version)}</h1></div></header>
      <section class="card"><p><strong>Tutup TƎRᗩ, lalu buka lagi</strong> lewat ikon TERA di Desktop supaya versi baru dipakai. Tutup juga jendela hitam TƎRᗩ.</p>
        <p class="small muted">${num(r.files)} file program diperbarui${r.removed ? `, ${num(r.removed)} file lama dibuang` : ""}. Hasil kerja dan pengaturanmu tidak diubah.${r.backup ? ` File program lama dicadangkan di <span class="mono">${esc(r.backup)}</span>.` : ""}</p>
        ${r.warning ? `<div class="banner" role="alert"><span>${esc(r.warning)}</span></div>` : ""}</section>`;
  } catch (e) { toast(e.message, true); btn.disabled = false; btn.textContent = "Perbarui sekarang"; }
}

// CHANGELOG.md -> [{version, date, groups: [{title, items}]}]
function parseChangelog(md) {
  const rel = [];
  let cur = null, grp = null;
  for (const raw of String(md || "").split(/\r?\n/)) {
    const line = raw.trim();
    let m;
    if ((m = line.match(/^##\s+(\d+\.\d+\.\d+)\s*(?:[—–-]\s*(.+))?$/))) { cur = { version: m[1], date: m[2] || "", groups: [] }; grp = null; rel.push(cur); }
    else if (cur && (m = line.match(/^###\s+(.+)$/))) { grp = { title: m[1], items: [] }; cur.groups.push(grp); }
    else if (cur && (m = line.match(/^[-*]\s+(.+)$/))) { if (!grp) { grp = { title: "", items: [] }; cur.groups.push(grp); } grp.items.push(m[1]); }
  }
  return rel;
}
const inlineMd = (t) => esc(t).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");

async function viewVersi(force) {
  const [ab, upd] = await Promise.all([api("/api/about"), checkUpdate(force === true)]);
  const src = ab.source || {};
  setNavVersion(src);
  const rel = parseChangelog(ab.changelog);
  const banner = src.too_old
    ? `<div class="banner error" role="alert"><span><strong>TƎRᗩ di laptop ini terlalu lama untuk Server AI bersama.</strong> Server mewajibkan minimal versi ${esc(src.min_version)}. Minta folder TƎRᗩ terbaru ke pemilik server, lalu salin menimpa folder lama (folder <code>runs</code>, <code>outputs</code>, dan <code>knowledge</code> milikmu tetap aman).</span></div>`
    : src.update_available
      ? `<div class="banner" role="status"><span><strong>Ada versi lebih baru.</strong> Server AI bersama memakai TƎRᗩ versi ${esc(src.server_version)}, laptop ini versi ${esc(src.version)}. Minta folder terbaru ke pemilik server bila ingin fitur barunya.</span></div>`
      : "";
  app.innerHTML = `
  <header class="page-head"><div><h1>Apa yang baru</h1>
    <p class="muted">TƎRᗩ di laptop ini versi <b class="num">${esc(ab.version)}</b>.${src.mode === "server" && src.server_version ? ` Server AI bersama versi <span class="num">${esc(src.server_version)}</span>.` : ""}</p></div></header>
  ${banner}
  ${updateCardHtml(upd)}
  ${rel.length ? rel.map((r) => `<section class="card release" aria-labelledby="rel-${esc(r.version)}">
      <div class="card-head"><h2 id="rel-${esc(r.version)}">Versi ${esc(r.version)}${r.version === ab.version ? ` <span class="chip-now">Versi kamu</span>` : ""}</h2>
        ${r.date ? `<span class="small muted">${esc(r.date)}</span>` : ""}</div>
      ${r.groups.map((g) => `${g.title ? `<h3 class="rel-group">${esc(g.title)}</h3>` : ""}<ul class="rel-list">${g.items.map((i) => `<li>${inlineMd(i)}</li>`).join("")}</ul>`).join("")}
    </section>`).join("") : `<p class="muted">Catatan perubahan belum tersedia.</p>`}`;
}

function setNavStatus(title, sub) {
  const box = document.querySelector(".nav-status");
  if (!box) return;
  box.hidden = !title;
  box.title = title ? `${title}. ${sub || ""}` : "";
  document.getElementById("nav-ai").textContent = title || "";
  document.getElementById("nav-ai-sub").textContent = sub || "";
}

function setActiveNav(view) {
  let current = null;
  document.querySelectorAll(".nav-links a, .nav-version").forEach((a) => {
    if (a.dataset.view === view) { a.setAttribute("aria-current", "page"); current = a; } else a.removeAttribute("aria-current");
  });
  const grp = current && current.closest(".nav-group");
  document.querySelectorAll(".nav-group-btn").forEach((b) => b.classList.toggle("has-current", !!grp && b.closest(".nav-group") === grp));
  if (grp) {
    const st = navState();
    if (st.groups[grp.dataset.group] === false) { st.groups[grp.dataset.group] = true; saveNav(); } // menu yang sedang dibuka selalu terlihat
  }
  applyNav();
}

/* ---------- menu samping: diciutkan (hanya ikon) dan grup menu buka/tutup; diingat di browser ini */
function navState() {
  if (S.nav) return S.nav;
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem("tera-menu") || "{}") || {}; } catch (e) { saved = {}; }
  // pertama kali: semua grup tertutup supaya menu pendek; grup halaman yang sedang dibuka otomatis terbuka
  S.nav = { mini: !!saved.mini, groups: saved.groups && typeof saved.groups === "object" ? saved.groups : { konversi: false, generator: false } };
  return S.nav;
}
function saveNav() { try { localStorage.setItem("tera-menu", JSON.stringify(navState())); } catch (e) { /* penyimpanan browser tidak tersedia */ } }
function applyNav() {
  const st = navState();
  const shell = document.querySelector(".shell");
  if (shell) shell.classList.toggle("nav-mini", st.mini);
  const t = document.getElementById("nav-toggle");
  if (t) {
    const label = st.mini ? "Lebarkan menu samping" : "Ciutkan menu samping";
    t.setAttribute("aria-expanded", String(!st.mini)); t.setAttribute("aria-label", label); t.title = label;
    const l = t.querySelector(".lbl"); if (l) l.textContent = st.mini ? "Lebarkan menu" : "Ciutkan menu";
  }
  document.querySelectorAll(".nav-group").forEach((g) => {
    const open = st.groups[g.dataset.group] !== false;
    g.classList.toggle("closed", !open);
    const b = g.querySelector(".nav-group-btn"), list = g.querySelector(".nav-group-list");
    b.setAttribute("aria-expanded", String(open && !st.mini));
    if (open && !st.mini) list.removeAttribute("inert"); else list.setAttribute("inert", "");
  });
}
applyNav();
document.getElementById("nav-toggle")?.addEventListener("click", () => { const st = navState(); st.mini = !st.mini; saveNav(); applyNav(); });
document.querySelector(".nav")?.addEventListener("click", (ev) => {
  const b = ev.target.closest(".nav-group-btn");
  if (!b) return;
  const st = navState(), key = b.dataset.groupBtn;
  if (st.mini) { st.mini = false; st.groups[key] = true; } // dari mode ikon: lebarkan dan buka grup yang diklik
  else st.groups[key] = st.groups[key] === false;
  saveNav(); applyNav();
});

/* ================================================================= BERANDA */
async function viewBeranda() {
  await refreshNav();
  const o = S.overview, pf = o.preflight, last = o.last, act = o.active;
  const rep = (last && last.report) || {};
  let active;
  if (act) {
    const p = act.progress || {}, total = p.total || 0, done = p.done || 0;
    const el = Date.now() / 1000 - (act.started || Date.now() / 1000);
    const eta = typeof p.eta === "number" ? Math.max(60, p.eta - (Date.now() / 1000 - (p.eta_at || Date.now() / 1000))) : null;
    active = `<p>${esc(act.prd_title)}</p>
      <div style="display:flex;flex-direction:column;gap:8px">
        <span class="bar" style="height:10px"><span style="width:${pct(done, total)}%"></span></span>
        <div class="small muted num" style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px">
          <span>${total ? `${num(done)} dari ${num(total)} skenario selesai` : "Sedang menyiapkan skenario"}</span>
          <span>${eta !== null ? `kira-kira ${fmtDur(eta)} lagi` : `sudah berjalan ${fmtDur(el)}, menghitung perkiraan waktu`}</span></div></div>
      <a href="#berjalan" style="margin-top:auto;font-weight:500">Lihat progresnya</a>`;
  } else {
    active = `<p class="muted">Tidak ada proses yang berjalan.</p>
      <a href="#mulai" style="margin-top:auto;font-weight:500">Mulai buat test case</a>`;
  }
  const ready = [
    (() => { const [k, t, sub] = aiStatus(pf); return [k, k === "ok" ? t : `${t}. ${sub}.`]; })(),
    [pf.ollama && !pf.missing.length ? "ok" : "err", pf.missing.length ? `Model belum terpasang: ${pf.missing.join(", ")}` : "AI penulis, pemeriksa, dan kasus rumit tersedia"],
    [pf.prd_count ? "ok" : "err", pf.prd_count ? `${pf.prd_count} dokumen PRD siap dipilih` : "Belum ada dokumen PRD"],
  ];
  if (act) ready.push(["warn", "Proses baru bisa dimulai setelah yang berjalan selesai"]);

  let lastHtml = `<div class="empty"><p>Belum ada hasil. Mulai proses pertama untuk melihat ringkasannya di sini.</p><a class="btn btn-primary" href="#mulai">Mulai buat test case</a></div>`;
  if (last) {
    lastHtml = `<section class="card" style="padding:0;gap:0" aria-labelledby="last-title">
      <div class="card-head" style="padding:22px 28px 6px"><h2 id="last-title">Hasil terakhir</h2>
        <span class="small muted">${esc(last.prd_title)}, selesai ${esc(fmtDate(last.finished))}</span></div>
      <div class="stat-strip" style="border:0">
        <a class="stat" href="#hasil/${esc(last.id)}"><b>${num(rep.test_cases)}</b><span>test case dibuat</span></a>
        <a class="stat warn" href="#cek/${esc(last.id)}"><b>${num(rep.needs_review)}</b><span>perlu dicek</span></a>
        <a class="stat" href="#cakupan/${esc(last.id)}"><b>${pct(rep.requirements_covered, rep.requirements_total)}%</b><span>requirement tercakup</span></a>
        <div class="stat"><b style="font-size:26px">${esc(fmtDur(runDur(last)))}</b><span>lama proses</span></div>
      </div></section>`;
  }

  let trend = "";
  const pts = (o.trend || []).filter((t) => t.needs_review !== null && t.needs_review !== undefined);
  if (pts.length >= 2) {
    const max = Math.max(...pts.map((t) => t.needs_review), 1);
    const a = pts[0].needs_review, b = pts[pts.length - 1].needs_review;
    const head = b < a ? `Yang perlu dicek turun dari ${a} ke ${b}` : b > a ? `Yang perlu dicek naik dari ${a} ke ${b}` : `Yang perlu dicek tetap ${b}`;
    trend = `<section class="card" aria-labelledby="trend-title">
      <div><h2 id="trend-title">${esc(head)}</h2><p class="small muted">Proses terakhir untuk dokumen yang sama, dari yang terlama</p></div>
      <div class="hbars" style="grid-template-columns:minmax(110px,auto) 1fr 40px">
        ${pts.map((t, i) => `<span class="${i === pts.length - 1 ? "" : "muted"}">${esc(fmtDate(t.finished))}</span>
          <span class="fill warm" style="width:${pct(t.needs_review, max)}%"></span><span class="val">${num(t.needs_review)}</span>`).join("")}
      </div><a class="small" href="#riwayat">Buka riwayat lengkap</a></section>`;
  }

  app.innerHTML = `
  <header class="page-head"><div>
      <h1>Selamat datang di TƎRᗩ</h1>
      <p class="muted">Ubah dokumen PRD menjadi test case siap pakai, langsung di laptop ini.</p></div>
    <div class="actions">${last ? `<a class="btn" href="#hasil/${esc(last.id)}">Lihat hasil terakhir</a>` : ""}
      <a class="btn btn-primary" href="#mulai">Mulai buat test case</a></div></header>
  <div class="grid grid-2s">
    <section class="card" aria-labelledby="now-title"><h2 id="now-title">Sedang berjalan</h2>${active}</section>
    <section class="card" aria-labelledby="ready-title"><h2 id="ready-title">Kesiapan laptop</h2>
      <ul class="ready-list">${ready.map(([k, t]) => `<li>${icon(k)}<span>${esc(t)}</span></li>`).join("")}</ul></section>
  </div>
  ${lastHtml}
  <div class="grid grid-2">
    ${trend}
    <section class="card" aria-labelledby="how-title"><h2 id="how-title">Cara kerjanya</h2>
      <ol class="how">
        <li><span class="n">1</span><span><b>Pilih dokumen PRD</b><br><span class="small muted">Dari layar Mulai baru. Satu proses berjalan pada satu waktu.</span></span></li>
        <li><span class="n">2</span><span><b>AI menulis dan memeriksa test case</b><br><span class="small muted">Bisa beberapa jam di laptop tanpa GPU. Browser boleh ditutup, jendela PowerShell jangan.</span></span></li>
        <li><span class="n">3</span><span><b>Baca yang perlu dicek, lalu unduh Excel</b><br><span class="small muted">Test case yang meragukan dikumpulkan di Perlu dicek beserta alasannya.</span></span></li>
      </ol></section>
  </div>`;
}

/* ================================================================= MULAI BARU */
async function viewMulai() {
  const [pf, prds, runs] = await Promise.all([api("/api/preflight"), api("/api/prds"), api("/api/runs")]);
  const chosen = S.mulaiPrd && prds.some((p) => p.file === S.mulaiPrd) ? S.mulaiPrd : (prds[0] || {}).file;
  const roleRows = pf.models.map((m) => [m.ok ? "ok" : "err", `AI ${m.role.toLowerCase()} ${m.ok ? "tersedia" : "belum terpasang"}`, m.ok ? m.name : pullHint(pf, m.name)]);
  const rows = [
    aiStatus(pf),
    ...(pf.ollama ? roleRows : []),
    [prds.length ? "ok" : "err", prds.length ? `${prds.length} dokumen PRD tersedia` : "Belum ada dokumen PRD", prds.length ? "" : "Tambahkan file .md dengan tombol Tambah dokumen PRD"],
  ];
  const ref = pf.reference || {};
  if (ref.locked && !ref.unlocked) rows.push(["warn", "Referensi test case perusahaan terkunci", "Test case tetap bisa dibuat, tetapi tanpa contoh gaya penulisan perusahaan. Isi password di Pengaturan."]);
  else if (ref.locked || ref.plain) rows.push(["ok", "Referensi test case perusahaan dipakai", `${num((ref.locked || 0) + (ref.plain || 0))} file${ref.plain ? ` (${num(ref.plain)} belum dikunci)` : ""}`]);
  if (pf.active_run) rows.push(["warn", "Ada proses yang masih berjalan", "Tunggu sampai selesai sebelum memulai yang baru"]);

  const estimate = (file) => {
    const r = runs.find((x) => x.prd === file && x.status === "selesai" && x.started && !(x.overrides || {}).max_obligations);
    return r ? `Perkiraan sekitar ${fmtDur(runDur(r))} di laptop ini, dari proses terakhir dokumen ini.` : "Belum ada perkiraan waktu: ini proses pertama untuk dokumen ini.";
  };
  S.estimate = estimate;

  app.innerHTML = `
  <header class="page-head"><div><h1>Buat test case baru</h1>
    <p class="muted">Pilih dokumen PRD, pastikan semuanya siap, lalu mulai. Hanya satu proses yang bisa berjalan dalam satu waktu.</p></div></header>
  ${pf.active_run ? `<div class="banner" role="status"><span><strong>Masih ada proses yang berjalan.</strong> Proses baru bisa dimulai setelah itu selesai atau dihentikan.</span><a href="#berjalan">Lihat progresnya</a></div>` : ""}
  <div class="grid grid-2">
    <section class="card" aria-labelledby="prd-title">
      <h2 id="prd-title">Dokumen</h2>
      <label class="field" for="prd-select">Dokumen PRD
        ${prds.length ? `<select id="prd-select" name="prd">${prds.map((p) => `<option value="${esc(p.file)}" ${p.file === chosen ? "selected" : ""}>${esc(p.title)}</option>`).join("")}</select>
          <span class="hint" id="prd-file-name">File: ${esc(chosen || "")}</span>` : `<span class="muted" id="prd-empty">Belum ada dokumen.</span>`}
      </label>
      <div class="actions"><button type="button" class="btn" data-action="upload">Tambah dokumen PRD</button>
        ${prds.length ? `<button type="button" class="btn" data-action="prd-del" ${pf.active_run ? "disabled" : ""}>Hapus dokumen ini</button>` : ""}
        <input type="file" id="prd-file" accept=".md" hidden></div>
      <p class="tiny muted">Daftar ini dibaca langsung dari folder <span class="mono">knowledge\prd</span>: file yang dihapus atau dipindah dari folder itu otomatis hilang dari daftar.</p>
      <div class="actions" style="padding-top:4px">
        <button type="button" class="btn btn-primary" data-action="start" ${pf.ready ? "" : "disabled"}>Mulai buat test case</button>
        <span class="small muted" id="estimate">${esc(chosen ? estimate(chosen) : "")}</span></div>
    </section>
    <section class="card" aria-labelledby="pf-title">
      <div class="card-head"><h2 id="pf-title">Kesiapan</h2>
        <button type="button" class="btn btn-small" data-action="recheck">Periksa ulang</button></div>
      <ul class="ready-list">${rows.map(([k, t, s]) => `<li>${icon(k)}<span><span style="font-weight:500">${esc(t)}</span>${s ? `<br><span class="tiny muted">${esc(s)}</span>` : ""}</span></li>`).join("")}</ul>
    </section>
  </div>`;
}

async function recheck(btn) {
  // tampilkan bahwa pemeriksaan sedang berjalan; minimal 0,6 detik supaya terlihat walau server cepat
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner" aria-hidden="true"></span>Memeriksa...`;
  const list = document.querySelector(".ready-list");
  if (list) list.classList.add("checking");
  try {
    await Promise.all([api("/api/preflight"), new Promise((r) => setTimeout(r, 600))]);
    await viewMulai();
    refreshNav();
    toast("Kesiapan sudah diperiksa ulang");
  } catch (e) {
    toast(e.message, true);
    btn.disabled = false;
    btn.textContent = "Periksa ulang";
    if (list) list.classList.remove("checking");
  }
}

async function uploadPrd(file) {
  if (!file) return;
  const box = document.getElementById("prd-select") || document.getElementById("prd-empty");
  if (!/\.md$/i.test(file.name)) return report([[box, `${file.name}: file PRD harus berformat .md`]]);
  if (file.size > 2000000) return report([[box, `${file.name}: PRD terlalu besar (maksimal 2 MB).`]]);
  try {
    const text = await file.text();
    if (text.includes("\uFFFD")) return report([[box, `${file.name}: isi file bukan teks UTF-8 yang bisa dibaca.`]]);
    const bad = V.prd(text);
    if (bad) return report([[box, `${file.name}: ${bad}`]]);
    const r = await api("/api/prds", { method: "POST", body: { name: file.name, content: text } });
    S.mulaiPrd = r.file;
    toast(`Dokumen ${r.title} ditambahkan`);
    route();
  } catch (e) { report([[box, e.message]]); }
}

async function startRun() {
  const sel = document.getElementById("prd-select");
  const prd = (sel || {}).value;
  if (!prd) return report([[sel || document.getElementById("prd-empty"), "Pilih dokumen PRD dulu, atau tambahkan file PRD (.md)."]]);
  const btn = document.querySelector('[data-action="start"]');
  btn.disabled = true;
  btn.textContent = "Memulai...";
  try {
    await api("/api/runs", { method: "POST", body: { prd } });
    location.hash = "#berjalan";
  } catch (e) {
    serverErr(e);
    btn.disabled = false;
    btn.textContent = "Mulai buat test case";
  }
}

/* ================================================================= ALUR KERJA (diagram animasi) */
const FLOWS = [
  {
    id: "konversi", title: "Catatan Konversi ke PRD", note: "Konversi Dokumen",
    steps: [
      ["in", "Catatan QA", "Kamu menempel catatan bebas: notulen, chat, poin-poin. Boleh campur Indonesia dan Inggris."],
      ["ai", "Baca per baris", "AI penulis mengambil setiap informasi beserta kutipan aslinya dari catatan."],
      ["code", "Penjaga anti-karangan", "Kode mengecek kutipan benar-benar ada di catatan, dan angka, role, serta status tidak dikarang. Yang gagal ditolak."],
      ["ai", "Baca ulang yang terlewat", "Baris catatan yang belum terbaca ditanyakan ulang sekali ke AI."],
      ["code", "Kelompokkan per fitur", "Aturan disusun per fitur, beserta status dan tabel hak akses per role."],
      ["ai", "Cari yang belum jelas", "AI mendaftar hal yang bertentangan atau belum jelas untuk ditanyakan ke tim."],
      ["out", "PRD + catatan review", "PRD siap dipakai generator test case. Hal yang diragukan ada di catatan review (PDF) terpisah."],
    ],
  },
  {
    id: "desain", title: "Desain Konversi ke PRD", note: "Konversi Dokumen",
    steps: [
      ["in", "Gambar + penjelasan", "Per halaman/fitur: gambar export Figma atau screenshot, plus penjelasan opsional dan deskripsi tambahan."],
      ["code", "Potong layar & latar buram", "Papan alur dipotong per layar. Latar buram di belakang modal/panel dibuang supaya tidak ada yang bisa ditebak. Layar kembar dibaca sekali."],
      ["code", "Baca teks (pembaca teks Windows)", "Teks di layar dibaca persis dalam hitungan detik, termasuk salah ketik. Tidak bisa mengarang karena hanya membaca huruf yang ada."],
      ["ai", "Kenali jenis elemen", "AI melihat gambar dan hanya memberi jenis pada teks bernomor: tombol, field, label, placeholder, pesan, tabel. AI tidak bisa menambah teks baru. Layar dengan teks yang sama tidak ditanyakan dua kali, dan yang terlewat AI dilengkapi kode."],
      ["code", "Susun alur bisnis", "Bingkai sampul di papan alur (mis. \"Users - Create\") menjadi nama alur. Tiap alur ditulis sebagai urutan langkah: layar, form dan isiannya, aturan isian, aksi, lalu notifikasi yang muncul. Layar yang sama tidak diulang."],
      ["ai", "Baca penjelasan", "Penjelasan QA diproses dengan penjaga kutipan yang sama seperti Catatan Konversi ke PRD."],
      ["out", "PRD + catatan review", "PRD siap dipakai generator test case. Hal yang perlu dikonfirmasi (mis. field abu-abu) ada di catatan review (PDF)."],
    ],
  },
  {
    id: "banding", title: "Bandingkan Test Case", note: "Menu sendiri",
    steps: [
      ["in", "Test case A dan B", "Dua kumpulan test case dari Riwayat atau file Excel/JSON, mis. hasil dari desain dan dari PRD."],
      ["code", "Rapikan & kembar persis", "Kata pembuka dibuang, kata bermakna sama disamakan (tampil = muncul = displayed). Yang isinya sama persis langsung jadi Sama."],
      ["code", "Skor kemiripan & bertentangan", "Dibandingkan per Sub Module: judul, Test Data, hasil harapan. Data sama tapi hasil berlawanan langsung ditandai Bertentangan."],
      ["ai", "Kemiripan makna", "Model embedding (ringan) menangkap kalimat beda kata tetapi sama maksud. Bukan AI chat, jadi cepat."],
      ["ai", "AI untuk yang ragu", "AI penulis hanya menilai pasangan yang masih ragu, beberapa sekaligus, dengan status yang sudah ditentukan. Mode cepat melewati langkah ini."],
      ["out", "Laporan perbandingan", "Berpasangan, Hanya di A, Hanya di B, Bertentangan, Kembar, Perlu dicek, kesimpulan, dan Excel."],
    ],
  },
  {
    id: "mdpdf", title: "MD Konversi ke PDF", note: "Konversi Dokumen",
    steps: [
      ["in", "File .md", "File PRD .md dari laptop (mis. unduhan Catatan atau Desain Konversi ke PRD), atau PRD yang sudah ada di TƎRᗩ."],
      ["code", "Baca format", "Judul, paragraf, daftar, tabel, kutipan, dan blok kode dikenali. Tanpa AI, jadi selesai dalam hitungan detik."],
      ["out", "PDF A4", "PDF rapi bernomor halaman langsung diunduh dan tercatat di Riwayat, jadi bisa diunduh lagi."],
    ],
  },
  {
    id: "generator", title: "Generator Test Case PRD", note: "Generator Test Case PRD",
    steps: [
      ["in", "Dokumen PRD", "PRD dipilih di menu Mulai baru, termasuk PRD hasil konversi catatan."],
      ["code", "Pecah aturan", "Setiap kalimat aturan dipecah menjadi aturan kecil: panjang, format, wajib diisi, perpindahan status, dan lainnya."],
      ["mix", "Rancang skenario uji", "Teknik uji dipilih otomatis: batas nilai, partisi, decision table, dan state transition. AI menganalisis nilai serta hasil decision table dari PRD."],
      ["ai", "Tulis test case", "AI penulis menulis judul, pre-condition, langkah, test data, dan expected result per kelompok kecil.", "loop"],
      ["code", "Periksa otomatis", "Kode mengecek angka, istilah, dan langkah. Kalau salah, test case ditulis ulang, maksimal 3 kali.", "loop"],
      ["ai", "AI pemeriksa", "Model AI kedua menilai setiap test case terhadap PRD. Yang meragukan ditandai Perlu dicek."],
      ["code", "Cakupan & rapikan", "Memastikan semua aturan punya test case, menggabungkan duplikat, dan menyamakan nama field dengan PRD."],
      ["out", "Excel test case", "Hasil siap diunduh, lengkap dengan ringkasan, daftar Perlu dicek, dan cakupan requirement."],
    ],
  },
];
const FLOW_TAG = { in: ["Masukan", "tag-in"], out: ["Hasil", "tag-out"], ai: ["AI", "tag-ai"], code: ["Kode", "tag-code"], mix: ["Kode + AI", "tag-ai"] };

function flowHtml(f, models) {
  const n = f.steps.length;
  const step = (s, i) => {
    const [kind, title, desc] = s;
    const [tag, cls] = FLOW_TAG[kind];
    const who = (kind === "ai" || kind === "mix") && !/makna/i.test(title) ? (/pemeriksa/i.test(title) ? models.judge : models.gen) : "";
    return `<li class="fstep" style="--i:${i};--n:${n}">
      <span class="fnum" aria-hidden="true">${i + 1}</span>
      <div class="fbody"><div class="fhead"><strong>${esc(title)}</strong><span class="ftag ${cls}">${esc(tag)}</span></div>
        <p>${esc(desc)}${who ? ` <span class="tiny muted">(${esc(who)})</span>` : ""}</p></div></li>`;
  };
  let html = "", i = 0;
  while (i < n) {
    if (f.steps[i][3] === "loop") {
      const start = i;
      while (i < n && f.steps[i][3] === "loop") i++;
      html += `<li class="floop"><span class="floop-label"><span class="spin-ico" aria-hidden="true">&#8635;</span> Diulang untuk setiap kelompok skenario</span>
        <ol class="flow">${f.steps.slice(start, i).map((s, k) => step(s, start + k)).join("")}</ol></li>`;
    } else { html += step(f.steps[i], i); i++; }
  }
  return `<section class="card" aria-labelledby="fl-${f.id}">
    <div class="card-head"><h2 id="fl-${f.id}">${esc(f.title)}</h2><span class="tiny muted">${n} tahap</span></div>
    <ol class="flow">${html}</ol></section>`;
}

/* ---------- siapa yang mengatur alur (orkestrator) */
function orchestratorHtml(models, src) {
  const shared = (src || {}).mode === "server";
  const layer = (n, title, sub, boxes) => `<li class="olayer" style="--i:${n}">
      <div class="olayer-head"><span class="fnum" aria-hidden="true" style="--i:${n};--n:5">${n + 1}</span><div><strong>${esc(title)}</strong><p>${esc(sub)}</p></div></div>
      <div class="oboxes">${boxes.map(([t, d, file, tag]) => `<div class="obox">
        <div class="fhead"><strong>${esc(t)}</strong>${tag === "now" ? `<span class="ftag tag-in">Dipakai sekarang</span>` : tag ? `<span class="ftag ${FLOW_TAG[tag][1]}">${esc(FLOW_TAG[tag][0])}</span>` : ""}</div>
        <p>${esc(d)}</p>${file ? `<span class="ofile mono">${esc(file)}</span>` : ""}</div>`).join("")}</div></li>`;
  const node = (code, name, tag, desc) => `<li class="gnode"><div class="gbox">
      <div class="fhead"><span class="mono gcode">${esc(code)}</span><strong>${esc(name)}</strong><span class="ftag ${FLOW_TAG[tag][1]}">${esc(FLOW_TAG[tag][0])}</span></div>
      <p>${esc(desc)}</p></div></li>`;
  return `
  <section class="card" aria-labelledby="orc-title">
    <div class="card-head"><h2 id="orc-title">Siapa yang mengatur alurnya?</h2><span class="tiny muted">Orkestrator</span></div>
    <p class="small">Di TƎRᗩ, yang mengatur urutan langkah (<b>orkestrator</b>) adalah <b>kode program, bukan AI</b>. AI hanya dipanggil sebagai pekerja di langkah tertentu dan tidak bisa mengubah urutan, melewati pemeriksaan, atau menambah langkah. Karena itu alurnya selalu sama dan hasilnya bisa ditelusuri.</p>
    <ol class="olayers">
      ${layer(0, "Kamu", "Memilih fitur dan menekan tombol di dashboard (browser).", [["Dashboard TƎRᗩ", "Tampilan yang kamu pakai sekarang.", "dashboard/index.html, app.js"]])}
      ${layer(1, "Manajer proses", "Menerima perintah dari dashboard dan menjaga proses tetap tertib.", [["dashboard.py", "Hanya satu proses AI berjalan dalam satu waktu, mencatat progres dan perkiraan waktu, menyediakan tombol Hentikan, dan menjaga laptop tidak tidur selama proses.", "dashboard.py", "code"]])}
      ${layer(2, "Orkestrator per fitur", "Setiap fitur punya pengatur urutannya sendiri.", [
        ["Generator Test Case PRD", "Diatur LangGraph: diagram langkah dengan simpang keputusan (lihat di bawah).", "tc_workflows/tc_graph.py", "code"],
        ["Catatan Konversi ke PRD", "Langkah berurutan: baca per baris, penjaga anti-karangan, susun per fitur, simpan.", "free_text_to_prd/pipeline.py", "code"],
        ["Desain Konversi ke PRD", "Langkah berurutan: potong layar, baca teks, kenali elemen, susun PRD, simpan.", "design_to_prd/pipeline.py", "code"],
        ["Bandingkan test case", "Saringan bertingkat: kode dulu, lalu kemiripan makna, AI chat hanya untuk pasangan yang ragu.", "tc_compare/pipeline.py", "code"],
        ["MD Konversi ke PDF", "Satu langkah tanpa AI, jadi tidak butuh orkestrator.", "tools/md_pdf.py", "code"]])}
      ${layer(3, "Pekerja", "Dipanggil orkestrator untuk mengerjakan satu tugas, lalu hasilnya dicek lagi oleh kode.", [
        ["AI penulis", `Menulis test case, mengambil aturan dari catatan, mengenali jenis elemen desain. (${models.gen})`, "agents/, tools/llm.py", "ai"],
        ["AI pemeriksa", `Memeriksa ulang test case yang hasilnya belum pasti. (${models.judge})`, "agents/semantic_verifier_agent.py", "ai"],
        ["Aturan kode", "Pemeriksaan pasti: format, kutipan asli, batas nilai, test case kembar, cakupan PRD.", "agents/, tools/", "code"],
        ["Pembaca teks Windows", "Membaca huruf di gambar desain persis apa adanya.", "design_to_prd/ocr.py", "code"]])}
      ${layer(4, "Mesin AI", "Tempat model AI benar-benar dijalankan, sesuai Pengaturan > Sumber AI.", [
        ["Ollama di laptop ini", "Semua proses dan data tetap di laptop ini.", "", shared ? "" : "now"],
        ["Server AI bersama", "AI di komputer teman lewat Tailscale, wajib login. Dokumen tetap di laptop ini; server hanya menjalankan AI.", "ai_server/", shared ? "now" : ""]])}
    </ol>
  </section>
  <section class="card" aria-labelledby="graph-title">
    <div class="card-head"><h2 id="graph-title">Orkestrator Generator Test Case PRD (LangGraph)</h2><span class="tiny muted mono">tc_workflows/tc_graph.py</span></div>
    <p class="small">LangGraph menjalankan langkah seperti diagram alur. Setelah setiap kelompok skenario diperiksa, ada <b>simpang keputusan</b> yang menentukan langkah berikutnya dengan aturan pasti, bukan tebakan AI.</p>
    <ol class="gflow">
      ${node("atomize", "Pecah aturan", "code", "PRD dipecah menjadi aturan kecil. AI hanya dipakai bila PRD tidak punya nomor FR/BR.")}
      ${node("design", "Rancang skenario", "mix", "Teknik uji dipilih: batas nilai, partisi, decision table, state transition. Skenario dimasukkan ke antrean.")}
      <li class="gloop"><span class="floop-label"><span class="spin-ico" aria-hidden="true">&#8635;</span> Diulang sampai antrean habis</span>
        <ol class="gflow">
          ${node("prepare_batch", "Ambil kelompok", "code", "Mengambil beberapa skenario berikutnya dari antrean (atur jumlahnya di Pengaturan).")}
          ${node("expand", "Tulis test case", "ai", "AI penulis menulis test case untuk kelompok ini.")}
          ${node("verify", "Periksa", "mix", "Kode mengecek format dan isi; yang ragu ditandai untuk AI pemeriksa.")}
          <li class="gnode gdecide"><div class="gbox">
            <div class="fhead"><span class="mono gcode">route_after_verify</span><strong>Simpang keputusan</strong><span class="ftag tag-code">Kode</span></div>
            <ul class="gbranch">
              <li><b>Masih ada yang belum lolos</b> di kelompok ini: kembali ke <span class="mono">expand</span> untuk ditulis ulang (dibatasi "Batas menulis ulang").</li>
              <li><b>Antrean masih ada</b>: kembali ke <span class="mono">prepare_batch</span> untuk kelompok berikutnya.</li>
              <li><b>Semua selesai</b>: lanjut ke pemeriksaan akhir.</li>
            </ul></div></li>
        </ol></li>
      ${node("judge_end", "Pemeriksaan akhir", "ai", "AI pemeriksa memeriksa ulang skenario yang hasilnya belum pasti, sekaligus di akhir supaya laptop tidak bolak-balik memuat AI.")}
      ${node("coverage", "Cek cakupan", "mix", "Memastikan setiap bagian PRD punya test case; yang belum ada dicatat di halaman Cakupan.")}
      ${node("export", "Buat Excel", "code", "Test case disusun menjadi file Excel siap unduh.")}
    </ol>
    <p class="tiny muted">Yang menyalakan diagram ini: <span class="mono">run.py</span> (fungsi run_pipeline), dipanggil dashboard saat kamu klik Mulai buat test case.</p>
  </section>`;
}

async function viewAlur() {
  let models = { gen: "AI penulis", judge: "AI pemeriksa" }, src = null;
  try {
    const pf = await api("/api/preflight");
    src = pf.source;
    const by = (r) => (pf.models.find((m) => new RegExp(r, "i").test(m.role)) || {}).name;
    models = { gen: by("penulis") || models.gen, judge: by("pemeriksa") || models.judge };
  } catch (e) { /* tanpa nama model pun diagram tetap tampil */ }
  const paused = S.flowPaused;
  app.innerHTML = `
  <header class="page-head"><div><h1>Alur kerja TƎRᗩ</h1>
    <p class="muted">Urutan proses yang terjadi di balik layar. Label <span class="ftag tag-ai">AI</span> berarti dikerjakan model AI di laptop ini, <span class="ftag tag-code">Kode</span> berarti aturan pasti yang dicek program (bukan tebakan AI).</p></div>
    <div class="actions"><button type="button" class="btn" data-action="flow-toggle">${paused ? "Putar animasi" : "Jeda animasi"}</button></div></header>
  <div class="flows${paused ? " paused" : ""}" style="display:flex;flex-direction:column;gap:24px">
    ${orchestratorHtml(models, src)}
    <h2 class="sec-title">Langkah setiap fitur</h2>
    <div class="grid grid-2">${FLOWS.map((f) => flowHtml(f, models)).join("")}</div>
  </div>
  <p class="small muted">Alur bisa disambung: hasil Catatan Konversi ke PRD dan Desain Konversi ke PRD bisa langsung dipakai di Generator Test Case PRD lewat tombol "Buat test case dari PRD ini", atau dijadikan PDF lewat tombol "Jadikan PDF"./p>`;
}

/* ================================================================= CATATAN QA -> PRD */
function stopNotesTimer() {
  if (S.notesTimer) { clearInterval(S.notesTimer); S.notesTimer = null; }
}

async function viewCatatan() {
  const n = await api("/api/notes");
  const running = n.status === "berjalan";
  const res = n.status === "selesai" ? n.result : null;
  const draft = S.notesDraft || { name: "", text: "" };
  const log = (n.log || []).map((l) => `<li><time>${esc(new Date(l.time * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }))}</time>${esc(l.msg)}</li>`).join("");
  app.innerHTML = `
  <header class="page-head"><div><p class="tiny muted">Konversi Dokumen</p><h1>Catatan Konversi ke PRD</h1>
    <p class="muted">Tempel catatan QA (bebas, boleh campur Indonesia dan Inggris). AI hanya merapikan isi catatan menjadi PRD: setiap aturan wajib punya kutipan asli dari catatan. Hal yang diragukan tidak dimasukkan ke PRD, melainkan ke catatan review terpisah yang bisa diunduh.</p></div></header>
  ${n.status === "gagal" ? `<div class="banner error" role="alert"><span><strong>Penyusunan gagal.</strong> ${esc(n.error || "")}</span></div>` : ""}
  <div class="grid grid-2">
    <section class="card" aria-labelledby="nt-title">
      <h2 id="nt-title">Catatan</h2>
      <label class="field" for="nt-name">Nama modul
        <input id="nt-name" type="text" maxlength="80" aria-required="true" placeholder="mis. Berita Acara" value="${esc(draft.name)}" ${running ? "disabled" : ""}>
        <span class="hint">Dipakai sebagai Module di test case dan nama file PRD.</span></label>
      <label class="field" for="nt-text">Isi catatan
        <textarea id="nt-text" class="notes" aria-required="true" ${running ? "disabled" : ""} placeholder="Tempel catatan QA di sini...">${esc(draft.text)}</textarea></label>
      <div class="actions"><button type="button" class="btn btn-primary" data-action="notes-start" ${running ? "disabled" : ""}>${running ? "Sedang disusun..." : "Susun PRD"}</button>
        <span class="small muted">Biasanya beberapa menit, tergantung panjang catatan.</span></div>
    </section>
    <section class="log" aria-labelledby="nt-log">
      <h2 id="nt-log">Progres</h2>
      <ul class="log-lines" aria-live="polite">${log || `<li>Belum ada proses.</li>`}</ul>
    </section>
  </div>
  ${res ? notesResult(res, "catatan") : ""}`;
  stopNotesTimer();
  if (running) S.notesTimer = setInterval(async () => {
    if (!location.hash.startsWith("#catatan")) return stopNotesTimer();
    const m = await api("/api/notes").catch(() => null);
    if (m && m.status !== "berjalan") { stopNotesTimer(); viewCatatan(); }
    else if (m) { const ul = document.querySelector(".log-lines"); if (ul) ul.innerHTML = (m.log || []).map((l) => `<li><time>${esc(new Date(l.time * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }))}</time>${esc(l.msg)}</li>`).join(""); }
  }, 3000);
}

function notesResult(r, kind) {
  const design = kind === "desain";
  const src = design ? "desain dan penjelasan" : "catatan";
  const qs = r.questions || [];
  const conflict = qs.filter((q) => q.jenis === "bertentangan").length;
  const qItem = (q) => `<li>${q.jenis === "bertentangan" ? `<span class="chip">Bertentangan</span> ` : q.jenis === "konfirmasi desain" ? `<span class="chip">Cek desain</span> ` : ""}${esc(q.pertanyaan)}${q.fitur ? ` <span class="tiny muted">(${esc(q.fitur)})</span>` : ""}${q.kutipan ? `<br><span class="quote">Catatan: “${esc(q.kutipan)}”</span>` : ""}</li>`;
  return `
  <section class="card" aria-labelledby="nr-title" style="margin-top:16px">
    <div class="card-head"><h2 id="nr-title">Hasil: ${esc(r.prd_file)}</h2>
      <span class="small muted">${num(r.features)} fitur, ${num(r.rules)} aturan; catatan review: ${num(qs.length)} pertanyaan${conflict ? ` (${conflict} bertentangan)` : ""}</span></div>
    ${design && r.stats ? `<p class="small muted">${num(r.stats.screens)} layar dari ${num(r.stats.images)} gambar${r.stats.duplicates ? ` (${num(r.stats.duplicates)} layar kembar dibaca sekali)` : ""}. Teks di dalam tanda kutip disalin persis dari desain oleh pembaca teks Windows.</p>` : ""}
    <p class="small muted">PRD ini sudah tersimpan dan muncul di daftar dokumen pada Mulai baru. PRD hanya berisi aturan dari ${src}; hal yang diragukan ada di catatan review terpisah.</p>
    <div class="card-head" style="margin-top:8px"><h3>Catatan review (terpisah dari PRD)</h3>
      <a class="btn btn-small" href="/api/conversions/${encodeURIComponent(r.id)}/review" download="${esc(r.review_file || "catatan_review.pdf")}">Unduh catatan review (PDF)</a></div>
    <p class="small muted">${design ? "Berisi hal di desain yang perlu dikonfirmasi, hal yang belum jelas, isian AI yang ditolak, teks yang terbaca per layar, dan asal setiap aturan." : "Berisi hal yang bertentangan atau belum jelas untuk ditanyakan ke tim, isian AI yang ditolak, baris catatan yang belum masuk, dan asal setiap aturan."} Tidak dipakai untuk membuat test case.</p>
    ${qs.length ? `<ol class="qlist">${qs.map(qItem).join("")}</ol>` : `<p class="small muted">Tidak ada pertanyaan terbuka.</p>`}
    ${(r.missed_lines || []).length ? `<details class="fold"><summary>${design ? "Baris penjelasan" : "Baris catatan"} yang belum masuk PRD (${r.missed_lines.length})</summary>
      <ul class="qlist">${r.missed_lines.map((m) => `<li>Baris ${m.baris}: “${esc(m.teks)}”</li>`).join("")}</ul></details>` : ""}
    ${(r.rejected || []).length ? `<details class="fold"><summary>Isian AI yang ditolak penjaga anti-karangan (${r.rejected.length})</summary>
      <ul class="qlist">${r.rejected.map((x) => `<li>${esc(x.pernyataan || "-")}<br><span class="quote">${esc(x.alasan || "")}</span></li>`).join("")}</ul></details>` : ""}
    <label class="field" for="nr-md" style="margin-top:12px">Isi PRD (boleh diedit)
      <textarea id="nr-md" class="notes tall">${esc((S.editedMd || {})[r.prd_file] ?? r.markdown)}</textarea></label>
    <div class="actions">
      <button type="button" class="btn" data-action="notes-save" data-file="${esc(r.prd_file)}">Simpan perubahan</button>
      <button type="button" class="btn" data-action="notes-md" data-file="${esc(r.prd_file)}">Unduh PRD (.md)</button>
      <button type="button" class="btn" data-action="notes-pdf" data-file="${esc(r.prd_file)}">Jadikan PDF</button>
      <button type="button" class="btn btn-primary" data-action="notes-use" data-file="${esc(r.prd_file)}">Buat test case dari PRD ini</button>
    </div>
    <p class="tiny muted">Unduh dan Jadikan PDF memakai isi PRD yang tampil di atas, termasuk editan yang belum disimpan.</p>
    <div class="actions" style="margin-top:4px;padding-top:12px;border-top:1px solid var(--line-soft)">
      <button type="button" class="btn" data-action="${design ? "design-reset" : "notes-reset"}">Mulai ulang (konversi baru)</button>
      <button type="button" class="btn" data-action="conv-delete" data-conv="${esc(r.id)}">Hapus hasil ini</button>
      <span class="small muted">Mulai ulang mengosongkan halaman ini, hasilnya tetap tersimpan di Riwayat. Hapus membuang PRD dan catatan review ini.</span>
    </div>
  </section>`;
}

async function notesStart() {
  const name = document.getElementById("nt-name").value.trim();
  const text = document.getElementById("nt-text").value;
  S.notesDraft = { name, text };
  if (!report([[document.getElementById("nt-name"), V.name(name)], [document.getElementById("nt-text"), V.notes(text)]])) return;
  try {
    await api("/api/notes", { method: "POST", body: { name, text } });
    viewCatatan();
  } catch (e) { serverErr(e); }
}

async function notesReset() {
  try {
    await api("/api/notes/reset", { method: "POST" });
    S.notesDraft = { name: "", text: "" };
    viewCatatan();
  } catch (e) { toast(e.message, true); }
}

async function convDelete(id, fromHistory) {
  if (!confirm("Hapus hasil konversi ini? PRD dan catatan review-nya ikut terhapus dan tidak bisa dikembalikan.")) return;
  try {
    await api(`/api/conversions/${encodeURIComponent(id)}`, { method: "DELETE" });
    toast("Hasil konversi dihapus");
    if (!fromHistory && location.hash.startsWith("#catatan")) S.notesDraft = { name: "", text: "" };
    if (!fromHistory && location.hash.startsWith("#desain")) S.design = null;
    route();
  } catch (e) { toast(e.message, true); }
}

async function notesSave(file, thenUse) {
  const ta = document.getElementById("nr-md");
  if (!report([[ta, V.prd(ta.value)]])) return;
  try {
    await api(`/api/prds/${encodeURIComponent(file)}`, { method: "PUT", body: { content: ta.value } });
    S.editedMd = { ...(S.editedMd || {}), [file]: ta.value };
    if (thenUse) { S.mulaiPrd = file; location.hash = "#mulai"; } else toast("PRD disimpan");
  } catch (e) { serverErr(e); }
}

/* ================================================================= DESAIN (gambar) -> PRD */
let cardSeq = 0;
const newCard = () => ({ key: ++cardSeq, nama: "", teks: "", images: [] });
function designState() {
  if (!S.design) S.design = { name: "", extra: "", cards: [newCard()] };
  return S.design;
}
function stopDesignTimer() {
  if (S.designTimer) { clearInterval(S.designTimer); S.designTimer = null; }
}
const logHtml = (log) => (log || []).map((l) => `<li><time>${esc(new Date(l.time * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }))}</time>${esc(l.msg)}</li>`).join("");

function designEstimate() {
  const D = designState();
  const busy = D.cards.flatMap((c) => c.images).filter((i) => i.status === "upload").length;
  if (busy) return `Sedang mengunggah dan memotong ${busy} gambar menjadi layar. Tombol Susun PRD aktif setelah semuanya selesai.`;
  const imgs = D.cards.flatMap((c) => c.images.filter((i) => i.status === "ok"));
  const screens = imgs.reduce((a, i) => a + (i.screens || 1), 0);
  const texts = D.cards.filter((c) => c.teks.trim()).length + (D.extra.trim() ? 1 : 0);
  if (!screens && !texts) return "Tambahkan gambar atau penjelasan untuk melihat perkiraan waktu.";
  const mins = Math.max(2, Math.round(screens * 2.5 + texts * 1.5 + 1));
  const dur = mins >= 90 ? `±${Math.round(mins / 6) / 10} jam` : `±${mins} menit`;
  return `Perkiraan kasar: ${dur}` + (screens ? ` (${screens} layar terdeteksi dari ${imgs.length} gambar; layar kembar dibaca sekali)` : "") + "." +
    (screens > 40 ? " Ini lama sekali; sebaiknya export per alur atau per section saja." : "");
}

const PHASES = { siapkan: "Menyiapkan gambar", baca_teks: "Membaca teks di gambar", kenali: "Mengenali elemen layar",
  penjelasan: "Membaca penjelasan", susun: "Menyusun PRD dan catatan review", selesai: "Menyimpan hasil" };

function designProgress(d) {
  const P = d.progress || {};
  const secs = P.screen_secs || [];
  const avg = secs.length ? secs.reduce((a, b) => a + b, 0) / secs.length : 150; // default ±2,5 menit per layar
  const st = P.screens_total || 0, sd = P.screens_done || 0, tt = P.texts_total || 0, td = P.texts_done || 0;
  const tail = 45;
  const total = st * avg + tt * 90 + tail;
  const done = sd * avg + td * 90 + (P.phase === "susun" || P.phase === "selesai" ? tail * 0.5 : 0);
  const pct = Math.max(2, Math.min(99, Math.round((done / Math.max(1, total)) * 100)));
  const remain = Math.max(30, total - done);
  return { pct, remain, avg, P, st, sd, tt, td, estimated: secs.length > 0 };
}

function designProgressHtml(d) {
  const g = designProgress(d);
  const elapsed = Math.max(0, (d.now || Date.now() / 1000) - (d.started || 0));
  const phase = PHASES[g.P.phase] || "Memulai";
  const detail = g.P.phase === "kenali" ? ` — layar ${num(Math.min(g.sd + 1, g.st))} dari ${num(g.st)}` :
    g.P.phase === "penjelasan" ? ` — ${num(g.td + 1)} dari ${num(g.tt)}` : "";
  const finish = new Date(Date.now() + g.remain * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
  return `<section class="card dprog" aria-labelledby="dp-h">
    <div class="dprog-head"><span class="spinner big" aria-hidden="true"></span>
      <div><h2 id="dp-h">${esc(phase)}${esc(detail)}</h2>
      <p class="small muted">Sudah berjalan <strong data-elapsed="${esc(String((d.started || 0)))}">${esc(fmtDur(elapsed))}</strong> · perkiraan sisa <strong>±${esc(fmtDur(g.remain))}</strong> (selesai sekitar ${esc(finish)})</p></div>
      <span class="dprog-pct">${g.pct}%</span></div>
    <div class="bar" role="progressbar" aria-label="Progres penyusunan PRD" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${g.pct}"><span style="width:${g.pct}%"></span></div>
    <p class="tiny muted">${g.estimated ? `Rata-rata ${esc(fmtDur(g.avg))} per layar di laptop ini.` : "Perkiraan awal ±2,5 menit per layar; makin tepat setelah layar pertama selesai."} Laptop dijaga tidak tidur; jangan tutup layar laptop. Halaman ini boleh ditinggal, prosesnya tetap jalan.</p>
  </section>`;
}

function imgsHtml(c, disabled) {
  return c.images.map((im, k) => `<figure class="dimg${im.status === "err" ? " err" : ""}${im.fresh && !(im.fresh = false) ? " img-in" : ""}">
      ${im.url ? `<img src="${esc(im.url)}" alt="">` : `<div class="dimg-ph" aria-hidden="true"></div>`}
      <figcaption><span class="dimg-name" title="${esc(im.name)}">${esc(im.name)}</span>
        <span class="tiny muted">${im.status === "upload" ? `<span class="spinner" aria-hidden="true"></span> mengunggah & menghitung layar...` : im.status === "err" ? esc(im.error || "gagal") : `${num(im.screens)} layar`}</span></figcaption>
      ${disabled ? "" : `<button type="button" class="dimg-x" data-action="design-img-del" data-card="${c.key}" data-img="${k}" aria-label="Hapus gambar ${esc(im.name)}">&times;</button>`}
    </figure>`).join("");
}

function cardHtml(c, i, n, disabled) {
  const fresh = S.cardJust === c.key;
  return `<section class="card dcard${fresh ? " card-in" : ""}" data-card="${c.key}" aria-labelledby="dc-${c.key}">
    <div class="card-head"><h2 id="dc-${c.key}">Halaman / fitur ${i + 1}</h2>
      ${n > 1 && !disabled ? `<button type="button" class="btn btn-small" data-action="design-card-del" data-card="${c.key}">Hapus</button>` : ""}</div>
    <label class="field" for="dn-${c.key}">Nama halaman / fitur
      <input id="dn-${c.key}" type="text" maxlength="80" aria-required="true" data-dfield="nama" data-card="${c.key}" placeholder="mis. Add User" value="${esc(c.nama)}" ${disabled ? "disabled" : ""}>
      <span class="hint">Jadi judul fitur di PRD dan Sub Module di test case.</span></label>
    <div class="dcard-body">
      <label class="field" for="dt-${c.key}">Penjelasan (opsional)
        <textarea id="dt-${c.key}" class="notes short" data-dfield="teks" data-card="${c.key}" placeholder="Aturan yang tidak terlihat di gambar, mis. siapa yang boleh mengakses, validasi, batas karakter..." ${disabled ? "disabled" : ""}>${esc(c.teks)}</textarea></label>
      <div class="field"><span>Gambar desain</span>
        <div class="dimgs" id="di-${c.key}" data-drop="${c.key}">${imgsHtml(c, disabled)}
          ${disabled ? "" : `<label class="dimg-add"><input type="file" accept="image/png,image/jpeg,image/webp" multiple data-dimg="${c.key}" class="sr-only">
            <span aria-hidden="true">+</span><span class="tiny">Tambah gambar</span></label>`}</div>
        <span class="hint">PNG/JPG hasil export Figma atau screenshot. Boleh banyak, boleh papan alur berisi beberapa layar. Bisa juga diseret ke sini.</span></div>
    </div></section>`;
}

async function viewDesain() {
  const d = await api("/api/design");
  const running = d.status === "berjalan";
  const res = d.status === "selesai" ? d.result : null;
  const D = designState();
  const locked = running || !!res;
  app.innerHTML = `
  <header class="page-head"><div><p class="tiny muted">Konversi Dokumen</p><h1>Desain Konversi ke PRD</h1>
    <p class="muted">Unggah gambar desain per halaman atau fitur, tambahkan penjelasan bila ada. Teks di gambar dibaca oleh pembaca teks bawaan Windows (persis, termasuk salah ketik), AI hanya menentukan jenisnya: tombol, field, label, dan seterusnya. Hal yang diragukan masuk catatan review terpisah.</p></div></header>
  ${d.status === "gagal" ? `<div class="banner error" role="alert"><span><strong>Penyusunan gagal.</strong> ${esc(d.error || "")}</span></div>` : ""}
  ${running ? `<div id="dz-prog">${designProgressHtml(d)}</div>` : ""}
  ${res ? "" : `
  <section class="card"><label class="field" for="dz-name">Nama modul
    <input id="dz-name" type="text" maxlength="80" aria-required="true" placeholder="mis. User Management" value="${esc(D.name)}" data-dfield="name" ${locked ? "disabled" : ""}>
    <span class="hint">Dipakai sebagai Module di test case dan nama file PRD.</span></label></section>
  <div id="dz-cards">${D.cards.map((c, i) => cardHtml(c, i, D.cards.length, locked)).join("")}</div>
  ${locked ? "" : `<div class="actions" style="justify-content:center;margin:4px 0 16px"><button type="button" class="btn" data-action="design-card-add">+ Tambah halaman / fitur</button></div>`}
  <section class="card"><label class="field" for="dz-extra">Deskripsi tambahan (opsional)
    <textarea id="dz-extra" class="notes short" data-dfield="extra" placeholder="Aturan umum yang berlaku di semua halaman, daftar role, dan sebagainya." ${locked ? "disabled" : ""}>${esc(D.extra)}</textarea></label>
    <div class="actions"><button type="button" class="btn btn-primary" id="dz-start" data-action="design-start" ${locked || designBusy() ? "disabled" : ""}>${running ? "Sedang disusun..." : designBusy() ? "Menunggu gambar..." : "Susun PRD"}</button>
      <span class="small muted" id="dz-est">${esc(designEstimate())}</span></div>
  </section>`}
  ${running || (d.log || []).length ? `<section class="log" aria-labelledby="dz-log"><h2 id="dz-log">Progres</h2>
    <ul class="log-lines" aria-live="polite">${logHtml(d.log) || "<li>Memulai...</li>"}</ul></section>` : ""}
  ${res ? notesResult(res, "desain") : ""}`;
  stopDesignTimer();
  if (running) {
    let last = { ...d, _at: Date.now() / 1000 };
    S.designTimer = setInterval(async () => {
      if (!location.hash.startsWith("#desain")) return stopDesignTimer();
      S.designTick = (S.designTick || 0) + 1;
      if (S.designTick % 3 === 0) {
        const m = await api("/api/design").catch(() => null);
        if (m && m.status !== "berjalan") { stopDesignTimer(); return viewDesain(); }
        if (m) {
          last = { ...m, _at: Date.now() / 1000 };
          const ul = document.querySelector(".log-lines"); if (ul) ul.innerHTML = logHtml(m.log);
        }
      }
      const box = document.getElementById("dz-prog");
      if (box) box.innerHTML = designProgressHtml({ ...last, now: (last.now || last._at) + (Date.now() / 1000 - last._at) });
    }, 1000);
  }
}

function designCard(key) { return designState().cards.find((c) => c.key === Number(key)); }
function refreshDesignImgs(c) {
  const box = document.getElementById(`di-${c.key}`);
  if (box) { const add = box.querySelector(".dimg-add"); box.querySelectorAll("figure").forEach((f) => f.remove()); add ? add.insertAdjacentHTML("beforebegin", imgsHtml(c, false)) : box.insertAdjacentHTML("afterbegin", imgsHtml(c, false)); }
  const e = document.getElementById("dz-est"); if (e) e.textContent = designEstimate();
  const b = document.getElementById("dz-start");
  if (b && b.textContent !== "Sedang disusun...") {
    const busy = designBusy();
    b.disabled = busy;
    b.textContent = busy ? "Menunggu gambar..." : "Susun PRD";
  }
}
// tombol Susun PRD baru aktif setelah semua gambar selesai diunggah dan dipotong per layar
function designBusy() { return designState().cards.some((c) => c.images.some((i) => i.status === "upload")); }
function readDataUrl(file) {
  return new Promise((ok, bad) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = () => bad(new Error("Gambar tidak terbaca")); r.readAsDataURL(file); });
}
async function designAddImages(key, files) {
  const c = designCard(key);
  if (!c) return;
  const box = document.getElementById(`di-${c.key}`);
  const problems = [];
  for (const file of files) {
    const bad = V.image(file) || (c.images.some((i) => i.name === file.name && i.bytes === file.size && i.status !== "err") ? `${file.name}: gambar ini sudah ditambahkan di halaman ini.` : "");
    if (bad) { problems.push(bad); continue; }
    if (box) clearErr(box);
    const im = { name: file.name, bytes: file.size, status: "upload", fresh: true, url: URL.createObjectURL(file) };
    c.images.push(im);
    refreshDesignImgs(c);
    try {
      const r = await api("/api/design/images", { method: "POST", body: { name: file.name, data: await readDataUrl(file) } });
      Object.assign(im, { id: r.id, screens: r.screens, status: "ok" });
    } catch (e) { Object.assign(im, { status: "err", error: e.message.replace(`${file.name}: `, "") }); problems.push(e.message.startsWith(file.name) ? e.message : `${file.name}: ${e.message}`); }
    refreshDesignImgs(c);
  }
  if (problems.length && box) { setErr(box, problems.join(" ")); toast(problems.length === 1 ? problems[0] : `${problems.length} gambar tidak bisa dipakai. Lihat keterangan di bawah kotak gambar.`, true); }
}
async function designStart() {
  const D = designState();
  if (designBusy()) return toast("Tunggu sampai semua gambar selesai diunggah", true);
  const $ = (id) => document.getElementById(id);
  const errs = [[$("dz-name"), V.name(D.name)]];
  const used = new Map();
  let filled = 0;
  D.cards.forEach((c, i) => {
    const n = i + 1;
    const nama = c.nama.replace(/\s+/g, " ").trim();
    const ok = c.images.filter((im) => im.status === "ok");
    const failed = c.images.filter((im) => im.status === "err");
    if (!nama && !c.teks.trim() && !c.images.length) return; // kartu kosong diabaikan
    filled++;
    let e = V.name(c.nama, `Nama halaman / fitur ke-${n}`);
    if (!e && used.has(nama.toLowerCase())) e = `Nama halaman / fitur ke-${n} sama dengan halaman ke-${used.get(nama.toLowerCase())}. Pakai nama yang berbeda.`;
    if (nama) used.set(nama.toLowerCase(), used.get(nama.toLowerCase()) || n);
    errs.push([$(`dn-${c.key}`), e]);
    errs.push([$(`dt-${c.key}`), V.optional(c.teks, `Penjelasan halaman ke-${n}`)]);
    if (failed.length) errs.push([$(`di-${c.key}`), `Ada ${failed.length} gambar yang gagal di halaman ke-${n}. Hapus gambar yang bertanda merah.`]);
    else if (!ok.length && !c.teks.trim()) errs.push([$(`di-${c.key}`), `Halaman ke-${n} belum berisi gambar atau penjelasan. Tambahkan salah satunya, atau hapus kartu ini.`]);
  });
  if (!filled) errs.push([$("dz-cards"), "Isi minimal satu halaman/fitur dengan gambar atau penjelasan."]);
  errs.push([$("dz-extra"), V.optional(D.extra, "Deskripsi tambahan")]);
  const total = D.cards.reduce((a, c) => a + c.teks.length, 0) + D.extra.length;
  if (total > 200000) errs.push([$("dz-extra"), `Total penjelasan terlalu panjang (maksimal ${V.fmt(200000)} karakter).`]);
  if (!report(errs)) return;
  const cards = D.cards.map((c) => ({ key: c.key, nama: c.nama.trim(), teks: c.teks, images: c.images.filter((i) => i.status === "ok").map((i) => ({ id: i.id, name: i.name })) }));
  try {
    await api("/api/design", { method: "POST", body: { name: D.name.trim(), extra: D.extra, cards } });
    await viewDesain();
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (e) { serverErr(e); }
}

async function designReset() {
  try {
    await api("/api/design/reset", { method: "POST" });
    S.design = null;
    viewDesain();
  } catch (e) { toast(e.message, true); }
}

/* ================================================================= SEDANG BERJALAN */
function closeStream() {
  if (S.es) { S.es.close(); S.es = null; }
}

async function viewBerjalan() {
  await refreshNav();
  if (!S.config) S.config = await api("/api/config").catch(() => ({}));
  const act = S.overview.active;
  if (!act) {
    closeStream();
    const runs = await api("/api/runs");
    const r = runs[0];
    let lastHtml = "";
    if (r) {
      const msg = { selesai: "Proses terakhir selesai.", dibatalkan: "Proses terakhir dihentikan.", gagal: `Proses terakhir gagal: ${r.error || "lihat jendela PowerShell untuk rinciannya"}.`, terputus: "Proses terakhir terputus karena server dashboard ditutup." }[r.status] || "";
      lastHtml = `<p>${esc(msg)} <span class="muted">${esc(r.prd_title)}, ${esc(fmtDate(r.finished))}</span></p>
`;
    }
    app.innerHTML = `<header class="page-head"><div><h1>Sedang berjalan</h1></div></header>
      <div class="empty"><p><strong>Tidak ada proses yang berjalan.</strong></p>${lastHtml}
        <div class="actions">${r && r.status === "selesai" ? `<a class="btn" href="#hasil/${esc(r.id)}">Lihat hasilnya</a>` : ""}
        <a class="btn btn-primary" href="#mulai">Mulai buat test case</a></div></div>`;
    return;
  }
  if (!S.es || !S.live || S.live.runId !== act.id) {
    closeStream();
    S.live = newLive(act); // stream baru memutar ulang semua event dari awal
  }
  S.live.run = act;
  renderLive();
  if (!S.es) {
    const es = new EventSource(`/api/runs/${encodeURIComponent(act.id)}/events`);
    S.es = es;
    es.onmessage = (m) => {
      try { reduce(S.live, JSON.parse(m.data)); } catch (e) { return; }
      if (currentView() === "berjalan") scheduleLiveRender();
    };
    es.addEventListener("end", () => {
      closeStream();
      refreshNav();
      if (currentView() === "berjalan") renderLive();
    });
  }
}

let liveTimer = null;
function scheduleLiveRender() {
  if (liveTimer) return;
  liveTimer = setTimeout(() => { liveTimer = null; renderLive(); }, 250);
}

function renderLive() {
  const L = S.live;
  if (!L) return;
  const run = L.run || {};
  const started = run.started || L.firstTime;
  const el = started ? Date.now() / 1000 - started : 0;
  const finished = L.status !== "berjalan";
  // perkiraan dari server: kecepatan kelompok terakhir, dikurangi waktu sejak perkiraan dibuat
  const eta = !finished && typeof L.eta === "number" ? Math.max(60, L.eta - (Date.now() / 1000 - (L.etaAt || Date.now() / 1000))) : null;
  const src = L.sources || {};
  const maxA = (S.config && S.config.max_attempts) || 3;
  const models = run.models || {};
  const genPct = L.total ? (100 * L.done) / L.total : 0;

  const head = {
    selesai: `<div class="banner info" role="status"><span><strong>Selesai.</strong> Semua test case sudah dibuat dan disimpan ke Excel.</span><a href="#hasil/${esc(L.runId)}">Lihat hasil</a></div>`,
    dibatalkan: `<div class="banner" role="status"><span><strong>Proses dihentikan.</strong> Test case yang sudah ditulis tidak disimpan.</span><a href="#mulai">Mulai lagi</a></div>`,
    gagal: `<div class="banner error" role="alert"><span><strong>Proses gagal.</strong> ${esc(L.error || "")}</span><a href="#mulai">Coba lagi</a></div>`,
  }[L.status] || "";

  app.innerHTML = `
  <header class="page-head"><div><h1>${{ selesai: "Proses selesai", dibatalkan: "Proses dihentikan", gagal: "Proses gagal" }[L.status] || "Sedang membuat test case"}</h1>
    <p class="muted">Dokumen: ${esc(run.prd_title)}, dimulai ${esc(fmtDate(run.started))}</p></div>
    <div class="actions">${finished ? "" : `<button type="button" class="btn btn-danger" data-action="cancel" ${L.cancelling ? "disabled" : ""}>${L.cancelling ? "Menghentikan..." : "Hentikan"}</button>`}</div></header>
  ${head}
  <section class="card" aria-labelledby="progress-title" style="gap:24px">
    <div class="big-progress">
      <h2 id="progress-title"><b>${num(L.done)}</b><span>dari ${L.total ? num(L.total) : "..."} skenario uji selesai</span></h2>
      <p class="muted num">${finished ? `Lama proses ${esc(fmtDur(runDur(run) || el))}${esc(pausedNote(run))}` : `Sudah berjalan ${esc(fmtDur(el))}${eta !== null ? `, kira-kira ${esc(fmtDur(eta))} lagi` : ", menghitung perkiraan waktu"}`}</p></div>
    <ol class="stages" aria-label="Tahapan">
      ${STAGES.map(([k, label]) => {
        const st = L.stages[k];
        const seg = k === "generate" && st.state === "running" ? `<span style="width:${genPct.toFixed(1)}%"></span>` : "";
        return `<li class="${st.state}"><span class="seg" aria-hidden="true">${seg}</span><b>${esc(label)}</b><span class="d">${esc(stageDetail(k, st, L))}</span></li>`;
      }).join("")}
    </ol>
    ${!finished && L.batch && L.stages.generate.state === "running" ? `<div class="now"><span style="font-weight:600">Sedang ditulis</span><span>${num(L.batch.n)} skenario, percobaan ${num(L.batch.attempt)} dari ${num(maxA)}</span></div>` : ""}
    ${finished ? "" : `<p class="small muted">Browser boleh ditutup. Proses tetap jalan selama jendela PowerShell dashboard tidak ditutup.${run.keep_awake ? " Laptop tidak akan tidur otomatis selama proses berjalan, tapi jangan tutup layar laptop atau pilih Sleep." : ""}</p>`}
  </section>
  <div class="grid grid-2">
    <section class="card" aria-labelledby="stat-title">
      <h2 id="stat-title">Sejauh ini</h2>
      <dl class="dl">
        <dt>Lolos pemeriksaan otomatis</dt><dd>${num(src.llm || 0)}</dd>
        <dt>Dibuat dari pola bawaan</dt><dd>${num(src.template || 0)}</dd>
        <dt>Ditandai ragu oleh AI pemeriksa</dt><dd style="color:var(--warn)">${num(src["llm-unverified"] || 0)}</dd>
        <dt>Ditulis ulang</dt><dd>${num(L.retry)}</dd>
        <dt>Skenario gagal dibuat</dt><dd>${num(L.dropped)}</dd>
        <dt>Diperiksa ulang oleh AI kedua</dt><dd>${num(L.judged)}</dd>
        <dt>Kecepatan</dt><dd>${el > 60 ? (L.done / (el / 60)).toLocaleString("id-ID", { maximumFractionDigits: 1 }) : "-"} test case per menit</dd>
      </dl>
      <p class="tiny muted">AI yang dipakai: ${esc(models.gen || "-")} menulis${models.judge ? `, ${esc(models.judge)} memeriksa ulang` : ""}${models.auto ? `, ${esc(models.auto)} untuk kasus rumit` : ""}.</p>
    </section>
    <section class="log" aria-labelledby="log-title">
      <div class="card-head"><h2 id="log-title">Aktivitas terbaru</h2><span class="tiny" style="opacity:.7">terbaru di atas</span></div>
      <ul class="log-lines">${L.logs.length ? L.logs.slice(0, 80).map((l) => `<li class="${l.cls}"><time>${esc(new Date(l.time * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }))}</time>${esc(l.text)}</li>`).join("") : '<li class="muted">Menunggu aktivitas pertama...</li>'}</ul>
    </section>
  </div>`;
}

async function cancelRun() {
  if (!S.live) return;
  if (!confirm("Hentikan proses? Test case yang sudah ditulis tidak disimpan.")) return;
  try {
    await api(`/api/runs/${encodeURIComponent(S.live.runId)}/cancel`, { method: "POST" });
    S.live.cancelling = true;
    toast("Berhenti setelah kelompok yang sedang ditulis selesai. Bisa beberapa menit.");
    renderLive();
  } catch (e) { toast(e.message, true); }
}

/* ================================================================= HASIL & CAKUPAN */
async function loadRunData(runId) {
  const runs = await api("/api/runs");
  let id = runId;
  if (!id) {
    const done = runs.filter((r) => r.status === "selesai");
    id = ((done.find((r) => r.has_tcs) || done[0]) || {}).id;
  }
  if (!id) return null;
  const H = S.hasil;
  if (H.runId !== id) {
    const [run, tcs] = await Promise.all([api(`/api/runs/${encodeURIComponent(id)}`), api(`/api/runs/${encodeURIComponent(id)}/tcs`)]);
    Object.assign(H, { runId: id, run, tcs, page: 0, sel: null, filters: { q: "", mod: "", tek: "", kat: "", flag: false } });
  }
  return H;
}

function noRunYet(title) {
  app.innerHTML = `<header class="page-head"><div><h1>${esc(title)}</h1></div></header>
    <div class="empty"><p><strong>Belum ada hasil.</strong> Hasil muncul di sini setelah satu proses selesai.</p>
    <a class="btn btn-primary" href="#mulai">Mulai buat test case</a></div>`;
}

function bars(obj, warm) {
  const rows = Object.entries(obj || {}).sort((a, b) => b[1] - a[1]);
  if (!rows.length) return '<p class="muted small">Tidak ada data.</p>';
  const max = Math.max(...rows.map((r) => r[1]), 1);
  return `<div class="hbars">${rows.map(([k, v]) => `<span>${esc(k)}</span><span class="fill${warm ? " warm" : ""}" style="width:${pct(v, max)}%"></span><span class="val">${num(v)}</span>`).join("")}</div>`;
}

async function viewHasil(runId, focus) {
  const H = await loadRunData(runId);
  if (!H) return noRunYet("Hasil test case");
  const run = H.run, rep = run.report || {}, prog = run.progress || {};
  if (S.pendingTc) {
    const i = H.tcs.findIndex((t) => t.tc_no === S.pendingTc);
    if (i >= 0) { H.sel = S.pendingTc; H.filters = { q: "", mod: "", tek: "", kat: "", flag: false }; H.page = Math.floor(i / PAGE); }
    S.pendingTc = null;
  }
  const cat = rep.by_category || {}, pri = rep.by_priority || {}, src = rep.by_source || {};
  const pos = cat.Positive || 0, neg = cat.Negative || 0, hi = pri.High || 0, me = pri.Medium || 0;
  const models = run.models || {};

  // cakupan per requirement
  const reqCount = {};
  H.tcs.forEach((t) => (t.requirement_ids || []).forEach((r) => { reqCount[r] = (reqCount[r] || 0) + 1; }));
  (rep.requirements_uncovered || []).forEach((r) => { reqCount[r] = reqCount[r] || 0; });
  const reqRows = Object.entries(reqCount).sort((a, b) => a[0].localeCompare(b[0], "id", { numeric: true }));
  const covTitle = rep.requirements_covered === rep.requirements_total && rep.atoms_covered === rep.atoms_total
    ? "Semua bagian PRD sudah tercakup" : "Ada bagian PRD yang belum tercakup";
  const cov = (label, a, b) => `<div style="display:flex;flex-direction:column;gap:8px"><div style="display:flex;justify-content:space-between"><span>${label}</span><span style="font-weight:600" class="num">${num(a)} / ${num(b)}</span></div><span class="bar"><span style="width:${pct(a, b)}%"></span></span></div>`;

  app.innerHTML = `
  <header class="page-head"><div><h1>Hasil test case</h1>
    <p class="muted">${esc(run.prd_title)}, selesai ${esc(fmtDate(run.finished, true))}${models.gen ? `, ditulis ${esc(models.gen)}` : ""}${run.imported ? " (diimpor dari hasil lama)" : ""}</p></div>
    <div class="actions">
      <a class="btn" href="#riwayat">Pilih hasil lain</a>
      <a class="btn" href="/api/runs/${encodeURIComponent(run.id)}/files/artifacts.json">Unduh data lengkap (JSON)</a>
      <a class="btn btn-primary" href="/api/runs/${encodeURIComponent(run.id)}/files/test_cases.xlsx">Unduh Excel</a></div></header>
  <section class="stat-strip" aria-label="Ringkasan">
    <div class="stat"><b>${num(rep.test_cases)}</b><span>test case</span></div>
    <a class="stat warn" href="#cek/${esc(run.id)}"><b>${num(rep.needs_review)}</b><span>perlu dicek</span></a>
    <div class="stat"><b>${num(rep.dedup_removed ?? 0)}</b><span>test case kembar digabung</span></div>
    <div class="stat"><b>${num(rep.dropped ?? 0)}</b><span>skenario gagal dibuat</span></div>
    <div class="stat"><b style="font-size:26px">${esc(fmtDur(runDur(run)))}</b><span>${prog.retry !== undefined ? `${num(prog.retry)} kali ditulis ulang` : "lama proses"}</span></div>
  </section>
  <section class="card" id="coverage" aria-labelledby="cov-title">
    <h2 id="cov-title">${esc(covTitle)}</h2>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr))">
      ${cov("Skenario uji", rep.obligations_covered, rep.obligations_total)}
      ${cov("Aturan PRD", rep.atoms_covered, rep.atoms_total)}
      ${cov("Requirement", rep.requirements_covered, rep.requirements_total)}</div>
    ${reqRows.length ? `<details ${focus === "cakupan" ? "open" : ""}><summary style="cursor:pointer;font-weight:500">Lihat jumlah test case per requirement</summary>
      <div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>Requirement</th><th class="r">Jumlah test case</th></tr></thead><tbody>
      ${reqRows.map(([r, n]) => `<tr><td class="mono">${esc(r)}</td><td class="r num">${n ? num(n) : '<span class="chip err">Belum tercakup</span>'}</td></tr>`).join("")}
      </tbody></table></div></details>` : ""}
  </section>
  <div class="grid grid-2">
    <section class="card" aria-labelledby="tech-title"><h2 id="tech-title">Per teknik uji</h2>${bars(rep.by_technique)}</section>
    <section class="card" aria-labelledby="mix-title"><h2 id="mix-title">Rincian</h2>
      <div style="display:flex;flex-direction:column;gap:8px">
        <div class="small" style="display:flex;justify-content:space-between"><span>Kategori</span><span><span class="pos" style="font-weight:600">Positive ${num(pos)}</span>, <span class="neg" style="font-weight:600">Negative ${num(neg)}</span></span></div>
        <div class="split" aria-hidden="true"><span style="width:${pct(pos, pos + neg)}%;background:var(--accent)"></span><span style="flex:1;background:var(--neg-bar)"></span></div></div>
      <div style="display:flex;flex-direction:column;gap:8px">
        <div class="small" style="display:flex;justify-content:space-between"><span>Prioritas</span><span><b>High ${num(hi)}</b>, <b>Medium ${num(me)}</b></span></div>
        <div class="split" aria-hidden="true"><span style="width:${pct(hi, hi + me)}%;background:var(--prio-high)"></span><span style="flex:1;background:var(--prio-med)"></span></div></div>
      <dl class="dl small">${Object.entries(src).map(([k, v]) => `<dt>${esc(SOURCE[k] || k)}</dt><dd>${num(v)}</dd>`).join("")}</dl>
    </section>
  </div>
  <section class="card" aria-labelledby="tc-title"><h2 id="tc-title">Test case</h2><div id="tc-zone"></div></section>`;
  renderTcZone();
  if (focus === "cakupan") document.getElementById("coverage").scrollIntoView({ block: "start" });
  else if (H.sel) { const d = document.getElementById("tc-detail"); if (d) d.scrollIntoView({ block: "center" }); }
}

// Sub Module/Menu = fitur yang diuji; hasil lama (sebelum kolom ini diubah) jatuh ke Module/Menu
const OLD_SUB = new Set(["Alur Utama", "Ambang Percobaan", "Aturan Bisnis", "Batas Jumlah Percobaan", "Batas Panjang", "Batas Panjang Maksimum", "Batas Panjang Minimum", "Decision Table", "Durasi Penguncian", "Edge Case", "Field Wajib", "Format Data", "Kelengkapan", "Keunikan Data", "Komposisi Karakter", "Masa Berlaku", "Panjang Tepat", "Performa", "Sekali Pakai", "Spasi Awal/Akhir", "Toleransi Waktu", "Transisi State", "Transisi Tidak Valid"]); // label jenis aturan di hasil lama, bukan nama fitur
const feat = (t) => (t.sub_label && t.sub_label !== "-" && !OLD_SUB.has(t.sub_label) ? t.sub_label : t.module);

function filteredTcs() {
  const H = S.hasil, f = H.filters, q = f.q.trim().toLowerCase();
  return H.tcs.filter((t) => (!q || `${t.tc_no} ${t.title}`.toLowerCase().includes(q))
    && (!f.mod || feat(t) === f.mod) && (!f.tek || t.technique === f.tek) && (!f.kat || t.category === f.kat)
    && (!f.flag || t.review_flag));
}

function renderTcZone() {
  const H = S.hasil, zone = document.getElementById("tc-zone");
  if (!zone) return;
  if (!H.tcs.length) {
    zone.innerHTML = `<div class="empty"><p>Hasil ini dibuat sebelum dashboard dipasang, jadi daftar test case-nya belum tersimpan. Excel tetap bisa diunduh. Jalankan proses baru untuk melihat tabel di sini.</p></div>`;
    return;
  }
  const uniq = (k) => [...new Set(H.tcs.map((t) => (k === "feat" ? feat(t) : t[k])).filter(Boolean))].sort();
  const opt = (k, label, val) => `<option value="">${label}</option>${uniq(k).map((v) => `<option ${v === val ? "selected" : ""}>${esc(v)}</option>`).join("")}`;
  const rows = filteredTcs();
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  H.page = Math.min(H.page, pages - 1);
  const shown = rows.slice(H.page * PAGE, H.page * PAGE + PAGE);
  const sel = H.tcs.find((t) => t.tc_no === H.sel);
  const f = H.filters;
  zone.innerHTML = `
  <div class="filters">
    <label class="field grow small" for="f-q">Cari judul atau ID<input id="f-q" type="search" maxlength="100" data-filter="q" value="${esc(f.q)}" placeholder="misalnya TC-109 atau login"></label>
    <label class="field small" for="f-mod">Fitur<select id="f-mod" data-filter="mod">${opt("feat", "Semua fitur", f.mod)}</select></label>
    <label class="field small" for="f-tek">Teknik<select id="f-tek" data-filter="tek">${opt("technique", "Semua teknik", f.tek)}</select></label>
    <label class="field small" for="f-kat">Kategori<select id="f-kat" data-filter="kat">${opt("category", "Semua", f.kat)}</select></label>
    <label class="check-inline small"><input type="checkbox" data-filter="flag" ${f.flag ? "checked" : ""}>Hanya yang perlu dicek</label>
  </div>
  <div class="tc-area">
    <div class="table-wrap">
      <table><thead><tr><th>ID</th><th>Judul</th><th>Fitur</th><th>Kategori</th><th>Teknik</th><th>Catatan</th></tr></thead><tbody>
      ${shown.length ? shown.map((t) => `<tr class="clickable ${t.tc_no === H.sel ? "selected" : ""}" data-action="pick" data-tc="${esc(t.tc_no)}" tabindex="0">
        <td class="mono">${esc(t.tc_no)}</td><td>${esc(t.title)}</td><td class="muted">${esc(feat(t))}</td>
        <td class="${t.category === "Negative" ? "neg" : "pos"}">${esc(t.category)}</td><td class="muted">${esc(t.technique)}</td>
        <td>${flagChips(t.review_flag)}</td></tr>`).join("") : `<tr><td colspan="6" class="muted">Tidak ada test case yang cocok dengan filter.</td></tr>`}
      </tbody></table>
      <div class="pager"><span>Menampilkan ${num(shown.length)} dari ${num(rows.length)}${rows.length !== H.tcs.length ? ` (total ${num(H.tcs.length)})` : ""}</span>
        <span class="actions"><button type="button" class="btn btn-small" data-action="prev" ${H.page === 0 ? "disabled" : ""}>Sebelumnya</button>
        <span>Halaman ${H.page + 1} dari ${pages}</span>
        <button type="button" class="btn btn-small" data-action="next" ${H.page >= pages - 1 ? "disabled" : ""}>Berikutnya</button></span></div>
    </div>
    <aside class="detail" id="tc-detail" aria-labelledby="detail-title">
      ${sel ? `<div><span class="mono muted">${esc(sel.tc_no)}${(sel.requirement_ids || []).length ? `, requirement ${esc(sel.requirement_ids.join(", "))}` : ""}</span>
        <h3 id="detail-title">${esc(sel.title)}</h3></div>
        ${flagInfo(sel.review_flag).map(([, txt]) => `<div class="note">${esc(txt)}</div>`).join("")}
        <dl>
          <div><dt>Modul dan fitur</dt><dd>${esc(sel.module)}${feat(sel) !== sel.module ? `, ${esc(feat(sel))}` : ""}</dd></div>
          <div><dt>Kategori dan prioritas</dt><dd>${esc(sel.category)}, ${esc(sel.priority)}</dd></div>
          <div><dt>Teknik uji</dt><dd>${esc(sel.technique)}</dd></div>
          <div><dt>Pre-condition</dt><dd>${esc(sel.preconditions || "-")}</dd></div>
          ${sel.steps ? `<div><dt>Test Steps</dt><dd style="white-space:pre-line">${esc(sel.steps)}</dd></div>` : ""}
          <div><dt>Test Data</dt><dd class="mono">${esc(sel.test_data || "-")}</dd></div>
          <div><dt>Expected Result</dt><dd>${esc(sel.expected_result)}</dd></div>
        </dl>` : `<h3 id="detail-title">Detail test case</h3><p class="muted">Klik salah satu baris untuk melihat isinya.</p>`}
    </aside>
  </div>`;
}

/* ================================================================= PERLU DICEK */
async function viewCek(runId) {
  const H = await loadRunData(runId);
  if (!H) return noRunYet("Perlu dicek");
  const run = H.run;
  const rv = await api(`/api/runs/${encodeURIComponent(run.id)}/review`);
  markReviewSeen(run.id);
  const groups = Object.fromEntries(GROUPS.map((g) => [g.key, []]));
  rv.tcs.forEach((t) => {
    const parts = flagInfo(t.review_flag);
    const seen = new Set();
    parts.forEach(([k, txt]) => { if (!seen.has(k)) { seen.add(k); groups[k].push({ t, txt }); } });
  });
  const total = rv.tcs.length;
  const used = GROUPS.filter((g) => groups[g.key].length);
  const SHOW = 3;
  const sec = (g) => {
    const items = groups[g.key];
    const open = S.cekOpen && S.cekOpen.has(g.key);
    const list = open ? items : items.slice(0, SHOW);
    return `<section class="card" id="g-${g.key}" aria-labelledby="h-${g.key}" style="gap:4px">
      <h2 id="h-${g.key}">${esc(g.title)}</h2><p class="small muted" style="margin-bottom:12px">${esc(g.desc)}</p>
      ${list.map(({ t, txt }, i) => `<article class="item${open && i >= SHOW && S.cekJust === g.key ? " item-in" : ""}"><div class="item-head"><span class="mono muted">${esc(t.tc_no)}</span><h3>${esc(t.title)}</h3></div>
        <p class="small">${esc(t.expected_result)}</p><p class="tiny muted">${esc(txt)}</p>
        <button type="button" class="link-btn small" data-action="goto-tc" data-tc="${esc(t.tc_no)}">Buka detail</button></article>`).join("")}
      ${items.length > SHOW ? `<button type="button" class="link-btn small" style="padding-top:10px" data-action="toggle-group" data-group="${g.key}">${open ? "Tampilkan lebih sedikit" : `Tampilkan ${items.length - SHOW} lainnya`}</button>` : ""}
    </section>`;
  };
  app.innerHTML = `
  <header class="page-head"><div><h1>Perlu dicek</h1>
    <p class="muted">${total ? `${num(total)} test case dari hasil ${esc(fmtDate(run.finished))} perlu dibaca sebelum dipakai. Dikelompokkan menurut alasannya; yang paling mungkin salah ada di atas.` : `Tidak ada test case yang ditandai di hasil ${esc(fmtDate(run.finished))}.`}</p></div>
    <div class="actions"><a class="btn" href="#riwayat">Pilih hasil lain</a></div></header>
  ${H.tcs.length ? "" : `<div class="banner">Hasil ini dibuat sebelum dashboard dipasang, jadi daftar test case belum tersimpan. Jalankan proses baru untuk melihat pengelompokannya.</div>`}
  <div class="review-layout">
    <nav class="review-nav" aria-label="Kelompok alasan">
      ${used.map((g) => `<button type="button" data-action="jump" data-target="g-${g.key}">${esc(g.title)}<span>${num(groups[g.key].length)}</span></button>`).join("") || '<p class="small muted" style="padding:8px 12px">Tidak ada kelompok.</p>'}
      <hr>
      <button type="button" data-action="jump" data-target="g-drop">Skenario gagal dibuat<span>${num(rv.dropped.length)}</span></button>
      <button type="button" data-action="jump" data-target="g-merge">Test case kembar digabung<span>${num(rv.merged.length)}</span></button>
      ${used.length > 1 ? '<p class="tiny muted" style="margin:8px 12px 4px">Satu test case bisa punya dua alasan, jadi total kelompok bisa lebih dari jumlah test case.</p>' : ""}
    </nav>
    <div class="review-main">
      ${used.map(sec).join("")}
      <section class="card" id="g-drop" aria-labelledby="h-drop" style="gap:4px"><h2 id="h-drop">Skenario gagal dibuat</h2>
        ${rv.dropped.length ? `<p class="small muted" style="margin-bottom:12px">Skenario ini tidak punya test case. Tulis manual atau jalankan ulang.</p>
          ${rv.dropped.map((d) => `<article class="item"><h3 style="font-size:15px;font-weight:600">${esc(cleanScenario(d.scenario))}</h3>
            <p class="tiny muted">${esc(friendlyDrop(d.reason))}${(d.requirement_ids || []).length ? `. Requirement ${esc(d.requirement_ids.join(", "))}` : ""}</p></article>`).join("")}`
          : `<p class="small muted">Semua skenario berhasil dibuatkan test case.</p>`}</section>
      <section class="card" id="g-merge" aria-labelledby="h-merge" style="gap:4px"><h2 id="h-merge">Test case kembar digabung</h2>
        ${rv.merged.length ? `<p class="small muted" style="margin-bottom:12px">Isinya sama dengan test case lain, jadi digabung. Requirement keduanya tetap tercatat.</p>
          ${rv.merged.map((d) => `<article class="item"><p class="small">${esc(cleanTitle(d.title))}</p></article>`).join("")}`
          : `<p class="small muted">Tidak ada test case kembar.</p>`}</section>
    </div>
  </div>`;
}

/* ================================================================= RIWAYAT */
async function viewRiwayat() {
  const [runs, convs, cmps, pdfs] = await Promise.all([api("/api/runs"), api("/api/conversions").catch(() => []),
    api("/api/compares").catch(() => []), api("/api/mdpdfs").catch(() => [])]);
  S.runsCache = runs;
  S.compare = new Set([...S.compare].filter((id) => runs.some((r) => r.id === id)));
  const rows = [
    ...runs.map((r) => ({ kind: "tc", t: r.finished || r.started || 0, r })),
    ...convs.map((c) => ({ kind: "conv", t: c.time || 0, c })),
    ...cmps.map((c) => ({ kind: "cmp", t: c.time || 0, c })),
    ...pdfs.map((c) => ({ kind: "pdf", t: c.time || 0, c })),
  ].sort((x, y) => y.t - x.t);
  const cmpRow = (c) => { const st = c.stats || {}, l = c.labels || {}; return `<tr>
    <td></td><td class="num nw">${esc(fmtDate(c.time))}</td><td class="nw"><span class="chip info">Bandingkan TC</span></td><td>${esc(c.name)}</td>
    <td>${esc(l.a)} ${esc(pctTxt(st.a_coverage))} dan ${esc(l.b)} ${esc(pctTxt(st.b_coverage))} berpasangan, ${num(st.bertentangan)} bertentangan, ${num(st.perlu_dicek)} perlu dicek</td>
    <td class="r">${esc(fmtDur(st.seconds))}</td><td>${statusChip("selesai")}</td>
    <td><span class="actions"><a class="btn btn-small" href="#banding/${encodeURIComponent(c.id)}">Lihat hasil</a>
      <a class="btn btn-small" href="/api/compares/${encodeURIComponent(c.id)}/xlsx">Excel</a>
      <button type="button" class="btn btn-small" data-action="hist-del" data-url="/api/compares/${encodeURIComponent(c.id)}">Hapus</button></span></td></tr>`; };
  const pdfRow = (c) => `<tr>
    <td></td><td class="num nw">${esc(fmtDate(c.time))}</td><td class="nw"><span class="chip grey">MD ke PDF</span></td><td>${esc(c.title || c.source)}</td>
    <td><span class="mono">${esc(c.source)}</span> menjadi PDF ${num(c.pages)} halaman (${esc(fmtSize(c.bytes || 0))})</td>
    <td class="r">${esc(fmtDur(c.seconds))}</td><td>${statusChip("selesai")}</td>
    <td><span class="actions"><a class="btn btn-small" href="/api/mdpdfs/${encodeURIComponent(c.id)}/pdf" download="${esc(c.pdf_file)}">Unduh PDF</a>
      <button type="button" class="btn btn-small" data-action="hist-del" data-url="/api/mdpdfs/${encodeURIComponent(c.id)}">Hapus</button></span></td></tr>`;
  const tcRow = (r) => { const rep = r.report || {}; return `<tr>
    <td><input type="checkbox" data-action="pick-run" data-run="${esc(r.id)}" ${S.compare.has(r.id) ? "checked" : ""} aria-label="Pilih proses ${esc(fmtDate(r.finished || r.started))} untuk dibandingkan"></td>
    <td class="num nw">${esc(fmtDate(r.finished || r.started))}</td><td class="nw"><span class="chip brand">Test case PRD</span></td><td>${esc(r.prd_title)}</td>
    <td>${num(rep.test_cases)} test case, ${num(rep.needs_review)} perlu dicek</td>
    <td class="r">${esc(fmtDur(runDur(r)))}</td><td>${statusChip(r.status)}</td>
    <td><span class="actions">${r.status === "selesai" ? `<a class="btn btn-small" href="#hasil/${esc(r.id)}">Lihat hasil</a>` : r.status === "berjalan" ? `<a class="btn btn-small" href="#berjalan">Lihat progres</a>` : ""}
      ${r.status !== "berjalan" ? `<button type="button" class="btn btn-small" data-action="delete-run" data-run="${esc(r.id)}">Hapus</button>` : ""}</span></td></tr>`; };
  const convRow = (c) => `<tr>
    <td></td><td class="num nw">${esc(fmtDate(c.time))}</td><td class="nw"><span class="chip grey">${c.kind === "desain" ? "Konversi desain" : "Konversi catatan"}</span></td><td>${esc(c.module || c.prd_file)}</td>
    <td>${num(c.features)} fitur, ${num(c.rules)} aturan, ${num(c.questions)} pertanyaan${c.conflicts ? ` (${num(c.conflicts)} bertentangan)` : ""}</td>
    <td class="r">${esc(fmtDur(c.seconds))}</td><td>${statusChip("selesai")}</td>
    <td><span class="actions">
      <a class="btn btn-small" href="/api/conversions/${encodeURIComponent(c.id)}/prd" download="${esc(c.prd_file)}">Unduh PRD</a>
      <a class="btn btn-small" href="/api/conversions/${encodeURIComponent(c.id)}/review" download>Review (PDF)</a>
      ${c.prd_exists ? `<button type="button" class="btn btn-small" data-action="conv-use" data-file="${esc(c.prd_file)}">Buat test case</button>` : ""}
      <button type="button" class="btn btn-small" data-action="conv-delete" data-conv="${esc(c.id)}">Hapus</button></span></td></tr>`;
  app.innerHTML = `
  <header class="page-head"><div><h1>Riwayat</h1><p class="muted">Semua proses di laptop ini beserta hasilnya (pembuatan test case, konversi catatan, konversi desain, MD ke PDF, dan perbandingan test case), terbaru di atas.</p></div>
    <div class="actions"><button type="button" class="btn" data-action="compare">Bandingkan angka 2 proses yang dipilih</button></div></header>
  <section class="card hist">
    ${rows.length ? `<div class="table-wrap"><table style="min-width:980px"><thead><tr>
      <th><span class="sr-only">Pilih</span></th><th>Waktu</th><th>Jenis</th><th>Dokumen</th><th>Ringkasan</th>
      <th class="r">Lama</th><th>Status</th><th style="width:300px"><span class="sr-only">Aksi</span></th></tr></thead><tbody>
      ${rows.map((x) => (x.kind === "tc" ? tcRow(x.r) : x.kind === "conv" ? convRow(x.c) : x.kind === "cmp" ? cmpRow(x.c) : pdfRow(x.c))).join("")}
      </tbody></table></div>` : `<div class="empty"><p>Belum ada proses. Mulai dari konversi catatan atau buat test case dari PRD.</p>
        <div class="actions"><a class="btn" href="#catatan">Catatan Konversi ke PRD</a><a class="btn btn-primary" href="#mulai">Mulai buat test case</a></div></div>`}
  </section>
  <section class="card" id="compare-zone" hidden aria-labelledby="cmp-title"></section>`;
}

function renderCompare() {
  const ids = [...S.compare];
  if (ids.length !== 2) return toast("Pilih tepat 2 proses untuk dibandingkan", true);
  const [a, b] = ids.map((id) => S.runsCache.find((r) => r.id === id)).sort((x, y) => (x.finished || 0) - (y.finished || 0));
  const R = (r) => r.report || {};
  const rows = [
    ["Selesai", (r) => fmtDate(r.finished), null], ["Dokumen", (r) => r.prd_title, null], ["AI penulis", (r) => (r.models || {}).gen || "-", null],
    ["Test case", (r) => R(r).test_cases, 0], ["Perlu dicek", (r) => R(r).needs_review, -1], ["Skenario gagal dibuat", (r) => R(r).dropped, -1],
    ["Test case kembar digabung", (r) => R(r).dedup_removed, 0], ["Ditulis ulang", (r) => (r.progress || {}).retry, -1],
    ["Requirement tercakup", (r) => (R(r).requirements_total ? `${R(r).requirements_covered} / ${R(r).requirements_total}` : null), null],
    ["Lama (menit)", (r) => (runDur(r) ? Math.round(runDur(r) / 60) : null), -1],
  ];
  const z = document.getElementById("compare-zone");
  z.hidden = false;
  z.innerHTML = `<h2 id="cmp-title">Perbandingan</h2><div class="table-wrap"><table><thead><tr><th></th><th>Lebih lama</th><th>Lebih baru</th><th>Perubahan</th></tr></thead><tbody>
    ${rows.map(([label, f, better]) => {
      const va = f(a), vb = f(b);
      let delta = "";
      if (better !== null && typeof va === "number" && typeof vb === "number") {
        const d = vb - va;
        const good = better === 0 ? null : (d < 0) === (better < 0);
        delta = d === 0 ? '<span class="muted">sama</span>' : `<span class="${good === null ? "" : good ? "pos" : "neg"}">${d > 0 ? "+" : ""}${num(d)}</span>`;
      }
      return `<tr><td>${esc(label)}</td><td class="num">${esc(va ?? "-")}</td><td class="num">${esc(vb ?? "-")}</td><td class="num">${delta}</td></tr>`;
    }).join("")}</tbody></table></div>
    <p class="tiny muted">Biru berarti membaik, oranye berarti memburuk.</p>`;
  z.scrollIntoView({ block: "start" });
}

async function deleteRun(id) {
  if (!confirm("Hapus proses ini dari Riwayat? File Excel di folder runs ikut terhapus.")) return;
  try {
    await api(`/api/runs/${encodeURIComponent(id)}`, { method: "DELETE" });
    S.compare.delete(id);
    if (S.hasil.runId === id) S.hasil.runId = null;
    toast("Proses dihapus dari Riwayat");
    refreshNav();
    route();
  } catch (e) { toast(e.message, true); }
}

/* ================================================================= BANDINGKAN TEST CASE
   Kode dulu (rapikan, kembar persis, kunci struktur, skor kemiripan, cek bertentangan), lalu kemiripan makna,
   dan AI chat hanya untuk pasangan yang masih ragu. */
const CMP_STATUS = { sama: ["Sama", "ok"], berkaitan: ["Berkaitan", "info"], sebagian: ["Sebagian", "brand"], bertentangan: ["Bertentangan", "err"], perlu_dicek: ["Perlu dicek", ""], berbeda: ["Berbeda", "grey"] };
const CMP_BY = { kode: "Kode", makna: "Kode + kemiripan makna", ai: "AI", mode_cepat: "Kode (mode cepat)" };
const CMP_PHASE = { rapikan: "Merapikan teks test case", makna: "Menghitung kemiripan makna", cocokkan: "Mencocokkan test case", ai: "AI menilai pasangan yang ragu", simpulkan: "Menyusun kesimpulan", selesai: "Selesai" };

function cmpState() {
  S.cmp = S.cmp || { a: { kind: "run", id: "", label: "Kumpulan A", file: null }, b: { kind: "run", id: "", label: "Kumpulan B", file: null }, mode: "lengkap", name: "" };
  return S.cmp;
}
function stopCompareTimer() { if (S.cmpTimer) { clearInterval(S.cmpTimer); S.cmpTimer = null; } }

function cmpSideHtml(side, st, sources, locked) {
  const s = st[side], U = side.toUpperCase();
  const fileBox = s.file
    ? `<div class="cmp-file"><div><span class="mono">${esc(s.file.name)}</span><br><span class="small">${num(s.file.count)} test case terbaca${s.file.sheet ? ` dari sheet "${esc(s.file.sheet)}"` : ""}.</span>
        ${(s.file.columns || []).length ? `<br><span class="tiny muted">Kolom dikenali: ${esc(s.file.columns.join(", "))}</span>` : ""}
        ${(s.file.missing || []).length ? `<br><span class="tiny" style="color:var(--warn)">Kolom kosong: ${esc(s.file.missing.join(", "))}. Perbandingan tetap jalan, hanya kurang teliti.</span>` : ""}</div>
        ${locked ? "" : `<button type="button" class="btn btn-small" data-action="cmp-file-clear" data-side="${side}">Ganti file</button>`}</div>`
    : s.uploading ? `<p class="small"><span class="spinner" aria-hidden="true"></span>Membaca ${esc(s.uploading)}...</p>`
      : `<div class="mdrop" id="cmp-file-${side}" data-cdrop="${side}" tabindex="-1">
          <label class="btn"><input type="file" accept=".xlsx,.json" data-cfile="${side}" class="sr-only">Pilih file</label>
          <span class="small muted">Excel (.xlsx) atau JSON, maks. 20 MB. Bisa juga diseret ke sini.</span></div>`;
  return `<section class="card" aria-labelledby="cmp-h-${side}"><h2 id="cmp-h-${side}">Test case ${U}</h2>
    <label class="field" for="cmp-label-${side}">Nama kumpulan
      <input id="cmp-label-${side}" type="text" maxlength="30" data-cfield="label" data-side="${side}" value="${esc(s.label)}" placeholder="mis. Dari desain" ${locked ? "disabled" : ""}>
      <span class="hint">Dipakai di hasil, mis. "Dari desain" dan "Dari PRD".</span></label>
    <fieldset id="cmp-src-${side}"><legend>Sumber</legend><div class="src-pick">
      <label class="radio-card"><input type="radio" name="cmp-src-${side}" value="run" ${s.kind === "run" ? "checked" : ""} ${locked || !sources.length ? "disabled" : ""}><span><b>Dari Riwayat</b><br><span class="tiny muted">${sources.length ? `${num(sources.length)} hasil Generator Test Case PRD` : "Belum ada hasil test case yang selesai"}</span></span></label>
      <label class="radio-card"><input type="radio" name="cmp-src-${side}" value="file" ${s.kind === "file" ? "checked" : ""} ${locked ? "disabled" : ""}><span><b>Unggah file</b><br><span class="tiny muted">Excel atau JSON dari mana saja</span></span></label>
    </div></fieldset>
    ${s.kind === "run"
      ? `<label class="field" for="cmp-run-${side}">Hasil run
          ${sources.length ? `<select id="cmp-run-${side}" data-cfield="id" data-side="${side}" ${locked ? "disabled" : ""}><option value="">Pilih hasil run...</option>
            ${sources.map((r) => `<option value="${esc(r.id)}" ${r.id === s.id ? "selected" : ""}>${esc(r.title)} · ${esc(fmtDate(r.finished))}${r.test_cases != null ? ` · ${num(r.test_cases)} TC` : ""}</option>`).join("")}</select>`
            : ""}</label>`
      : `<div class="field"><span>File test case</span>${fileBox}</div>`}
  </section>`;
}

function cmpProgressHtml(d) {
  const P = d.progress || {}, now = d.now || Date.now() / 1000;
  const el = Math.max(0, now - (d.started || now));
  let pctv = 5, detail = "", remain = null;
  if (P.phase === "makna" && P.emb_total) { pctv = 10 + Math.round(30 * P.emb_done / P.emb_total); detail = ` — ${num(P.emb_done)} dari ${num(P.emb_total)}`; }
  else if (P.phase === "cocokkan") { pctv = 40 + Math.round(10 * (P.match_done || 0) / Math.max(1, P.match_total || 1)); }
  else if (P.phase === "ai" && P.ai_total) {
    pctv = 50 + Math.round(45 * P.ai_done / P.ai_total); detail = ` — kelompok ${num(Math.min(P.ai_done + 1, P.ai_total))} dari ${num(P.ai_total)}`;
    const secs = P.ai_secs || [], avg = secs.length ? secs.reduce((x, y) => x + y, 0) / secs.length : 60;
    remain = Math.max(20, (P.ai_total - P.ai_done) * avg);
  } else if (P.phase === "simpulkan") { pctv = 96; remain = d.mode === "lengkap" ? 60 : 5; }
  return `<section class="card dprog" aria-labelledby="cp-h">
    <div class="dprog-head"><span class="spinner big" aria-hidden="true"></span>
      <div><h2 id="cp-h">${esc(CMP_PHASE[P.phase] || "Memulai")}${esc(detail)}</h2>
      <p class="small muted">Sudah berjalan <strong>${esc(fmtDur(el))}</strong>${remain != null ? ` · perkiraan sisa <strong>±${esc(fmtDur(remain))}</strong>` : ""}</p></div>
      <span class="dprog-pct">${pctv}%</span></div>
    <div class="bar" role="progressbar" aria-label="Progres perbandingan" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pctv}"><span style="width:${pctv}%"></span></div>
    <p class="tiny muted">${P.phase === "ai" ? "AI hanya menilai pasangan yang masih ragu; sisanya sudah diputuskan kode. " : ""}Halaman ini boleh ditinggal, prosesnya tetap jalan.</p>
  </section>`;
}

function cmpTcCell(t) {
  if (!t) return "-";
  return `<span class="mono">${esc(t.no)}</span> ${esc(t.title || "-")}
    <div class="tiny muted">${t.sub ? `${esc(t.sub)} · ` : ""}${t.category ? `${esc(t.category)} · ` : ""}Data: ${esc(t.data || "-")}</div>
    <div class="tiny muted">Hasil: ${esc(t.expected || "-")}</div>`;
}

function cmpResultHtml(r, saved) {
  const s = r.stats, la = r.labels.a, lb = r.labels.b, tab = S.cmpTab || "pairs";
  const pairs = r.pairs || [];
  const tabs = [["pairs", "Berpasangan", pairs.filter((p) => ["sama", "berkaitan", "sebagian", "bertentangan"].includes(p.status)).length],
    ["conflict", "Bertentangan", s.bertentangan], ["review", "Perlu dicek", s.perlu_dicek],
    ["only_a", `Hanya di ${la}`, s.a_only], ["only_b", `Hanya di ${lb}`, s.b_only], ["dup", "Kembar", s.dup_a + s.dup_b]];
  const q = (S.cmpQ || "").toLowerCase();
  const hit = (...xs) => !q || xs.some((x) => String(x || "").toLowerCase().includes(q));
  let rows = [], head = "";
  if (["pairs", "conflict", "review"].includes(tab)) {
    const want = tab === "pairs" ? ["sama", "berkaitan", "sebagian", "bertentangan"] : tab === "conflict" ? ["bertentangan"] : ["perlu_dicek"];
    rows = pairs.filter((p) => want.includes(p.status) && hit(p.a, p.b, p.alasan, p.a_tc.title, p.b_tc.title));
    head = `<tr><th>Status</th><th>${esc(la)}</th><th>${esc(lb)}</th><th>Alasan</th></tr>`;
    rows = rows.map((p) => `<tr><td class="nw"><span class="chip ${CMP_STATUS[p.status][1]}">${esc(CMP_STATUS[p.status][0])}</span><div class="tiny muted">skor ${esc(String(p.skor).replace(".", ","))}<br>${esc(CMP_BY[p.by] || p.by)}</div></td>
      <td>${cmpTcCell(p.a_tc)}</td><td>${cmpTcCell(p.b_tc)}</td><td class="small">${esc(p.alasan)}</td></tr>`);
  } else if (tab === "only_a" || tab === "only_b") {
    const other = tab === "only_a" ? lb : la;
    rows = r[tab].filter((t) => hit(t.no, t.title, t.sub, t.expected)).map((t) => `<tr><td>${cmpTcCell(t)}</td>
      <td class="small">${t.mirip ? `Paling mirip: <span class="mono">${esc(t.mirip)}</span> (skor ${esc(String(t.mirip_skor).replace(".", ","))})` : `Tidak ada yang mirip di ${esc(other)}`}</td></tr>`);
    head = `<tr><th>Test case</th><th>Catatan</th></tr>`;
  } else {
    const d = [...r.duplicates.a.map((x) => [la, x]), ...r.duplicates.b.map((x) => [lb, x])].filter(([, x]) => hit(x.a, x.b));
    rows = d.map(([l, x]) => `<tr><td>${esc(l)}</td><td class="mono">${esc(x.a)}</td><td class="mono">${esc(x.b)}</td><td class="small">${esc(x.alasan)}</td></tr>`);
    head = `<tr><th>Kumpulan</th><th>Test case</th><th>Kembar dengan</th><th>Alasan</th></tr>`;
  }
  const limit = S.cmpLimit || 100, shown = rows.slice(0, limit);
  const c = r.conclusion || {};
  return `
  <section class="card" aria-labelledby="cr-h">
    <div class="card-head"><div><h2 id="cr-h">${esc(r.name)}</h2>
      <p class="small muted">${esc(la)}: ${esc(r.sources.a.source)} · ${esc(lb)}: ${esc(r.sources.b.source)} · ${r.mode === "lengkap" ? "Mode lengkap" : "Mode cepat"}${r.stats.seconds != null ? ` · ${esc(fmtDur(r.stats.seconds))}` : ""}</p></div>
      <div class="actions">${r.id ? `<a class="btn btn-primary" href="/api/compares/${encodeURIComponent(r.id)}/xlsx">Unduh Excel</a>` : ""}
        ${saved ? `<a class="btn" href="#banding">Kembali</a>` : `<button type="button" class="btn" data-action="cmp-reset">Perbandingan baru</button>`}</div></div>
    <div class="stat-strip" style="border:0">
      <div class="stat"><b>${esc(pctTxt(s.a_coverage))}</b><span>${esc(la)} berpasangan (${num(s.a_paired)} dari ${num(s.a_total)})</span></div>
      <div class="stat"><b>${esc(pctTxt(s.b_coverage))}</b><span>${esc(lb)} berpasangan (${num(s.b_paired)} dari ${num(s.b_total)})</span></div>
      <div class="stat${s.bertentangan ? " warn" : ""}"><b>${num(s.bertentangan)}</b><span>bertentangan</span></div>
      <div class="stat${s.perlu_dicek ? " warn" : ""}"><b>${num(s.perlu_dicek)}</b><span>perlu dicek</span></div>
    </div>
  </section>
  <section class="card" aria-labelledby="cc-h"><h2 id="cc-h">Kesimpulan</h2>
    ${r.ai_summary ? `<p>${esc(r.ai_summary)} <span class="ftag tag-ai">AI</span></p>` : ""}
    ${(c.summary || []).map((l) => `<p class="small">${esc(l)}</p>`).join("")}
    <h3 class="rel-group">Rekomendasi</h3><ul class="rel-list">${(c.recommendations || []).map((l) => `<li>${esc(l)}</li>`).join("")}</ul>
    ${(r.notes || []).length ? `<p class="tiny" style="color:var(--warn)">${esc(r.notes.join(" "))}</p>` : ""}
    <p class="tiny muted">${esc((c.limits || []).join(" "))} Diputuskan kode: ${num(s.decided_by_code)} pasangan; dinilai AI: ${num(s.judged_by_ai)} pasangan.</p>
  </section>
  <section class="card" aria-labelledby="ct-h" style="gap:12px">
    <h2 id="ct-h" class="sr-only">Detail</h2>
    <div class="cmp-tabs" role="tablist">${tabs.map(([k, l, n]) => `<button type="button" role="tab" aria-selected="${k === tab}" data-action="cmp-tab" data-tab="${k}">${esc(l)} <span class="num">${num(n)}</span></button>`).join("")}</div>
    <input type="search" id="cmp-q" placeholder="Cari nomor, judul, atau alasan..." value="${esc(S.cmpQ || "")}" aria-label="Cari di tabel">
    ${rows.length ? `<div class="table-wrap"><table class="cmp-table${["only_a", "only_b", "dup"].includes(tab) ? " two" : ""}"><thead>${head}</thead><tbody>${shown.join("")}</tbody></table></div>
      ${rows.length > limit ? `<button type="button" class="btn" data-action="cmp-more">Tampilkan ${num(Math.min(100, rows.length - limit))} lagi (dari ${num(rows.length)})</button>` : ""}`
      : `<p class="muted">Tidak ada data di bagian ini.</p>`}
  </section>`;
}
const pctTxt = (v) => `${String(Math.round((v || 0) * 10) / 10).replace(".", ",")}%`;

async function viewBanding(arg) {
  stopCompareTimer();
  if (arg) {
    const r = await api(`/api/compares/${encodeURIComponent(arg)}`);
    if (S.cmpView !== arg) { S.cmpView = arg; S.cmpTab = "pairs"; S.cmpQ = ""; S.cmpLimit = 100; }
    app.innerHTML = `<header class="page-head"><div><h1>Bandingkan Test Case</h1></div></header>${cmpResultHtml(r, true)}`;
    S.cmpShown = r;
    return;
  }
  const [d, sources, past] = await Promise.all([api("/api/compare"), api("/api/compare/sources"), api("/api/compares")]);
  const st = cmpState();
  if (!sources.length) ["a", "b"].forEach((k) => { if (st[k].kind === "run") st[k].kind = "file"; }); // belum ada hasil run: langsung unggah file
  const running = d.status === "berjalan", res = d.status === "selesai" ? d.result : null;
  if (res && S.cmpView !== res.id) { S.cmpView = res.id; S.cmpTab = "pairs"; S.cmpQ = ""; S.cmpLimit = 100; }
  S.cmpShown = res;
  const locked = running;
  app.innerHTML = `
  <header class="page-head"><div><h1>Bandingkan Test Case</h1>
    <p class="muted">Bandingkan dua kumpulan test case, mis. hasil dari desain dengan hasil dari PRD, atau versi lama dengan versi baru. Kode memutuskan yang sudah jelas, kemiripan makna mempersempit sisanya, dan AI hanya menilai pasangan yang masih ragu. Test case sumber tidak diubah.</p></div></header>
  ${d.status === "gagal" ? `<div class="banner error" role="alert"><span><strong>Perbandingan gagal.</strong> ${esc(d.error || "")}</span><button type="button" class="btn btn-small" data-action="cmp-reset">Tutup</button></div>` : ""}
  ${running ? `<div id="cmp-prog">${cmpProgressHtml(d)}</div>` : ""}
  ${res ? cmpResultHtml(res, false) : `
  ${sources.length ? "" : `<div class="banner" role="status"><span><strong>Belum ada hasil test case di Riwayat.</strong> Pilihan "Dari Riwayat" hanya berisi hasil <b>Generator Test Case PRD</b> yang sudah selesai (bukan hasil konversi PRD). Unggah file Excel/JSON test case, atau buat test case dulu.</span><a href="#mulai">Mulai buat test case</a></div>`}
  <div class="grid grid-2">${cmpSideHtml("a", st, sources, locked)}${cmpSideHtml("b", st, sources, locked)}</div>
  <section class="card" aria-labelledby="cmp-opt-h"><h2 id="cmp-opt-h">Cara membandingkan</h2>
    <fieldset id="cmp-mode"><legend>Mode</legend><div class="src-pick">
      <label class="radio-card"><input type="radio" name="cmp-mode" value="lengkap" ${st.mode === "lengkap" ? "checked" : ""} ${locked ? "disabled" : ""}><span><b>Lengkap</b><br><span class="tiny muted">Kode, kemiripan makna, lalu AI untuk yang ragu. Biasanya ±10–20 menit.</span></span></label>
      <label class="radio-card"><input type="radio" name="cmp-mode" value="cepat" ${st.mode === "cepat" ? "checked" : ""} ${locked ? "disabled" : ""}><span><b>Cepat</b><br><span class="tiny muted">Tanpa AI chat, ±1 menit. Pasangan yang ragu masuk Perlu dicek.</span></span></label>
    </div></fieldset>
    <ul class="ready-list" style="margin:0">
      <li>${icon(d.embed ? "ok" : "warn")}<span><span style="font-weight:500">Kemiripan makna ${d.embed ? "tersedia" : "belum tersedia"}</span><br><span class="tiny muted">${d.embed ? `Model ${esc(d.embed_model)}` : `Model ${esc(d.embed_model)} belum ada, jadi lapis ini dilewati. ${(d.ai ? "" : "AI belum terhubung. ")}Jalankan Pasang_Tera.bat, atau: ollama pull ${esc(d.embed_model)}`}</span></span></li>
      <li>${icon(d.ai ? "ok" : "warn")}<span><span style="font-weight:500">AI ${d.ai ? "terhubung" : "belum terhubung"}</span><br><span class="tiny muted">${d.ai ? "Dipakai di mode Lengkap untuk pasangan yang ragu." : "Mode Lengkap butuh AI. Mode Cepat tetap bisa dipakai."}</span></span></li>
    </ul>
    <label class="field" for="cmp-name">Nama perbandingan (opsional)
      <input id="cmp-name" type="text" maxlength="80" data-cfield="name" value="${esc(st.name)}" placeholder="${esc(`${st.a.label} vs ${st.b.label}`)}" ${locked ? "disabled" : ""}></label>
    <div class="actions"><button type="button" class="btn btn-primary" data-action="cmp-start" ${locked || st.a.uploading || st.b.uploading ? "disabled" : ""}>${running ? "Sedang membandingkan..." : "Bandingkan"}</button>
      <span class="small muted">Hanya satu proses yang berjalan dalam satu waktu.</span></div>
  </section>`}
  ${running || (d.log || []).length ? `<section class="log" aria-labelledby="cmp-log"><h2 id="cmp-log">Progres</h2><ul class="log-lines" aria-live="polite">${logHtml(d.log) || "<li>Memulai...</li>"}</ul></section>` : ""}
  ${past.length ? `<section class="card" aria-labelledby="cmp-past"><h2 id="cmp-past">Perbandingan sebelumnya</h2>
    <div class="table-wrap"><table><thead><tr><th>Nama</th><th>Waktu</th><th class="r">Berpasangan</th><th class="r">Bertentangan</th><th></th></tr></thead><tbody>
    ${past.map((p) => `<tr><td>${esc(p.name)}<br><span class="tiny muted">${esc((p.labels || {}).a)} vs ${esc((p.labels || {}).b)} · ${p.mode === "lengkap" ? "Lengkap" : "Cepat"}</span></td>
      <td class="nw small">${esc(fmtDate(p.time))}</td>
      <td class="r small">${esc(pctTxt((p.stats || {}).a_coverage))} / ${esc(pctTxt((p.stats || {}).b_coverage))}</td>
      <td class="r num">${num((p.stats || {}).bertentangan)}</td>
      <td><div class="actions" style="justify-content:flex-end"><a class="btn btn-small" href="#banding/${encodeURIComponent(p.id)}">Lihat</a>
        <a class="btn btn-small" href="/api/compares/${encodeURIComponent(p.id)}/xlsx">Excel</a>
        <button type="button" class="btn btn-small" data-action="cmp-del" data-cmp="${esc(p.id)}">Hapus</button></div></td></tr>`).join("")}
    </tbody></table></div></section>` : ""}`;
  if (running) {
    let last = { ...d, _at: Date.now() / 1000 }, tick = 0;
    S.cmpTimer = setInterval(async () => {
      if (!location.hash.startsWith("#banding")) return stopCompareTimer();
      tick++;
      if (tick % 2 === 0) {
        const m = await api("/api/compare").catch(() => null);
        if (m && m.status !== "berjalan") { stopCompareTimer(); return viewBanding(); }
        if (m) { last = { ...m, _at: Date.now() / 1000 }; const ul = document.querySelector(".log-lines"); if (ul) ul.innerHTML = logHtml(m.log); }
      }
      const box = document.getElementById("cmp-prog");
      if (box) box.innerHTML = cmpProgressHtml({ ...last, now: (last.now || last._at) + (Date.now() / 1000 - last._at) });
    }, 1000);
  }
}

function cmpRerenderTable() {
  const r = S.cmpShown; if (!r) return;
  const saved = location.hash.startsWith("#banding/");
  const cards = app.querySelectorAll("section.card");
  const html = cmpResultHtml(r, saved);
  const tmp = document.createElement("div"); tmp.innerHTML = html;
  const fresh = tmp.querySelectorAll("section.card"), old = [...cards].filter((c) => c.querySelector("#ct-h"));
  if (old[0] && fresh[2]) old[0].replaceWith(fresh[2]);
}

async function cmpUpload(side, file) {
  const st = cmpState(), s = st[side];
  const box = () => document.getElementById(`cmp-file-${side}`);
  const err = !/\.(xlsx|json)$/i.test(file.name) ? `${file.name}: format harus Excel (.xlsx) atau JSON (.json).`
    : !file.size ? `${file.name}: file kosong.` : file.size > 20 * 1024 * 1024 ? `${file.name}: ukuran file maksimal 20 MB.` : "";
  if (err) { setErr(box(), err); toast(err, true); return; }
  s.uploading = file.name; s.file = null; await viewBanding();
  try {
    const data = await readDataUrl(file);
    const r = await api("/api/compare/upload", { method: "POST", body: { name: file.name, data, side } });
    s.file = r; s.token = r.token;
    toast(`${file.name}: ${r.count} test case terbaca`);
  } catch (e) { s.uploading = null; await viewBanding(); serverErr(e); return; }
  s.uploading = null; await viewBanding();
}

async function cmpStart() {
  const st = cmpState(), $ = (id) => document.getElementById(id);
  const errs = [];
  for (const side of ["a", "b"]) {
    const s = st[side], U = side.toUpperCase(), lbl = s.label.trim();
    errs.push([$(`cmp-label-${side}`), !lbl ? `Nama kumpulan ${U} wajib diisi.` : lbl.length > 30 ? `Nama kumpulan ${U} maksimal 30 karakter.` : /[\\/:*?"<>|]/.test(lbl) ? `Nama kumpulan ${U} tidak boleh memakai karakter \\ / : * ? " < > |` : ""]);
    if (s.kind === "run") errs.push([$(`cmp-run-${side}`) || $(`cmp-src-${side}`), s.id ? "" : `Pilih hasil run untuk ${U}.`]);
    else errs.push([$(`cmp-file-${side}`) || $(`cmp-src-${side}`), s.file ? "" : `Unggah file test case untuk ${U}.`]);
  }
  const same = st.a.kind === st.b.kind && (st.a.kind === "run" ? st.a.id && st.a.id === st.b.id : st.a.token && st.a.token === st.b.token);
  if (same) errs.push([$("cmp-run-b") || $("cmp-src-b"), "A dan B memakai sumber yang sama. Pilih dua kumpulan test case yang berbeda."]);
  if (st.a.label.trim() && st.a.label.trim().toLowerCase() === st.b.label.trim().toLowerCase()) errs.push([$("cmp-label-b"), "Nama kumpulan A dan B harus berbeda."]);
  if (st.name.trim()) errs.push([$("cmp-name"), V.name(st.name, "Nama perbandingan")]);
  if (!report(errs)) return;
  const side = (s) => ({ kind: s.kind, id: s.id, token: s.token, label: s.label.trim() });
  try {
    await api("/api/compare", { method: "POST", body: { a: side(st.a), b: side(st.b), mode: st.mode, name: st.name.trim() } });
    S.cmpView = null;
    await viewBanding();
    refreshNav();
  } catch (e) { serverErr(e); }
}

/* ================================================================= MD KONVERSI KE PDF
   Tanpa AI: PDF dibuat saat tombol diklik dan langsung diunduh, tidak disimpan dan tidak mengganggu proses lain. */
function mdState() { S.md = S.md || { files: [], seq: 0 }; return S.md; }
const mdTitle = (t) => ((String(t).match(/^#\s+(.+)$/m) || [])[1] || "").replace(/[*_`]/g, "").trim();
const fmtSize = (b) => (b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toLocaleString("id-ID", { maximumFractionDigits: 1 })} KB` : `${(b / 1048576).toLocaleString("id-ID", { maximumFractionDigits: 1 })} MB`);

function mdAdd(name, content, size) {
  const M = mdState();
  const err = V.md(name, size, content);
  if (err) return err;
  if (M.files.some((f) => f.name === name && f.content === content)) return `${name}: sudah ada di daftar.`;
  M.files.push({ key: ++M.seq, name, content, size, title: mdTitle(content) });
  return "";
}

async function mdAddFiles(files) {
  const errs = [];
  for (const f of files) {
    let text = "";
    if (/\.(md|markdown)$/i.test(f.name) && f.size <= 2000000) { try { text = await f.text(); } catch (e) { text = ""; } }
    const e = mdAdd(f.name, text, f.size);
    if (e) errs.push(e);
  }
  await viewMdpdf();
  const box = document.getElementById("md-files");
  if (errs.length) { setErr(box, errs.join(" ")); toast(errs.length === 1 ? errs[0] : `${errs.length} file tidak bisa ditambahkan.`, true); }
  else if (files.length) toast(`${files.length} file ditambahkan`);
}

async function mdAddPrd() {
  const sel = document.getElementById("md-prd");
  if (!sel || !sel.value) { report([[sel || document.getElementById("md-files"), "Pilih PRD dulu."]]); return; }
  try {
    const p = await api(`/api/prds/${encodeURIComponent(sel.value)}`);
    const e = mdAdd(p.file, p.content, new Blob([p.content]).size);
    if (e) { report([[sel, e]]); return; }
    S.mdPick = sel.value;
    await viewMdpdf();
    toast(`${p.file} ditambahkan`);
  } catch (e) { toast(e.message, true); }
}

async function mdConvert(f) {
  const r = await fetch("/api/md-pdf", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: f.name, content: f.content }) });
  if (!r.ok) { let d = {}; try { d = await r.json(); } catch (e) { /* bukan JSON */ } throw new Error(d.detail || `Gagal membuat PDF (${r.status})`); }
  return r.blob();
}
const pdfName = (n) => `${n.replace(/\.(md|markdown)$/i, "") || "dokumen"}.pdf`;

async function mdRun(key, how, btn) {
  const f = mdState().files.find((x) => x.key === Number(key));
  if (!f) return;
  const win = how === "view" ? window.open("", "_blank") : null; // dibuka langsung supaya tidak diblokir browser
  const label = btn ? btn.innerHTML : "";
  if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spinner" aria-hidden="true"></span>Membuat PDF...`; }
  try {
    const blob = await mdConvert(f);
    const url = URL.createObjectURL(blob);
    if (win) win.location.href = url;
    else { const a = document.createElement("a"); a.href = url; a.download = pdfName(f.name); document.body.appendChild(a); a.click(); a.remove(); toast(`${pdfName(f.name)} diunduh`); }
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    return true;
  } catch (e) {
    if (win) win.close();
    toast(e.message, true);
    return false;
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = label; }
  }
}

async function mdAll(btn) {
  const files = mdState().files;
  btn.disabled = true;
  let ok = 0;
  for (let i = 0; i < files.length; i++) {
    btn.innerHTML = `<span class="spinner" aria-hidden="true"></span>Membuat PDF ${i + 1} dari ${files.length}...`;
    if (await mdRun(files[i].key, "download")) ok++;
    await new Promise((r) => setTimeout(r, 400)); // jeda supaya browser tidak menolak unduhan beruntun
  }
  btn.disabled = false; btn.textContent = "Unduh semua PDF";
  if (ok > 1) toast(`${ok} PDF diunduh. Bila browser bertanya, izinkan unduhan beberapa file.`);
}

async function viewMdpdf() {
  const M = mdState();
  if (S.mdQueue) { const q = S.mdQueue; S.mdQueue = null; const e = mdAdd(q.name, q.content, new Blob([q.content]).size); if (e && !/sudah ada/.test(e)) toast(e, true); }
  let prds = [];
  try { prds = await api("/api/prds"); } catch (e) { /* daftar PRD opsional */ }
  const pick = S.mdPick && prds.some((p) => p.file === S.mdPick) ? S.mdPick : "";
  app.innerHTML = `
  <header class="page-head"><div><p class="tiny muted">Konversi Dokumen</p><h1>MD Konversi ke PDF</h1>
    <p class="muted">Ubah file PRD .md (hasil Catatan atau Desain Konversi ke PRD, atau buatan sendiri) menjadi PDF yang rapi untuk dibagikan. Tanpa AI: selesai dalam hitungan detik dan tidak mengganggu proses lain yang sedang berjalan.</p></div></header>
  <div class="grid grid-2">
    <section class="card" aria-labelledby="md-up-title"><h2 id="md-up-title">Tambah file</h2>
      <div class="field"><span>File Markdown (.md)</span>
        <div class="mdrop" id="md-files" data-mdrop tabindex="-1">
          <label class="btn"><input type="file" id="md-input" accept=".md,.markdown,text/markdown" multiple class="sr-only">Pilih file .md</label>
          <span class="small muted">atau seret file ke sini</span></div>
        <span class="hint">Maksimal 2 MB per file. Boleh beberapa file sekaligus.</span></div>
    </section>
    <section class="card" aria-labelledby="md-prd-title"><h2 id="md-prd-title">Ambil dari TƎRᗩ</h2>
      <label class="field" for="md-prd">PRD yang sudah ada
        ${prds.length ? `<select id="md-prd"><option value="">Pilih PRD...</option>${prds.map((p) => `<option value="${esc(p.file)}" ${p.file === pick ? "selected" : ""}>${esc(p.title)} (${esc(p.file)})</option>`).join("")}</select>`
          : `<span class="muted" style="font-weight:400">Belum ada PRD di TƎRᗩ.</span>`}</label>
      ${prds.length ? `<div><button type="button" class="btn" data-action="md-add-prd">Tambahkan ke daftar</button></div>` : ""}
    </section>
  </div>
  <section class="card" aria-labelledby="md-list-title">
    <div class="card-head"><h2 id="md-list-title">Daftar file${M.files.length ? ` (${M.files.length})` : ""}</h2>
      ${M.files.length ? `<div class="actions">${M.files.length > 1 ? `<button type="button" class="btn btn-primary" data-action="md-all">Unduh semua PDF</button>` : ""}
        <button type="button" class="btn" data-action="md-clear">Kosongkan daftar</button></div>` : ""}</div>
    ${M.files.length ? `<ul class="md-list">${M.files.map((f) => `<li>
        <div class="md-info"><span class="mono">${esc(f.name)}</span><span class="tiny muted">${f.title ? `${esc(f.title)} · ` : ""}${esc(fmtSize(f.size))}</span></div>
        <div class="actions"><button type="button" class="btn btn-small" data-action="md-view" data-md="${f.key}">Lihat PDF</button>
          <button type="button" class="btn btn-small btn-primary" data-action="md-download" data-md="${f.key}">Unduh PDF</button>
          <button type="button" class="btn btn-small" data-action="md-del" data-md="${f.key}" aria-label="Hapus ${esc(f.name)} dari daftar">Hapus</button></div></li>`).join("")}</ul>`
      : `<p class="muted">Belum ada file. Tambahkan file .md dari laptop atau pilih PRD yang sudah ada di TƎRᗩ.</p>`}
    <p class="tiny muted">PDF dibuat saat tombol diklik dan langsung diunduh. PDF yang pernah dibuat tercatat di menu Riwayat dan bisa diunduh lagi.</p>
  </section>`;
}

/* ================================================================= PENGATURAN */
const KINDS = [["decision", "Tabel keputusan"], ["edge", "Kasus tepi"], ["whitespace", "Spasi di awal/akhir"]];

async function viewPengaturan() {
  const [cfg, mi, pf, vault] = await Promise.all([api("/api/config"), api("/api/models"), api("/api/preflight"), api("/api/vault").catch(() => null)]);
  S.config = cfg;
  const installed = (mi.models || []).map((m) => m.name);
  const sel = (id, val, allowNone) => {
    const names = [...new Set([...installed, ...(val ? [val] : [])])];
    return `<select id="${id}">${allowNone ? `<option value="" ${!val ? "selected" : ""}>Tidak dipakai</option>` : ""}
      ${names.map((n) => `<option value="${esc(n)}" ${n === val ? "selected" : ""}>${esc(n)}${installed.includes(n) || installed.includes(`${n}:latest`) ? "" : " (belum terpasang)"}</option>`).join("")}</select>`;
  };
  const kinds = cfg.auto_model_kinds || ["decision", "edge", "whitespace"];
  const locked = !!pf.active_run;
  const gb = (b) => (b ? `${(b / 1e9).toLocaleString("id-ID", { maximumFractionDigits: 1 })} GB` : "-");
  app.innerHTML = `
  <header class="page-head"><div><h1>Pengaturan</h1>
    <p class="muted">Perubahan berlaku untuk proses berikutnya. Salinan pengaturan lama disimpan otomatis (configs/ai.json.bak).</p></div>
    <div class="actions"><button type="button" class="btn" data-action="reset-config">Batalkan perubahan</button>
      <button type="button" class="btn btn-primary" data-action="save-config" ${locked ? "disabled" : ""}>Simpan pengaturan</button></div></header>
  ${locked ? `<div class="banner" role="status"><span>Pengaturan tidak bisa disimpan selama ada proses yang berjalan.</span><a href="#berjalan">Lihat progresnya</a></div>` : ""}
  ${mi.ollama ? "" : `<div class="banner error">${esc(aiStatus(mi)[1])}, jadi daftar model tidak bisa dibaca. ${esc(aiStatus(mi)[2])}.</div>`}
  ${sourceCard(mi.source || { mode: "lokal" }, mi.ollama, locked)}
  ${vaultCard(vault, locked)}
  <div class="grid grid-2">
    <section class="card" aria-labelledby="m-title"><h2 id="m-title">AI yang dipakai</h2>
      <label class="field" for="c-gen">AI penulis test case${sel("c-gen", cfg.generation_model)}</label>
      <label class="field" for="c-judge">AI pemeriksa${sel("c-judge", cfg.judge_model)}</label>
      <label class="field" for="c-auto">AI untuk kasus rumit${sel("c-auto", cfg.auto_model, true)}
        <span class="hint">Dikerjakan paling akhir supaya laptop tidak bolak-balik memuat AI.</span></label>
      <fieldset id="c-kinds"><legend>AI kasus rumit dipakai untuk</legend><div style="display:flex;flex-wrap:wrap;gap:4px 20px">
        ${KINDS.map(([k, l]) => `<label class="check-inline"><input type="checkbox" data-kind="${k}" ${kinds.includes(k) ? "checked" : ""}>${l}</label>`).join("")}</div></fieldset>
    </section>
    <section class="card" aria-labelledby="r-title"><h2 id="r-title">Cara kerja</h2>
      <div class="fields">
        <label class="field" for="c-bs">Skenario per kelompok<input id="c-bs" type="number" min="1" max="20" step="1" inputmode="numeric" value="${esc(cfg.batch_size ?? 5)}"><span class="hint">1–20</span></label>
        <label class="field" for="c-ma">Batas menulis ulang<input id="c-ma" type="number" min="1" max="10" step="1" inputmode="numeric" value="${esc(cfg.max_attempts ?? 3)}"><span class="hint">1–10</span></label>
        <label class="field" for="c-mo">Jumlah skenario maksimum<input id="c-mo" type="number" min="1" max="10000" step="1" inputmode="numeric" value="${esc(cfg.max_obligations ?? "")}" placeholder="Semua"><span class="hint">Kosongkan untuk semua, atau 1–10.000</span></label>
        <label class="field" for="c-ctx">Kapasitas teks per permintaan<input id="c-ctx" type="number" min="2048" max="131072" step="1024" inputmode="numeric" value="${esc(cfg.num_ctx ?? 8192)}"><span class="hint">Kelipatan 1024, 2.048–131.072</span></label>
      </div>
      <label class="check"><input type="checkbox" id="c-judge-on" ${cfg.judge_enabled !== false ? "checked" : ""}><span>Periksa ulang dengan AI kedua<br><span class="hint">Hanya untuk skenario yang hasilnya belum pasti.</span></span></label>
      <label class="check"><input type="checkbox" id="c-think" ${cfg.think ? "checked" : ""}><span>Izinkan AI berpikir lebih lama<br><span class="hint">Sebaiknya mati di laptop tanpa GPU karena jauh lebih lambat.</span></span></label>
      <label class="check"><input type="checkbox" id="c-dedup" ${cfg.dedup !== false ? "checked" : ""}><span>Gabungkan test case kembar<br><span class="hint">Judul, data uji, dan kategori yang sama digabung jadi satu.</span></span></label>
      <div><span style="font-weight:500">Prioritas otomatis</span><br><span class="small">Positive menjadi ${esc((cfg.priority_rule || {}).Positive || "High")}, Negative menjadi ${esc((cfg.priority_rule || {}).Negative || "Medium")}</span></div>
    </section>
  </div>
  <section class="card" aria-labelledby="o-title"><div class="card-head"><h2 id="o-title">${(mi.source || {}).mode === "server" ? "AI yang tersedia di Server AI bersama" : "AI yang terpasang di laptop ini"}</h2></div>
    ${(mi.models || []).length ? `<div class="table-wrap"><table style="min-width:520px"><thead><tr><th>Nama AI</th><th class="r">Ukuran</th><th>Dipakai untuk</th></tr></thead><tbody>
      ${mi.models.map((m) => `<tr><td class="mono">${esc(m.name)}</td><td class="r num">${esc(gb(m.size))}</td><td class="${m.use.length ? "" : "muted"}">${esc(m.use.join(", ") || "Tidak dipakai")}</td></tr>`).join("")}
      </tbody></table></div>` : '<p class="muted">Belum ada model yang terbaca.</p>'}
  </section>`;
}

/* ---------- Sumber AI: laptop ini atau Server AI bersama (lewat Tailscale, wajib login) */
function sourceCard(src, ok, locked) {
  const want = S.sourcePick || src.mode;
  const fmtExp = (t) => new Date(t * 1000).toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric" });
  let body;
  if (want !== "server") {
    body = `<p class="small muted">TƎRᗩ memakai Ollama di laptop ini. Semua proses dan data tetap di laptop ini.</p>`;
  } else if (src.mode === "server" && src.logged_in) {
    body = `<div class="src-status"><span>${icon(ok ? "ok" : "err")}</span><div>
        <div style="font-weight:500">${ok ? "Terhubung" : esc(aiStatus({ ollama: ok, source: src })[1])} sebagai <span class="mono">${esc(src.username)}</span></div>
        <div class="tiny muted">Server <span class="mono">${esc(src.url)}</span>${src.expires ? `. Login berlaku sampai ${esc(fmtExp(src.expires))}` : ""}</div>
        ${ok ? "" : `<div class="tiny muted">${esc(aiStatus({ ollama: ok, source: src })[2])}.</div>`}</div></div>
      ${src.too_old || src.update_available ? `<p class="small ${src.too_old ? "err-text" : "muted"}">Server memakai TƎRᗩ versi ${esc(src.server_version)}${src.too_old ? ` dan mewajibkan minimal versi ${esc(src.min_version)}` : ""}; laptop ini versi ${esc(src.version)}. <a href="#versi">Lihat detail</a></p>` : ""}
      <p class="small muted">Dokumen tetap disimpan di laptop ini. Server hanya menjalankan AI dan mencatat jumlah pemakaian, bukan isi dokumen.</p>
      <div class="actions"><button type="button" class="btn" data-action="src-logout" ${locked ? "disabled" : ""}>Keluar</button></div>`;
  } else {
    body = `<p class="small muted">Isi alamat dan akun dari pemilik Server AI. Laptop ini harus tersambung ke Tailscale.</p>
      <form id="src-form" class="fields" novalidate autocomplete="off">
        <label class="field" for="sa-url">Alamat server<input id="sa-url" inputmode="url" spellcheck="false" maxlength="200" placeholder="http://100.101.102.103:11500" value="${esc(src.url || "")}">
          <span class="hint">Dari pemilik server, mis. http://100.101.102.103:11500</span></label>
        <label class="field" for="sa-user">Nama pengguna<input id="sa-user" autocomplete="username" spellcheck="false" maxlength="32" value="${esc(src.username || "")}"></label>
        <label class="field" for="sa-pass">Password<input id="sa-pass" type="password" autocomplete="current-password" maxlength="128"></label>
        <div class="actions" style="padding-top:27px"><button type="submit" class="btn btn-primary" ${locked ? "disabled" : ""}>Masuk</button></div>
      </form>`;
  }
  return `<section class="card" aria-labelledby="src-title"><h2 id="src-title">Sumber AI</h2>
    <div class="src-pick" role="radiogroup" aria-label="Sumber AI">
      <label class="radio-card"><input type="radio" name="src" value="lokal" ${want !== "server" ? "checked" : ""} ${locked ? "disabled" : ""}><span><b>AI di laptop ini</b><br><span class="tiny muted">Ollama di laptop ini</span></span></label>
      <label class="radio-card"><input type="radio" name="src" value="server" ${want === "server" ? "checked" : ""} ${locked ? "disabled" : ""}><span><b>Server AI bersama</b><br><span class="tiny muted">AI di komputer teman, lewat Tailscale</span></span></label>
    </div>${body}</section>`;
}

/* ---------- kunci file referensi test case perusahaan */
function vaultCard(v, locked) {
  if (!v) return "";
  const mode = S.vaultMode;
  const total = v.plain + v.locked;
  let state, actions = "";
  if (!total) state = `<p class="small muted">Belum ada file referensi di <span class="mono">knowledge\\company_testcases</span>. Taruh file Excel contoh test case perusahaan di folder itu bila ingin gaya penulisannya ditiru.</p>`;
  else {
    const rows = [];
    if (v.plain) rows.push(["warn", `${num(v.plain)} file belum dikunci`, "File ini masih bisa dibuka siapa pun yang memegang folder TƎRᗩ, dan tidak ikut naik ke GitHub sampai dikunci."]);
    if (v.locked) rows.push([v.unlocked ? "ok" : "warn", `${num(v.locked)} file terkunci`, v.unlocked ? "Kunci tersimpan di laptop ini, jadi file dipakai sebagai referensi saat membuat test case." : "Isi password supaya file ini dipakai sebagai referensi di laptop ini."]);
    state = `<ul class="ready-list" style="margin:0">${rows.map(([k, t, sub]) => `<li>${icon(k)}<span><span style="font-weight:500">${esc(t)}</span><br><span class="tiny muted">${esc(sub)}</span></span></li>`).join("")}</ul>`;
    const b = (m, label, primary) => `<button type="button" class="btn${primary ? " btn-primary" : ""}" data-action="vault-mode" data-mode="${m}" ${locked ? "disabled" : ""}>${label}</button>`;
    actions = `<div class="actions">${v.plain ? b("lock", v.has_vault ? "Kunci file yang belum dikunci" : "Kunci dengan password", true) : ""}
      ${v.locked && !v.unlocked ? b("unlock", "Isi password", !v.plain) : ""}
      ${v.locked && v.unlocked ? `<button type="button" class="btn" data-action="vault-forget" ${locked ? "disabled" : ""}>Lepas kunci dari laptop ini</button>` : ""}
      ${v.locked ? b("restore", "Buka kunci permanen") : ""}</div>`;
  }
  const fresh = mode === "lock" && !v.has_vault;
  const title = { lock: fresh ? "Buat password untuk mengunci file" : "Masukkan password yang sama untuk mengunci file baru", unlock: "Masukkan password file referensi", restore: "Masukkan password untuk mengembalikan file asli (.xlsx)" }[mode];
  const form = mode ? `<form id="vault-form" class="fields" novalidate autocomplete="off" style="border-top:1px solid var(--line-soft);padding-top:14px">
      <p class="small" style="grid-column:1/-1;font-weight:500">${esc(title)}</p>
      <label class="field" for="vl-pass">Password<input id="vl-pass" type="password" maxlength="128" autocomplete="${fresh ? "new-password" : "current-password"}">
        ${fresh ? `<span class="hint">Minimal 8 karakter, berisi huruf dan angka.</span>` : ""}</label>
      ${fresh ? `<label class="field" for="vl-pass2">Ulangi password<input id="vl-pass2" type="password" maxlength="128" autocomplete="new-password"></label>` : ""}
      <div class="actions" style="padding-top:27px"><button type="submit" class="btn btn-primary">${{ lock: "Kunci file", unlock: "Simpan", restore: "Kembalikan file asli" }[mode]}</button>
        <button type="button" class="btn" data-action="vault-cancel">Batal</button></div>
      ${fresh ? `<p class="tiny" style="grid-column:1/-1;color:var(--warn)">Simpan password ini baik-baik. Kalau lupa, file referensi tidak bisa dibuka lagi oleh siapa pun. Simpan dulu salinan file aslinya di tempat aman di luar folder TƎRᗩ.</p>` : ""}
      ${mode === "restore" ? `<p class="tiny" style="grid-column:1/-1;color:var(--warn)">File kembali menjadi .xlsx biasa dan versi terkuncinya dihapus.</p>` : ""}
    </form>` : "";
  return `<section class="card" aria-labelledby="vault-title"><h2 id="vault-title">Referensi test case perusahaan</h2>
    <p class="small muted">Contoh test case perusahaan yang gaya penulisannya ditiru AI. File bisa dikunci dengan password: yang ikut ke GitHub dan ke laptop teman hanya versi terkunci, dan hanya yang tahu password yang bisa memakainya.</p>
    ${state}${mode ? "" : actions}${form}</section>`;
}

async function vaultSubmit(form) {
  const mode = S.vaultMode, $ = (id) => document.getElementById(id);
  const p = $("vl-pass"), p2 = $("vl-pass2");
  const errs = [[p, p2 ? V.password(p.value) : (p.value ? "" : "Password wajib diisi.")]];
  if (p2) errs.push([p2, p2.value ? (p2.value === p.value ? "" : "Ulangi password belum sama.") : "Ulangi password wajib diisi."]);
  if (!report(errs, form)) return;
  const btn = form.querySelector("button[type=submit]"), label = btn.textContent;
  btn.disabled = true; btn.innerHTML = `<span class="spinner" aria-hidden="true"></span>Memproses...`;
  try {
    await api(`/api/vault/${mode}`, { method: "POST", body: { password: p.value, password2: p2 ? p2.value : "" } });
    S.vaultMode = null;
    toast({ lock: "File referensi dikunci", unlock: "Password benar. File referensi dipakai di laptop ini.", restore: "File asli dikembalikan" }[mode]);
    await viewPengaturan();
  } catch (e) { btn.disabled = false; btn.textContent = label; p.value = ""; serverErr(e); }
}

async function sourcePick(mode) {
  S.sourcePick = mode;
  if (mode === "lokal") {
    try { await api("/api/ai-source/local", { method: "POST" }); toast("Sekarang memakai AI di laptop ini"); } catch (e) { toast(e.message, true); }
    S.sourcePick = null;
    refreshNav();
  }
  await viewPengaturan();
  if (mode === "server") document.getElementById("sa-url")?.focus();
}

async function sourceLogin(form) {
  const $ = (id) => document.getElementById(id);
  const u = $("sa-url"), n = $("sa-user"), p = $("sa-pass");
  const errs = [[u, V.serverUrl(u.value)], [n, V.username(n.value.trim())],
    [p, p.value ? (p.value.length > 128 ? "Password maksimal 128 karakter." : "") : "Password wajib diisi."]];
  if (!report(errs, form)) return;
  const btn = form.querySelector("button[type=submit]");
  btn.disabled = true; btn.innerHTML = `<span class="spinner" aria-hidden="true"></span>Menghubungkan...`;
  try {
    const r = await api("/api/ai-source/login", { method: "POST", body: { url: u.value.trim(), username: n.value.trim(), password: p.value } });
    S.sourcePick = null;
    toast(r.ok ? `Masuk sebagai ${r.username}. TƎRᗩ sekarang memakai Server AI bersama.` : `Masuk sebagai ${r.username}, tapi server belum bisa dipakai.`, !r.ok);
    await viewPengaturan();
    refreshNav();
  } catch (e) {
    btn.disabled = false; btn.textContent = "Masuk";
    if (e.field === "sa-pass") p.value = "";
    serverErr(e);
  }
}

async function sourceLogout() {
  try { await api("/api/ai-source/logout", { method: "POST" }); toast("Sudah keluar dari Server AI bersama"); } catch (e) { toast(e.message, true); }
  await viewPengaturan();
  refreshNav();
}

async function saveConfig() {
  const $ = (id) => document.getElementById(id);
  const v = (id) => $(id).value.trim();
  const int = (id) => { const x = v(id); return x === "" ? null : Number(x); };
  const kinds = [...document.querySelectorAll("[data-kind]:checked")].map((c) => c.dataset.kind);
  const errs = [
    [$("c-gen"), v("c-gen") ? "" : "Pilih AI penulis test case."],
    [$("c-judge"), v("c-judge") ? "" : "Pilih AI pemeriksa."],
    [$("c-kinds"), v("c-auto") && !kinds.length ? "AI kasus rumit dipilih, jadi centang minimal satu pemakaiannya." : ""],
    ...["c-bs", "c-ma", "c-mo", "c-ctx"].map((id) => [$(id), V.number(id, $(id).value)]),
  ];
  if (!report(errs)) return;
  const values = {
    generation_model: v("c-gen"), judge_model: v("c-judge"), auto_model: v("c-auto"), auto_model_kinds: kinds,
    batch_size: int("c-bs"), max_attempts: int("c-ma"), max_obligations: int("c-mo"), num_ctx: int("c-ctx"),
    judge_enabled: $("c-judge-on").checked, think: $("c-think").checked, dedup: $("c-dedup").checked,
  };
  try {
    await api("/api/config", { method: "PUT", body: values });
    S.config = null;
    toast("Pengaturan disimpan. Berlaku untuk proses berikutnya.");
    refreshNav();
  } catch (e) { serverErr(e); }
}

/* ================================================================= router & event */
function currentView() { return (location.hash.replace(/^#/, "").split("/")[0]) || "beranda"; }

let lastRouted = null;
async function route() {
  const [view, arg] = location.hash.replace(/^#/, "").split("/");
  const v = view || "beranda";
  const changed = lastRouted !== location.hash;
  lastRouted = location.hash;
  setActiveNav(v);
  if (v !== "berjalan") closeStream();
  if (v !== "catatan") stopNotesTimer();
  if (v !== "desain") stopDesignTimer();
  if (v !== "pengaturan") { S.sourcePick = null; S.vaultMode = null; }
  if (v !== "banding") stopCompareTimer();
  try {
    if (v === "beranda") await viewBeranda();
    else if (v === "mulai") await viewMulai();
    else if (v === "catatan") await viewCatatan();
    else if (v === "desain") await viewDesain();
    else if (v === "alur") await viewAlur();
    else if (v === "berjalan") await viewBerjalan();
    else if (v === "hasil") await viewHasil(arg && decodeURIComponent(arg));
    else if (v === "cakupan") { setActiveNav("cakupan"); await viewHasil(arg && decodeURIComponent(arg), "cakupan"); }
    else if (v === "cek") await viewCek(arg && decodeURIComponent(arg));
    else if (v === "riwayat") await viewRiwayat();
    else if (v === "pengaturan") await viewPengaturan();
    else if (v === "versi") await viewVersi(false);
    else if (v === "mdpdf") await viewMdpdf();
    else if (v === "banding") await viewBanding(arg && decodeURIComponent(arg));
    else { location.hash = "#beranda"; return; }
    if (changed) { app.classList.remove("view-in"); void app.offsetWidth; app.classList.add("view-in"); }
  } catch (e) {
    app.innerHTML = `<div class="banner error" role="alert"><span><strong>Halaman gagal dimuat.</strong> ${esc(e.message)}</span>
      <button type="button" class="btn btn-small" data-action="reload">Coba lagi</button></div>`;
  }
}

app.addEventListener("click", (ev) => {
  const el = ev.target.closest("[data-action]");
  if (!el) return;
  const a = el.dataset.action, H = S.hasil;
  if (a === "upload") document.getElementById("prd-file").click();
  else if (a === "prd-del") {
    const sel = document.getElementById("prd-select"); if (!sel || !sel.value) return;
    const file = sel.value, title = sel.options[sel.selectedIndex].textContent;
    if (el.dataset.confirm !== "1") {
      el.dataset.confirm = "1"; el.textContent = `Yakin hapus "${title}"?`; el.classList.add("btn-danger-confirm");
      setTimeout(() => { if (el.isConnected) { el.dataset.confirm = ""; el.textContent = "Hapus dokumen ini"; el.classList.remove("btn-danger-confirm"); } }, 5000);
      return;
    }
    api(`/api/prds/${encodeURIComponent(file)}`, { method: "DELETE" })
      .then((r) => { if (S.mulaiPrd === file) S.mulaiPrd = null; toast(r.note ? `${file} dihapus. ${r.note}` : `${file} dihapus dari daftar dokumen`); viewMulai(); refreshNav(); })
      .catch((e) => toast(e.message, true));
  }
  else if (a === "start") startRun();
  else if (a === "notes-start") notesStart();
  else if (a === "notes-save") notesSave(el.dataset.file, false);
  else if (a === "notes-use") notesSave(el.dataset.file, true);
  else if (a === "notes-reset") notesReset();
  else if (a === "design-reset") designReset();
  else if (a === "design-start") designStart();
  else if (a === "design-card-add") { const c = newCard(); designState().cards.push(c); S.cardJust = c.key; viewDesain().then(() => { S.cardJust = null; const n = document.getElementById(`dn-${c.key}`); if (n) n.focus({ preventScroll: true }); n && n.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" }); }); }
  else if (a === "design-card-del") {
    const D = designState(); const key = Number(el.dataset.card);
    const sec = el.closest(".dcard");
    const go = () => { D.cards = D.cards.filter((c) => c.key !== key); viewDesain(); };
    if (sec && !matchMedia("(prefers-reduced-motion: reduce)").matches) { sec.classList.add("card-out"); setTimeout(go, 200); } else go();
  }
  else if (a === "design-img-del") { const c = designCard(el.dataset.card); if (c) { c.images.splice(Number(el.dataset.img), 1); refreshDesignImgs(c); } }
  else if (a === "flow-toggle") { S.flowPaused = !S.flowPaused; viewAlur(); }
  else if (a === "conv-delete") convDelete(el.dataset.conv, location.hash.startsWith("#riwayat"));
  else if (a === "conv-use") { S.mulaiPrd = el.dataset.file; location.hash = "#mulai"; }
  else if (a === "recheck") recheck(el);
  else if (a === "cancel") cancelRun();
  else if (a === "pick") { H.sel = el.dataset.tc; renderTcZone(); }
  else if (a === "prev") { H.page = Math.max(0, H.page - 1); renderTcZone(); }
  else if (a === "next") { H.page += 1; renderTcZone(); }
  else if (a === "goto-tc") { S.pendingTc = el.dataset.tc; location.hash = `#hasil/${encodeURIComponent(H.runId)}`; }
  else if (a === "toggle-group") { S.cekOpen = S.cekOpen || new Set(); const g = el.dataset.group; S.cekOpen.has(g) ? S.cekOpen.delete(g) : S.cekOpen.add(g); S.cekJust = S.cekOpen.has(g) ? g : null; viewCek(H.runId).then(() => { S.cekJust = null; }); }
  else if (a === "jump") { const t = document.getElementById(el.dataset.target); if (t) t.scrollIntoView({ block: "start", behavior: "smooth" }); }
  else if (a === "compare") renderCompare();
  else if (a === "delete-run") deleteRun(el.dataset.run);
  else if (a === "save-config") saveConfig();
  else if (a === "src-logout") sourceLogout();
  else if (a === "md-add-prd") mdAddPrd();
  else if (a === "hist-del") {
    if (el.dataset.confirm !== "1") { el.dataset.confirm = "1"; el.textContent = "Yakin hapus?"; el.classList.add("btn-danger-confirm"); setTimeout(() => { if (el.isConnected) { el.dataset.confirm = ""; el.textContent = "Hapus"; el.classList.remove("btn-danger-confirm"); } }, 4000); return; }
    api(el.dataset.url, { method: "DELETE" }).then(() => { toast("Dihapus dari Riwayat"); viewRiwayat(); }).catch((e) => toast(e.message, true));
  }
  else if (a === "upd-check") viewVersi(true);
  else if (a === "upd-apply") updateApply(el);
  else if (a === "vault-forget") api("/api/vault/forget", { method: "POST", body: {} }).then(() => { toast("Kunci di laptop ini dilepas"); viewPengaturan(); }).catch((e) => toast(e.message, true));
  else if (a === "vault-mode") { S.vaultMode = el.dataset.mode; viewPengaturan().then(() => document.getElementById("vl-pass")?.focus()); }
  else if (a === "vault-cancel") { S.vaultMode = null; viewPengaturan(); }
  else if (a === "cmp-start") cmpStart();
  else if (a === "cmp-reset") { api("/api/compare/reset", { method: "POST" }).then(() => { S.cmpView = null; viewBanding(); }).catch((e) => toast(e.message, true)); }
  else if (a === "cmp-file-clear") { const s = cmpState()[el.dataset.side]; s.file = null; s.token = null; viewBanding(); }
  else if (a === "cmp-tab") { S.cmpTab = el.dataset.tab; S.cmpLimit = 100; cmpRerenderTable(); }
  else if (a === "cmp-more") { S.cmpLimit = (S.cmpLimit || 100) + 100; cmpRerenderTable(); }
  else if (a === "cmp-del") {
    if (el.dataset.confirm !== "1") { el.dataset.confirm = "1"; el.textContent = "Yakin hapus?"; el.classList.add("btn-danger-confirm"); setTimeout(() => { if (el.isConnected) { el.dataset.confirm = ""; el.textContent = "Hapus"; el.classList.remove("btn-danger-confirm"); } }, 4000); return; }
    api(`/api/compares/${encodeURIComponent(el.dataset.cmp)}`, { method: "DELETE" }).then(() => { toast("Hasil perbandingan dihapus"); viewBanding(); }).catch((e) => toast(e.message, true));
  }
  else if (a === "md-view") mdRun(el.dataset.md, "view", el);
  else if (a === "md-download") mdRun(el.dataset.md, "download", el);
  else if (a === "md-all") mdAll(el);
  else if (a === "md-del") { const M = mdState(); M.files = M.files.filter((f) => f.key !== Number(el.dataset.md)); viewMdpdf(); }
  else if (a === "md-clear") { mdState().files = []; viewMdpdf(); }
  else if (a === "notes-md" || a === "notes-pdf") {
    const ta = document.getElementById("nr-md"), content = ta ? ta.value : "";
    const err = V.md(el.dataset.file, new Blob([content]).size, content);
    if (err) { report([[ta, err]]); return; }
    if (a === "notes-md") {
      const url = URL.createObjectURL(new Blob([content], { type: "text/markdown;charset=utf-8" }));
      const link = document.createElement("a"); link.href = url; link.download = el.dataset.file; document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      toast(`${el.dataset.file} diunduh`);
    } else { S.mdQueue = { name: el.dataset.file, content }; location.hash = "#mdpdf"; }
  }
  else if (a === "reset-config") route();
  else if (a === "reload") route();
});

app.addEventListener("submit", (ev) => {
  if (ev.target.id === "src-form") { ev.preventDefault(); sourceLogin(ev.target); }
  if (ev.target.id === "vault-form") { ev.preventDefault(); vaultSubmit(ev.target); }
});

app.addEventListener("keydown", (ev) => {
  const row = ev.target.closest && ev.target.closest('tr[data-action="pick"]');
  if (row && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); S.hasil.sel = row.dataset.tc; renderTcZone(); }
});

app.addEventListener("change", (ev) => {
  const t = ev.target;
  if (t.id === "prd-file") uploadPrd(t.files[0]);
  else if (t.dataset.dimg) { designAddImages(t.dataset.dimg, [...t.files]); t.value = ""; }
  else if (t.name === "src") sourcePick(t.value);
  else if (t.dataset.cfile) { const f = t.files[0]; t.value = ""; if (f) cmpUpload(t.dataset.cfile, f); }
  else if (t.name === "cmp-src-a" || t.name === "cmp-src-b") { cmpState()[t.name.slice(-1)].kind = t.value; viewBanding(); }
  else if (t.name === "cmp-mode") cmpState().mode = t.value;
  else if (t.dataset.cfield === "id") { cmpState()[t.dataset.side].id = t.value; clearErr(t); }
  else if (t.id === "md-input") { const fs = [...t.files]; t.value = ""; mdAddFiles(fs); }
  else if (t.id === "md-prd") { S.mdPick = t.value; clearErr(t); }
  else if (t.id === "prd-select") {
    S.mulaiPrd = t.value;
    const e = document.getElementById("estimate"); if (e && S.estimate) e.textContent = S.estimate(t.value);
    const f = document.getElementById("prd-file-name"); if (f) f.textContent = `File: ${t.value}`;
  }
  else if (t.dataset.action === "pick-run") { t.checked ? S.compare.add(t.dataset.run) : S.compare.delete(t.dataset.run); }
  else if (t.dataset.filter && t.dataset.filter !== "q") {
    S.hasil.filters[t.dataset.filter] = t.type === "checkbox" ? t.checked : t.value;
    S.hasil.page = 0;
    renderTcZone();
  }
});

let searchTimer = null;
document.addEventListener("input", (ev) => { if (ev.target.getAttribute && ev.target.getAttribute("aria-invalid")) clearErr(ev.target); });
app.addEventListener("input", (ev) => {
  const t = ev.target;
  if (t.dataset.cfield === "label") cmpState()[t.dataset.side].label = t.value;
  else if (t.dataset.cfield === "name") cmpState().name = t.value;
  else if (t.id === "cmp-q") {
    clearTimeout(S.cmpQTimer);
    S.cmpQTimer = setTimeout(() => { S.cmpQ = t.value; S.cmpLimit = 100; cmpRerenderTable(); const q = document.getElementById("cmp-q"); if (q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); } }, 250);
  }
});
document.addEventListener("change", (ev) => {
  const t = ev.target;
  if (t.getAttribute && t.getAttribute("aria-invalid")) clearErr(t);
  const fs = t.closest && t.closest("fieldset.has-err"); if (fs) clearErr(fs);
  if (t.id === "c-auto" && !t.value) { const k = document.getElementById("c-kinds"); if (k) clearErr(k); }
});
app.addEventListener("input", (ev) => {
  const t = ev.target;
  if (t.dataset.dfield) {
    const D = designState();
    if (t.dataset.card) { const c = designCard(t.dataset.card); if (c) c[t.dataset.dfield] = t.value; } else D[t.dataset.dfield] = t.value;
    const e = document.getElementById("dz-est"); if (e) e.textContent = designEstimate();
    return;
  }
  if (t.dataset.filter !== "q") return;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    S.hasil.filters.q = t.value;
    S.hasil.page = 0;
    const pos = t.selectionStart;
    renderTcZone();
    const n = document.getElementById("f-q");
    if (n) { n.focus(); n.setSelectionRange(pos, pos); }
  }, 250);
});

app.addEventListener("dragover", (ev) => { const z = ev.target.closest && ev.target.closest("[data-drop], [data-mdrop], [data-cdrop]"); if (z) { ev.preventDefault(); z.classList.add("drag"); } });
app.addEventListener("dragleave", (ev) => { const z = ev.target.closest && ev.target.closest("[data-drop], [data-mdrop], [data-cdrop]"); if (z) z.classList.remove("drag"); });
app.addEventListener("drop", (ev) => {
  const z = ev.target.closest && ev.target.closest("[data-drop], [data-mdrop], [data-cdrop]");
  if (!z) return;
  ev.preventDefault();
  z.classList.remove("drag");
  if (z.hasAttribute("data-mdrop")) mdAddFiles([...(ev.dataTransfer.files || [])]);
  else if (z.dataset.cdrop) { const f = (ev.dataTransfer.files || [])[0]; if (f) cmpUpload(z.dataset.cdrop, f); }
  else designAddImages(z.dataset.drop, [...(ev.dataTransfer.files || [])]);
});

window.addEventListener("hashchange", () => { app.focus({ preventScroll: true }); window.scrollTo(0, 0); route(); });

// segarkan menu samping dan Beranda secara berkala
setInterval(async () => {
  const wasActive = S.overview && S.overview.active;
  await refreshNav();
  const v = currentView();
  if (v === "beranda" && (wasActive || (S.overview && S.overview.active))) viewBeranda();
  if (v === "berjalan" && S.live && S.live.status === "berjalan") renderLive();
  if (v === "berjalan" && !wasActive && S.overview && S.overview.active) viewBerjalan();
}, 10000);

refreshNav();
route();
setTimeout(() => checkUpdate(false), 4000); // cek versi baru di GitHub sekali saat dibuka (diam bila tanpa internet)

/* ================================================================= LAYAR PEMBUKA */
// Muncul sekali setiap TƎRᗩ dibuka di tab baru. Setelah klik Masuk, refresh halaman tidak memunculkannya lagi.
(function splash() {
  const el = document.getElementById("splash");
  if (!el) return;
  let seen = false;
  try { seen = sessionStorage.getItem("tera-masuk") === "1"; } catch (e) { /* penyimpanan browser tidak tersedia */ }
  if (seen) { el.hidden = true; return; }
  const main = document.querySelector(".shell") || document.getElementById("app");
  if (main) main.setAttribute("aria-hidden", "true");
  const btn = document.getElementById("splash-enter");
  const enter = () => {
    try { sessionStorage.setItem("tera-masuk", "1"); } catch (e) { /* abaikan */ }
    if (main) main.removeAttribute("aria-hidden");
    el.classList.add("leaving");
    const done = () => { el.hidden = true; const a = document.getElementById("app"); if (a) a.focus(); };
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) done(); else setTimeout(done, 340);
  };
  btn.addEventListener("click", enter);
  api("/api/about").then((ab) => {
    const n = document.getElementById("splash-note"), s = ab.source || {};
    if (n) n.textContent = `Versi ${ab.version}. ` + (s.mode === "server"
      ? "Dokumen tersimpan di laptop ini; AI memakai Server AI bersama lewat Tailscale."
      : "Berjalan di laptop ini. Data tidak dikirim ke internet.");
  }).catch(() => {});
  el.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === "Escape") { ev.preventDefault(); enter(); } });
  btn.focus();
})();
