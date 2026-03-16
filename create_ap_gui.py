#!/usr/bin/env python3

import json
import os
import queue
import re
import shutil
import socket
import signal
import subprocess
import tempfile
import threading
import tkinter as tk
from pathlib import Path
import re as regex
from tkinter import messagebox, ttk


class CreateApGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("create_ap GUI")
        self.root.geometry("860x620")

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.clients_window: tk.Toplevel | None = None
        self.clients_tree: ttk.Treeview | None = None
        self.qr_window: tk.Toplevel | None = None
        self.qr_image: tk.PhotoImage | None = None
        self.auto_retry_no_virt_attempted = False
        self.instance_check_done = False
        self.external_running = False
        self.external_running_ifaces: list[str] = []
        self.running_ap_settings: dict[str, object] | None = None
        self.instance_status = tk.StringVar(value="Instance check pending")
        self.last_applied_settings: dict[str, object] = {}
        self.profile_dir = Path.home() / ".config" / "create_ap" / "profiles"
        self.legacy_profile_path = Path.home() / ".config" / "create_ap" / "gui_profile.json"
        self.profile_name = tk.StringVar(value="default")
        self.profile_listbox: tk.Listbox | None = None

        self.wifi_iface = tk.StringVar(value="wlan0")
        self.internet_iface = tk.StringVar(value="eth0")
        self.share_method = tk.StringVar(value="nat")
        self.ssid = tk.StringVar(value="MyAccessPoint")
        self.passphrase = tk.StringVar(value="12345678")
        self.channel = tk.StringVar(value="default")
        self.wpa_version = tk.StringVar(value="2")
        self.country = tk.StringVar(value="")
        self.freq_band = tk.StringVar(value="2.4")
        self.driver = tk.StringVar(value="nl80211")

        self.hidden = tk.BooleanVar(value=False)
        self.isolate_clients = tk.BooleanVar(value=False)
        self.no_virt = tk.BooleanVar(value=False)
        self.show_passphrase = tk.BooleanVar(value=False)

        self.create_ap_bin = self._resolve_create_ap_binary()
        self._apply_system_defaults()
        self._migrate_legacy_profile_if_needed()

        self._build_ui()
        self._refresh_interfaces()
        self._bind_change_tracking()
        self._mark_current_settings_as_applied()
        self._set_action_buttons_for_check(pending=True)
        self.check_running_instances()
        self._poll_log_queue()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _resolve_create_ap_binary(self) -> str | None:
        local_script = Path(__file__).with_name("create_ap")
        if local_script.is_file() and os.access(local_script, os.X_OK):
            return str(local_script)
        if shutil.which("create_ap"):
            return "create_ap"
        return None

    def _list_interfaces(self) -> tuple[list[str], list[str]]:
        net_dir = Path("/sys/class/net")
        if not net_dir.is_dir():
            return [], []

        all_ifaces = sorted([p.name for p in net_dir.iterdir() if p.is_dir()])
        wifi_ifaces = [
            name for name in all_ifaces if (net_dir / name / "wireless").exists() or name.startswith("wl")
        ]
        return wifi_ifaces, all_ifaces

    def _get_default_route_iface(self) -> str | None:
        if shutil.which("ip") is None:
            return None
        completed = subprocess.run(["ip", "-o", "route", "show", "default"], capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            return None
        for line in completed.stdout.splitlines():
            match = regex.search(r"\bdev\s+(\S+)", line)
            if match:
                return match.group(1)
        return None

    def _get_connected_wifi_iface(self, wifi_ifaces: list[str]) -> str | None:
        if not wifi_ifaces or shutil.which("iw") is None:
            return None
        for iface in wifi_ifaces:
            completed = subprocess.run(["iw", "dev", iface, "link"], capture_output=True, text=True, check=False)
            if completed.returncode == 0 and "Connected to" in completed.stdout:
                return iface
        return None

    def _driver_from_configs(self) -> str | None:
        candidates = [Path("/etc/create_ap.conf"), Path(__file__).with_name("create_ap.conf")]
        for conf in candidates:
            if not conf.is_file():
                continue
            try:
                text = conf.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith("DRIVER="):
                    value = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                    if value:
                        return value
        return None

    def _apply_system_defaults(self) -> None:
        wifi_ifaces, all_ifaces = self._list_interfaces()

        wifi_default = self._get_connected_wifi_iface(wifi_ifaces) or (wifi_ifaces[0] if wifi_ifaces else None)
        internet_default = self._get_default_route_iface()
        if internet_default is None:
            for iface in all_ifaces:
                if iface != "lo":
                    internet_default = iface
                    break

        driver_default = self._driver_from_configs()
        if driver_default is None:
            driver_default = "nl80211" if shutil.which("iw") else self.driver.get()

        if wifi_default:
            self.wifi_iface.set(wifi_default)
        if internet_default:
            self.internet_iface.set(internet_default)
        if driver_default:
            self.driver.set(driver_default)

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        cfg = ttk.LabelFrame(main, text="Access Point Settings", padding=10)
        cfg.pack(fill=tk.X)

        row = 0
        ttk.Label(cfg, text="WiFi interface").grid(row=row, column=0, sticky=tk.W, padx=4, pady=4)
        self.wifi_combo = ttk.Combobox(cfg, textvariable=self.wifi_iface, state="readonly")
        self.wifi_combo.grid(row=row, column=1, sticky=tk.EW, padx=4, pady=4)
        self.wifi_combo.bind("<<ComboboxSelected>>", lambda _: self._load_selected_running_settings())

        ttk.Label(cfg, text="Internet interface").grid(row=row, column=2, sticky=tk.W, padx=4, pady=4)
        self.internet_combo = ttk.Combobox(cfg, textvariable=self.internet_iface, state="readonly")
        self.internet_combo.grid(row=row, column=3, sticky=tk.EW, padx=4, pady=4)

        row += 1
        ttk.Label(cfg, text="Share method").grid(row=row, column=0, sticky=tk.W, padx=4, pady=4)
        share_combo = ttk.Combobox(
            cfg,
            textvariable=self.share_method,
            values=["nat", "bridge", "none"],
            state="readonly",
        )
        share_combo.grid(row=row, column=1, sticky=tk.EW, padx=4, pady=4)
        share_combo.bind("<<ComboboxSelected>>", lambda _: self._toggle_internet_iface_state())

        ttk.Label(cfg, text="Channel").grid(row=row, column=2, sticky=tk.W, padx=4, pady=4)
        channel_combo = ttk.Combobox(
            cfg,
            textvariable=self.channel,
            values=["default"] + [str(c) for c in range(1, 14)],
            state="readonly",
        )
        channel_combo.grid(row=row, column=3, sticky=tk.EW, padx=4, pady=4)

        row += 1
        ttk.Label(cfg, text="SSID").grid(row=row, column=0, sticky=tk.W, padx=4, pady=4)
        ttk.Entry(cfg, textvariable=self.ssid).grid(row=row, column=1, sticky=tk.EW, padx=4, pady=4)

        ttk.Label(cfg, text="Passphrase").grid(row=row, column=2, sticky=tk.W, padx=4, pady=4)
        self.passphrase_entry = ttk.Entry(cfg, textvariable=self.passphrase, show="*")
        self.passphrase_entry.grid(row=row, column=3, sticky=tk.EW, padx=4, pady=4)

        row += 1
        ttk.Label(cfg, text="WPA version").grid(row=row, column=0, sticky=tk.W, padx=4, pady=4)
        wpa_combo = ttk.Combobox(cfg, textvariable=self.wpa_version, values=["1", "2", "1+2"], state="readonly")
        wpa_combo.grid(row=row, column=1, sticky=tk.EW, padx=4, pady=4)

        ttk.Label(cfg, text="Driver").grid(row=row, column=2, sticky=tk.W, padx=4, pady=4)
        ttk.Entry(cfg, textvariable=self.driver).grid(row=row, column=3, sticky=tk.EW, padx=4, pady=4)

        row += 1
        ttk.Label(cfg, text="Country").grid(row=row, column=0, sticky=tk.W, padx=4, pady=4)
        ttk.Entry(cfg, textvariable=self.country).grid(row=row, column=1, sticky=tk.EW, padx=4, pady=4)
        ttk.Label(
            cfg,
            text="2-letter regulatory code (e.g. US, DE). Does not change SSID or password.",
        ).grid(row=row, column=2, columnspan=2, sticky=tk.W, padx=4, pady=4)

        ttk.Label(cfg, text="Freq band").grid(row=row, column=2, sticky=tk.W, padx=4, pady=4)
        freq_combo = ttk.Combobox(cfg, textvariable=self.freq_band, values=["2.4", "5"], state="readonly")
        freq_combo.grid(row=row, column=3, sticky=tk.EW, padx=4, pady=4)

        row += 1
        ttk.Checkbutton(cfg, text="Hidden SSID", variable=self.hidden).grid(row=row, column=0, sticky=tk.W, padx=4, pady=4)
        ttk.Checkbutton(cfg, text="Isolate clients", variable=self.isolate_clients).grid(row=row, column=1, sticky=tk.W, padx=4, pady=4)
        ttk.Checkbutton(cfg, text="No virtual interface", variable=self.no_virt).grid(row=row, column=2, sticky=tk.W, padx=4, pady=4)
        ttk.Checkbutton(
            cfg,
            text="Show passphrase",
            variable=self.show_passphrase,
            command=self._toggle_passphrase_visibility,
        ).grid(row=row, column=3, sticky=tk.W, padx=4, pady=4)

        for col in range(4):
            cfg.columnconfigure(col, weight=1)

        buttons = ttk.Frame(main, padding=(0, 10, 0, 10))
        buttons.pack(fill=tk.X)

        row1 = ttk.Frame(buttons)
        row1.pack(fill=tk.X, pady=(0, 6))
        row2 = ttk.Frame(buttons)
        row2.pack(fill=tk.X)

        self.start_button = ttk.Button(row1, text="Start AP", command=self.start_ap)
        self.start_button.pack(side=tk.LEFT, padx=(0, 8))

        self.stop_button = ttk.Button(row1, text="Stop AP", command=self.stop_ap)
        self.stop_button.pack(side=tk.LEFT, padx=(0, 8))

        self.apply_button = ttk.Button(row1, text="Apply changes", command=self.apply_changes)
        self.apply_button.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(row1, text="Preflight", command=lambda: self.preflight_check(show_success=True)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(row1, text="Check instances", command=self.check_running_instances).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(row1, text="Refresh interfaces", command=self._refresh_interfaces).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(row1, text="Show running", command=self.show_running).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(row1, text="Clear log", command=self.clear_log).pack(side=tk.RIGHT)

        self.show_clients_button = ttk.Button(row2, text="Show clients", command=self.show_clients)
        self.show_clients_button.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(row2, text="Show QR", command=self.show_qr_code).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(row2, text="Load Running AP", command=self.load_running_ap).pack(side=tk.LEFT, padx=(0, 8))

        profiles = ttk.LabelFrame(main, text="Saved Profiles", padding=8)
        profiles.pack(fill=tk.X, pady=(0, 8))

        profile_controls = ttk.Frame(profiles)
        profile_controls.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(profile_controls, text="Profile name").pack(side=tk.LEFT)
        ttk.Entry(profile_controls, textvariable=self.profile_name, width=22).pack(side=tk.LEFT, padx=(8, 10))
        ttk.Button(profile_controls, text="Save/Update", command=self.save_profile).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(profile_controls, text="Load", command=self.load_profile).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(profile_controls, text="Delete", command=self.clear_profile).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(profile_controls, text="Refresh", command=self._refresh_profile_list).pack(side=tk.LEFT)

        self.profile_listbox = tk.Listbox(profiles, height=4, exportselection=False)
        self.profile_listbox.pack(fill=tk.X)
        self.profile_listbox.bind("<<ListboxSelect>>", self._on_profile_selected)
        self._refresh_profile_list()

        status = ttk.Frame(main)
        status.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(status, textvariable=self.instance_status).pack(side=tk.LEFT)

        log_frame = ttk.LabelFrame(main, text="Output", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log = tk.Text(log_frame, wrap=tk.WORD, state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True)

        self._toggle_internet_iface_state()

    def _sanitize_profile_name(self, raw_name: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name.strip())
        cleaned = cleaned.strip("._-")
        return cleaned or "default"

    def _profile_path(self, profile_name: str) -> Path:
        safe = self._sanitize_profile_name(profile_name)
        return self.profile_dir / f"{safe}.json"

    def _selected_profile_path(self) -> Path:
        selected_name = self._sanitize_profile_name(self.profile_name.get())
        self.profile_name.set(selected_name)
        return self._profile_path(selected_name)

    def _list_profile_names(self) -> list[str]:
        if not self.profile_dir.is_dir():
            return []
        names: list[str] = []
        for item in sorted(self.profile_dir.glob("*.json")):
            names.append(item.stem)
        return names

    def _refresh_profile_list(self) -> None:
        if self.profile_listbox is None:
            return

        current = self._sanitize_profile_name(self.profile_name.get())
        names = self._list_profile_names()
        self.profile_listbox.delete(0, tk.END)
        for name in names:
            self.profile_listbox.insert(tk.END, name)

        if current in names:
            idx = names.index(current)
            self.profile_listbox.selection_set(idx)
            self.profile_listbox.activate(idx)
        elif names:
            self.profile_name.set(names[0])
            self.profile_listbox.selection_set(0)
            self.profile_listbox.activate(0)

    def _on_profile_selected(self, _event: object) -> None:
        if self.profile_listbox is None:
            return
        selected = self.profile_listbox.curselection()
        if not selected:
            return
        name = self.profile_listbox.get(selected[0])
        self.profile_name.set(name)

    def _migrate_legacy_profile_if_needed(self) -> None:
        if not self.legacy_profile_path.is_file():
            return
        try:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            default_path = self._profile_path("default")
            if not default_path.exists():
                shutil.copy2(self.legacy_profile_path, default_path)
        except OSError:
            return

    def _toggle_internet_iface_state(self) -> None:
        if self.share_method.get() == "none":
            self.internet_combo.configure(state="disabled")
        else:
            self.internet_combo.configure(state="readonly")

    def _toggle_passphrase_visibility(self) -> None:
        self.passphrase_entry.configure(show="" if self.show_passphrase.get() else "*")

    def _settings_snapshot(self) -> dict[str, object]:
        return {
            "wifi_iface": self.wifi_iface.get(),
            "internet_iface": self.internet_iface.get(),
            "share_method": self.share_method.get(),
            "ssid": self.ssid.get(),
            "passphrase": self.passphrase.get(),
            "channel": self.channel.get(),
            "wpa_version": self.wpa_version.get(),
            "country": self.country.get(),
            "freq_band": self.freq_band.get(),
            "driver": self.driver.get(),
            "hidden": self.hidden.get(),
            "isolate_clients": self.isolate_clients.get(),
            "no_virt": self.no_virt.get(),
        }

    def _mark_current_settings_as_applied(self) -> None:
        self.last_applied_settings = self._settings_snapshot()

    def _has_settings_changes(self) -> bool:
        return self._settings_snapshot() != self.last_applied_settings

    def _on_settings_changed(self, *_args: object) -> None:
        if self.instance_check_done:
            self._set_running_ui(False)

    def _bind_change_tracking(self) -> None:
        tracked_vars = [
            self.wifi_iface,
            self.internet_iface,
            self.share_method,
            self.ssid,
            self.passphrase,
            self.channel,
            self.wpa_version,
            self.country,
            self.freq_band,
            self.driver,
            self.hidden,
            self.isolate_clients,
            self.no_virt,
        ]
        for variable in tracked_vars:
            variable.trace_add("write", self._on_settings_changed)

    def _refresh_interfaces(self) -> None:
        wifi_ifaces, all_ifaces = self._list_interfaces()

        self.wifi_combo["values"] = wifi_ifaces or all_ifaces
        self.internet_combo["values"] = all_ifaces

        if self.wifi_iface.get() not in self.wifi_combo["values"] and self.wifi_combo["values"]:
            self.wifi_iface.set(self.wifi_combo["values"][0])

        if self.internet_iface.get() not in self.internet_combo["values"] and self.internet_combo["values"]:
            for candidate in self.internet_combo["values"]:
                if candidate != self.wifi_iface.get():
                    self.internet_iface.set(candidate)
                    break

    def _auth_prefix(self) -> list[str]:
        if os.geteuid() == 0:
            return []
        if shutil.which("pkexec"):
            return ["pkexec"]
        if shutil.which("sudo"):
            return ["sudo"]
        return []

    def _required_tools(self) -> list[str]:
        tools = ["hostapd", "iw", "ip"]
        if self.share_method.get() in {"nat", "none"}:
            tools.extend(["dnsmasq", "iptables"])
        return tools

    def preflight_check(self, show_success: bool = False) -> bool:
        missing_tools = [name for name in self._required_tools() if shutil.which(name) is None]
        issues: list[str] = []

        if not self.create_ap_bin:
            issues.append("create_ap binary was not found")

        wifi = self.wifi_iface.get().strip()
        if not wifi:
            issues.append("WiFi interface is not selected")
        elif not (Path("/sys/class/net") / wifi).exists():
            issues.append(f"WiFi interface '{wifi}' does not exist")

        if self.share_method.get() != "none":
            internet = self.internet_iface.get().strip()
            if not internet:
                issues.append("Internet interface is not selected")
            elif not (Path("/sys/class/net") / internet).exists():
                issues.append(f"Internet interface '{internet}' does not exist")

        if missing_tools:
            issues.append("Missing dependencies: " + ", ".join(missing_tools))

        if issues:
            message = "Preflight checks failed:\n\n- " + "\n- ".join(issues)
            self.log_queue.put("\n[Preflight failed]\n" + message + "\n")
            messagebox.showerror("create_ap", message)
            return False

        self.log_queue.put("\n[Preflight passed]\n")
        if show_success:
            messagebox.showinfo("create_ap", "Preflight checks passed")
        return True

    def _build_start_command(self, force_no_virt: bool = False) -> list[str]:
        if not self.create_ap_bin:
            raise RuntimeError("create_ap binary not found. Make it executable here or install it in PATH.")

        wifi = self.wifi_iface.get().strip()
        internet = self.internet_iface.get().strip()
        ssid = self.ssid.get().strip()
        passphrase = self.passphrase.get().strip()

        if not wifi:
            raise ValueError("WiFi interface is required")
        if not ssid:
            raise ValueError("SSID is required")
        if passphrase and len(passphrase) < 8:
            raise ValueError("Passphrase must be at least 8 characters (or leave empty for open network)")

        cmd: list[str] = self._auth_prefix() + [self.create_ap_bin]

        if self.share_method.get() == "none":
            cmd.append("-n")
        elif self.share_method.get() in {"nat", "bridge"}:
            cmd.extend(["-m", self.share_method.get()])

        if self.channel.get() and self.channel.get() != "default":
            cmd.extend(["-c", self.channel.get()])

        if passphrase and self.wpa_version.get():
            cmd.extend(["-w", self.wpa_version.get()])

        if self.hidden.get():
            cmd.append("--hidden")
        if self.isolate_clients.get():
            cmd.append("--isolate-clients")
        if self.no_virt.get() or force_no_virt:
            cmd.append("--no-virt")

        if self.country.get().strip():
            cmd.extend(["--country", self.country.get().strip().upper()])

        if self.freq_band.get().strip() in {"2.4", "5"}:
            cmd.extend(["--freq-band", self.freq_band.get().strip()])

        if self.driver.get().strip():
            cmd.extend(["--driver", self.driver.get().strip()])

        if self.share_method.get() == "none":
            cmd.extend([wifi, ssid])
        else:
            if not internet:
                raise ValueError("Internet interface is required for NAT/bridge mode")
            cmd.extend([wifi, internet, ssid])

        if passphrase:
            cmd.append(passphrase)

        return cmd

    def _profile_data(self) -> dict[str, object]:
        return self._settings_snapshot()

    def _apply_profile(self, profile: dict[str, object]) -> None:
        self.wifi_iface.set(str(profile.get("wifi_iface", self.wifi_iface.get())))
        self.internet_iface.set(str(profile.get("internet_iface", self.internet_iface.get())))
        self.share_method.set(str(profile.get("share_method", self.share_method.get())))
        self.ssid.set(str(profile.get("ssid", self.ssid.get())))
        self.passphrase.set(str(profile.get("passphrase", self.passphrase.get())))
        self.channel.set(str(profile.get("channel", self.channel.get())))
        self.wpa_version.set(str(profile.get("wpa_version", self.wpa_version.get())))
        self.country.set(str(profile.get("country", self.country.get())))
        self.freq_band.set(str(profile.get("freq_band", self.freq_band.get())))
        self.driver.set(str(profile.get("driver", self.driver.get())))
        self.hidden.set(bool(profile.get("hidden", self.hidden.get())))
        self.isolate_clients.set(bool(profile.get("isolate_clients", self.isolate_clients.get())))
        self.no_virt.set(bool(profile.get("no_virt", self.no_virt.get())))
        self._toggle_internet_iface_state()

    def _running_confdirs(self) -> list[Path]:
        confdirs: list[Path] = []
        for path in Path("/tmp").glob("create_ap.*"):
            try:
                pid_file = path / "pid"
                wifi_file = path / "wifi_iface"
                if not (pid_file.is_file() and wifi_file.is_file()):
                    continue
                pid = pid_file.read_text(encoding="utf-8").strip()
            except (OSError, PermissionError):
                continue
            if pid.isdigit() and Path(f"/proc/{pid}").exists():
                confdirs.append(path)
        return confdirs

    def _find_running_confdir(self, wifi_iface: str) -> Path | None:
        for confdir in self._running_confdirs():
            if confdir.name.startswith(f"create_ap.{wifi_iface}.conf."):
                return confdir
            try:
                current_iface = (confdir / "wifi_iface").read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if current_iface == wifi_iface:
                return confdir
        return None

    def _parse_cmdline_settings(self, pid: str) -> dict[str, object]:
        settings: dict[str, object] = {}
        try:
            raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            return settings

        args = [part.decode("utf-8", errors="ignore") for part in raw.split(b"\0") if part]
        if not args:
            return settings

        if len(args) >= 2 and Path(args[0]).name in {"bash", "sh", "dash"} and (Path(args[1]).name == "create_ap" or args[1].endswith("/create_ap")):
            filtered = args[2:]
        elif Path(args[0]).name == "create_ap" or args[0].endswith("/create_ap"):
            filtered = args[1:]
        else:
            filtered = args[1:]

        share_method = "nat"
        positional: list[str] = []
        index = 0
        while index < len(filtered):
            arg = filtered[index]
            if arg == "-n":
                share_method = "none"
            elif arg == "-m" and index + 1 < len(filtered):
                share_method = filtered[index + 1]
                index += 1
            elif arg == "-c" and index + 1 < len(filtered):
                settings["channel"] = filtered[index + 1]
                index += 1
            elif arg == "-w" and index + 1 < len(filtered):
                settings["wpa_version"] = filtered[index + 1]
                index += 1
            elif arg == "--freq-band" and index + 1 < len(filtered):
                settings["freq_band"] = filtered[index + 1]
                index += 1
            elif arg == "--driver" and index + 1 < len(filtered):
                settings["driver"] = filtered[index + 1]
                index += 1
            elif arg == "--country" and index + 1 < len(filtered):
                settings["country"] = filtered[index + 1]
                index += 1
            elif arg == "--hidden":
                settings["hidden"] = True
            elif arg == "--isolate-clients":
                settings["isolate_clients"] = True
            elif arg == "--no-virt":
                settings["no_virt"] = True
            elif arg.startswith("-"):
                if arg in {"--hostapd-debug", "--mac-filter-accept", "--ht_capab", "--vht_capab", "--mac", "--dhcp-dns", "-g", "-e", "--pidfile", "--logfile", "--stop", "--list-clients", "--mkconfig", "--config"} and index + 1 < len(filtered):
                    index += 1
            else:
                positional.append(arg)
            index += 1

        settings["share_method"] = share_method
        if share_method == "none":
            if len(positional) >= 1:
                settings["wifi_iface"] = positional[0]
            if len(positional) >= 2:
                settings["ssid"] = positional[1]
            if len(positional) >= 3:
                settings["passphrase"] = positional[2]
        else:
            if len(positional) >= 1:
                settings["wifi_iface"] = positional[0]
            if len(positional) >= 2:
                settings["internet_iface"] = positional[1]
            if len(positional) >= 3:
                settings["ssid"] = positional[2]
            if len(positional) >= 4:
                settings["passphrase"] = positional[3]

        return settings

    def _parse_hostapd_settings(self, confdir: Path) -> dict[str, object]:
        settings: dict[str, object] = {}
        hostapd_conf = confdir / "hostapd.conf"
        if not hostapd_conf.is_file():
            return settings
        try:
            lines = hostapd_conf.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return settings

        data: dict[str, str] = {}
        for line in lines:
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()

        if "ssid" in data:
            settings["ssid"] = data["ssid"]
        if "interface" in data:
            settings["wifi_iface"] = data["interface"]
        if "driver" in data:
            settings["driver"] = data["driver"]
        if "channel" in data:
            settings["channel"] = data["channel"]
        if data.get("ignore_broadcast_ssid") == "1":
            settings["hidden"] = True
        if data.get("ap_isolate") == "1":
            settings["isolate_clients"] = True
        if "country_code" in data:
            settings["country"] = data["country_code"]
        if "hw_mode" in data:
            settings["freq_band"] = "5" if data["hw_mode"] == "a" else "2.4"
        if data.get("bridge"):
            settings["share_method"] = "bridge"
        if "wpa_passphrase" in data:
            settings["passphrase"] = data["wpa_passphrase"]
        if "wpa" in data:
            settings["wpa_version"] = "1+2" if data["wpa"] == "3" else data["wpa"]
        return settings

    def _read_running_ap_settings(self, wifi_iface: str) -> dict[str, object] | None:
        confdir = self._find_running_confdir(wifi_iface)
        if confdir is None:
            return None

        settings: dict[str, object] = {
            "hidden": False,
            "isolate_clients": False,
            "no_virt": False,
        }
        try:
            pid = (confdir / "pid").read_text(encoding="utf-8").strip()
        except OSError:
            pid = ""

        settings.update(self._parse_hostapd_settings(confdir))
        if pid:
            settings.update(self._parse_cmdline_settings(pid))

        if settings.get("share_method") != "bridge" and (confdir / "dnsmasq.conf").is_file() and "share_method" not in settings:
            settings["share_method"] = "nat"

        settings.setdefault("wifi_iface", wifi_iface)
        return settings

    def _apply_running_ap_settings(self, wifi_iface: str) -> None:
        settings = self._read_running_ap_settings(wifi_iface)
        if not settings:
            self.running_ap_settings = None
            return

        self.running_ap_settings = settings
        self._apply_profile(settings)
        self._mark_current_settings_as_applied()

    def _load_selected_running_settings(self) -> None:
        wifi_iface = self.wifi_iface.get().strip()
        if wifi_iface and (wifi_iface in self.external_running_ifaces or self._find_running_confdir(wifi_iface) is not None):
            self._apply_running_ap_settings(wifi_iface)

    def load_running_ap(self) -> None:
        """Explicitly load settings from any currently running AP into the form."""
        confdirs = self._running_confdirs()
        if not confdirs:
            messagebox.showinfo("create_ap", "No running create_ap instance found.\nStart a hotspot first, then click Load Running AP.")
            return

        # Prefer the interface already selected in the form
        wifi_iface = self.wifi_iface.get().strip()
        confdir = self._find_running_confdir(wifi_iface) if wifi_iface else None
        if confdir is None:
            # Fall back to first running interface
            first = confdirs[0]
            iface_file = first / "wifi_iface"
            wifi_iface = iface_file.read_text(encoding="utf-8").strip() if iface_file.is_file() else ""

        if not wifi_iface:
            messagebox.showerror("create_ap", "Could not determine the running AP interface.")
            return

        self._apply_running_ap_settings(wifi_iface)

        if self.running_ap_settings:
            ssid = self.running_ap_settings.get("ssid", "unknown")
            self.instance_status.set(f"Loaded running AP settings — SSID: {ssid} (iface: {wifi_iface})")
            self.log_queue.put(f"\n[Load Running AP] Loaded settings from running AP on {wifi_iface} (SSID: {ssid})\n")
            messagebox.showinfo("create_ap", f"Loaded settings from running AP:\n  Interface: {wifi_iface}\n  SSID: {ssid}")
        else:
            messagebox.showwarning("create_ap", f"Found a running AP on {wifi_iface} but could not read its settings.\nThe AP may have been started externally or the config files are not accessible.")

    def save_profile(self) -> None:
        path = self._selected_profile_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self._profile_data(), indent=2), encoding="utf-8")
            self.log_queue.put(f"\n[Profile saved] {path}\n")
            self._refresh_profile_list()
            messagebox.showinfo("create_ap", f"Profile saved:\n{path}")
        except OSError as exc:
            messagebox.showerror("create_ap", f"Failed to save profile: {exc}")

    def load_profile(self) -> None:
        path = self._selected_profile_path()
        if not path.is_file():
            messagebox.showerror("create_ap", f"Profile not found:\n{path}")
            return

        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("create_ap", f"Failed to load profile: {exc}")
            return

        if not isinstance(profile, dict):
            messagebox.showerror("create_ap", "Invalid profile format")
            return

        self._apply_profile(profile)
        self.log_queue.put(f"\n[Profile loaded] {path}\n")
        messagebox.showinfo("create_ap", "Profile loaded")

    def clear_profile(self) -> None:
        path = self._selected_profile_path()
        if not path.is_file():
            messagebox.showinfo("create_ap", "No saved profile to clear")
            return

        confirmed = messagebox.askyesno(
            "create_ap",
            f"Delete saved profile '{path.stem}'?\n\n{path}",
            icon="warning",
        )
        if not confirmed:
            return

        try:
            path.unlink()
            self.log_queue.put(f"\n[Profile deleted] {path}\n")
            self._refresh_profile_list()
            messagebox.showinfo("create_ap", "Saved profile deleted")
        except OSError as exc:
            messagebox.showerror("create_ap", f"Failed to clear profile: {exc}")

    def _append_log(self, text: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text)
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _poll_log_queue(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(line)

        self.root.after(120, self._poll_log_queue)

    def _set_running_ui(self, running: bool) -> None:
        if not self.instance_check_done:
            self._set_action_buttons_for_check(pending=True)
            return

        self.start_button.configure(state="disabled" if running else ("disabled" if self.external_running else "normal"))
        self.stop_button.configure(state="normal" if (running or self.external_running) else "disabled")
        self.apply_button.configure(state="normal" if self._has_settings_changes() else "disabled")
        self.show_clients_button.configure(state="normal")

    def _set_action_buttons_for_check(self, pending: bool) -> None:
        state = "disabled" if pending else "normal"
        self.start_button.configure(state=state)
        self.stop_button.configure(state=state)
        self.apply_button.configure(state="disabled")
        self.show_clients_button.configure(state=state)

    def _parse_running_instances(self, output: str) -> list[str]:
        ifaces: list[str] = []
        for line in output.splitlines():
            text = line.strip()
            if not text or text.startswith("List of running"):
                continue
            if re.match(r"^[0-9]+\s+", text):
                match = re.match(r"^[0-9]+\s+\S+(?:\s+\(([^)]+)\))?$", text)
                if not match:
                    continue
                if match.group(1):
                    iface = match.group(1).strip()
                else:
                    parts = text.split()
                    if len(parts) < 2:
                        continue
                    iface = parts[1]
                if iface and iface not in ifaces:
                    ifaces.append(iface)
        return ifaces

    def _effective_running_iface(self) -> str:
        wifi = self.wifi_iface.get().strip()
        if not self.external_running:
            return wifi
        if wifi in self.external_running_ifaces:
            return wifi
        if len(self.external_running_ifaces) == 1:
            selected = self.external_running_ifaces[0]
            self.wifi_iface.set(selected)
            return selected
        return wifi

    def _apply_instance_check_result(self, returncode: int, output: str, error: str) -> None:
        if returncode != 0:
            self.instance_check_done = False
            self.external_running = False
            self.external_running_ifaces = []
            self.instance_status.set("Instance check failed. Click 'Check instances' and review log.")
            self._set_action_buttons_for_check(pending=True)
            if error:
                self.log_queue.put(error)
            return

        running_ifaces = self._parse_running_instances(output)
        self.instance_check_done = True
        self.external_running_ifaces = running_ifaces
        self.external_running = len(running_ifaces) > 0

        if self.external_running:
            self.instance_status.set("Detected running AP instance(s): " + ", ".join(running_ifaces))
            if self.wifi_iface.get().strip() not in running_ifaces:
                self.wifi_iface.set(running_ifaces[0])
            self._apply_running_ap_settings(self.wifi_iface.get().strip())
        else:
            self.instance_status.set("No running create_ap instance detected")
            self.running_ap_settings = None

        self._mark_current_settings_as_applied()
        self._set_running_ui(False)

    def _check_running_instances_worker(self) -> None:
        if not self.create_ap_bin:
            self.root.after(
                0,
                lambda: (
                    self.instance_status.set("create_ap binary not found"),
                    self._set_action_buttons_for_check(pending=True),
                ),
            )
            return

        cmd = [self.create_ap_bin, "--list-running"]
        self.log_queue.put("\n$ " + " ".join(cmd) + "\n")
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        out = completed.stdout or ""
        err = completed.stderr or ""
        if out:
            self.log_queue.put(out)
        if err:
            self.log_queue.put(err)
        self.log_queue.put(f"[exit code {completed.returncode}]\n")
        self.root.after(0, lambda: self._apply_instance_check_result(completed.returncode, out, err))

    def check_running_instances(self) -> None:
        self.instance_check_done = False
        self.external_running = False
        self.external_running_ifaces = []
        self.instance_status.set("Checking running instances...")
        self._set_action_buttons_for_check(pending=True)
        threading.Thread(target=self._check_running_instances_worker, daemon=True).start()

    def _should_offer_no_virt_retry(self, output: str) -> bool:
        markers = [
            "Maybe your WiFi adapter does not fully support virtual interfaces",
            "ERROR: Your adapter can not transmit to channel",
            "Creating a virtual WiFi interface",
        ]
        return any(marker in output for marker in markers)

    def _handle_process_exit(self, rc: int, output: str) -> None:
        self._set_running_ui(False)
        if rc == 0:
            self.auto_retry_no_virt_attempted = False
            return

        if self.no_virt.get() or self.auto_retry_no_virt_attempted:
            return

        if self._should_offer_no_virt_retry(output):
            retry = messagebox.askyesno(
                "create_ap",
                "The hotspot failed and your adapter may not support virtual AP mode reliably.\n\nRetry with --no-virt now?",
            )
            if retry:
                self.auto_retry_no_virt_attempted = True
                self.start_ap(force_no_virt=True, skip_preflight=True)

    def _stream_process_output(self, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        output_lines: list[str] = []
        for line in proc.stdout:
            output_lines.append(line)
            self.log_queue.put(line)

        rc = proc.wait()
        self.process = None
        self.log_queue.put(f"\n[create_ap exited with code {rc}]\n")
        output = "".join(output_lines)
        self.root.after(0, lambda: self._handle_process_exit(rc, output))

    def start_ap(self, force_no_virt: bool = False, skip_preflight: bool = False) -> None:
        if not self.instance_check_done:
            messagebox.showwarning("create_ap", "Run instance check first (click 'Check instances').")
            return

        if self.process and self.process.poll() is None:
            restart = messagebox.askyesno(
                "create_ap",
                "create_ap is already running. Restart AP now to apply current settings?",
            )
            if restart:
                self.apply_changes()
            return

        if self.external_running and not force_no_virt:
            messagebox.showwarning(
                "create_ap",
                "Another create_ap instance is already running. Stop it first or use Apply changes.",
            )
            return

        if not skip_preflight and not self.preflight_check(show_success=False):
            return

        if not force_no_virt:
            self.auto_retry_no_virt_attempted = False

        try:
            cmd = self._build_start_command(force_no_virt=force_no_virt)
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("create_ap", str(exc))
            return

        if force_no_virt:
            self.log_queue.put("\n[Retrying with --no-virt]\n")

        self.log_queue.put("\n$ " + " ".join(cmd) + "\n")

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid,
            )
        except FileNotFoundError as exc:
            messagebox.showerror("create_ap", f"Failed to start: {exc}")
            return
        except PermissionError:
            messagebox.showerror(
                "create_ap",
                "Permission denied. Run as root or ensure pkexec/sudo is available.",
            )
            return

        self._mark_current_settings_as_applied()
        self._set_running_ui(True)
        threading.Thread(target=self._stream_process_output, args=(self.process,), daemon=True).start()

    def _run_command_and_log(self, cmd: list[str]) -> None:
        self.log_queue.put("\n$ " + " ".join(cmd) + "\n")
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
            out = completed.stdout or ""
            err = completed.stderr or ""
            if out:
                self.log_queue.put(out)
            if err:
                self.log_queue.put(err)
            self.log_queue.put(f"[exit code {completed.returncode}]\n")
        except Exception as exc:
            self.log_queue.put(f"Command failed: {exc}\n")

    def stop_ap(self) -> None:
        if not self.instance_check_done:
            messagebox.showwarning("create_ap", "Run instance check first (click 'Check instances').")
            return

        if self.process and self.process.poll() is None:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGINT)
            except ProcessLookupError:
                pass

        if not self.create_ap_bin:
            messagebox.showerror("create_ap", "create_ap binary not found")
            return

        wifi = self._effective_running_iface()
        if not wifi:
            messagebox.showerror("create_ap", "WiFi interface is required to stop a running instance")
            return

        cmd = self._auth_prefix() + [self.create_ap_bin, "--stop", wifi]
        threading.Thread(target=self._run_command_and_log, args=(cmd,), daemon=True).start()
        self.root.after(2000, self.check_running_instances)

    def show_running(self) -> None:
        if not self.create_ap_bin:
            messagebox.showerror("create_ap", "create_ap binary not found")
            return

        cmd = self._auth_prefix() + [self.create_ap_bin, "--list-running"]
        threading.Thread(target=self._run_command_and_log, args=(cmd,), daemon=True).start()

    def _resolve_hostname(self, ipaddr: str, current_name: str) -> str:
        if current_name and current_name != "*":
            return current_name
        if not ipaddr or ipaddr == "*":
            return "*"
        try:
            return socket.gethostbyaddr(ipaddr)[0]
        except (socket.herror, socket.gaierror, OSError):
            return "*"

    def _parse_clients_output(self, output: str) -> list[tuple[str, str, str]]:
        clients: list[tuple[str, str, str]] = []
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("MAC") or stripped.startswith("No clients connected"):
                continue
            parts = stripped.split()
            if len(parts) < 3:
                continue
            mac = parts[0]
            ipaddr = parts[1]
            hostname = self._resolve_hostname(ipaddr, " ".join(parts[2:]))
            clients.append((mac, ipaddr, hostname))
        return clients

    def _render_clients_window(self, clients: list[tuple[str, str, str]]) -> None:
        if self.clients_window is None or not self.clients_window.winfo_exists():
            self.clients_window = tk.Toplevel(self.root)
            self.clients_window.title("Connected Devices")
            self.clients_window.geometry("640x320")

            frame = ttk.Frame(self.clients_window, padding=10)
            frame.pack(fill=tk.BOTH, expand=True)

            self.clients_tree = ttk.Treeview(frame, columns=("mac", "ip", "name"), show="headings")
            self.clients_tree.heading("mac", text="MAC")
            self.clients_tree.heading("ip", text="IP")
            self.clients_tree.heading("name", text="Name")
            self.clients_tree.column("mac", width=190)
            self.clients_tree.column("ip", width=140)
            self.clients_tree.column("name", width=260)
            self.clients_tree.pack(fill=tk.BOTH, expand=True)

            footer = ttk.Frame(frame)
            footer.pack(fill=tk.X, pady=(8, 0))
            ttk.Button(footer, text="Refresh", command=self.show_clients).pack(side=tk.LEFT)
            ttk.Button(footer, text="Close", command=self.clients_window.destroy).pack(side=tk.RIGHT)

        assert self.clients_tree is not None
        self.clients_tree.delete(*self.clients_tree.get_children())

        if not clients:
            self.clients_tree.insert("", tk.END, values=("-", "-", "No clients connected"))
        else:
            for client in clients:
                self.clients_tree.insert("", tk.END, values=client)

        self.clients_window.lift()
        self.clients_window.focus_force()

    def _virtual_iface_hint_detected(self, output: str) -> bool:
        markers = [
            "ERROR: '",
            "is not used from create_ap instance",
            "Maybe you need to pass the virtual interface instead.",
        ]
        return all(marker in output for marker in markers)

    def _clients_iface_candidates(self, selected_iface: str) -> list[str]:
        candidates: list[str] = []

        def _add_candidate(iface: str) -> None:
            iface = iface.strip()
            if iface and iface not in candidates:
                candidates.append(iface)

        _add_candidate(selected_iface)

        effective_iface = self._effective_running_iface()
        _add_candidate(effective_iface)

        if self.running_ap_settings:
            running_iface = str(self.running_ap_settings.get("wifi_iface", "")).strip()
            _add_candidate(running_iface)

        confdir = self._find_running_confdir(selected_iface)
        if confdir is not None:
            hostapd_iface = str(self._parse_hostapd_settings(confdir).get("wifi_iface", "")).strip()
            _add_candidate(hostapd_iface)

        return candidates

    def _fetch_and_render_clients(self, ifaces: list[str]) -> None:
        try:
            last_out = ""
            last_err = ""
            last_rc = 1

            for index, iface in enumerate(ifaces):
                cmd = self._auth_prefix() + [self.create_ap_bin, "--list-clients", iface]
                self.log_queue.put("\n$ " + " ".join(cmd) + "\n")
                completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
                out = completed.stdout or ""
                err = completed.stderr or ""
                if out:
                    self.log_queue.put(out)
                if err:
                    self.log_queue.put(err)
                self.log_queue.put(f"[exit code {completed.returncode}]\n")

                last_out = out
                last_err = err
                last_rc = completed.returncode

                if completed.returncode == 0:
                    if self.wifi_iface.get().strip() != iface:
                        self.wifi_iface.set(iface)
                    clients = self._parse_clients_output(out)
                    self.root.after(0, lambda: self._render_clients_window(clients))
                    return

                combined = f"{out}\n{err}"
                should_retry = self._virtual_iface_hint_detected(combined)
                if should_retry and index + 1 < len(ifaces):
                    next_iface = ifaces[index + 1]
                    self.log_queue.put(f"[Retrying --list-clients with interface: {next_iface}]\n")
                    continue
                break

            detail = f"\n\nLast exit code: {last_rc}" if last_rc is not None else ""
            if last_err.strip() or last_out.strip():
                detail += "\nCheck log output for details."
            self.root.after(0, lambda: messagebox.showerror("create_ap", "Failed to list connected clients." + detail))
        except Exception as exc:
            self.log_queue.put(f"Command failed: {exc}\n")
            self.root.after(0, lambda: messagebox.showerror("create_ap", f"Failed to list clients: {exc}"))

    def show_clients(self) -> None:
        if not self.create_ap_bin:
            messagebox.showerror("create_ap", "create_ap binary not found")
            return

        wifi = self._effective_running_iface()
        if not wifi:
            messagebox.showerror("create_ap", "Select a WiFi interface first")
            return

        iface_candidates = self._clients_iface_candidates(wifi)
        threading.Thread(target=self._fetch_and_render_clients, args=(iface_candidates,), daemon=True).start()

    def _escape_wifi_qr_value(self, value: str) -> str:
        escaped = value.replace("\\", "\\\\")
        escaped = escaped.replace(";", "\\;")
        escaped = escaped.replace(",", "\\,")
        escaped = escaped.replace(":", "\\:")
        escaped = escaped.replace('"', '\\"')
        return escaped

    def _wifi_qr_payload(self) -> str:
        source_settings = self._settings_snapshot()
        if self.external_running and self.running_ap_settings:
            source_settings = {**source_settings, **self.running_ap_settings}

        ssid = str(source_settings.get("ssid", "")).strip()
        passphrase = str(source_settings.get("passphrase", "")).strip()
        hidden = bool(source_settings.get("hidden", False))

        if not ssid:
            raise ValueError("SSID is required before generating a QR code")

        auth = "nopass"
        payload = [f"WIFI:T:{auth}", f"S:{self._escape_wifi_qr_value(ssid)}"]

        if passphrase:
            auth = "WPA"
            payload[0] = f"WIFI:T:{auth}"
            payload.append(f"P:{self._escape_wifi_qr_value(passphrase)}")

        if hidden:
            payload.append("H:true")

        return ";".join(payload) + ";;"

    def _render_qr_window(self, image_path: str, payload: str) -> None:
        if self.qr_window is None or not self.qr_window.winfo_exists():
            self.qr_window = tk.Toplevel(self.root)
            self.qr_window.title("Hotspot QR Code")
            self.qr_window.geometry("420x520")

            frame = ttk.Frame(self.qr_window, padding=12)
            frame.pack(fill=tk.BOTH, expand=True)

            qr_label = ttk.Label(frame)
            qr_label.pack(pady=(0, 12))

            info_label = ttk.Label(
                frame,
                text="Scan this code from another device to join the hotspot.",
                justify=tk.CENTER,
            )
            info_label.pack(pady=(0, 8))

            payload_text = tk.Text(frame, height=5, wrap=tk.WORD)
            payload_text.pack(fill=tk.X, pady=(0, 8))
            payload_text.insert("1.0", payload)
            payload_text.configure(state=tk.DISABLED)

            ttk.Button(frame, text="Close", command=self.qr_window.destroy).pack(side=tk.BOTTOM)

            self.qr_window.qr_label = qr_label  # type: ignore[attr-defined]
            self.qr_window.payload_text = payload_text  # type: ignore[attr-defined]

        self.qr_image = tk.PhotoImage(file=image_path)
        qr_label = self.qr_window.qr_label  # type: ignore[attr-defined]
        payload_text = self.qr_window.payload_text  # type: ignore[attr-defined]
        qr_label.configure(image=self.qr_image)
        payload_text.configure(state=tk.NORMAL)
        payload_text.delete("1.0", tk.END)
        payload_text.insert("1.0", payload)
        payload_text.configure(state=tk.DISABLED)
        self.qr_window.lift()
        self.qr_window.focus_force()

    def show_qr_code(self) -> None:
        if shutil.which("qrencode") is None:
            messagebox.showerror(
                "create_ap",
                "qrencode is not installed. Install it first to generate hotspot QR codes.",
            )
            return

        try:
            payload = self._wifi_qr_payload()
        except ValueError as exc:
            messagebox.showerror("create_ap", str(exc))
            return

        temp_dir = Path(tempfile.gettempdir())
        image_path = temp_dir / "create_ap_wifi_qr.png"
        cmd = ["qrencode", "-o", str(image_path), "-s", "8", payload]
        self.log_queue.put("\n$ " + " ".join(cmd) + "\n")

        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if completed.stdout:
            self.log_queue.put(completed.stdout)
        if completed.stderr:
            self.log_queue.put(completed.stderr)
        self.log_queue.put(f"[exit code {completed.returncode}]\n")

        if completed.returncode != 0 or not image_path.is_file():
            messagebox.showerror("create_ap", "Failed to generate QR code. Check log output.")
            return

        try:
            self._render_qr_window(str(image_path), payload)
        except tk.TclError as exc:
            messagebox.showerror("create_ap", f"Failed to display QR code: {exc}")

    def clear_log(self) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)

    def apply_changes(self) -> None:
        if not self.instance_check_done:
            messagebox.showwarning("create_ap", "Run instance check first (click 'Check instances').")
            return

        if not self._has_settings_changes():
            messagebox.showinfo("create_ap", "No setting changes detected.")
            return

        running_now = (self.process is not None and self.process.poll() is None) or self.external_running
        if not running_now:
            self.start_ap(skip_preflight=False)
            return

        if self.process and self.process.poll() is None:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGINT)
            except ProcessLookupError:
                pass
            self.process = None

        self.stop_ap()
        self.root.after(2200, lambda: self.start_ap(skip_preflight=False))

    def on_close(self) -> None:
        if self.process and self.process.poll() is None:
            answer = messagebox.askyesnocancel(
                "create_ap",
                "Hotspot is still running. Stop it before closing?",
            )
            if answer is None:
                return
            if answer:
                self.stop_ap()

        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    CreateApGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
