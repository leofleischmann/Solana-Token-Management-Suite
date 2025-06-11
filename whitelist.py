#!/usr/bin/env python3
# === Blockchain Monitor: Erweitertes Überwachungstool mit Visualisierung ===

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
import threading
import queue
import time
import os
import sys
import json
import asyncio
import logging
import webbrowser
from collections import deque
from datetime import datetime
from typing import Dict, Set, Optional

# --- Neu für Visualisierung ---
try:
    from pyvis.network import Network
except ImportError:
    messagebox.showerror("Fehlende Bibliothek", "Die 'pyvis' Bibliothek wird für die Netzwerk-Visualisierung benötigt. Bitte installieren Sie sie mit: pip install pyvis")
    sys.exit(1)

# --- Solana-Bibliotheken ---
try:
    import websockets
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.signature import Signature
    from solders.transaction import Transaction
    from solana.rpc.api import Client
    from solana.rpc.async_api import AsyncClient
    from spl.token.instructions import (
        get_associated_token_address,
        freeze_account, FreezeAccountParams
    )
    from spl.token.constants import TOKEN_PROGRAM_ID
except ImportError as e:
    messagebox.showerror("Fehler", f"Erforderliche Solana-Bibliotheken fehlen: {e}. Bitte installieren Sie diese.")
    sys.exit(1)

# === Strukturiertes Logging Setup ===
def setup_transaction_logger():
    """Konfiguriert einen Logger, um Transaktionen in eine Datei zu schreiben."""
    logger = logging.getLogger('transaction_logger')
    logger.setLevel(logging.INFO)
    logger.propagate = False 
    if not logger.handlers:
        handler = logging.FileHandler('transactions.jsonl', mode='a', encoding='utf-8')
        logger.addHandler(handler)
    return logger

# === UI Komponenten (integriert für Einfachheit) ===
class DesignSystem:
    COLORS = {'primary': '#3B82F6', 'success': '#22C55E', 'error': '#EF4444', 'warning': '#F97316', 'info': '#60A5FA', 'secondary': '#6B7280', 'text_primary': '#FFFFFF', 'text_secondary': '#D1D5DB'}
    SPACING = {'sm': 4, 'md': 8, 'lg': 16}
    RADIUS = {'sm': 4, 'md': 8, 'lg': 12}
    ICONS = {'start': '▶', 'stop': '■', 'refresh': '🔄', 'edit': '✏️', 'save': '💾', 'expand': '📂', 'search': '🔍', 'settings': '⚙️', 'info': 'ℹ️', 'success': '✅', 'error': '❌', 'graph': '🌐'}

def show_error(parent, title, message):
    messagebox.showerror(title, message, parent=parent)

def show_info(parent, title, message):
    messagebox.showinfo(title, message, parent=parent)

def truncate_address(address: str, chars: int = 4) -> str:
    if not isinstance(address, str) or len(address) < chars * 2: return address
    return f"{address[:chars]}...{address[-chars:]}"

class StatusIndicator(ctk.CTkFrame):
    def __init__(self, parent, status="unknown", text="Gestoppt"):
        super().__init__(parent, fg_color="transparent")
        self.status_text = ctk.CTkLabel(self, text=text, font=ctk.CTkFont(size=12))
        self.status_text.pack(side="right", padx=(DesignSystem.SPACING['sm'], 0))
        self.status_color = ctk.CTkFrame(self, width=12, height=12, corner_radius=6)
        self.status_color.pack(side="right")
        self.set_status(status, text)

    def set_status(self, status, text):
        color_map = {"success": DesignSystem.COLORS['success'], "error": DesignSystem.COLORS['error'], "info": DesignSystem.COLORS['info'], "unknown": DesignSystem.COLORS['secondary']}
        self.status_color.configure(fg_color=color_map.get(status, "gray"))
        self.status_text.configure(text=text)

