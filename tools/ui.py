# tools/ui.py
"""
Tampilan terminal pipeline. Memakai `rich` bila tersedia & output adalah terminal interaktif,
jika tidak otomatis jatuh ke teks biasa (log CI, redirect ke file, `--plain`).

Semua method aman dipanggil kapan saja (tidak error bila UI belum di-start).
"""

import time
from collections import Counter, deque
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

try:
    from rich import box
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn, TimeRemainingColumn
    from rich.table import Table
    from rich.text import Text

    HAVE_RICH = True
except Exception:  # rich belum terpasang
    HAVE_RICH = False

STAGES = [
    ("atomize", "Parse & atomisasi PRD"),
    ("design", "Desain obligation (teknik uji)"),
    ("generate", "Generate + verifikasi (LLM)"),
    ("coverage", "Coverage, dedup, prioritas"),
    ("export", "Export Excel"),
]
_SOURCE_LABEL = {
    "llm": ("LLM terverifikasi", "green"),
    "template": ("Template deterministik", "cyan"),
    "llm-unverified": ("LLM perlu review", "yellow"),
}


class RunUI:
    def __init__(self) -> None:
        self.console: Optional["Console"] = Console() if HAVE_RICH else None
        self.plain = not HAVE_RICH
        self._live: Optional["Live"] = None
        self._listeners: List[Any] = []
        self.reset()

    # ------------------------------------------------------------------ listeners (dashboard)
    def subscribe(self, fn) -> None:
        self._listeners.append(fn)

    def unsubscribe(self, fn) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def _emit(self, kind: str, **data: Any) -> None:
        for fn in list(getattr(self, "_listeners", [])):
            try:
                fn({"type": kind, "time": time.time(), **data})
            except Exception:
                pass

    # ------------------------------------------------------------------ state
    def reset(self) -> None:
        self.prd_name = ""
        self.gen_model = ""
        self.judge_model = ""
        self.stage_state: Dict[str, str] = {k: "pending" for k, _ in STAGES}
        self.stage_detail: Dict[str, str] = {}
        self.total = 0
        self.done = 0
        self.sources: Counter = Counter()
        self.retries = 0
        self.dropped = 0
        self.judge_calls = 0
        self.judge_skipped = 0
        self.judge_overruled = 0
        self.current_batch: List[str] = []
        self.current_attempt = 1
        self.events: deque = deque(maxlen=9)
        self.t0 = time.time()
        self._progress: Optional["Progress"] = None
        self._task = None

    def configure(self, plain: bool = False) -> None:
        self.plain = plain or not HAVE_RICH or not (self.console and self.console.is_terminal)

    # ------------------------------------------------------------------ lifecycle
    def start(self, prd_name: str, gen_model: str, judge_model: str, auto_model: str = "") -> None:
        self._emit("start", prd=prd_name, gen=gen_model, judge=judge_model, auto=auto_model)
        self.reset()
        self.prd_name, self.gen_model, self.judge_model = prd_name, gen_model, judge_model
        self.auto_model = auto_model
        if self.plain:
            print(f"== AI QA Generator == PRD: {prd_name} | gen: {gen_model} | judge: {judge_model}"
                  + (f" | auto: {auto_model}" if auto_model else ""))
        elif HAVE_RICH:
            self._progress = Progress(
                TextColumn("[bold]Obligation"), BarColumn(bar_width=None), MofNCompleteColumn(),
                TextColumn("[dim]elapsed"), TimeElapsedColumn(), TextColumn("[dim]ETA"), TimeRemainingColumn(),
                expand=True)
            self._task = self._progress.add_task("ob", total=1)

    @contextmanager
    def live(self):
        if self.plain or not HAVE_RICH:
            yield self
            return
        with Live(get_renderable=self._render, console=self.console, refresh_per_second=8, transient=False) as lv:
            self._live = lv
            try:
                yield self
            finally:
                self._live = None

    # ------------------------------------------------------------------ events
    def stage(self, key: str, detail: str = "") -> None:
        if key not in self.stage_state:
            return
        self._emit("stage", key=key, detail=detail)
        if self.stage_state[key] == "running":
            if detail:
                self.stage_detail[key] = detail  # sudah berjalan: perbarui detail saja, jangan cetak ulang
            return
        order = [k for k, _ in STAGES]
        for k in order[: order.index(key)]:
            if self.stage_state[k] != "done":
                self.stage_state[k] = "done"
        self.stage_state[key] = "running"
        if detail:
            self.stage_detail[key] = detail
        if self.plain:
            label = dict(STAGES)[key]
            print(f"[{label}] {detail}".rstrip())

    def stage_done(self, key: str, detail: str = "") -> None:
        self._emit("stage_done", key=key, detail=detail)
        if key in self.stage_state:
            self.stage_state[key] = "done"
            if detail:
                self.stage_detail[key] = detail

    def event(self, tag: str, msg: str, style: str = "") -> None:
        self._emit("log", tag=tag, msg=msg, style=style)
        line = f"[{tag}] {msg}"
        self.events.append((time.strftime("%H:%M:%S"), line, style))
        if self.plain:
            print(line)

    def set_total(self, n: int) -> None:
        self._emit("total", total=n)
        self.total = n
        if self._progress is not None:
            self._progress.update(self._task, total=max(n, 1))

    def batch_start(self, ids: List[str], attempt: int) -> None:
        self._emit("batch_start", ids=list(ids), attempt=attempt)
        self.stage("generate")
        self.current_batch, self.current_attempt = list(ids), attempt
        if self.plain:
            print(f"  expand {ids} attempt={attempt}")

    def batch_result(self, accepted: List[Dict[str, Any]], retry: int, dropped: int = 0,
                     judged: int = 0, skipped: int = 0, overruled: int = 0) -> None:
        self.done += len(accepted) + dropped
        self.dropped += dropped
        self.retries += retry
        self.judge_calls += judged
        self.judge_skipped += skipped
        self.judge_overruled += overruled
        for t in accepted:
            self.sources[t.get("source", "llm")] += 1
        self._emit("progress", done=self.done, total=self.total, retry=self.retries, dropped=self.dropped,
                   judged=self.judge_calls, sources=dict(self.sources), accepted=len(accepted), retry_now=retry)
        if self._progress is not None:
            self._progress.update(self._task, completed=min(self.done, max(self.total, 1)))
        if retry:
            self.event("verifier", f"{retry} TC dikembalikan ke expander (retry)", "yellow")
        if self.plain:
            print(f"  verify accepted={len(accepted)} retry={retry} dropped={dropped} total={self.done}/{self.total}")

    # ------------------------------------------------------------------ render
    def _stage_table(self) -> "Table":
        tb = Table.grid(padding=(0, 1))
        icons = {"pending": ("○", "dim"), "running": ("◉", "bold cyan"), "done": ("✔", "green")}
        for k, label in STAGES:
            icon, st = icons[self.stage_state[k]]
            det = self.stage_detail.get(k, "")
            tb.add_row(Text(icon, style=st), Text(label, style=st), Text(det, style="dim"))
        return tb

    def _counter_table(self) -> "Table":
        tb = Table.grid(padding=(0, 2))
        el = max(time.time() - self.t0, 1)
        speed = self.done / el * 60
        for key, (label, style) in _SOURCE_LABEL.items():
            tb.add_row(Text(label, style=style), Text(str(self.sources.get(key, 0)), style="bold " + style))
        tb.add_row(Text("Retry (batch)", style="magenta"), Text(str(self.retries), style="bold magenta"))
        tb.add_row(Text("Tanpa TC (dibuang)", style="red"), Text(str(self.dropped), style="bold red"))
        tb.add_row(Text("Juri dipanggil / dilewati", style="dim"), Text(f"{self.judge_calls} / {self.judge_skipped}"))
        tb.add_row(Text("Kecepatan", style="dim"), Text(f"{speed:.1f} TC/menit"))
        return tb

    def _render(self) -> "Group":
        head = Text.assemble(("AI QA Generator", "bold white on blue"), "  ", (self.prd_name, "bold"),
                             ("\ngen: ", "dim"), self.gen_model or "-", ("   judge: ", "dim"), self.judge_model or "-",
                             *((("   auto: ", "dim"), getattr(self, "auto_model", "")) if getattr(self, "auto_model", "") else ()))
        batch = ""
        if self.current_batch and self.stage_state["generate"] == "running":
            batch = f"batch {', '.join(self.current_batch)}  (attempt {self.current_attempt})"
        ev = Text()
        for ts, line, style in self.events:
            ev.append(f"{ts} ", style="dim")
            ev.append(line + "\n", style=style or "")
        left = Panel(self._stage_table(), title="Tahapan", box=box.ROUNDED, padding=(0, 1))
        right = Panel(self._counter_table(), title="Statistik", box=box.ROUNDED, padding=(0, 1))
        cols = Table.grid(expand=True)
        cols.add_column(ratio=3)
        cols.add_column(ratio=2)
        cols.add_row(left, right)
        parts: List[Any] = [Panel(head, box=box.ROUNDED), cols]
        if self._progress is not None:
            parts.append(self._progress)
        if batch:
            parts.append(Text("  ⟳ " + batch, style="cyan"))
        parts.append(Panel(ev if ev.plain else Text("-", style="dim"), title="Log", box=box.ROUNDED, padding=(0, 1)))
        return Group(*parts)

    # ------------------------------------------------------------------ ringkasan akhir
    def finish(self, report: Dict[str, Any], path: str, removed: int = 0, dropped: Optional[List[Dict[str, Any]]] = None,
               review_samples: Optional[List[Dict[str, Any]]] = None) -> None:
        self._emit("finish", report=report)
        dropped = dropped or []
        for k, _ in STAGES:
            self.stage_state[k] = "done"
        elapsed = time.time() - self.t0
        if self.plain or not HAVE_RICH:
            print("\n=== SELESAI ===")
            print(f"File           : {path}")
            print(f"Test case      : {report.get('test_cases')}  (needs review: {report.get('needs_review')})")
            print(f"Dedup dibuang  : {removed}   Tanpa TC: {len(dropped)}")
            print(f"Obligation     : {report.get('obligations_covered')}/{report.get('obligations_total')}")
            print(f"Rule atom      : {report.get('atoms_covered')}/{report.get('atoms_total')}")
            print(f"Requirement ID : {report.get('requirements_covered')}/{report.get('requirements_total')}")
            print(f"Sumber TC      : {report.get('by_source')}")
            print(f"Waktu          : {elapsed / 60:.1f} menit")
            return
        c = self.console
        sm = Table(title="Ringkasan", box=box.ROUNDED, show_header=False, title_style="bold")
        sm.add_column(style="dim")
        sm.add_column(justify="right", style="bold")
        sm.add_row("Test case", str(report.get("test_cases")))
        sm.add_row("Perlu review", str(report.get("needs_review")))
        sm.add_row("Duplikat digabung", str(removed))
        sm.add_row("Obligation tanpa TC", str(len(dropped)))
        sm.add_row("Obligation ter-cover", f"{report.get('obligations_covered')}/{report.get('obligations_total')}")
        sm.add_row("Rule atom ter-cover", f"{report.get('atoms_covered')}/{report.get('atoms_total')}")
        sm.add_row("Requirement ID", f"{report.get('requirements_covered')}/{report.get('requirements_total')}")
        sm.add_row("Waktu", f"{elapsed / 60:.1f} menit")

        def bars(title: str, data: Dict[str, int], style: str) -> "Table":
            tb = Table(title=title, box=box.ROUNDED, title_style="bold", show_header=False)
            tb.add_column(min_width=14, no_wrap=True)
            tb.add_column(justify="right")
            tb.add_column(no_wrap=True)
            mx = max(data.values()) if data else 1
            for k, v in sorted(data.items(), key=lambda x: -x[1]):
                tb.add_row(str(k), str(v), Text("█" * max(1, round(10 * v / mx)), style=style))
            return tb

        c.print()
        g1 = Table.grid(padding=(0, 2))
        g1.add_row(sm, bars("Per Teknik", report.get("by_technique", {}), "cyan"))
        c.print(g1)
        g2 = Table.grid(padding=(0, 2))
        g2.add_row(bars("Kategori", report.get("by_category", {}), "green"),
                   bars("Prioritas", report.get("by_priority", {}), "yellow"),
                   bars("Sumber", report.get("by_source", {}), "magenta"))
        c.print(g2)
        if review_samples:
            rt = Table(title=f"Contoh TC perlu review (maks {len(review_samples)})", box=box.SIMPLE_HEAD, title_style="bold yellow")
            rt.add_column("TC", no_wrap=True)
            rt.add_column("Judul", overflow="ellipsis", max_width=50)
            rt.add_column("Alasan", overflow="ellipsis", max_width=70)
            for t in review_samples:
                rt.add_row(t.get("tc_no", ""), t.get("title", ""), t.get("review_flag", ""))
            c.print(rt)
        c.print(Panel(Text(path, style="bold green"), title="File output", box=box.ROUNDED, border_style="green"))


ui = RunUI()