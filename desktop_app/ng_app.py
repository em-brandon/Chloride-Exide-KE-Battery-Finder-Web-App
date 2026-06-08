"""NiceGUI desktop pipeline dashboard — native window mode."""
from __future__ import annotations

import asyncio
import socket
import sys
import threading
from pathlib import Path

from nicegui import app, run, ui

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auth
import db_queries
import ng_pipeline


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


# ── Login page ────────────────────────────────────────────────────────────────

@ui.page("/login")
def login_page() -> None:
    ui.query("body").style("background:#f4f5f7; margin:0")

    with ui.card().classes("absolute-center").style(
        "width:380px; border-radius:16px; padding:32px 36px; "
        "box-shadow:0 4px 24px rgba(0,0,0,0.08)"
    ):
        with ui.column().classes("items-center w-full gap-1"):
            ui.label("🔋").style("font-size:2.8rem; line-height:1")
            ui.label("Battery Finder").style(
                "font-size:14pt; font-weight:700; color:#111827; margin-top:4px"
            )
            ui.label("Pipeline Dashboard").style("font-size:9pt; color:#6b7280")

        ui.separator().classes("my-5")

        username_input = ui.input("Username").classes("w-full")
        password_input = ui.input(
            "Password", password=True, password_toggle_button=True
        ).classes("w-full mt-2")
        error_label = ui.label("").style(
            "color:#CC0000; font-size:8pt; text-align:center; min-height:16px"
        ).classes("w-full mt-1")

        async def do_login() -> None:
            u = username_input.value.strip()
            p = password_input.value
            if not u or not p:
                error_label.set_text("Please enter credentials.")
                return
            error_label.set_text("Authenticating…")
            user = await run.io_bound(auth.login, u, p)
            if user:
                app.storage.user["authenticated"] = True
                app.storage.user["username"] = user.username
                ui.navigate.to("/")
            else:
                error_label.set_text("Invalid credentials.")
                password_input.value = ""

        username_input.on("keydown.enter", do_login)
        password_input.on("keydown.enter", do_login)

        ui.button("Sign In", on_click=do_login).classes("w-full mt-4").style(
            "background:#CC0000; color:white; font-weight:700; "
            "border-radius:8px; padding:10px; font-size:9.5pt"
        )


# ── Main page ─────────────────────────────────────────────────────────────────