class EnhancedTextbox(ctk.CTkTextbox):
    def __init__(self, parent):
        super().__init__(parent, wrap="word", font=ctk.CTkFont(family="monospace", size=11))
        self.tag_config("info", foreground=DesignSystem.COLORS['info'])
        self.tag_config("warning", foreground=DesignSystem.COLORS['warning'])
        self.tag_config("error", foreground=DesignSystem.COLORS['error'])
        self.tag_config("success", foreground=DesignSystem.COLORS['success'])
        self.tag_config("header", foreground=DesignSystem.COLORS['text_secondary'])

    def append_text(self, message, level="info"):
        self.configure(state="normal")
        self.insert("end", f"{message}\n", (level,))
        self.configure(state="disabled")
        self.see("end")

    def clear_text(self):
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")

# === Hilfsfunktionen ===
def load_config():
    try:
        with open("config.json", 'r') as f: return json.load(f)
    except Exception: return None

def load_keypair(wallet_folder: str, filename: str):
    path = os.path.join(wallet_folder, filename)
    if not os.path.exists(path): raise FileNotFoundError(f"Wallet-Datei '{path}' nicht gefunden.")
    with open(path, 'r') as f: return Keypair.from_bytes(bytes(json.load(f)))

def load_whitelist(wallet_folder: str) -> set:
    path = os.path.join(wallet_folder, "whitelist.txt")
    if not os.path.exists(path): return set()
    with open(path, 'r', encoding='utf-8') as f: return {line.strip() for line in f if line.strip() and not line.startswith('#')}

