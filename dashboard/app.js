/* Dashboard lokal Tera (Asisten QA berbasis AI) - semua layar dalam satu file.
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
  if (!r.ok) throw new Error((data && data.detail) || `Server menjawab ${r.status}`);
  return data;
}

function toast(msg, isErr) {
  const t = document.createElement("div");
  t.className = "toast" + (isErr ? " err" : "");
  t.setAttribute("role", isErr ? "alert" : "status");
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), isErr ? 7000 : 3500);
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
    setNavStatus("Tera tidak terhubung", "Jendela PowerShell Tera harus tetap terbuka");
    return;
  }
  const o = S.overview, pf = o.preflight;
  document.getElementById("nav-dot").hidden = !o.active;
  // titik di menu Perlu dicek: hanya untuk hasil terbaru yang belum dibuka halamannya
  const badge = document.getElementById("nav-badge");
  const nr = o.last && o.last.report ? o.last.report.needs_review : 0;
  badge.hidden = !(nr && o.last.id !== seenReview());
  // kotak status hanya muncul bila ada masalah; saat semuanya siap, sidebar bersih
  if (!pf.ollama) setNavStatus("AI belum aktif", "Buka aplikasi Ollama dulu");
  else if (pf.missing.length) setNavStatus("AI belum lengkap", "Cek menu Pengaturan");
  else setNavStatus(null);
}

function setNavStatus(title, sub) {
  const box = document.querySelector(".nav-status");
  if (!box) return;
  box.hidden = !title;
  document.getElementById("nav-ai").textContent = title || "";
  document.getElementById("nav-ai-sub").textContent = sub || "";
}

function setActiveNav(view) {
  document.querySelectorAll(".nav-links a").forEach((a) => {
    if (a.dataset.view === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
}

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
    [pf.ollama ? "ok" : "err", pf.ollama ? "Mesin AI lokal menyala" : "Mesin AI lokal belum menyala. Buka aplikasi Ollama."],
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
      <h1>Selamat datang di Tera</h1>
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
  const roleRows = pf.models.map((m) => [m.ok ? "ok" : "err", `AI ${m.role.toLowerCase()} ${m.ok ? "tersedia" : "belum terpasang"}`, m.ok ? m.name : `Unduh dengan: ollama pull ${m.name}`]);
  const rows = [
    [pf.ollama ? "ok" : "err", pf.ollama ? "Mesin AI lokal menyala" : "Mesin AI lokal belum menyala", pf.ollama ? "Berjalan di laptop ini" : "Buka aplikasi Ollama, lalu klik Periksa ulang"],
    ...(pf.ollama ? roleRows : []),
    [prds.length ? "ok" : "err", prds.length ? `${prds.length} dokumen PRD tersedia` : "Belum ada dokumen PRD", prds.length ? "" : "Tambahkan file .md dengan tombol Tambah dokumen PRD"],
  ];
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
          <span class="hint" id="prd-file-name">File: ${esc(chosen || "")}</span>` : `<span class="muted">Belum ada dokumen.</span>`}
      </label>
      <div><button type="button" class="btn" data-action="upload">Tambah dokumen PRD</button>
        <input type="file" id="prd-file" accept=".md" hidden></div>
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
  if (!/\.md$/i.test(file.name)) return toast("Pilih file berformat .md", true);
  try {
    const text = await file.text();
    const r = await api("/api/prds", { method: "POST", body: { name: file.name, content: text } });
    S.mulaiPrd = r.file;
    toast(`Dokumen ${r.title} ditambahkan`);
    route();
  } catch (e) { toast(e.message, true); }
}

async function startRun() {
  const prd = (document.getElementById("prd-select") || {}).value;
  if (!prd) return toast("Pilih dokumen PRD dulu", true);
  const btn = document.querySelector('[data-action="start"]');
  btn.disabled = true;
  btn.textContent = "Memulai...";
  try {
    await api("/api/runs", { method: "POST", body: { prd } });
    location.hash = "#berjalan";
  } catch (e) {
    toast(e.message, true);
    btn.disabled = false;
    btn.textContent = "Mulai buat test case";
  }
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
        <input id="nt-name" type="text" maxlength="80" placeholder="mis. Berita Acara" value="${esc(draft.name)}" ${running ? "disabled" : ""}>
        <span class="hint">Dipakai sebagai Module di test case dan nama file PRD.</span></label>
      <label class="field" for="nt-text">Isi catatan
        <textarea id="nt-text" class="notes" ${running ? "disabled" : ""} placeholder="Tempel catatan QA di sini...">${esc(draft.text)}</textarea></label>
      <div class="actions"><button type="button" class="btn btn-primary" data-action="notes-start" ${running ? "disabled" : ""}>${running ? "Sedang disusun..." : "Susun PRD"}</button>
        <span class="small muted">Biasanya beberapa menit, tergantung panjang catatan.</span></div>
    </section>
    <section class="log" aria-labelledby="nt-log">
      <h2 id="nt-log">Progres</h2>
      <ul class="log-lines" aria-live="polite">${log || `<li>Belum ada proses.</li>`}</ul>
    </section>
  </div>
  ${res ? notesResult(res) : ""}`;
  stopNotesTimer();
  if (running) S.notesTimer = setInterval(async () => {
    if (!location.hash.startsWith("#catatan")) return stopNotesTimer();
    const m = await api("/api/notes").catch(() => null);
    if (m && m.status !== "berjalan") { stopNotesTimer(); S.notesEdited = null; viewCatatan(); }
    else if (m) { const ul = document.querySelector(".log-lines"); if (ul) ul.innerHTML = (m.log || []).map((l) => `<li><time>${esc(new Date(l.time * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }))}</time>${esc(l.msg)}</li>`).join(""); }
  }, 3000);
}

function notesResult(r) {
  const qs = r.questions || [];
  const conflict = qs.filter((q) => q.jenis === "bertentangan").length;
  const qItem = (q) => `<li>${q.jenis === "bertentangan" ? `<span class="chip">Bertentangan</span> ` : ""}${esc(q.pertanyaan)}${q.fitur ? ` <span class="tiny muted">(${esc(q.fitur)})</span>` : ""}${q.kutipan ? `<br><span class="quote">Catatan: “${esc(q.kutipan)}”</span>` : ""}</li>`;
  return `
  <section class="card" aria-labelledby="nr-title" style="margin-top:16px">
    <div class="card-head"><h2 id="nr-title">Hasil: ${esc(r.prd_file)}</h2>
      <span class="small muted">${num(r.features)} fitur, ${num(r.rules)} aturan; catatan review: ${num(qs.length)} pertanyaan${conflict ? ` (${conflict} bertentangan)` : ""}</span></div>
    <p class="small muted">PRD ini sudah tersimpan dan muncul di daftar dokumen pada Mulai baru. PRD hanya berisi aturan dari catatan; hal yang diragukan ada di catatan review terpisah.</p>
    <div class="card-head" style="margin-top:8px"><h3>Catatan review (terpisah dari PRD)</h3>
      <a class="btn btn-small" href="/api/conversions/${encodeURIComponent(r.id)}/review" download="${esc(r.review_file || "catatan_review.pdf")}">Unduh catatan review (PDF)</a></div>
    <p class="small muted">Berisi hal yang bertentangan atau belum jelas untuk ditanyakan ke tim, isian AI yang ditolak, baris catatan yang belum masuk, dan asal setiap aturan. Tidak dipakai untuk membuat test case.</p>
    ${qs.length ? `<ol class="qlist">${qs.map(qItem).join("")}</ol>` : `<p class="small muted">Tidak ada pertanyaan terbuka.</p>`}
    ${(r.missed_lines || []).length ? `<details class="fold"><summary>Baris catatan yang belum masuk PRD (${r.missed_lines.length})</summary>
      <ul class="qlist">${r.missed_lines.map((m) => `<li>Baris ${m.baris}: “${esc(m.teks)}”</li>`).join("")}</ul></details>` : ""}
    ${(r.rejected || []).length ? `<details class="fold"><summary>Isian AI yang ditolak penjaga anti-karangan (${r.rejected.length})</summary>
      <ul class="qlist">${r.rejected.map((x) => `<li>${esc(x.pernyataan || "-")}<br><span class="quote">${esc(x.alasan || "")}</span></li>`).join("")}</ul></details>` : ""}
    <label class="field" for="nr-md" style="margin-top:12px">Isi PRD (boleh diedit)
      <textarea id="nr-md" class="notes tall">${esc(S.notesEdited ?? r.markdown)}</textarea></label>
    <div class="actions">
      <button type="button" class="btn" data-action="notes-save" data-file="${esc(r.prd_file)}">Simpan perubahan</button>
      <button type="button" class="btn btn-primary" data-action="notes-use" data-file="${esc(r.prd_file)}">Buat test case dari PRD ini</button>
    </div>
    <div class="actions" style="margin-top:4px;padding-top:12px;border-top:1px solid var(--line-soft)">
      <button type="button" class="btn" data-action="notes-reset">Mulai ulang (konversi baru)</button>
      <button type="button" class="btn" data-action="conv-delete" data-conv="${esc(r.id)}">Hapus hasil ini</button>
      <span class="small muted">Mulai ulang mengosongkan halaman ini, hasilnya tetap tersimpan di Riwayat. Hapus membuang PRD dan catatan review ini.</span>
    </div>
  </section>`;
}

async function notesStart() {
  const name = document.getElementById("nt-name").value.trim();
  const text = document.getElementById("nt-text").value;
  S.notesDraft = { name, text };
  if (!name) return toast("Isi nama modul dulu", true);
  if (text.trim().length < 20) return toast("Tempel catatan QA dulu", true);
  try {
    S.notesEdited = null;
    await api("/api/notes", { method: "POST", body: { name, text } });
    viewCatatan();
  } catch (e) { toast(e.message, true); }
}

async function notesReset() {
  try {
    await api("/api/notes/reset", { method: "POST" });
    S.notesDraft = { name: "", text: "" };
    S.notesEdited = null;
    viewCatatan();
  } catch (e) { toast(e.message, true); }
}

async function convDelete(id, fromHistory) {
  if (!confirm("Hapus hasil konversi ini? PRD dan catatan review-nya ikut terhapus dan tidak bisa dikembalikan.")) return;
  try {
    await api(`/api/conversions/${encodeURIComponent(id)}`, { method: "DELETE" });
    toast("Hasil konversi dihapus");
    if (!fromHistory) { S.notesDraft = { name: "", text: "" }; S.notesEdited = null; }
    route();
  } catch (e) { toast(e.message, true); }
}

async function notesSave(file, thenUse) {
  const ta = document.getElementById("nr-md");
  try {
    await api(`/api/prds/${encodeURIComponent(file)}`, { method: "PUT", body: { content: ta.value } });
    S.notesEdited = ta.value;
    if (thenUse) { S.mulaiPrd = file; location.hash = "#mulai"; } else toast("PRD disimpan");
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
    <label class="field grow small" for="f-q">Cari judul atau ID<input id="f-q" type="search" data-filter="q" value="${esc(f.q)}" placeholder="misalnya TC-109 atau login"></label>
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
      ${list.map(({ t, txt }) => `<article class="item"><div class="item-head"><span class="mono muted">${esc(t.tc_no)}</span><h3>${esc(t.title)}</h3></div>
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
  const [runs, convs] = await Promise.all([api("/api/runs"), api("/api/conversions").catch(() => [])]);
  S.runsCache = runs;
  S.compare = new Set([...S.compare].filter((id) => runs.some((r) => r.id === id)));
  const rows = [
    ...runs.map((r) => ({ kind: "tc", t: r.finished || r.started || 0, r })),
    ...convs.map((c) => ({ kind: "conv", t: c.time || 0, c })),
  ].sort((x, y) => y.t - x.t);
  const tcRow = (r) => { const rep = r.report || {}; return `<tr>
    <td><input type="checkbox" data-action="pick-run" data-run="${esc(r.id)}" ${S.compare.has(r.id) ? "checked" : ""} aria-label="Pilih proses ${esc(fmtDate(r.finished || r.started))} untuk dibandingkan"></td>
    <td class="num nw">${esc(fmtDate(r.finished || r.started))}</td><td class="nw"><span class="chip brand">Test case PRD</span></td><td>${esc(r.prd_title)}</td>
    <td>${num(rep.test_cases)} test case, ${num(rep.needs_review)} perlu dicek</td>
    <td class="r">${esc(fmtDur(runDur(r)))}</td><td>${statusChip(r.status)}</td>
    <td><span class="actions">${r.status === "selesai" ? `<a class="btn btn-small" href="#hasil/${esc(r.id)}">Lihat hasil</a>` : r.status === "berjalan" ? `<a class="btn btn-small" href="#berjalan">Lihat progres</a>` : ""}
      ${r.status !== "berjalan" ? `<button type="button" class="btn btn-small" data-action="delete-run" data-run="${esc(r.id)}">Hapus</button>` : ""}</span></td></tr>`; };
  const convRow = (c) => `<tr>
    <td></td><td class="num nw">${esc(fmtDate(c.time))}</td><td class="nw"><span class="chip grey">Konversi catatan</span></td><td>${esc(c.module || c.prd_file)}</td>
    <td>${num(c.features)} fitur, ${num(c.rules)} aturan, ${num(c.questions)} pertanyaan${c.conflicts ? ` (${num(c.conflicts)} bertentangan)` : ""}</td>
    <td class="r">${esc(fmtDur(c.seconds))}</td><td>${statusChip("selesai")}</td>
    <td><span class="actions">
      <a class="btn btn-small" href="/api/conversions/${encodeURIComponent(c.id)}/prd" download="${esc(c.prd_file)}">Unduh PRD</a>
      <a class="btn btn-small" href="/api/conversions/${encodeURIComponent(c.id)}/review" download>Review (PDF)</a>
      ${c.prd_exists ? `<button type="button" class="btn btn-small" data-action="conv-use" data-file="${esc(c.prd_file)}">Buat test case</button>` : ""}
      <button type="button" class="btn btn-small" data-action="conv-delete" data-conv="${esc(c.id)}">Hapus</button></span></td></tr>`;
  app.innerHTML = `
  <header class="page-head"><div><h1>Riwayat</h1><p class="muted">Semua proses di laptop ini (pembuatan test case dan konversi catatan), terbaru di atas.</p></div>
    <div class="actions"><button type="button" class="btn" data-action="compare">Bandingkan 2 test case yang dipilih</button></div></header>
  <section class="card hist">
    ${rows.length ? `<div class="table-wrap"><table style="min-width:980px"><thead><tr>
      <th><span class="sr-only">Pilih</span></th><th>Waktu</th><th>Jenis</th><th>Dokumen</th><th>Ringkasan</th>
      <th class="r">Lama</th><th>Status</th><th style="width:300px"><span class="sr-only">Aksi</span></th></tr></thead><tbody>
      ${rows.map((x) => (x.kind === "tc" ? tcRow(x.r) : convRow(x.c))).join("")}
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

/* ================================================================= PENGATURAN */
const KINDS = [["decision", "Tabel keputusan"], ["edge", "Kasus tepi"], ["whitespace", "Spasi di awal/akhir"]];

