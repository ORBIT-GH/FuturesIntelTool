from __future__ import annotations

import json
import os
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any
from tkinter import messagebox, ttk
import tkinter as tk
from zoneinfo import ZoneInfo

from .config import ensure_runtime_dirs, load_config
from .db import MarketDB
from .pipeline import Collector
from .report import build_report_context, generate_daily_report
from .settings import normalize_product, prepare_desktop_environment, save_products

SHANGHAI = ZoneInfo("Asia/Shanghai")

class FuturesDesktopApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.data_root, self.config_path = prepare_desktop_environment()
        self.config = load_config(self.config_path)
        ensure_runtime_dirs(self.config)
        self.db = MarketDB(self.config["database"])
        self.db.initialize()
        self.context: dict[str, Any] = {}
        self.settings_products: list[dict[str, Any]] = []
        self.busy = False
        self.date_var = tk.StringVar(value=datetime.now(SHANGHAI).date().isoformat())
        self.status_var = tk.StringVar(value="就绪")
        self.data_root_var = tk.StringVar(value=str(self.data_root))
        self._configure_window()
        self._configure_style()
        self._build_ui()
        self._load_products()
        self.refresh()

    def _configure_window(self) -> None:
        self.root.title("期货资讯工具")
        self.root.geometry("1180x780")
        self.root.minsize(960, 650)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#F4F7FB")
        style.configure("Card.TFrame", background="#FFFFFF")
        style.configure("TLabel", background="#F4F7FB", foreground="#263445", font=("Microsoft YaHei UI", 9))
        style.configure("Card.TLabel", background="#FFFFFF", foreground="#263445", font=("Microsoft YaHei UI", 9))
        style.configure("Muted.TLabel", background="#F4F7FB", foreground="#718096", font=("Microsoft YaHei UI", 9))
        style.configure("PageTitle.TLabel", background="#FFFFFF", foreground="#132238", font=("Microsoft YaHei UI", 17, "bold"))
        style.configure("CardTitle.TLabel", background="#FFFFFF", foreground="#718096", font=("Microsoft YaHei UI", 9))
        style.configure("CardValue.TLabel", background="#FFFFFF", foreground="#132238", font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("TButton", padding=(12, 7), font=("Microsoft YaHei UI", 9), borderwidth=0)
        style.configure("Accent.TButton", background="#0D7A68", foreground="#FFFFFF")
        style.map("Accent.TButton", background=[("active", "#096B5B"), ("disabled", "#9FB7B2")])
        style.configure("Secondary.TButton", background="#E8EEF4", foreground="#263445")
        style.map("Secondary.TButton", background=[("active", "#DCE6EE")])
        style.configure(
            "Treeview",
            rowheight=30,
            font=("Microsoft YaHei UI", 9),
            background="#FFFFFF",
            fieldbackground="#FFFFFF",
            foreground="#263445",
            borderwidth=0,
        )
        style.map("Treeview", background=[("selected", "#D9EEE9")], foreground=[("selected", "#132238")])
        style.configure(
            "Treeview.Heading",
            background="#E8EEF4",
            foreground="#496174",
            relief="flat",
            font=("Microsoft YaHei UI", 9, "bold"),
            padding=(8, 8),
        )
        style.map("Treeview.Heading", background=[("active", "#DCE6EE")])
        style.configure("TEntry", padding=7, fieldbackground="#FFFFFF")
        style.configure("TCombobox", padding=5)
        style.configure("TLabelframe", background="#FFFFFF", bordercolor="#DDE6EE")
        style.configure("TLabelframe.Label", background="#FFFFFF", foreground="#496174", font=("Microsoft YaHei UI", 9, "bold"))

    def _build_ui(self) -> None:
        shell = tk.Frame(self.root, bg="#F4F7FB")
        shell.pack(fill="both", expand=True)

        sidebar = tk.Frame(shell, bg="#102A2B", width=224)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(
            sidebar,
            text="FUTURES",
            bg="#102A2B",
            fg="#78D6C6",
            font=("Microsoft YaHei UI", 10, "bold"),
            anchor="w",
        ).pack(fill="x", padx=22, pady=(24, 0))
        tk.Label(
            sidebar,
            text="期货资讯工具",
            bg="#102A2B",
            fg="#FFFFFF",
            font=("Microsoft YaHei UI", 17, "bold"),
            anchor="w",
        ).pack(fill="x", padx=22, pady=(3, 24))

        self.nav_buttons: dict[str, tk.Button] = {}
        for key, label in (
            ("overview", "行情看板"),
            ("health", "数据源"),
            ("report", "日报"),
            ("settings", "合约设置"),
        ):
            button = tk.Button(
                sidebar,
                text=label,
                command=lambda current=key: self.show_page(current),
                bg="#173536",
                fg="#D9E9E6",
                activebackground="#0D7A68",
                activeforeground="#FFFFFF",
                relief="flat",
                bd=0,
                anchor="w",
                padx=22,
                pady=12,
                font=("Microsoft YaHei UI", 10),
                cursor="hand2",
            )
            button.pack(fill="x", padx=12, pady=3)
            self.nav_buttons[key] = button

        tk.Label(
            sidebar,
            text="自动采集 · 本地入库\nOpenClaw 只读简报",
            bg="#102A2B",
            fg="#8FAEAA",
            justify="left",
            anchor="w",
            font=("Microsoft YaHei UI", 8),
        ).pack(side="bottom", fill="x", padx=22, pady=20)

        main = tk.Frame(shell, bg="#F4F7FB")
        main.pack(side="left", fill="both", expand=True)

        topbar = tk.Frame(main, bg="#FFFFFF", height=76)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        title_box = tk.Frame(topbar, bg="#FFFFFF")
        title_box.pack(side="left", fill="y", padx=24)
        self.page_title_var = tk.StringVar(value="行情看板")
        tk.Label(
            title_box,
            textvariable=self.page_title_var,
            bg="#FFFFFF",
            fg="#132238",
            font=("Microsoft YaHei UI", 17, "bold"),
        ).pack(anchor="w", pady=(16, 0))
        tk.Label(
            title_box,
            text="本地数据、日报和合约设置",
            bg="#FFFFFF",
            fg="#718096",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w")

        controls = tk.Frame(topbar, bg="#FFFFFF")
        controls.pack(side="right", padx=18, pady=16)
        tk.Label(controls, text="交易日", bg="#FFFFFF", fg="#718096").pack(side="left", padx=(0, 6))
        ttk.Entry(controls, textvariable=self.date_var, width=12).pack(side="left")
        self.refresh_button = ttk.Button(controls, text="刷新", command=self.refresh, style="Secondary.TButton")
        self.refresh_button.pack(side="left", padx=6)
        self.run_button = ttk.Button(controls, text="采集并生成日报", command=self.run_now, style="Accent.TButton")
        self.run_button.pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="打开数据目录", command=self.open_data_dir, style="Secondary.TButton").pack(side="left")

        self.content_host = tk.Frame(main, bg="#F4F7FB")
        self.content_host.pack(fill="both", expand=True, padx=16, pady=16)
        self.pages: dict[str, tk.Frame] = {}
        for key in ("overview", "health", "report", "settings"):
            page = tk.Frame(self.content_host, bg="#F4F7FB")
            self.pages[key] = page
        self.overview_tab = self.pages["overview"]
        self.health_tab = self.pages["health"]
        self.report_tab = self.pages["report"]
        self.settings_tab = self.pages["settings"]

        self._build_overview_tab()
        self._build_health_tab()
        self._build_report_tab()
        self._build_settings_tab()
        self.show_page("overview")

        footer = tk.Frame(main, bg="#F4F7FB")
        footer.pack(fill="x", padx=20, pady=(0, 12))
        tk.Label(footer, textvariable=self.status_var, bg="#F4F7FB", fg="#496174").pack(side="left")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=160)
        self.progress.pack(side="right")
        tk.Label(
            footer,
            textvariable=self.data_root_var,
            bg="#F4F7FB",
            fg="#8A9AAB",
            font=("Microsoft YaHei UI", 8),
        ).pack(side="right", padx=12)

    def show_page(self, key: str) -> None:
        for name, page in self.pages.items():
            if name == key:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
        labels = {
            "overview": "行情看板",
            "health": "数据源",
            "report": "日报",
            "settings": "合约设置",
        }
        self.page_title_var.set(labels.get(key, ""))
        for name, button in self.nav_buttons.items():
            if name == key:
                button.configure(bg="#0D7A68", fg="#FFFFFF")
            else:
                button.configure(bg="#173536", fg="#D9E9E6")

    def _build_overview_tab(self) -> None:
        metrics = tk.Frame(self.overview_tab, bg="#F4F7FB")
        metrics.pack(fill="x", pady=(0, 14))
        self.metric_vars = {
            "date": tk.StringVar(value="-"),
            "status": tk.StringVar(value="-"),
            "products": tk.StringVar(value="-"),
            "anomalies": tk.StringVar(value="-"),
        }
        for key, title in (
            ("date", "交易日"),
            ("status", "运行状态"),
            ("products", "覆盖品种"),
            ("anomalies", "异常提示"),
        ):
            card = tk.Frame(metrics, bg="#FFFFFF", highlightbackground="#E4EBF1", highlightthickness=1)
            card.pack(side="left", fill="x", expand=True, padx=(0, 10))
            tk.Label(card, text=title, bg="#FFFFFF", fg="#718096", font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=16, pady=(13, 2))
            tk.Label(card, textvariable=self.metric_vars[key], bg="#FFFFFF", fg="#132238", font=("Microsoft YaHei UI", 17, "bold")).pack(anchor="w", padx=16, pady=(0, 13))

        table_card = tk.Frame(self.overview_tab, bg="#FFFFFF", highlightbackground="#E4EBF1", highlightthickness=1)
        table_card.pack(fill="x")
        tk.Label(table_card, text="最新行情", bg="#FFFFFF", fg="#132238", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=16, pady=(13, 8))
        columns = ("code", "name", "mode", "contract", "close", "change", "volume", "oi", "date")
        self.market_tree = ttk.Treeview(table_card, columns=columns, show="headings", height=10)
        headings = {
            "code": "代码", "name": "品种", "mode": "模式", "contract": "报告合约",
            "close": "收盘/最新", "change": "涨跌", "volume": "成交量",
            "oi": "持仓量", "date": "数据日",
        }
        widths = {
            "code": 70, "name": 80, "mode": 70, "contract": 100, "close": 95,
            "change": 85, "volume": 110, "oi": 110, "date": 95,
        }
        for column in columns:
            self.market_tree.heading(column, text=headings[column])
            self.market_tree.column(column, width=widths[column], anchor="center")
        self.market_tree.tag_configure("up", foreground="#C43D3D")
        self.market_tree.tag_configure("down", foreground="#118562")
        self.market_tree.pack(fill="x", padx=12, pady=(0, 12))

        anomaly_card = tk.Frame(self.overview_tab, bg="#FFFFFF", highlightbackground="#E4EBF1", highlightthickness=1)
        anomaly_card.pack(fill="both", expand=True, pady=(14, 0))
        tk.Label(anomaly_card, text="异常与口径提示", bg="#FFFFFF", fg="#132238", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=16, pady=(13, 6))
        self.anomaly_text = tk.Text(anomaly_card, height=8, wrap="word", state="disabled", bg="#FFFFFF", fg="#496174", relief="flat", padx=12, pady=6, font=("Microsoft YaHei UI", 9))
        self.anomaly_text.pack(fill="both", expand=True, padx=8, pady=(0, 10))

    def _build_health_tab(self) -> None:
        card = tk.Frame(self.health_tab, bg="#FFFFFF", highlightbackground="#E4EBF1", highlightthickness=1)
        card.pack(fill="both", expand=True)
        tk.Label(card, text="最近一次数据源运行", bg="#FFFFFF", fg="#132238", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=16, pady=(14, 8))
        columns = ("source", "status", "count", "message", "finished")
        self.health_tree = ttk.Treeview(card, columns=columns, show="headings")
        for column, title, width in (
            ("source", "来源", 240), ("status", "状态", 80), ("count", "数量", 80),
            ("message", "信息", 420), ("finished", "完成时间", 180),
        ):
            self.health_tree.heading(column, text=title)
            self.health_tree.column(column, width=width, anchor="w")
        self.health_tree.tag_configure("success", foreground="#118562")
        self.health_tree.tag_configure("failed", foreground="#C43D3D")
        self.health_tree.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _build_report_tab(self) -> None:
        card = tk.Frame(self.report_tab, bg="#FFFFFF", highlightbackground="#E4EBF1", highlightthickness=1)
        card.pack(fill="both", expand=True)
        bar = tk.Frame(card, bg="#FFFFFF")
        bar.pack(fill="x", padx=14, pady=12)
        ttk.Button(bar, text="打开日报目录", command=self.open_report_dir, style="Secondary.TButton").pack(side="left")
        tk.Label(bar, text="OpenClaw 默认读取的精简内容", bg="#FFFFFF", fg="#718096", font=("Microsoft YaHei UI", 9)).pack(side="left", padx=10)
        self.report_text = tk.Text(card, wrap="word", state="disabled", bg="#FFFFFF", fg="#263445", relief="flat", padx=16, pady=10, font=("Microsoft YaHei UI", 10))
        self.report_text.pack(fill="both", expand=True, padx=8, pady=(0, 12))

    def _build_settings_tab(self) -> None:
        intro = tk.Frame(self.settings_tab, bg="#E6F3F0", highlightbackground="#C9E3DD", highlightthickness=1)
        intro.pack(fill="x", pady=(0, 12))
        tk.Label(
            intro,
            text="选择品种后修改模式或合约。保存设置会自动应用当前编辑，下一次采集生效。",
            bg="#E6F3F0",
            fg="#0A5A4E",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", padx=14, pady=11)

        body = tk.Frame(self.settings_tab, bg="#F4F7FB")
        body.pack(fill="both", expand=True)
        left = tk.Frame(body, bg="#FFFFFF", highlightbackground="#E4EBF1", highlightthickness=1)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="品种列表", bg="#FFFFFF", fg="#132238", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=14, pady=(12, 7))
        self.settings_tree = ttk.Treeview(left, columns=("code", "name", "exchange", "mode", "contract"), show="headings")
        for column, title, width in (
            ("code", "代码", 70), ("name", "品种", 90), ("exchange", "交易所", 80),
            ("mode", "模式", 80), ("contract", "指定合约", 110),
        ):
            self.settings_tree.heading(column, text=title)
            self.settings_tree.column(column, width=width, anchor="center")
        self.settings_tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.settings_tree.bind("<<TreeviewSelect>>", self._select_product)

        form = ttk.LabelFrame(body, text="品种设置", padding=14)
        form.pack(side="left", fill="y", padx=(14, 0))
        self.code_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.exchange_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="自动主力")
        self.contract_var = tk.StringVar()
        for row, (label, variable) in enumerate((
            ("代码", self.code_var), ("名称", self.name_var), ("交易所", self.exchange_var)
        )):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=5)
            ttk.Entry(form, textvariable=variable, width=22).grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Label(form, text="模式").grid(row=3, column=0, sticky="w", pady=5)
        mode = ttk.Combobox(form, textvariable=self.mode_var, values=("自动主力", "固定合约"), state="readonly", width=19)
        mode.grid(row=3, column=1, sticky="ew", pady=5)
        mode.bind("<<ComboboxSelected>>", self._toggle_contract_state)
        ttk.Label(form, text="指定合约").grid(row=4, column=0, sticky="w", pady=5)
        self.contract_entry = ttk.Entry(form, textvariable=self.contract_var, width=22)
        self.contract_entry.grid(row=4, column=1, sticky="ew", pady=5)
        ttk.Button(form, text="添加/更新", command=self._update_product, style="Secondary.TButton").grid(row=5, column=0, columnspan=2, sticky="ew", pady=(12, 4))
        ttk.Button(form, text="删除选中", command=self._delete_product, style="Secondary.TButton").grid(row=6, column=0, columnspan=2, sticky="ew", pady=4)
        ttk.Button(form, text="保存设置（含当前编辑）", command=self._save_settings, style="Accent.TButton").grid(row=7, column=0, columnspan=2, sticky="ew", pady=(16, 4))
        tk.Label(form, text="合约格式示例：SH2701", bg="#FFFFFF", fg="#8A9AAB", font=("Microsoft YaHei UI", 8)).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self._toggle_contract_state()

    def _toggle_contract_state(self, _event: Any = None) -> None:
        if self.mode_var.get() == "固定合约":
            self.contract_entry.configure(state="normal")
        else:
            self.contract_var.set("")
            self.contract_entry.configure(state="disabled")

    def _load_products(self) -> None:
        self.settings_products = []
        for product in self.config["products"]:
            item = dict(product)
            item["mode"] = "fixed" if item.get("contract_override") else "auto"
            self.settings_products.append(item)
        self._refresh_settings_tree()

    def _refresh_settings_tree(self) -> None:
        for row_id in self.settings_tree.get_children():
            self.settings_tree.delete(row_id)
        for product in self.settings_products:
            mode = "固定" if product.get("mode") == "fixed" else "自动"
            self.settings_tree.insert(
                "",
                "end",
                iid=product["code"],
                values=(
                    product["code"],
                    product.get("name", ""),
                    product.get("exchange", ""),
                    mode,
                    product.get("contract_override", ""),
                ),
            )

    def _select_product(self, _event: Any = None) -> None:
        selected = self.settings_tree.selection()
        if not selected:
            return
        code = selected[0]
        product = next((item for item in self.settings_products if item["code"] == code), None)
        if not product:
            return
        self.code_var.set(product["code"])
        self.name_var.set(product.get("name", ""))
        self.exchange_var.set(product.get("exchange", ""))
        self.mode_var.set("固定合约" if product.get("mode") == "fixed" else "自动主力")
        self.contract_var.set(product.get("contract_override", ""))
        self._toggle_contract_state()

    def _update_product(self) -> bool:
        try:
            product = normalize_product(
                {
                    "code": self.code_var.get(),
                    "name": self.name_var.get(),
                    "exchange": self.exchange_var.get(),
                    "mode": "fixed" if self.mode_var.get() == "固定合约" else "auto",
                    "contract_override": self.contract_var.get(),
                }
            )
        except ValueError as exc:
            messagebox.showerror("设置错误", str(exc))
            return False
        product["mode"] = "fixed" if product.get("contract_override") else "auto"
        selected = self.settings_tree.selection()
        if selected:
            old_code = selected[0]
            index = next(
                (i for i, item in enumerate(self.settings_products) if item["code"] == old_code),
                None,
            )
            if index is not None:
                self.settings_products[index] = product
            else:
                self.settings_products.append(product)
        else:
            existing = next(
                (i for i, item in enumerate(self.settings_products) if item["code"] == product["code"]),
                None,
            )
            if existing is None:
                self.settings_products.append(product)
            else:
                self.settings_products[existing] = product
        self._refresh_settings_tree()
        if self.settings_tree.exists(product["code"]):
            self.settings_tree.selection_set(product["code"])
        return True

    def _delete_product(self) -> None:
        selected = self.settings_tree.selection()
        if not selected:
            messagebox.showinfo("删除品种", "请先选择要删除的品种。")
            return
        code = selected[0]
        if not messagebox.askyesno("删除品种", f"确认删除 {code}？"):
            return
        self.settings_products = [item for item in self.settings_products if item["code"] != code]
        self._refresh_settings_tree()
        self.code_var.set("")
        self.name_var.set("")
        self.exchange_var.set("")
        self.mode_var.set("自动主力")
        self.contract_var.set("")
        self._toggle_contract_state()

    def _save_settings(self) -> None:
        if (
            self.code_var.get().strip()
            or self.contract_var.get().strip()
            or self.settings_tree.selection()
        ):
            if not self._update_product():
                return
        try:
            saved = save_products(self.config_path, self.settings_products)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        self.config = load_config(self.config_path)
        ensure_runtime_dirs(self.config)
        self.settings_products = []
        for product in saved:
            item = dict(product)
            item["mode"] = "fixed" if item.get("contract_override") else "auto"
            self.settings_products.append(item)
        self._refresh_settings_tree()
        messagebox.showinfo("保存成功", "合约设置已保存。下次采集将使用这些设置。")
        self.status_var.set("合约设置已更新")

    def _current_date(self) -> str:
        value = self.date_var.get().strip()
        try:
            return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        except ValueError as exc:
            raise ValueError("交易日必须使用 YYYY-MM-DD 格式") from exc

    def _set_text(self, widget: tk.Text, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def refresh(self) -> None:
        try:
            trading_date = self._current_date()
            self.context = build_report_context(self.db, self.config, trading_date)
        except Exception as exc:
            messagebox.showerror("刷新失败", str(exc))
            return

        products = self.context.get("products", [])
        anomalies = self.context.get("anomalies", [])
        missing_count = sum(1 for item in products if item.get("missing"))
        self.metric_vars["date"].set(trading_date)
        self.metric_vars["status"].set(str(self.context.get("status", "-")).upper())
        self.metric_vars["products"].set(f"{len(products) - missing_count}/{len(products)}")
        self.metric_vars["anomalies"].set(str(len(anomalies)))

        mode_by_code = {
            product["code"]: "固定" if product.get("contract_override") else "自动"
            for product in self.config["products"]
        }
        for row_id in self.market_tree.get_children():
            self.market_tree.delete(row_id)
        for item in products:
            if item.get("missing"):
                self.market_tree.insert(
                    "",
                    "end",
                    values=(item["code"], item["name"], mode_by_code.get(item["code"], ""), "数据暂缺"),
                    tags=("down",),
                )
                continue
            bar = item["bar"]
            close = bar.get("close")
            change = item.get("change_pct")
            tag = "up" if change is not None and float(change) > 0 else "down" if change is not None and float(change) < 0 else ""
            self.market_tree.insert(
                "",
                "end",
                values=(
                    item["code"],
                    item["name"],
                    mode_by_code.get(item["code"], ""),
                    item["contract"],
                    f"{float(close):,.2f}" if close is not None else "-",
                    f"{float(change):+.2f}%" if change is not None else "-",
                    f"{float(bar.get('volume') or 0):,.0f}",
                    f"{float(bar.get('open_interest') or 0):,.0f}",
                    bar.get("trading_date", ""),
                ),
                tags=(tag,) if tag else (),
            )
        anomaly_text = "\n".join(
            f"[{item['severity']}] {item['message']}" for item in anomalies
        ) or "未发现异常。"
        self._set_text(self.anomaly_text, anomaly_text)

        latest_run = self.db.query("SELECT * FROM collect_runs ORDER BY id DESC LIMIT 1")
        health = []
        if latest_run:
            health = self.db.query(
                "SELECT * FROM source_health WHERE run_id=? ORDER BY id",
                (latest_run[0]["id"],),
            )
        for row_id in self.health_tree.get_children():
            self.health_tree.delete(row_id)
        for row in health:
            status = str(row["status"])
            tags = ("success",) if status == "success" else ("failed",) if status in {"failed", "partial"} else ()
            self.health_tree.insert(
                "",
                "end",
                values=(
                    row["source"], row["status"], row["item_count"],
                    row["message"], row["finished_at"] or "",
                ),
                tags=tags,
            )

        report_dir = Path(self.config["reports_dir"]) / trading_date
        brief_path = report_dir / "daily-brief.md"
        self._set_text(
            self.report_text,
            brief_path.read_text(encoding="utf-8") if brief_path.exists() else "当天还没有生成日报。",
        )
        self.status_var.set(
            f"状态：{self.context.get('status', '-')} ｜ 数据截至：{self.context.get('effective_market_date', '-')}"
        )

    def open_data_dir(self) -> None:
        os.startfile(self.data_root)

    def open_report_dir(self) -> None:
        try:
            report_dir = Path(self.config["reports_dir"]) / self._current_date()
        except ValueError:
            report_dir = Path(self.config["reports_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(report_dir)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.run_button.configure(state=state)
        self.refresh_button.configure(state=state)
        if busy:
            self.progress.start(12)
            self.status_var.set("正在采集并生成日报...")
        else:
            self.progress.stop()

    def run_now(self) -> None:
        if self.busy:
            return
        try:
            trading_date = self._current_date()
        except ValueError as exc:
            messagebox.showerror("日期错误", str(exc))
            return
        self._set_busy(True)

        def worker() -> None:
            try:
                collect_result = Collector(self.config, self.db).collect(trading_date)
                report_result = generate_daily_report(self.db, self.config, trading_date)
                self.root.after(
                    0,
                    lambda: self._run_finished(collect_result.as_dict(), report_result, None),
                )
            except Exception as exc:
                detail = traceback.format_exc()
                self.root.after(0, lambda: self._run_finished({}, {}, (exc, detail)))

        threading.Thread(target=worker, daemon=True).start()

    def _run_finished(
        self,
        collect_result: dict[str, Any],
        report_result: dict[str, Any],
        error: tuple[Exception, str] | None,
    ) -> None:
        self._set_busy(False)
        if error:
            exc, detail = error
            self.status_var.set("运行失败")
            messagebox.showerror("运行失败", f"{exc}\n\n{detail[-2000:]}")
            return
        self.status_var.set(
            f"采集：{collect_result.get('status')} ｜ 日报：{report_result.get('status')}"
        )
        self.refresh()


def main() -> None:
    root = tk.Tk()
    FuturesDesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