# === Netzwerk-Visualisierung ===
class NetworkVisualizer:
    def __init__(self, log_file: str, whitelist: Set[str], output_path: str):
        self.log_file, self.whitelist, self.output_path = log_file, whitelist, output_path

    def generate_graph(self):
        if not os.path.exists(self.log_file): raise FileNotFoundError("Log-Datei 'transactions.jsonl' nicht gefunden.")
        net = Network(height="95vh", width="100%", bgcolor="#222222", font_color="white", notebook=True, cdn_resources='in_line')
        all_wallets, frozen_wallets, edges = set(), set(), []
        with open(self.log_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    tx = json.loads(line)
                    sender, recipient = tx.get('sender'), tx.get('recipient')
                    if sender: all_wallets.add(sender)
                    if recipient: all_wallets.add(recipient)
                    if sender and recipient: edges.append(tx)
                    if tx.get('status') == 'VIOLATION_FROZEN': frozen_wallets.update(tx.get('frozen_wallets', []))
                except json.JSONDecodeError: continue
        for wallet in all_wallets:
            color = DesignSystem.COLORS['error'] if wallet in frozen_wallets else (DesignSystem.COLORS['success'] if wallet in self.whitelist else DesignSystem.COLORS['primary'])
            net.add_node(wallet, label=truncate_address(wallet), title=wallet, color=color)
        for tx in edges:
            try: net.add_edge(tx['sender'], tx['recipient'], title=f"{tx.get('amount', 0)} Tokens", value=tx.get('amount', 0))
            except Exception: continue
        net.set_options("""{"physics": {"barnesHut": {"gravitationalConstant": -2000, "centralGravity": 0.1, "springLength": 150}, "minVelocity": 0.75}}""")
        
        # KORREKTUR: Manuelles Speichern der Datei mit UTF-8-Kodierung, um den 'charmap' Fehler zu vermeiden
        try:
            html_content = net.generate_html()
            with open(self.output_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
        except Exception as e:
            raise IOError(f"Fehler beim Speichern der HTML-Visualisierungsdatei: {e}")


# === Whitelist Monitor Logik ===
class WhitelistMonitorBot:
    TOKEN_DECIMALS = 9
    
    def __init__(self, config: dict, log_func, stop_event: threading.Event, reload_event: threading.Event, freeze_sender: bool, transaction_logger, notification_callback=None):
        self.config, self.log_func, self.stop_event, self.reload_event = config, log_func, stop_event, reload_event
        self.freeze_sender_on_violation, self.transaction_logger, self.notification_callback = freeze_sender, transaction_logger, notification_callback
        self.wallet_folder = config['wallet_folder']
        self.ws_uri = config['rpc_url'].replace("http", "ws")
        self.stats = {'transactions_analyzed': 0, 'violations_detected': 0, 'accounts_frozen': 0, 'start_time': datetime.now()}
        
        self.log_func("--- Initialisiere Whitelist Monitor ---", "header")
        self.http_client = Client(config['rpc_url'])
        self.async_http_client = AsyncClient(config['rpc_url'])
        self.payer_keypair = load_keypair(self.wallet_folder, "payer-wallet.json")
        self.mint_keypair = load_keypair(self.wallet_folder, "mint-wallet.json")
        self.whitelist = load_whitelist(self.wallet_folder)
        self.processed_signatures = deque(maxlen=500)
        self.log_func(f"{DesignSystem.ICONS['success']} Monitor initialisiert. Token: {self.mint_keypair.pubkey()}", "success")
        self.log_func(f"👥 {len(self.whitelist)} Adressen auf Whitelist.", "info")

    def reload_whitelist(self):
        self.log_func("🔄 Lade Whitelist neu...", "info")
        old_count = len(self.whitelist)
        self.whitelist = load_whitelist(self.wallet_folder)
        self.log_func(f"{DesignSystem.ICONS['success']} Whitelist neu geladen. {old_count} → {len(self.whitelist)} Adressen.", "success")
        self.reload_event.set()

    async def _freeze_account(self, ata_to_freeze: Pubkey, owner_address: str, role: str):
        self.log_func(f"❄️ Friere Konto für {role} ein: {owner_address}...", "error")
        try:
            params = FreezeAccountParams(program_id=TOKEN_PROGRAM_ID, account=ata_to_freeze, mint=self.mint_keypair.pubkey(), authority=self.payer_keypair.pubkey())
            tx = Transaction.new_signed_with_payer([freeze_account(params)], self.payer_keypair.pubkey(), [self.payer_keypair], self.http_client.get_latest_blockhash().value.blockhash)
            self.http_client.send_transaction(tx)
            self.log_func(f"{DesignSystem.ICONS['success']} ERFOLG '{role} Konto einfrieren'! Wallet: {owner_address}", "success")
            self.stats['accounts_frozen'] += 1
        except Exception as e:
            self.log_func(f"{DesignSystem.ICONS['error']} FEHLER bei '{role} Konto einfrieren': {e}", "error")

    async def _analyze_transaction(self, signature_str: str):
        if signature_str in self.processed_signatures: return

        # --- Client-seitiger Filter ---
        # 1. Transaktion einmalig abrufen
        try:
            sig = Signature.from_string(signature_str)
            tx_resp = await self.async_http_client.get_transaction(sig, max_supported_transaction_version=0)
            if not tx_resp or not tx_resp.value or not tx_resp.value.transaction or tx_resp.value.transaction.meta.err:
                return
        except Exception: return # Ignorieren, wenn Abruf fehlschlägt

        # 2. Prüfen, ob die Transaktion unseren Token betrifft
        tx_meta = tx_resp.value.transaction.meta
        is_relevant = any(b.mint == self.mint_keypair.pubkey() for b in (tx_meta.pre_token_balances + tx_meta.post_token_balances))
        if not is_relevant:
            return

        # --- RELEVANTE TRANSAKTION GEFUNDEN - ANALYSE STARTEN ---
        self.processed_signatures.append(signature_str)
        self.stats['transactions_analyzed'] += 1
        self.log_func(f"\n--- Analyse: {signature_str[:30]}... ---", "header")
        
        log_entry = {'timestamp': datetime.utcnow().isoformat(),'signature': signature_str, 'sender': None, 'recipient': None, 'amount': 0, 'status': 'UNKNOWN', 'frozen_wallets': []}

        try:
            account_keys = tx_resp.value.transaction.transaction.message.account_keys
            balance_changes = {} 
            for balance in (tx_meta.pre_token_balances + tx_meta.post_token_balances):
                if balance.mint == self.mint_keypair.pubkey():
                    owner_str = str(balance.owner)
                    if owner_str not in balance_changes:
                        balance_changes[owner_str] = {'ata': account_keys[balance.account_index], 'pre': 0, 'post': 0}
            
            for pre in tx_meta.pre_token_balances:
                if str(pre.owner) in balance_changes: 
                    if pre.ui_token_amount.amount:
                        balance_changes[str(pre.owner)]['pre'] = int(pre.ui_token_amount.amount)
            for post in tx_meta.post_token_balances:
                if str(post.owner) in balance_changes: 
                    if post.ui_token_amount.amount:
                        balance_changes[str(post.owner)]['post'] = int(post.ui_token_amount.amount)

            for owner, data in balance_changes.items():
                change = data['post'] - data['pre']
                if change < 0:
                    log_entry['sender'] = owner
                    log_entry['amount'] = abs(change) / (10**self.TOKEN_DECIMALS)
                elif change > 0:
                    log_entry['recipient'] = owner

            sender, recipient = log_entry['sender'], log_entry['recipient']
            if not sender or not recipient:
                log_entry['status'] = 'NON_TRANSFER'
                self.log_func("→ Kein Transfer (z.B. Mint/Burn), ignoriert.", "info")
            else:
                self.log_func(f"Absender:    {truncate_address(sender)}", "info")
                self.log_func(f"Empfänger:   {truncate_address(recipient)}", "info")
                self.log_func(f"Menge:       {log_entry['amount']} Tokens", "info")
                if recipient in self.whitelist:
                    self.log_func("STATUS: ✅ Empfänger ist autorisiert.", "success")
                    log_entry['status'] = 'AUTHORIZED'
                else:
                    self.log_func("STATUS: 🚨 Whitelist-Verstoß! Empfänger nicht autorisiert.", "error")
                    self.stats['violations_detected'] += 1
                    log_entry['status'] = 'VIOLATION_FROZEN'
                    if self.notification_callback: self.notification_callback("Whitelist-Verstoß", f"Transfer an {truncate_address(recipient)}")
                    await self._freeze_account(balance_changes[recipient]['ata'], recipient, "Empfänger")
                    log_entry['frozen_wallets'].append(recipient)
                    if self.freeze_sender_on_violation:
                        self.log_func("→ Option 'Absender ebenfalls einfrieren' aktiv.", "info")
                        await self._freeze_account(balance_changes[sender]['ata'], sender, "Absender")
                        log_entry['frozen_wallets'].append(sender)
        except Exception as e: 
            self.log_func(f"{DesignSystem.ICONS['error']} Fehler bei Detail-Analyse: {e}", "error")
            log_entry['status'] = 'ANALYSIS_ERROR'
        finally:
            self.transaction_logger.info(json.dumps(log_entry))
            self.log_func("------------------------------------------", "header")

    async def run(self):
        while not self.stop_event.is_set():
            self.reload_event.clear()
            try:
                async with websockets.connect(self.ws_uri) as websocket:
                    self.log_func(f"🔌 Verbunden mit WebSocket: {self.ws_uri}", "success")
                    # *** KORRIGIERTE METHODE: logsSubscribe mit breiterem Filter ***
                    await websocket.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "logsSubscribe",
                        "params": [
                            {"mentions": [str(TOKEN_PROGRAM_ID)]},
                            {"commitment": "finalized"}
                        ]
                    }))
                    await websocket.recv() # Subscription confirmation
                    self.log_func(f"\n{DesignSystem.ICONS['success']} Angemeldet für Token-Program-Logs. Warte auf Transaktionen...", "success")
                    while not self.stop_event.is_set() and not self.reload_event.is_set():
                        try:
                            message_str = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                            data = json.loads(message_str)
                            if data.get('method') == 'logsNotification':
                                log_value = data.get('params', {}).get('result', {}).get('value', {})
                                if log_value and not log_value.get('err'):
                                    sig = log_value.get('signature')
                                    if sig:
                                        await self._analyze_transaction(sig)
                        except asyncio.TimeoutError:
                            continue
            except Exception as e:
                self.log_func(f"🔌 WebSocket-Fehler: {e}. Versuche in 10s erneut...", "error")
                await asyncio.sleep(10)
        await self.async_http_client.close()
        self.log_func("--- Monitor-Bot wurde gestoppt. ---", "header")