async function viewPengaturan() {
  const [cfg, mi, pf] = await Promise.all([api("/api/config"), api("/api/models"), api("/api/preflight")]);
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
  ${mi.ollama ? "" : `<div class="banner error">Mesin AI lokal belum menyala, jadi daftar model tidak bisa dibaca. Buka aplikasi Ollama lalu muat ulang halaman ini.</div>`}
  <div class="grid grid-2">
    <section class="card" aria-labelledby="m-title"><h2 id="m-title">AI yang dipakai</h2>
      <label class="field" for="c-gen">AI penulis test case${sel("c-gen", cfg.generation_model)}</label>
      <label class="field" for="c-judge">AI pemeriksa${sel("c-judge", cfg.judge_model)}</label>
      <label class="field" for="c-auto">AI untuk kasus rumit${sel("c-auto", cfg.auto_model, true)}
        <span class="hint">Dikerjakan paling akhir supaya laptop tidak bolak-balik memuat AI.</span></label>
      <fieldset><legend>AI kasus rumit dipakai untuk</legend><div style="display:flex;flex-wrap:wrap;gap:4px 20px">
        ${KINDS.map(([k, l]) => `<label class="check-inline"><input type="checkbox" data-kind="${k}" ${kinds.includes(k) ? "checked" : ""}>${l}</label>`).join("")}</div></fieldset>
    </section>
    <section class="card" aria-labelledby="r-title"><h2 id="r-title">Cara kerja</h2>
      <div class="fields">
        <label class="field" for="c-bs">Skenario per kelompok<input id="c-bs" type="number" min="1" value="${esc(cfg.batch_size ?? 5)}"></label>
        <label class="field" for="c-ma">Batas menulis ulang<input id="c-ma" type="number" min="1" value="${esc(cfg.max_attempts ?? 3)}"></label>
        <label class="field" for="c-mo">Jumlah skenario maksimum<input id="c-mo" type="number" min="1" value="${esc(cfg.max_obligations ?? "")}" placeholder="Semua"></label>
        <label class="field" for="c-ctx">Kapasitas teks per permintaan<input id="c-ctx" type="number" min="1024" step="1024" value="${esc(cfg.num_ctx ?? 8192)}"></label>
      </div>
      <label class="check"><input type="checkbox" id="c-judge-on" ${cfg.judge_enabled !== false ? "checked" : ""}><span>Periksa ulang dengan AI kedua<br><span class="hint">Hanya untuk skenario yang hasilnya belum pasti.</span></span></label>
      <label class="check"><input type="checkbox" id="c-think" ${cfg.think ? "checked" : ""}><span>Izinkan AI berpikir lebih lama<br><span class="hint">Sebaiknya mati di laptop tanpa GPU karena jauh lebih lambat.</span></span></label>
      <label class="check"><input type="checkbox" id="c-dedup" ${cfg.dedup !== false ? "checked" : ""}><span>Gabungkan test case kembar<br><span class="hint">Judul, data uji, dan kategori yang sama digabung jadi satu.</span></span></label>
      <div><span style="font-weight:500">Prioritas otomatis</span><br><span class="small">Positive menjadi ${esc((cfg.priority_rule || {}).Positive || "High")}, Negative menjadi ${esc((cfg.priority_rule || {}).Negative || "Medium")}</span></div>
    </section>
  </div>
  <section class="card" aria-labelledby="o-title"><div class="card-head"><h2 id="o-title">AI yang terpasang di laptop ini</h2></div>
    ${(mi.models || []).length ? `<div class="table-wrap"><table style="min-width:520px"><thead><tr><th>Nama AI</th><th class="r">Ukuran</th><th>Dipakai untuk</th></tr></thead><tbody>
      ${mi.models.map((m) => `<tr><td class="mono">${esc(m.name)}</td><td class="r num">${esc(gb(m.size))}</td><td class="${m.use.length ? "" : "muted"}">${esc(m.use.join(", ") || "Tidak dipakai")}</td></tr>`).join("")}
      </tbody></table></div>` : '<p class="muted">Belum ada model yang terbaca.</p>'}
  </section>`;
}

async function saveConfig() {
  const v = (id) => document.getElementById(id).value.trim();
  const int = (id) => { const x = v(id); return x === "" ? null : Number(x); };
  const values = {
    generation_model: v("c-gen"), judge_model: v("c-judge"), auto_model: v("c-auto"),
    auto_model_kinds: [...document.querySelectorAll("[data-kind]:checked")].map((c) => c.dataset.kind),
    batch_size: int("c-bs"), max_attempts: int("c-ma"), max_obligations: int("c-mo"), num_ctx: int("c-ctx"),
    judge_enabled: document.getElementById("c-judge-on").checked, think: document.getElementById("c-think").checked,
    dedup: document.getElementById("c-dedup").checked,
  };
  for (const k of ["batch_size", "max_attempts", "num_ctx"]) {
    if (values[k] === null || !Number.isInteger(values[k]) || values[k] < 1) return toast("Isi angka bulat minimal 1 di semua kolom angka (kecuali Jumlah skenario maksimum)", true);
  }
  if (values.max_obligations !== null && (!Number.isInteger(values.max_obligations) || values.max_obligations < 1)) return toast("Jumlah skenario maksimum harus angka bulat, atau kosongkan untuk semua", true);
  try {
    await api("/api/config", { method: "PUT", body: values });
    S.config = null;
    toast("Pengaturan disimpan. Berlaku untuk proses berikutnya.");
    refreshNav();
  } catch (e) { toast(e.message, true); }
}

/* ================================================================= router & event */
function currentView() { return (location.hash.replace(/^#/, "").split("/")[0]) || "beranda"; }

async function route() {
  const [view, arg] = location.hash.replace(/^#/, "").split("/");
  const v = view || "beranda";
  setActiveNav(v);
  if (v !== "berjalan") closeStream();
  if (v !== "catatan") stopNotesTimer();
  try {
    if (v === "beranda") await viewBeranda();
    else if (v === "mulai") await viewMulai();
    else if (v === "catatan") await viewCatatan();
    else if (v === "berjalan") await viewBerjalan();
    else if (v === "hasil") await viewHasil(arg && decodeURIComponent(arg));
    else if (v === "cakupan") { setActiveNav("cakupan"); await viewHasil(arg && decodeURIComponent(arg), "cakupan"); }
    else if (v === "cek") await viewCek(arg && decodeURIComponent(arg));
    else if (v === "riwayat") await viewRiwayat();
    else if (v === "pengaturan") await viewPengaturan();
    else { location.hash = "#beranda"; return; }
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
  else if (a === "start") startRun();
  else if (a === "notes-start") notesStart();
  else if (a === "notes-save") notesSave(el.dataset.file, false);
  else if (a === "notes-use") notesSave(el.dataset.file, true);
  else if (a === "notes-reset") notesReset();
  else if (a === "conv-delete") convDelete(el.dataset.conv, location.hash.startsWith("#riwayat"));
  else if (a === "conv-use") { S.mulaiPrd = el.dataset.file; location.hash = "#mulai"; }
  else if (a === "recheck") recheck(el);
  else if (a === "cancel") cancelRun();
  else if (a === "pick") { H.sel = el.dataset.tc; renderTcZone(); }
  else if (a === "prev") { H.page = Math.max(0, H.page - 1); renderTcZone(); }
  else if (a === "next") { H.page += 1; renderTcZone(); }
  else if (a === "goto-tc") { S.pendingTc = el.dataset.tc; location.hash = `#hasil/${encodeURIComponent(H.runId)}`; }
  else if (a === "toggle-group") { S.cekOpen = S.cekOpen || new Set(); const g = el.dataset.group; S.cekOpen.has(g) ? S.cekOpen.delete(g) : S.cekOpen.add(g); viewCek(H.runId); }
  else if (a === "jump") { const t = document.getElementById(el.dataset.target); if (t) t.scrollIntoView({ block: "start", behavior: "smooth" }); }
  else if (a === "compare") renderCompare();
  else if (a === "delete-run") deleteRun(el.dataset.run);
  else if (a === "save-config") saveConfig();
  else if (a === "reset-config") route();
  else if (a === "reload") route();
});

app.addEventListener("keydown", (ev) => {
  const row = ev.target.closest && ev.target.closest('tr[data-action="pick"]');
  if (row && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); S.hasil.sel = row.dataset.tc; renderTcZone(); }
});

app.addEventListener("change", (ev) => {
  const t = ev.target;
  if (t.id === "prd-file") uploadPrd(t.files[0]);
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
app.addEventListener("input", (ev) => {
  const t = ev.target;
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
