# -*- coding: utf-8 -*-
"""
マイクラサーバーマネージャー (MC Server Manager)

Minecraft Java Edition の統合サーバー(Vanilla)を、GUIから
ダウンロード・設定・起動・停止・コンソール操作できるアプリ。

依存: 標準ライブラリのみ(tkinter, urllib, json, subprocess, threading)
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import tkinter.simpledialog as simpledialog

APP_TITLE = "マイクラサーバーマネージャー"
CONFIG_FILE = "mcsm_config.json"
VERSION_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"


def app_base_dir():
    """実行ファイル/スクリプトの置かれているディレクトリを返す(PyInstaller対応)"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def load_config():
    path = os.path.join(app_base_dir(), CONFIG_FILE)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(cfg):
    path = os.path.join(app_base_dir(), CONFIG_FILE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class McServerManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("880x640")
        self.minsize(760, 560)

        self.config_data = load_config()
        self.server_process = None
        self.server_thread = None
        self.is_running = False
        self.version_list = []  # [(id, url, type), ...]

        self._build_ui()
        self._restore_config_to_ui()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- UI構築 ----------------
    def _build_ui(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        frame_dir = ttk.LabelFrame(root, text="サーバーフォルダ", padding=8)
        frame_dir.pack(fill=tk.X, pady=4)

        self.var_dir = tk.StringVar()
        ttk.Entry(frame_dir, textvariable=self.var_dir, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(frame_dir, text="参照...", command=self.choose_dir).pack(side=tk.LEFT)
        ttk.Button(frame_dir, text="新規フォルダ作成", command=self.create_new_dir).pack(side=tk.LEFT, padx=(6, 0))

        # --- バージョン選択/ダウンロード ---
        frame_ver = ttk.LabelFrame(root, text="サーバーjarの取得", padding=8)
        frame_ver.pack(fill=tk.X, pady=4)

        ttk.Label(frame_ver, text="バージョン:").grid(row=0, column=0, sticky="w")
        self.var_version = tk.StringVar()
        self.combo_version = ttk.Combobox(frame_ver, textvariable=self.var_version, width=20, state="readonly")
        self.combo_version.grid(row=0, column=1, sticky="w", padx=4)

        self.var_show_snapshot = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame_ver, text="スナップショットも表示", variable=self.var_show_snapshot,
                         command=self.refresh_versions).grid(row=0, column=2, padx=6)

        ttk.Button(frame_ver, text="バージョン一覧取得", command=self.refresh_versions).grid(row=0, column=3, padx=4)
        ttk.Button(frame_ver, text="このバージョンをダウンロード", command=self.download_selected_version).grid(row=0, column=4, padx=4)

        ttk.Label(frame_ver, text="既存のserver.jarを使う場合:").grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(frame_ver, text="jarファイルを選択", command=self.choose_jar).grid(row=1, column=3, pady=(6, 0))
        self.var_jar_name = tk.StringVar(value="(未選択)")
        ttk.Label(frame_ver, textvariable=self.var_jar_name).grid(row=1, column=2, sticky="w", pady=(6, 0))

        # --- 起動設定 ---
        frame_opt = ttk.LabelFrame(root, text="起動設定", padding=8)
        frame_opt.pack(fill=tk.X, pady=4)

        ttk.Label(frame_opt, text="最小メモリ(MB):").grid(row=0, column=0, sticky="w")
        self.var_xms = tk.StringVar(value="1024")
        ttk.Entry(frame_opt, textvariable=self.var_xms, width=8).grid(row=0, column=1, sticky="w")

        ttk.Label(frame_opt, text="最大メモリ(MB):").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.var_xmx = tk.StringVar(value="2048")
        ttk.Entry(frame_opt, textvariable=self.var_xmx, width=8).grid(row=0, column=3, sticky="w")

        self.var_eula = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame_opt, text="EULA(利用規約)に同意する (https://aka.ms/MinecraftEULA)",
                         variable=self.var_eula).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        self.var_online_mode = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame_opt, text="オンラインモード(正規ユーザー認証)を有効にする",
                         variable=self.var_online_mode).grid(row=2, column=0, columnspan=4, sticky="w")

        ttk.Label(frame_opt, text="ポート:").grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.var_port = tk.StringVar(value="25565")
        ttk.Entry(frame_opt, textvariable=self.var_port, width=8).grid(row=3, column=1, sticky="w", pady=(4, 0))

        # --- 操作ボタン ---
        frame_btn = ttk.Frame(root, padding=(0, 6))
        frame_btn.pack(fill=tk.X)

        self.btn_start = ttk.Button(frame_btn, text="▶ サーバー起動", command=self.start_server)
        self.btn_start.pack(side=tk.LEFT)
        self.btn_stop = ttk.Button(frame_btn, text="■ サーバー停止", command=self.stop_server, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=6)

        self.var_status = tk.StringVar(value="状態: 停止中")
        ttk.Label(frame_btn, textvariable=self.var_status, foreground="#555").pack(side=tk.LEFT, padx=12)

        # --- コンソール ---
        frame_console = ttk.LabelFrame(root, text="コンソール", padding=6)
        frame_console.pack(fill=tk.BOTH, expand=True, pady=4)

        self.text_console = scrolledtext.ScrolledText(frame_console, state=tk.DISABLED, wrap=tk.WORD, bg="#111", fg="#ddd")
        self.text_console.pack(fill=tk.BOTH, expand=True)

        frame_cmd = ttk.Frame(root)
        frame_cmd.pack(fill=tk.X, pady=(4, 0))
        self.var_cmd = tk.StringVar()
        entry_cmd = ttk.Entry(frame_cmd, textvariable=self.var_cmd)
        entry_cmd.pack(side=tk.LEFT, fill=tk.X, expand=True)
        entry_cmd.bind("<Return>", lambda e: self.send_command())
        ttk.Button(frame_cmd, text="送信", command=self.send_command).pack(side=tk.LEFT, padx=(6, 0))

    # ---------------- 設定の復元 ----------------
    def _restore_config_to_ui(self):
        cfg = self.config_data
        self.var_dir.set(cfg.get("server_dir", ""))
        self.var_xms.set(str(cfg.get("xms", 1024)))
        self.var_xmx.set(str(cfg.get("xmx", 2048)))
        self.var_eula.set(cfg.get("eula", False))
        self.var_online_mode.set(cfg.get("online_mode", True))
        self.var_port.set(str(cfg.get("port", 25565)))
        jar = cfg.get("jar_name", "")
        if jar:
            self.var_jar_name.set(jar)

    def _save_current_config(self):
        cfg = {
            "server_dir": self.var_dir.get(),
            "xms": self.var_xms.get(),
            "xmx": self.var_xmx.get(),
            "eula": self.var_eula.get(),
            "online_mode": self.var_online_mode.get(),
            "port": self.var_port.get(),
            "jar_name": self.var_jar_name.get(),
        }
        save_config(cfg)

    # ---------------- フォルダ/ファイル選択 ----------------
    def choose_dir(self):
        d = filedialog.askdirectory(title="サーバーフォルダを選択")
        if d:
            self.var_dir.set(d)

    def create_new_dir(self):
        d = filedialog.askdirectory(title="新規サーバーフォルダの親ディレクトリを選択")
        if not d:
            return
        name = simpledialog.askstring("新規フォルダ", "フォルダ名を入力してください")
        if not name:
            return
        new_path = os.path.join(d, name)
        try:
            os.makedirs(new_path, exist_ok=True)
            self.var_dir.set(new_path)
        except Exception as e:
            messagebox.showerror("エラー", f"フォルダ作成に失敗しました: {e}")

    def choose_jar(self):
        f = filedialog.askopenfilename(title="server.jar を選択", filetypes=[("Jar files", "*.jar")])
        if not f:
            return
        d = self.var_dir.get()
        if not d:
            d = os.path.dirname(f)
            self.var_dir.set(d)
        name = os.path.basename(f)
        dest = os.path.join(d, name)
        if os.path.abspath(f) != os.path.abspath(dest):
            try:
                import shutil
                shutil.copy(f, dest)
            except Exception as e:
                messagebox.showerror("エラー", f"コピーに失敗しました: {e}")
                return
        self.var_jar_name.set(name)

    # ---------------- バージョン一覧 ----------------
    def refresh_versions(self):
        self.append_console("[INFO] バージョン一覧を取得中...\n")
        threading.Thread(target=self._fetch_versions_thread, daemon=True).start()

    def _fetch_versions_thread(self):
        try:
            with urllib.request.urlopen(VERSION_MANIFEST_URL, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            self.append_console(f"[ERROR] バージョン一覧の取得に失敗しました: {e}\n")
            return

        show_snapshot = self.var_show_snapshot.get()
        versions = []
        for v in data.get("versions", []):
            if v["type"] == "release" or (show_snapshot and v["type"] == "snapshot"):
                versions.append((v["id"], v["url"], v["type"]))

        self.version_list = versions
        ids = [v[0] for v in versions]
        self.after(0, lambda: self._set_version_combo(ids))

    def _set_version_combo(self, ids):
        self.combo_version["values"] = ids
        if ids:
            self.combo_version.current(0)
        self.append_console(f"[INFO] {len(ids)} 件のバージョンを取得しました。\n")

    def download_selected_version(self):
        ver_id = self.var_version.get()
        if not ver_id:
            messagebox.showwarning("警告", "バージョンを選択してください。")
            return
        target = next((v for v in self.version_list if v[0] == ver_id), None)
        if not target:
            messagebox.showwarning("警告", "バージョン情報が見つかりません。再取得してください。")
            return
        d = self.var_dir.get()
        if not d:
            messagebox.showwarning("警告", "先にサーバーフォルダを選択/作成してください。")
            return
        os.makedirs(d, exist_ok=True)
        threading.Thread(target=self._download_version_thread, args=(target,), daemon=True).start()

    def _download_version_thread(self, target):
        ver_id, meta_url, _ = target
        self.append_console(f"[INFO] {ver_id} のメタデータを取得中...\n")
        try:
            with urllib.request.urlopen(meta_url, timeout=15) as resp:
                meta = json.loads(resp.read().decode("utf-8"))
            server_info = meta["downloads"]["server"]
            jar_url = server_info["url"]
        except Exception as e:
            self.append_console(f"[ERROR] メタデータ取得に失敗しました: {e}\n")
            return

        d = self.var_dir.get()
        jar_name = f"server_{ver_id}.jar"
        dest = os.path.join(d, jar_name)
        self.append_console(f"[INFO] server.jar ({ver_id}) をダウンロード中...\n")
        try:
            urllib.request.urlretrieve(jar_url, dest)
        except Exception as e:
            self.append_console(f"[ERROR] ダウンロードに失敗しました: {e}\n")
            return

        self.append_console(f"[INFO] ダウンロード完了: {jar_name}\n")
        self.after(0, lambda: self.var_jar_name.set(jar_name))

    # ---------------- サーバー起動/停止 ----------------
    def start_server(self):
        if self.is_running:
            return

        d = self.var_dir.get()
        jar = self.var_jar_name.get()
        if not d or jar == "(未選択)" or not jar:
            messagebox.showwarning("警告", "サーバーフォルダとjarファイルを指定してください。")
            return
        jar_path = os.path.join(d, jar)
        if not os.path.exists(jar_path):
            messagebox.showerror("エラー", f"jarファイルが見つかりません: {jar_path}")
            return

        if not self.var_eula.get():
            messagebox.showwarning("警告", "EULAに同意するにチェックを入れてください。")
            return

        try:
            xms = int(self.var_xms.get())
            xmx = int(self.var_xmx.get())
            port = int(self.var_port.get())
        except ValueError:
            messagebox.showerror("エラー", "メモリ/ポートの値は数値で入力してください。")
            return

        try:
            with open(os.path.join(d, "eula.txt"), "w", encoding="utf-8") as f:
                f.write("eula=true\n")
        except Exception as e:
            messagebox.showerror("エラー", f"eula.txtの書き込みに失敗しました: {e}")
            return

        self._update_server_properties(d, port, self.var_online_mode.get())
        self._save_current_config()

        java_path = self._find_java()
        if not java_path:
            messagebox.showerror("エラー", "Javaが見つかりません。Java(JDK/JRE)をインストールしてください。")
            return

        cmd = [java_path, f"-Xms{xms}M", f"-Xmx{xmx}M", "-jar", jar_path, "nogui"]
        self.append_console(f"[INFO] 起動コマンド: {' '.join(cmd)}\n")

        try:
            self.server_process = subprocess.Popen(
                cmd, cwd=d,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception as e:
            messagebox.showerror("エラー", f"サーバー起動に失敗しました: {e}")
            return

        self.is_running = True
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.var_status.set("状態: 起動中")

        self.server_thread = threading.Thread(target=self._read_output_thread, daemon=True)
        self.server_thread.start()

    def _find_java(self):
        java_home = os.environ.get("JAVA_HOME")
        if java_home:
            candidate = os.path.join(java_home, "bin", "java.exe" if os.name == "nt" else "java")
            if os.path.exists(candidate):
                return candidate
        import shutil as sh
        return sh.which("java")

    def _update_server_properties(self, d, port, online_mode):
        props_path = os.path.join(d, "server.properties")
        lines = []
        if os.path.exists(props_path):
            with open(props_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

        def set_prop(lines, key, value):
            found = False
            for i, line in enumerate(lines):
                if line.strip().startswith(f"{key}="):
                    lines[i] = f"{key}={value}\n"
                    found = True
                    break
            if not found:
                lines.append(f"{key}={value}\n")
            return lines

        lines = set_prop(lines, "server-port", port)
        lines = set_prop(lines, "online-mode", "true" if online_mode else "false")

        with open(props_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    def _read_output_thread(self):
        proc = self.server_process
        try:
            for line in proc.stdout:
                self.append_console(line)
        except Exception:
            pass
        finally:
            self.append_console("[INFO] サーバープロセスが終了しました。\n")
            self.after(0, self._on_server_stopped)

    def _on_server_stopped(self):
        self.is_running = False
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.var_status.set("状態: 停止中")
        self.server_process = None

    def stop_server(self):
        if not self.is_running or not self.server_process:
            return
        try:
            self.server_process.stdin.write("stop\n")
            self.server_process.stdin.flush()
        except Exception:
            try:
                self.server_process.terminate()
            except Exception:
                pass
        self.var_status.set("状態: 停止処理中...")

    def send_command(self):
        cmd = self.var_cmd.get().strip()
        if not cmd:
            return
        if self.is_running and self.server_process and self.server_process.stdin:
            try:
                self.server_process.stdin.write(cmd + "\n")
                self.server_process.stdin.flush()
                self.append_console(f"> {cmd}\n")
            except Exception as e:
                self.append_console(f"[ERROR] コマンド送信失敗: {e}\n")
        else:
            self.append_console("[WARN] サーバーが起動していません。\n")
        self.var_cmd.set("")

    # ---------------- コンソール出力 ----------------
    def append_console(self, text):
        def do_append():
            self.text_console.config(state=tk.NORMAL)
            self.text_console.insert(tk.END, text)
            self.text_console.see(tk.END)
            self.text_console.config(state=tk.DISABLED)
        if threading.current_thread() is threading.main_thread():
            do_append()
        else:
            self.after(0, do_append)

    # ---------------- 終了処理 ----------------
    def _on_close(self):
        if self.is_running:
            if not messagebox.askyesno("確認", "サーバーが起動中です。停止して終了しますか？"):
                return
            self.stop_server()
            time.sleep(1)
        self._save_current_config()
        self.destroy()


def main():
    app = McServerManagerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