# === Haupt-UI ===
class MonitorUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Blockchain Monitor")
        self.geometry("1200x800")
        self.minsize(1000, 600)
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.log_queue = queue.Queue()
        self.monitor_thread = None
        self.monitor_instance = None
        self.stop_event = None
        self.reload_event = None
        self.transaction_logger = setup_transaction_logger()
        self._create_widgets()
        self.after(200, self.process_log_queue)
        self.update_whitelist_display()

    def _create_widgets(self):
        self._create_header()
        self._create_main_content()

    def _create_header(self):
        header = ctk.CTkFrame(self)
        header.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        header.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(header, text=f"{DesignSystem.ICONS['search']} Blockchain Monitor", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, padx=10, pady=10)
        controls = ctk.CTkFrame(header, fg_color="transparent")
        controls.grid(row=0, column=1, padx=10)
        self.start_button = ctk.CTkButton(controls, text=f"{DesignSystem.ICONS['start']} Start", command=self.start_monitor, fg_color=DesignSystem.COLORS['success'])
        self.start_button.pack(side="left", padx=5)
        self.stop_button = ctk.CTkButton(controls, text=f"{DesignSystem.ICONS['stop']} Stop", command=self.stop_monitor, state="disabled", fg_color=DesignSystem.COLORS['error'])
        self.stop_button.pack(side="left", padx=5)
        status = ctk.CTkFrame(header, fg_color="transparent")
        status.grid(row=0, column=2, padx=10, sticky="e")
        self.status_indicator = StatusIndicator(status)
        self.status_indicator.pack(anchor="e")
        self.freeze_sender_check = ctk.CTkCheckBox(status, text="Absender bei Verstoß ebenfalls sperren")
        self.freeze_sender_check.pack(anchor="e", pady=5)
        self.freeze_sender_check.select()

    def _create_main_content(self):
        self.tab_view = ctk.CTkTabview(self)
        self.tab_view.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        tabs = ["📋 Live Log", "📝 Whitelist", "🌐 Netzwerk Visualisierung", "⚙️ Einstellungen"]
        for tab in tabs: self.tab_view.add(tab)
        self._create_log_tab(self.tab_view.tab("📋 Live Log"))
        self._create_whitelist_tab(self.tab_view.tab("📝 Whitelist"))
        self._create_network_tab(self.tab_view.tab("🌐 Netzwerk Visualisierung"))
        self._create_settings_tab(self.tab_view.tab("⚙️ Einstellungen"))

    def _create_log_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1); tab.grid_rowconfigure(0, weight=1)
        self.log_textbox = EnhancedTextbox(tab)
        self.log_textbox.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

    def _create_whitelist_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1); tab.grid_rowconfigure(1, weight=1)
        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(row=0, column=0, padx=10, pady=10, sticky="e")
        ctk.CTkButton(actions, text=f"{DesignSystem.ICONS['refresh']} Neu laden", command=self.reload_whitelist_action).pack(side="right")
        self.whitelist_textbox = ctk.CTkTextbox(tab, state="disabled", font=ctk.CTkFont(family="monospace", size=11))
        self.whitelist_textbox.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

    def _create_network_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tab, text="Interaktive Transaktions-Visualisierung", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, padx=20, pady=20, sticky="w")
        info_text = "Klicken Sie auf den Button, um eine interaktive Netzwerkkarte aus den geloggten Transaktionen zu erstellen. Die Karte wird in Ihrem Webbrowser geöffnet.\n\n- Grüne Knoten: Whitelist-Adressen\n- Rote Knoten: Gesperrte Adressen\n- Blaue Knoten: Andere Adressen"
        ctk.CTkLabel(tab, text=info_text, wraplength=600, justify="left").grid(row=1, column=0, padx=20, pady=10, sticky="nw")
        self.update_graph_button = ctk.CTkButton(tab, text=f"{DesignSystem.ICONS['graph']} Visualisierung erstellen & öffnen", command=self.generate_and_open_graph, height=40)
        self.update_graph_button.grid(row=2, column=0, padx=20, pady=20, sticky="w")
        self.graph_status_label = ctk.CTkLabel(tab, text="", text_color=DesignSystem.COLORS['text_secondary'])
        self.graph_status_label.grid(row=3, column=0, padx=20, pady=10, sticky="w")
        
    def _create_settings_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        connection_frame = ctk.CTkFrame(tab)
        connection_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        ctk.CTkLabel(connection_frame, text=f"{DesignSystem.ICONS['info']} Verbindung", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=10, pady=10)
        try:
            config = load_config()
            if config:
                ctk.CTkLabel(connection_frame, text=f"RPC Endpunkt: {config['rpc_url']}").pack(anchor="w", padx=10)
                ctk.CTkLabel(connection_frame, text=f"Wallet-Ordner: {config['wallet_folder']}").pack(anchor="w", padx=10, pady=5)
        except Exception as e:
            ctk.CTkLabel(connection_frame, text=f"Fehler beim Laden der config.json: {e}").pack(anchor="w", padx=10)

    def start_monitor(self):
        self.log_textbox.clear_text(); self.log("INFO: Monitor wird gestartet...", "info")
        self.start_button.configure(state="disabled"); self.stop_button.configure(state="normal")
        self.status_indicator.set_status("info", "Initialisierung...")
        self.stop_event, self.reload_event = threading.Event(), threading.Event()
        try:
            config = load_config()
            if not config: raise ValueError("Konfiguration konnte nicht geladen werden.")
            self.monitor_instance = WhitelistMonitorBot(config, self.log, self.stop_event, self.reload_event, self.freeze_sender_check.get(), self.transaction_logger)
            self.monitor_thread = threading.Thread(target=lambda: asyncio.run(self.monitor_instance.run()), daemon=True)
            self.monitor_thread.start()
            self.status_indicator.set_status("success", "Läuft")
        except Exception as e:
            self.log(f"FEHLER: Start fehlgeschlagen - {e}", "error")
            show_error(self, "Startfehler", f"Monitor konnte nicht starten:\n\n{e}")
            self.stop_monitor()

    def stop_monitor(self):
        if self.stop_event: self.stop_event.set()
        self.start_button.configure(state="normal"); self.stop_button.configure(state="disabled")
        self.status_indicator.set_status("unknown", "Gestoppt")
        self.monitor_instance = None; self.monitor_thread = None

    def reload_whitelist_action(self):
        self.update_whitelist_display()
        if self.monitor_instance: self.monitor_instance.reload_whitelist()
        show_info(self, "Whitelist", "Whitelist wurde neu geladen.")

    def generate_and_open_graph(self):
        self.graph_status_label.configure(text="INFO: Erstelle Netzwerk-Visualisierung... Dies kann einen Moment dauern.")
        self.update_graph_button.configure(state="disabled")
        threading.Thread(target=self._run_visualization_task, daemon=True).start()

    def _run_visualization_task(self):
        try:
            config = load_config()
            if not config: raise ValueError("Config nicht gefunden")
            visualizer = NetworkVisualizer('transactions.jsonl', load_whitelist(config['wallet_folder']),'network_visualization.html')
            visualizer.generate_graph()
            self.after(0, self._on_graph_generation_success)
        except Exception as e:
            self.after(0, lambda e=e: self._on_graph_generation_error(e))
    
    def _on_graph_generation_success(self):
        self.graph_status_label.configure(text=f"✓ Erfolg! network_visualization.html erstellt. Wird im Browser geöffnet.", text_color=DesignSystem.COLORS['success'])
        webbrowser.open(f"file://{os.path.realpath('network_visualization.html')}")
        self.update_graph_button.configure(state="normal")

    def _on_graph_generation_error(self, e):
        show_error(self, "Visualisierungs-Fehler", f"Konnte die Netzwerkkarte nicht erstellen:\n\n{e}")
        self.graph_status_label.configure(text=f"❌ Fehler: {e}", text_color=DesignSystem.COLORS['error'])
        self.update_graph_button.configure(state="normal")

    def log(self, message, level="info"):
        self.log_queue.put((message, level))

    def process_log_queue(self):
        try:
            while True: self.log_textbox.append_text(*self.log_queue.get_nowait())
        except queue.Empty: pass
        finally: self.after(200, self.process_log_queue)

    def update_whitelist_display(self):
        try:
            config = load_config()
            if not config: return
            path = os.path.join(config['wallet_folder'], "whitelist.txt")
            content = open(path, 'r', encoding='utf-8').read() if os.path.exists(path) else "# whitelist.txt nicht gefunden"
            self.whitelist_textbox.configure(state="normal")
            self.whitelist_textbox.delete("1.0", "end")
            self.whitelist_textbox.insert("1.0", content)
            self.whitelist_textbox.configure(state="disabled")
        except Exception as e:
            self.whitelist_textbox.insert("1.0", f"Fehler beim Laden: {e}")

    def on_closing(self):
        self.stop_monitor()
        self.destroy()

if __name__ == "__main__":
    app = MonitorUI()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