@ui.page("/")
def main_page() -> None:
    if not app.storage.user.get("authenticated"):
        ui.navigate.to("/login")
        return

    username: str = app.storage.user.get("username", "Admin")

    # ── Mutable UI element references ─────────────────────────────────────────
    R: dict = {
        "status_badge": None,
        "donut_chart": None,
        "stat_labels": {},
        "unmatched_count": None,
        "unmatched_body": None,
        "unmatched_toggle": None,
        "unmatched_table": None,
        "all_unmatched": [],
        "log_panel": None,
        "progress_bar": None,
        "progress_label": None,
        "pipeline_status": None,
        "run_btn": None,
        "pause_btn": None,
        "cancel_btn": None,
        "provider_checks": {},
        "phase_select": None,
        "staging_count": None,
        "staging_badge": None,
        "staging_table": None,
        "staging_pg": None,
        "staging_prev": None,
        "staging_next": None,
        "ver_table": None,
        "ver_pg": None,
        "ver_prev": None,
        "ver_next": None,
        "match_table": None,
        "match_pg": None,
        "match_count": None,
        "quotas_grid": None,
        "panels": None,
        "nav_btns": {},
    }
    S: dict = {
        "staging": {"page": 1, "filter": "all", "total": 0, "page_size": 50},
        "versions": {"page": 1, "total": 0, "page_size": 20},
        "matched": {"page": 1, "total": 0, "page_size": 50, "search": ""},
        "pipeline": {"cancel": None, "pause": None, "paused": False},
        "unmatched_open": False,
    }

    # ── Header ────────────────────────────────────────────────────────────────
    with ui.header().style(
        "background:#CC0000; padding:0 20px; min-height:48px; "
        "display:flex; align-items:center; gap:12px"
    ):
        ui.label("Pipeline Dashboard").style(
            "color:white; font-size:11pt; font-weight:700"
        )
        ui.space()
        ui.label(f"👤  {username}").style(
            "color:rgba(255,255,255,0.85); font-size:8.5pt; font-weight:600"
        )
        R["status_badge"] = ui.label("Idle").style(
            "background:rgba(255,255,255,0.20); color:white; border-radius:10px; "
            "padding:3px 14px; font-size:8pt; font-weight:700"
        )

    def set_status(label: str, bg: str = "rgba(255,255,255,0.20)") -> None:
        R["status_badge"].set_text(label)
        R["status_badge"].style(
            f"background:{bg}; color:white; border-radius:10px; "
            f"padding:3px 14px; font-size:8pt; font-weight:700"
        )

    # ── Sidebar ───────────────────────────────────────────────────────────────
    NAV = [
        ("▣", "Dashboard",  "dashboard"),
        ("▶", "Pipeline",   "pipeline"),
        ("⊞", "Staging",    "staging"),
        ("⏱", "Versions",   "versions"),
        ("⬡", "Quotas",     "quotas"),
    ]

    def activate(tab: str) -> None:
        R["panels"].set_value(tab)
        for name, btn in R["nav_btns"].items():
            if name == tab:
                btn.style(
                    "background:#312e81; color:#ffffff; width:100%; border-radius:8px; "
                    "padding:10px 16px; font-size:9pt; font-weight:600; "
                    "justify-content:flex-start; text-align:left"
                )
            else:
                btn.style(
                    "background:transparent; color:#9ca3af; width:100%; border-radius:8px; "
                    "padding:10px 16px; font-size:9pt; font-weight:600; "
                    "justify-content:flex-start; text-align:left"
                )

    with ui.left_drawer(fixed=True, top_corner=True, bottom_corner=True).style(
        "background:#111827; border-right:1px solid #1f2937; "
        "padding:0; width:200px; display:flex; flex-direction:column"
    ):
        ui.label("🔋 Battery Finder").style(
            "color:#ffffff; font-size:11pt; font-weight:700; padding:18px 16px 14px"
        )
        ui.separator().style("background:#1f2937; margin:0; height:1px")
        ui.space().style("height:8px; flex:none")

        for icon, label, tab in NAV:
            with ui.row().classes("no-wrap items-center").style("padding:0 8px"):
                btn = (
                    ui.button(f"  {icon}  {label}")
                    .props("flat no-caps")
                    .style(
                        "background:transparent; color:#9ca3af; width:100%; border-radius:8px; "
                        "padding:10px 16px; font-size:9pt; font-weight:600; "
                        "justify-content:flex-start; text-align:left"
                    )
                )
                btn.on_click(lambda t=tab: activate(t))
                R["nav_btns"][tab] = btn

                if tab == "staging":
                    R["staging_badge"] = ui.badge("").style(
                        "background:#CC0000; color:white; border-radius:8px; "
                        "padding:1px 6px; font-size:7pt; font-weight:700"
                    )
                    R["staging_badge"].set_visibility(False)

        ui.space()
        ui.separator().style("background:#1f2937; margin:0; height:1px")
        ui.label(username).style(
            "color:#ffffff; font-size:8.5pt; font-weight:700; padding:6px 16px 2px"
        )
        ui.label("Pipeline Admin").style(
            "color:#6b7280; font-size:7.5pt; padding:0 16px 16px"
        )

    # ── Content panels ────────────────────────────────────────────────────────
    R["panels"] = ui.tab_panels(value="dashboard").classes("w-full").style(
        "background:#f4f5f7; flex:1; overflow-y:auto"
    )

    with R["panels"]:

        # ── Dashboard ──────────────────────────────────────────────────────────
        with ui.tab_panel("dashboard").style("padding:20px; background:#f4f5f7"):

            # Coverage card
            with ui.card().classes("w-full").style(
                "border-radius:14px; border:1px solid #e2e4e9; padding:0; overflow:hidden"
            ):
                with ui.row().classes("items-center justify-between w-full").style(
                    "background:#f4f5f7; padding:12px 16px"
                ):
                    ui.label("Coverage").style(
                        "font-size:10pt; font-weight:700; color:#111827"
                    )
                    ui.button(
                        "↺", on_click=lambda: asyncio.ensure_future(load_coverage())
                    ).props("flat round dense").style("color:#6b7280")

                with ui.row().classes("items-center gap-8 w-full").style("padding:20px 24px"):
                    R["donut_chart"] = ui.echart({
                        "series": [{
                            "type": "pie",
                            "radius": ["62%", "82%"],
                            "center": ["50%", "50%"],
                            "data": [
                                {"value": 0, "name": "Covered",
                                 "itemStyle": {"color": "#22c55e"}},
                                {"value": 100, "name": "",
                                 "itemStyle": {"color": "#e2e4e9"}},
                            ],
                            "label": {"show": False},
                            "emphasis": {"disabled": True},
                        }],
                        "legend": {"show": False},
                        "tooltip": {"show": False},
                        "graphic": [{
                            "type": "text", "left": "center", "top": "46%",
                            "style": {
                                "text": "0%",
                                "font": "bold 13px Segoe UI,sans-serif",
                                "fill": "#111827", "textAlign": "center",
                            },
                        }, {
                            "type": "text", "left": "center", "top": "56%",
                            "style": {
                                "text": "COVERED",
                                "font": "600 9px Segoe UI,sans-serif",
                                "fill": "#6b7280", "textAlign": "center",
                            },
                        }],
                    }).classes("w-44 h-44").style("flex:none")

                    with ui.grid(columns=2).classes("gap-x-10 gap-y-3"):
                        stat_defs = [
                            ("Matched",       "matched",        "#22c55e"),
                            ("Unmatched",     "unmatched",      "#CC0000"),
                            ("Total Combos",  "total",          "#111827"),
                            ("Master Records","master_count",   "#6366f1"),
                            ("In Staging",    "staging_count",  "#f59e0b"),
                            ("Cache Entries", "web_cache_size", "#0891b2"),
                        ]
                        for lbl_text, key, color in stat_defs:
                            ui.label(lbl_text).style("color:#6b7280; font-size:8pt")
                            val_lbl = ui.label("—").style(
                                f"color:{color}; font-weight:700; font-size:9pt"
                            )
                            R["stat_labels"][key] = val_lbl

            ui.space().style("height:14px")

            # Unmatched vehicles card
            with ui.card().classes("w-full").style(
                "border-radius:14px; border:1px solid #e2e4e9; padding:0; overflow:hidden"
            ):
                with ui.row().classes("items-center justify-between w-full cursor-pointer").style(
                    "background:#fff5f5; padding:12px 16px"
                ) as um_hdr:
                    R["unmatched_toggle"] = ui.label("▶  Unmatched Vehicles").style(
                        "font-size:10pt; font-weight:700; color:#CC0000; cursor:pointer"
                    )
                    R["unmatched_count"] = ui.label("0 unmatched").style(
                        "color:#CC0000; font-size:8pt; font-weight:700"
                    )

                R["unmatched_body"] = ui.column().classes("w-full").style("padding:12px 16px")
                R["unmatched_body"].set_visibility(False)
                with R["unmatched_body"]:
                    um_search = ui.input(placeholder="Filter make / model…").style("width:260px")
                    R["unmatched_table"] = ui.table(
                        columns=[
                            {"name": "make",  "label": "Make",  "field": "make",  "sortable": True},
                            {"name": "model", "label": "Model", "field": "model", "sortable": True},
                            {"name": "year",  "label": "Year",  "field": "year",  "sortable": True},
                        ],
                        rows=[], row_key="make",
                    ).classes("w-full")

                def toggle_unmatched() -> None:
                    S["unmatched_open"] = not S["unmatched_open"]
                    R["unmatched_body"].set_visibility(S["unmatched_open"])
                    R["unmatched_toggle"].set_text(
                        "▼  Unmatched Vehicles" if S["unmatched_open"] else "▶  Unmatched Vehicles"
                    )

                um_hdr.on('click', toggle_unmatched)

                def filter_unmatched(q: str = "") -> None:
                    q = q.upper()
                    rows = (
                        [r for r in R["all_unmatched"]
                         if q in str(r.get("make","")).upper() or q in str(r.get("model","")).upper()]
                        if q else R["all_unmatched"]
                    )
                    R["unmatched_table"].rows = rows
                    R["unmatched_table"].update()

                um_search.on("input", lambda e: filter_unmatched(
                    e.args.get("value", "") if isinstance(e.args, dict) else ""
                ))

        # ── Pipeline ───────────────────────────────────────────────────────────
        with ui.tab_panel("pipeline").style("padding:20px; background:#f4f5f7"):

            with ui.card().classes("w-full").style(
                "border-radius:14px; border:1px solid #e2e4e9; padding:0; overflow:hidden"
            ):
                with ui.row().classes("items-center justify-between").style(
                    "background:#f4f5f7; padding:12px 16px"
                ):
                    ui.label("Pipeline Controls").style(
                        "font-size:10pt; font-weight:700; color:#111827"
                    )
                    R["pipeline_status"] = ui.label("Idle").style(
                        "color:#6b7280; font-size:8pt"
                    )

                with ui.column().classes("w-full gap-3").style("padding:16px"):
                    with ui.row().classes("items-center gap-4 flex-wrap"):
                        ui.label("Providers:").style(
                            "color:#6b7280; font-size:8.5pt; font-weight:600"
                        )
                        for prov in ["searxng", "duckduckgo", "brave", "tavily"]:
                            R["provider_checks"][prov] = ui.checkbox(prov, value=True)

                    with ui.row().classes("items-center gap-4 w-full"):
                        R["phase_select"] = ui.select(
                            {"both": "Both phases", "phase1": "Phase 1 only", "phase2": "Phase 2 only"},
                            value="both", label="Phase",
                        ).style("width:180px")
                        ui.space()
                        R["run_btn"] = ui.button(
                            "▶  Run Pipeline",
                            on_click=lambda: asyncio.ensure_future(start_run()),
                        ).style(
                            "background:#22c55e; color:white; font-weight:700; "
                            "border-radius:8px; padding:8px 20px"
                        )
                        R["pause_btn"] = ui.button("⏸  Pause").style(
                            "background:#f59e0b; color:white; font-weight:700; border-radius:8px"
                        )
                        R["pause_btn"].on_click(lambda: on_pause_click())
                        R["pause_btn"].set_visibility(False)

                        R["cancel_btn"] = ui.button("✕  Cancel").style(
                            "background:#dc2626; color:white; font-weight:700; border-radius:8px"
                        )
                        R["cancel_btn"].on_click(lambda: on_cancel_click())
                        R["cancel_btn"].set_visibility(False)

                    R["progress_bar"] = ui.linear_progress(value=0, show_value=False).style(
                        "width:100%; height:8px; border-radius:4px"
                    )
                    R["progress_bar"].set_visibility(False)
                    R["progress_label"] = ui.label("").style("color:#6b7280; font-size:8pt")
                    R["progress_label"].set_visibility(False)

            ui.space().style("height:14px")

            with ui.card().classes("w-full").style(
                "border-radius:14px; border:1px solid #e2e4e9; padding:0; overflow:hidden"
            ):
                with ui.row().classes("items-center justify-between").style(
                    "background:#f4f5f7; padding:12px 16px"
                ):
                    ui.label("Log").style("font-size:10pt; font-weight:700; color:#111827")
                    ui.button("Clear", on_click=lambda: R["log_panel"].clear()).props(
                        "flat dense no-caps"
                    ).style("color:#6b7280; font-size:8pt")

                R["log_panel"] = ui.log(max_lines=2000).style(
                    "background:#0d1117; color:#e5e7eb; "
                    "font-family:'Cascadia Code',Consolas,monospace; "
                    "font-size:8pt; padding:12px; min-height:320px; width:100%; "
                    "border-radius:0 0 14px 14px"
                )

        # ── Staging ────────────────────────────────────────────────────────────
        with ui.tab_panel("staging").style("padding:20px; background:#f4f5f7"):

            with ui.card().classes("w-full").style(
                "border-radius:14px; border:1px solid #e2e4e9; padding:0; overflow:hidden"
            ):
                with ui.row().classes("items-center justify-between w-full").style(
                    "background:#f4f5f7; padding:12px 16px"
                ):
                    ui.label("Staging Results").style(
                        "font-size:10pt; font-weight:700; color:#111827"
                    )
                    R["staging_count"] = ui.badge("0 rows").style(
                        "background:#e0f2fe; color:#0369a1; border-radius:10px; "
                        "padding:2px 10px; font-size:8pt"
                    )
                    ui.space()
                    ui.button(
                        "✓  Commit to Master",
                        on_click=lambda: asyncio.ensure_future(on_commit()),
                    ).style(
                        "background:#22c55e; color:white; font-weight:700; "
                        "border-radius:8px; padding:6px 14px; font-size:8.5pt"
                    )
                    ui.button(
                        "✕  Discard",
                        on_click=lambda: asyncio.ensure_future(on_discard()),
                    ).style(
                        "background:white; color:#dc2626; border:1px solid #fecaca; "
                        "border-radius:8px; padding:6px 14px; font-size:8.5pt"
                    )

                with ui.tabs(
                    value="all",
                    on_change=lambda e: asyncio.ensure_future(on_staging_filter(e.value)),
                ).style("border-bottom:1px solid #e2e4e9"):
                    for lbl, val in [("All","all"),("Valid","valid"),("Invalid","invalid"),("Conflicts","conflicts")]:
                        ui.tab(val, label=lbl).props("no-caps")

                R["staging_table"] = ui.table(
                    columns=[
                        {"name": "make_n",       "label": "Make",         "field": "make_n"},
                        {"name": "model_n",      "label": "Model",        "field": "model_n"},
                        {"name": "year",         "label": "Year",         "field": "year"},
                        {"name": "battery_code", "label": "Battery Code", "field": "battery_code"},
                        {"name": "ah",           "label": "Ah",           "field": "ah"},
                        {"name": "technology",   "label": "Tech",         "field": "technology"},
                        {"name": "source",       "label": "Source",       "field": "source"},
                        {"name": "is_valid",     "label": "Valid",        "field": "is_valid"},
                        {"name": "conflict",     "label": "Conflict",     "field": "conflict"},
                        {"name": "actions",      "label": "Actions",      "field": "id"},
                    ],
                    rows=[], row_key="id",
                ).classes("w-full")
                R["staging_table"].add_slot("body-cell-is_valid", """
                    <q-td :props="props">
                        <span :style="{color: props.value ? '#22c55e' : '#CC0000', fontWeight:700}">
                            {{ props.value ? '✓' : '✗' }}
                        </span>
                    </q-td>
                """)
                R["staging_table"].add_slot("body-cell-conflict", """
                    <q-td :props="props">
                        <span style="color:#CC0000;font-weight:700" v-if="props.value">!</span>
                    </q-td>
                """)
                R["staging_table"].add_slot("body-cell-actions", """
                    <q-td :props="props">
                        <q-btn flat dense size="sm" color="primary"
                               @click="$emit('edit', props.row)">Edit</q-btn>
                    </q-td>
                """)
                R["staging_table"].on("edit", lambda e: asyncio.ensure_future(open_edit_dialog(e.args)))

                with ui.row().classes("items-center justify-between w-full").style("padding:8px 12px"):
                    R["staging_pg"] = ui.label("").style("color:#6b7280; font-size:8pt")
                    with ui.row().classes("gap-2"):
                        R["staging_prev"] = ui.button(
                            "← Prev",
                            on_click=lambda: asyncio.ensure_future(
                                go_staging_page(S["staging"]["page"] - 1)
                            ),
                        ).props("flat no-caps dense").style("font-size:8pt")
                        R["staging_next"] = ui.button(
                            "Next →",
                            on_click=lambda: asyncio.ensure_future(
                                go_staging_page(S["staging"]["page"] + 1)
                            ),
                        ).props("flat no-caps dense").style("font-size:8pt")

        # ── Versions ───────────────────────────────────────────────────────────
        with ui.tab_panel("versions").style("padding:20px; background:#f4f5f7"):

            with ui.card().classes("w-full").style(
                "border-radius:14px; border:1px solid #e2e4e9; padding:0; overflow:hidden"
            ):
                with ui.row().classes("items-center justify-between").style(
                    "background:#f4f5f7; padding:12px 16px"
                ):
                    ui.label("Version History").style(
                        "font-size:10pt; font-weight:700; color:#111827"
                    )
                    ui.button("↺", on_click=lambda: asyncio.ensure_future(load_versions())).props(
                        "flat round dense"
                    ).style("color:#6b7280")

                R["ver_table"] = ui.table(
                    columns=[
                        {"name": "version_number",  "label": "#",        "field": "version_number"},
                        {"name": "committed_at",    "label": "Date",     "field": "committed_at"},
                        {"name": "committed_by",    "label": "By",       "field": "committed_by"},
                        {"name": "committed_count", "label": "Records",  "field": "committed_count"},
                        {"name": "conflict_count",  "label": "Conflicts","field": "conflict_count"},
                        {"name": "actions",         "label": "Actions",  "field": "id"},
                    ],
                    rows=[], row_key="id",
                ).classes("w-full")
                R["ver_table"].add_slot("body-cell-actions", """
                    <q-td :props="props">
                        <q-btn flat dense size="sm"
                               @click="$emit('changelog', props.row)">Changelog</q-btn>
                        <q-btn flat dense size="sm" color="negative"
                               @click="$emit('revert', props.row)">Revert</q-btn>
                    </q-td>
                """)
                R["ver_table"].on("changelog", lambda e: asyncio.ensure_future(show_changelog(e.args)))
                R["ver_table"].on("revert",    lambda e: asyncio.ensure_future(do_revert(e.args)))

                with ui.row().classes("items-center justify-between").style("padding:8px 12px"):
                    R["ver_pg"] = ui.label("").style("color:#6b7280; font-size:8pt")
                    with ui.row().classes("gap-2"):
                        R["ver_prev"] = ui.button(
                            "← Prev",
                            on_click=lambda: asyncio.ensure_future(
                                go_ver_page(S["versions"]["page"] - 1)
                            ),
                        ).props("flat no-caps dense").style("font-size:8pt")
                        R["ver_next"] = ui.button(
                            "Next →",
                            on_click=lambda: asyncio.ensure_future(
                                go_ver_page(S["versions"]["page"] + 1)
                            ),
                        ).props("flat no-caps dense").style("font-size:8pt")

            ui.space().style("height:14px")

            # Matched records
            with ui.card().classes("w-full").style(
                "border-radius:14px; border:1px solid #e2e4e9; padding:0; overflow:hidden"
            ):
                with ui.row().classes("items-center gap-3").style(
                    "background:#f4f5f7; padding:12px 16px"
                ):
                    ui.label("Matched Records").style(
                        "font-size:10pt; font-weight:700; color:#111827"
                    )
                    R["match_count"] = ui.badge("0 records").style(
                        "background:#f0fdf4; color:#15803d; border-radius:10px; "
                        "padding:2px 10px; font-size:8pt"
                    )
                    ui.space()
                    match_search = ui.input(placeholder="Search make / model…").style("width:240px")
                    match_search.on("input", lambda e: asyncio.ensure_future(on_match_search(
                        e.args.get("value", "") if isinstance(e.args, dict) else ""
                    )))

                R["match_table"] = ui.table(
                    columns=[
                        {"name": "make_n",       "label": "Make",         "field": "make_n",       "sortable": True},
                        {"name": "model_n",      "label": "Model",        "field": "model_n",      "sortable": True},
                        {"name": "year",         "label": "Year",         "field": "year",         "sortable": True},
                        {"name": "battery_code", "label": "Battery Code", "field": "battery_code"},
                        {"name": "ah",           "label": "Ah",           "field": "ah"},
                        {"name": "technology",   "label": "Tech",         "field": "technology"},
                        {"name": "source",       "label": "Source",       "field": "source"},
                    ],
                    rows=[], row_key="id",
                ).classes("w-full")

                with ui.row().classes("items-center justify-between").style("padding:8px 12px"):
                    R["match_pg"] = ui.label("").style("color:#6b7280; font-size:8pt")
                    with ui.row().classes("gap-2"):
                        ui.button(
                            "← Prev",
                            on_click=lambda: asyncio.ensure_future(
                                go_match_page(S["matched"]["page"] - 1)
                            ),
                        ).props("flat no-caps dense").style("font-size:8pt")
                        ui.button(
                            "Next →",
                            on_click=lambda: asyncio.ensure_future(
                                go_match_page(S["matched"]["page"] + 1)
                            ),
                        ).props("flat no-caps dense").style("font-size:8pt")

        # ── Quotas ─────────────────────────────────────────────────────────────
        with ui.tab_panel("quotas").style("padding:20px; background:#f4f5f7"):
            with ui.row().classes("items-center justify-between w-full").style("padding-bottom:14px"):
                ui.label("API Quotas (this month)").style(
                    "font-size:10pt; font-weight:700; color:#111827"
                )
                ui.button("↺", on_click=lambda: asyncio.ensure_future(load_quotas())).props(
                    "flat round dense"
                ).style("color:#6b7280")
            R["quotas_grid"] = ui.grid(columns=2).classes("w-full gap-4")

    # ── Action functions ──────────────────────────────────────────────────────

    def update_staging_badge(count: int) -> None:
        if R["staging_badge"] is None:
            return
        R["staging_badge"].set_text(str(count))
        R["staging_badge"].set_visibility(count > 0)

    async def load_coverage() -> None:
        try:
            data = await run.io_bound(db_queries.get_coverage)
            matched = data.get("matched", 0)
            total   = data.get("total", 0)
            pct     = round(matched / total * 100, 1) if total else 0.0

            chart = R["donut_chart"]
            chart.options["series"][0]["data"][0]["value"] = pct
            chart.options["series"][0]["data"][1]["value"] = max(0.0, 100 - pct)
            chart.options["graphic"][0]["style"]["text"] = f"{pct:.1f}%"
            chart.update()

            for key, lbl in R["stat_labels"].items():
                lbl.set_text(str(data.get(key, "—")))

            vehicles = data.get("unmatched_vehicles", [])
            R["unmatched_count"].set_text(f"{len(vehicles):,} unmatched")
            R["all_unmatched"].clear()
            R["all_unmatched"].extend(vehicles)
            R["unmatched_table"].rows = list(vehicles)
            R["unmatched_table"].update()
        except Exception:
            import traceback; traceback.print_exc()

    async def load_quotas() -> None:
        try:
            quotas = await run.io_bound(db_queries.get_quotas)
            prov_colors = {
                "brave": "#f59e0b", "tavily": "#6366f1",
                "searxng": "#22c55e", "duckduckgo": "#0ea5e9",
            }
            R["quotas_grid"].clear()
            with R["quotas_grid"]:
                for q in quotas:
                    prov  = q.get("provider", "")
                    calls = q.get("calls_made", 0)
                    limit = q.get("quota_limit", -1)
                    pct   = q.get("pct_used", 0)
                    color = prov_colors.get(prov, "#6b7280")
                    usage = f"{calls:,} / {limit:,}" if limit != -1 else f"{calls:,} (unlimited)"
                    with ui.card().style(
                        "border-radius:10px; border:1px solid #e2e4e9; padding:14px"
                    ):
                        ui.label(prov.capitalize()).style(
                            f"color:{color}; font-weight:700; font-size:9pt"
                        )
                        ui.label(usage).style("color:#111827; font-size:8.5pt; margin-top:4px")
                        if limit != -1:
                            ui.linear_progress(value=pct / 100, show_value=False).style(
                                f"height:6px; border-radius:3px; margin-top:6px; color:{color}"
                            )
                            ui.label(f"{pct:.1f}% used").style("color:#6b7280; font-size:7.5pt")
        except Exception:
            import traceback; traceback.print_exc()

    async def load_staging() -> None:
        st = S["staging"]
        try:
            data = await run.io_bound(
                db_queries.get_staging, st["page"], st["filter"], st["page_size"]
            )
        except Exception:
            import traceback; traceback.print_exc()
            return
        total      = data["total"]
        st["total"] = total
        items      = data["items"]
        pages      = max(1, -(-total // st["page_size"]))

        R["staging_count"].set_text(f"{total:,} rows")
        R["staging_pg"].set_text(f"Page {st['page']} / {pages}")
        R["staging_prev"].props("disabled" if st["page"] <= 1 else "")
        R["staging_next"].props("disabled" if st["page"] >= pages else "")
        R["staging_table"].rows = [dict(r) for r in items]
        R["staging_table"].update()
        update_staging_badge(total)

    async def on_staging_filter(val: str) -> None:
        S["staging"]["filter"] = val
        S["staging"]["page"]   = 1
        await load_staging()

    async def go_staging_page(page: int) -> None:
        total = S["staging"]["total"]
        pages = max(1, -(-total // S["staging"]["page_size"]))
        S["staging"]["page"] = max(1, min(page, pages))
        await load_staging()

    async def open_edit_dialog(row: dict) -> None:
        with ui.dialog() as dlg, ui.card().style("min-width:300px; padding:20px"):
            ui.label(
                f"{row.get('make_n','')} {row.get('model_n','')} {row.get('year','')}"
            ).style("font-weight:700; font-size:10pt; margin-bottom:12px")
            ah_inp   = ui.number("Ah", value=float(row.get("ah") or 45), min=20, max=250).classes("w-full")
            tech_sel = ui.select(
                ["MF","AGM","EFB","GEL","WET"],
                value=(row.get("technology") or "MF").upper(),
                label="Technology",
            ).classes("w-full")

            async def save() -> None:
                try:
                    await run.io_bound(db_queries.patch_staging, row["id"], ah_inp.value, tech_sel.value)
                    dlg.close()
                    await load_staging()
                except Exception as exc:
                    ui.notify(str(exc), color="negative")

            with ui.row().classes("gap-2 justify-end w-full mt-4"):
                ui.button("Cancel", on_click=dlg.close).props("flat no-caps")
                ui.button("Save", on_click=save).style(
                    "background:#CC0000; color:white"
                ).props("no-caps")
        dlg.open()

    async def show_conflict_dialog(conflicts: list) -> dict:
        radio_refs: dict = {}
        with ui.dialog() as dlg, ui.card().style(
            "min-width:500px; max-height:600px; overflow-y:auto; padding:20px"
        ):
            ui.label("Resolve Conflicts").style("font-weight:700; font-size:10pt; margin-bottom:12px")
            for c in conflicts:
                with ui.card().style(
                    "padding:10px; margin-bottom:8px; border:1px solid #e2e4e9; border-radius:8px"
                ):
                    ui.label(
                        f"{c.get('make','')} {c.get('model','')} {c.get('year','')}"
                    ).style("font-weight:600; font-size:9pt")
                    radio_refs[c["id"]] = ui.radio(
                        ["Keep Current", "Keep Staging"], value="Keep Staging"
                    ).props("inline")

            async def confirm() -> None:
                result = {
                    cid: ("current" if r.value == "Keep Current" else "staging")
                    for cid, r in radio_refs.items()
                }
                dlg.submit(result)

            with ui.row().classes("gap-2 justify-end w-full mt-4"):
                ui.button("Cancel", on_click=lambda: dlg.submit({})).props("flat no-caps")
                ui.button("Confirm", on_click=confirm).style(
                    "background:#CC0000; color:white"
                ).props("no-caps")
        return await dlg

    async def on_commit() -> None:
        try:
            pre = await run.io_bound(db_queries.pre_commit)
        except Exception as exc:
            ui.notify(str(exc), color="negative")
            return

        resolutions: dict = {}
        if pre.get("conflict_count", 0) > 0:
            resolutions = await show_conflict_dialog(pre["conflicts"])

        with ui.dialog() as confirm_dlg, ui.card().style("padding:20px; max-width:400px"):
            ui.label("Write all valid staging rows to the master table?").style("font-weight:600")
            with ui.row().classes("gap-2 justify-end w-full mt-4"):
                ui.button("Cancel", on_click=lambda: confirm_dlg.submit(False)).props("flat no-caps")
                ui.button("Commit", on_click=lambda: confirm_dlg.submit(True)).style(
                    "background:#22c55e; color:white"
                ).props("no-caps")
        if not await confirm_dlg:
            return

        try:
            result = await run.io_bound(db_queries.commit_staging, resolutions, username)
            ui.notify(
                f"Version #{result['version']} created.  Added: {result['added']}  "
                f"Updated: {result['updated']}",
                color="positive", timeout=6000,
            )
            update_staging_badge(0)
            await load_coverage()
            await load_versions()
            await load_staging()
        except Exception as exc:
            ui.notify(str(exc), color="negative")

    async def on_discard() -> None:
        with ui.dialog() as dlg, ui.card().style("padding:20px; max-width:380px"):
            ui.label("Delete all staging rows? This cannot be undone.").style("font-weight:600")
            with ui.row().classes("gap-2 justify-end w-full mt-4"):
                ui.button("Cancel", on_click=lambda: dlg.submit(False)).props("flat no-caps")
                ui.button("Discard", on_click=lambda: dlg.submit(True)).style(
                    "background:#dc2626; color:white"
                ).props("no-caps")
        if not await dlg:
            return
        try:
            await run.io_bound(db_queries.discard_staging)
            ui.notify("Staging discarded.", color="positive")
            update_staging_badge(0)
            await load_staging()
        except Exception as exc:
            ui.notify(str(exc), color="negative")

    async def load_versions() -> None:
        vs = S["versions"]
        try:
            data  = await run.io_bound(db_queries.get_versions, vs["page"], vs["page_size"])
            total = data["total"]
            vs["total"] = total
            pages = max(1, -(-total // vs["page_size"]))
            R["ver_pg"].set_text(f"Page {vs['page']} / {pages}")
            R["ver_prev"].props("disabled" if vs["page"] <= 1 else "")
            R["ver_next"].props("disabled" if vs["page"] >= pages else "")
            rows = []
            for v in data.get("items", []):
                row = dict(v)
                if row.get("committed_at"):
                    row["committed_at"] = str(row["committed_at"])[:16]
                rows.append(row)
            R["ver_table"].rows = rows
            R["ver_table"].update()
        except Exception:
            import traceback; traceback.print_exc()

    async def go_ver_page(page: int) -> None:
        vs    = S["versions"]
        pages = max(1, -(-vs["total"] // vs["page_size"]))
        vs["page"] = max(1, min(page, pages))
        await load_versions()

    async def show_changelog(ver: dict) -> None:
        try:
            changes = await run.io_bound(db_queries.get_changelog, ver.get("id"))
        except Exception as exc:
            ui.notify(str(exc), color="negative")
            return
        colors = {"added": "#15803d", "updated": "#1d4ed8", "removed": "#CC0000"}
        with ui.dialog() as dlg, ui.card().style(
            "min-width:600px; max-height:700px; overflow-y:auto; padding:20px"
        ):
            ui.label(f"Changelog — Version #{ver.get('version_number','')}").style(
                "font-weight:700; font-size:10pt; margin-bottom:12px"
            )
            for ch in changes:
                ct    = ch.get("change_type", "updated")
                color = colors.get(ct, "#6b7280")
                with ui.card().style(
                    f"padding:8px 12px; margin-bottom:6px; "
                    f"border-left:3px solid {color}; border-radius:4px"
                ):
                    with ui.row().classes("items-center gap-2"):
                        ui.badge(ct.upper()).style(
                            f"background:{color}; color:white; font-size:7pt"
                        )
                        ui.label(
                            f"{ch.get('make','')} {ch.get('model','')} {ch.get('year','')}"
                        ).style("font-size:8.5pt; font-weight:600")
                    if ch.get("old_values") or ch.get("new_values"):
                        ui.label(
                            f"Old: {ch.get('old_values')}  →  New: {ch.get('new_values')}"
                        ).style("font-size:7.5pt; color:#6b7280; margin-top:2px")
            ui.button("Close", on_click=dlg.close).props("no-caps").style("margin-top:12px")
        dlg.open()

    async def do_revert(ver: dict) -> None:
        ver_num = ver.get("version_number", "?")
        with ui.dialog() as dlg, ui.card().style("padding:20px; max-width:400px"):
            ui.label(f"Revert version #{ver_num}?").style("font-weight:600")
            ui.label("This will undo all changes committed in this version.").style(
                "color:#6b7280; font-size:8.5pt; margin-top:4px"
            )
            with ui.row().classes("gap-2 justify-end w-full mt-4"):
                ui.button("Cancel", on_click=lambda: dlg.submit(False)).props("flat no-caps")
                ui.button("Revert", on_click=lambda: dlg.submit(True)).style(
                    "background:#dc2626; color:white"
                ).props("no-caps")
        if not await dlg:
            return
        try:
            await run.io_bound(db_queries.revert_version, ver.get("id"), username)
            ui.notify(f"Version #{ver_num} reverted.", color="positive")
            await load_versions()
            await load_coverage()
        except Exception as exc:
            ui.notify(str(exc), color="negative")

    async def load_matched() -> None:
        ms = S["matched"]
        try:
            data  = await run.io_bound(db_queries.get_matched, ms["page"], ms["search"], ms["page_size"])
            total = data["total"]
            ms["total"] = total
            pages = max(1, -(-total // ms["page_size"]))
            R["match_count"].set_text(f"{total:,} records")
            R["match_pg"].set_text(f"Page {ms['page']} / {pages}")
            R["match_table"].rows = [dict(r) for r in data.get("items", [])]
            R["match_table"].update()
        except Exception:
            pass

    async def on_match_search(q: str) -> None:
        S["matched"]["search"] = q
        S["matched"]["page"]   = 1
        await load_matched()

    async def go_match_page(page: int) -> None:
        ms    = S["matched"]
        pages = max(1, -(-ms["total"] // ms["page_size"]))
        ms["page"] = max(1, min(page, pages))
        await load_matched()

    # ── Pipeline run controls ─────────────────────────────────────────────────

    async def start_run() -> None:
        providers = [p for p, cb in R["provider_checks"].items() if cb.value]
        if not providers:
            ui.notify("Select at least one provider.", color="warning")
            return
        phase = R["phase_select"].value

        R["run_btn"].set_visibility(False)
        R["pause_btn"].set_visibility(True)
        R["cancel_btn"].set_visibility(True)
        R["progress_bar"].set_visibility(True)
        R["progress_label"].set_visibility(True)
        R["progress_bar"].value = 0
        R["pipeline_status"].set_text("Running…")
        set_status("Running…", "#22c55e")
        R["log_panel"].push(f"\n[Run] Starting  phase={phase}  providers={providers}")

        cancel_ev = threading.Event()
        pause_ev  = threading.Event()
        S["pipeline"]["cancel"] = cancel_ev
        S["pipeline"]["pause"]  = pause_ev
        S["pipeline"]["paused"] = False

        loop = asyncio.get_running_loop()

        def log_cb(line: str) -> None:
            loop.call_soon_threadsafe(R["log_panel"].push, line)

        def progress_cb(processed: int, total: int, provider: str) -> None:
            def _upd() -> None:
                R["progress_bar"].value = processed / total if total else 0
                R["progress_label"].set_text(f"{processed} / {total} · {provider}")
            loop.call_soon_threadsafe(_upd)

        async def on_finish(result: dict) -> None:
            fetched = result.get("fetched", 0)
            failed  = result.get("failed", 0)
            R["log_panel"].push(f"[Run] Finished — fetched={fetched}  failed={failed}")
            R["run_btn"].set_visibility(True)
            R["pause_btn"].set_visibility(False)
            R["cancel_btn"].set_visibility(False)
            R["pipeline_status"].set_text(f"Done — {fetched} fetched, {failed} failed")
            set_status("Done", "#22c55e")
            await load_coverage()
            await load_quotas()
            await load_staging()

        async def on_error(msg: str) -> None:
            R["log_panel"].push(f"[Run] ERROR: {msg}")
            R["run_btn"].set_visibility(True)
            R["pause_btn"].set_visibility(False)
            R["cancel_btn"].set_visibility(False)
            R["pipeline_status"].set_text("Error — see log")
            set_status("Error", "#dc2626")
            ui.notify(f"Pipeline error: {msg}", color="negative", timeout=8000)

        await ng_pipeline.execute(
            providers=providers, phase=phase,
            cancel_event=cancel_ev, pause_event=pause_ev,
            log_push=log_cb, set_progress=progress_cb,
            on_finish=on_finish, on_error=on_error,
        )

    def on_pause_click() -> None:
        pipe = S["pipeline"]
        if pipe["cancel"] is None:
            return
        if not pipe["paused"]:
            pipe["pause"].set()
            pipe["paused"] = True
            R["pause_btn"].set_text("▷  Resume")
            R["pipeline_status"].set_text("Paused")
            set_status("Paused", "#f59e0b")
        else:
            pipe["pause"].clear()
            pipe["paused"] = False
            R["pause_btn"].set_text("⏸  Pause")
            R["pipeline_status"].set_text("Running…")
            set_status("Running…", "#22c55e")

    def on_cancel_click() -> None:
        pipe = S["pipeline"]
        if pipe["cancel"]:
            pipe["cancel"].set()
            if pipe["pause"]:
                pipe["pause"].clear()
            R["pipeline_status"].set_text("Cancelling…")
            set_status("Cancelling…", "#f59e0b")
            R["log_panel"].push("[Run] Cancelling…")

    # ── Initial load ──────────────────────────────────────────────────────────

    async def initial_load() -> None:
        activate("dashboard")
        await load_coverage()
        await load_quotas()
        await load_versions()
        await load_matched()
        await load_staging()

    ui.timer(0.3, lambda: asyncio.ensure_future(initial_load()), once=True)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ui.run(
        native=True,
        window_size=(1280, 900),
        title="Battery Finder — Pipeline Dashboard",
        storage_secret="chloride-exide-ke-pipeline-2025",
        port=find_free_port(),
        reload=False,
        show=False,
    )
