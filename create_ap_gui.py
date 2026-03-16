#!/usr/bin/env python3

import json
import os
import queue
import re
import shutil
import socket
import signal
import subprocess
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
        self.auto_retry_no_virt_attempted = False
        self.instance_check_done = False
        self.external_running = False
        self.external_running_ifaces: list[str] = []
        self.instance_status = tk.StringVar(value="Instance check pending")
        self.last_applied_settings: dict[str, object] = {}
        self.profile_path = Path.home() / ".config" / "create_ap" / "gui_profile.json"

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

        self.start_button = ttk.Button(buttons, text="Start AP", command=self.start_ap)
        self.start_button.pack(side=tk.LEFT, padx=(0, 8))

        self.stop_button = ttk.Button(buttons, text="Stop AP", command=self.stop_ap)
        self.stop_button.pack(side=tk.LEFT, padx=(0, 8))

        self.apply_button = ttk.Button(buttons, text="Apply changes", command=self.apply_changes)
        self.apply_button.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(buttons, text="Preflight", command=lambda: self.preflight_check(show_success=True)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(buttons, text="Check instances", command=self.check_running_instances).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(buttons, text="Refresh interfaces", command=self._refresh_interfaces).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(buttons, text="Show running", command=self.show_running).pack(side=tk.LEFT, padx=(0, 8))
        self.show_clients_button = ttk.Button(buttons, text="Show clients", command=self.show_clients)
        self.show_clients_button.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(buttons, text="Save profile", command=self.save_profile).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(buttons, text="Load profile", command=self.load_profile).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(buttons, text="Clear log", command=self.clear_log).pack(side=tk.RIGHT)

        status = ttk.Frame(main)
        status.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(status, textvariable=self.instance_status).pack(side=tk.LEFT)

        log_frame = ttk.LabelFrame(main, text="Output", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log = tk.Text(log_frame, wrap=tk.WORD, state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True)

        self._toggle_internet_iface_state()

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

    def save_profile(self) -> None:
        try:
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            self.profile_path.write_text(json.dumps(self._profile_data(), indent=2), encoding="utf-8")
            self.log_queue.put(f"\n[Profile saved] {self.profile_path}\n")
            messagebox.showinfo("create_ap", f"Profile saved to:\n{self.profile_path}")
        except OSError as exc:
            messagebox.showerror("create_ap", f"Failed to save profile: {exc}")

    def load_profile(self) -> None:
        if not self.profile_path.is_file():
            messagebox.showerror("create_ap", f"Profile not found:\n{self.profile_path}")
            return

        try:
            profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("create_ap", f"Failed to load profile: {exc}")
            return

        if not isinstance(profile, dict):
            messagebox.showerror("create_ap", "Invalid profile format")
            return

        self._apply_profile(profile)
        self.log_queue.put(f"\n[Profile loaded] {self.profile_path}\n")
        messagebox.showinfo("create_ap", "Profile loaded")

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
                parts = text.split()
                if len(parts) >= 2:
                    iface = parts[1]
                    ifaces.append(iface)
        return ifaces

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
        else:
            self.instance_status.set("No running create_ap instance detected")

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

        wifi = self.wifi_iface.get().strip()
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

    def _fetch_and_render_clients(self, cmd: list[str]) -> None:
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

            if completed.returncode != 0:
                self.root.after(0, lambda: messagebox.showerror("create_ap", "Failed to list connected clients. Check log output."))
                return

            clients = self._parse_clients_output(out)
            self.root.after(0, lambda: self._render_clients_window(clients))
        except Exception as exc:
            self.log_queue.put(f"Command failed: {exc}\n")
            self.root.after(0, lambda: messagebox.showerror("create_ap", f"Failed to list clients: {exc}"))

    def show_clients(self) -> None:
        if not self.create_ap_bin:
            messagebox.showerror("create_ap", "create_ap binary not found")
            return

        wifi = self.wifi_iface.get().strip()
        if not wifi:
            messagebox.showerror("create_ap", "Select a WiFi interface first")
            return

        cmd = self._auth_prefix() + [self.create_ap_bin, "--list-clients", wifi]
        threading.Thread(target=self._fetch_and_render_clients, args=(cmd,), daemon=True).start()

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
