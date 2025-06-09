#!/usr/bin/env python3
# === whitelist_ui_improved.py: Verbesserte grafische Benutzeroberfläche für den Whitelist Monitor ===

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
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional

# Import der gemeinsamen UI-Komponenten
from ui_components import (
    DesignSystem, StatusIndicator, CopyableLabel, ProgressDialog, 
    ConfirmDialog, EnhancedTextbox, show_error, show_info, run_in_thread,
    format_sol_amount, format_token_amount, truncate_address
)

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
    messagebox.showerror("Fehler", f"Erforderliche Bibliotheken fehlen: {e}. Bitte installieren Sie diese.")
    sys.exit(1)

# --- Hilfsfunktionen ---
def load_config():
    try:
        with open("config.json", 'r') as f: 
            return json.load(f)
    except Exception as e:
        messagebox.showerror("Config Fehler", f"config.json konnte nicht geladen werden: {e}")
        return None

def load_keypair(wallet_folder: str, filename: str):
    path = os.path.join(wallet_folder, filename)
    if not os.path.exists(path): 
        raise FileNotFoundError(f"Wallet-Datei '{path}' nicht gefunden.")
    with open(path, 'r') as f: 
        return Keypair.from_bytes(bytes(json.load(f)))

def confirm_and_send_transaction(http_client, instructions, signers, label, log_func):
    log_func(f"→ Sende Transaktion: '{label}'...", "info")
    try:
        blockhash_resp = http_client.get_latest_blockhash()
        tx = Transaction.new_signed_with_payer(instructions, signers[0].pubkey(), signers, blockhash_resp.value.blockhash)
        result = http_client.send_transaction(tx)
        http_client.confirm_transaction(result.value, "finalized", sleep_seconds=5.0)
        log_func(f"{DesignSystem.ICONS['success']} ERFOLG '{label}'! Signatur: {result.value}", "success")
    except Exception as e:
        log_func(f"{DesignSystem.ICONS['error']} FEHLER bei '{label}': {e}", "error")

# === Whitelist Monitor Logik ===

class WhitelistMonitorBot:
    TOKEN_DECIMALS = 9
    
    def __init__(self, config: dict, log_func, stop_event: threading.Event, reload_event: threading.Event, 
                 freeze_sender: bool, notification_callback=None):
        self.config = config
        self.log_func = log_func
        self.stop_event = stop_event
        self.reload_event = reload_event
        self.freeze_sender_on_violation = freeze_sender
        self.notification_callback = notification_callback
        
        self.wallet_folder = config['wallet_folder']
        self.ws_uri = config['rpc_url'].replace("http", "ws")
        
        # Statistiken
        self.stats = {
            'transactions_analyzed': 0,
            'violations_detected': 0,
            'accounts_frozen': 0,
            'start_time': datetime.now()
        }
        
        self.log_func("--- Initialisiere Whitelist Monitor ---", "header")
        self.http_client = Client(config['rpc_url'])
        self.async_http_client = AsyncClient(config['rpc_url'])
        self.payer_keypair = load_keypair(self.wallet_folder, "payer-wallet.json")
        self.mint_keypair = load_keypair(self.wallet_folder, "mint-wallet.json")
        self.whitelist = self._load_whitelist()
        self.processed_signatures = deque(maxlen=200)
        
        self.log_func(f"{DesignSystem.ICONS['success']} Monitor initialisiert. Überwacht Token: {self.mint_keypair.pubkey()}", "success")
        self.log_func(f"👥 {len(self.whitelist)} Adressen auf Whitelist.", "info")

    def _load_whitelist(self) -> set:
        path = os.path.join(self.wallet_folder, "whitelist.txt")
        if not os.path.exists(path):
            self.log_func(f"⚠️ Warnung: '{path}' nicht gefunden. Leere Whitelist wird verwendet.", "warning")
            return set()
        with open(path, 'r') as f:
            return {line.strip() for line in f if line.strip() and not line.startswith('#')}

    def reload_whitelist(self):
        self.log_func("🔄 Lade Whitelist neu...", "info")
        old_count = len(self.whitelist)
        self.whitelist = self._load_whitelist()
        new_count = len(self.whitelist)
        self.log_func(f"{DesignSystem.ICONS['success']} Whitelist neu geladen. {old_count} → {new_count} Adressen.", "success")
        self.reload_event.set()

    def get_stats(self) -> dict:
        runtime = datetime.now() - self.stats['start_time']
        return {
            **self.stats,
            'runtime_seconds': int(runtime.total_seconds()),
            'whitelist_size': len(self.whitelist)
        }

    async def _freeze_account(self, ata_to_freeze: Pubkey, role: str):
        self.log_func(f"❄️ Friere Konto für {role} ein: {ata_to_freeze}...", "error")
        freeze_params = FreezeAccountParams(
            program_id=TOKEN_PROGRAM_ID, 
            account=ata_to_freeze, 
            mint=self.mint_keypair.pubkey(), 
            authority=self.payer_keypair.pubkey()
        )
        confirm_and_send_transaction(
            self.http_client, 
            [freeze_account(freeze_params)],
            [self.payer_keypair], 
            f"Freeze {role} Konto", 
            self.log_func
        )
        self.stats['accounts_frozen'] += 1

    async def _analyze_transaction(self, signature_str: str):
        if signature_str in self.processed_signatures: 
            return
        self.processed_signatures.append(signature_str)
        self.stats['transactions_analyzed'] += 1
        
        self.log_func(f"\n--- Transaktions-Analyse: {signature_str} ---", "header")
        
        try:
            sig = Signature.from_string(signature_str)
            tx_resp = await self.async_http_client.get_transaction(sig, max_supported_transaction_version=0)
            
            if not tx_resp or not tx_resp.value or not tx_resp.value.transaction:
                self.log_func("→ Transaktion nicht gefunden.", "error")
                return
            
            tx_meta = tx_resp.value.transaction.meta
            if tx_meta.err: 
                self.log_func("→ Transaktion fehlgeschlagen, wird ignoriert.", "info")
                return

            if tx_resp.value.block_time:
                ts = datetime.fromtimestamp(tx_resp.value.block_time).strftime('%Y-%m-%d %H:%M:%S')
                self.log_func(f"Zeitstempel: {ts}", "info")
            
            account_keys = tx_resp.value.transaction.transaction.message.account_keys
            balance_changes = {} 

            for balance in (tx_meta.pre_token_balances + tx_meta.post_token_balances):
                if balance.mint == self.mint_keypair.pubkey():
                    owner_str = str(balance.owner)
                    if owner_str not in balance_changes:
                        balance_changes[owner_str] = {'ata': account_keys[balance.account_index], 'pre': 0, 'post': 0}
            
            for pre in tx_meta.pre_token_balances:
                if str(pre.owner) in balance_changes: 
                    balance_changes[str(pre.owner)]['pre'] = int(pre.ui_token_amount.amount)
            for post in tx_meta.post_token_balances:
                if str(post.owner) in balance_changes: 
                    balance_changes[str(post.owner)]['post'] = int(post.ui_token_amount.amount)

            sender, recipient, amount = None, None, 0
            for owner, data in balance_changes.items():
                change = data['post'] - data['pre']
                if change < 0:
                    sender = owner
                    amount = abs(change) / (10**self.TOKEN_DECIMALS)
                elif change > 0:
                    recipient = owner

            if not sender or not recipient: 
                self.log_func("→ Kein Transfer (z.B. Mint/Burn). Wird ignoriert.", "info")
                return

            self.log_func(f"Absender:    {truncate_address(sender)}", "info")
            self.log_func(f"Empfänger:   {truncate_address(recipient)}", "info")
            self.log_func(f"Menge:       {format_token_amount(amount, 6)} Tokens", "info")

            # Whitelist-Prüfung auf den EMPFÄNGER
            self.log_func(f"Prüfe Empfänger: {truncate_address(recipient)}", "info")
            if recipient in self.whitelist:
                self.log_func("STATUS: ✅ Empfänger ist autorisiert (auf der Whitelist).", "success")
            else:
                self.log_func("STATUS: 🚨 Whitelist-Verstoß! Empfänger ist nicht autorisiert.", "error")
                self.stats['violations_detected'] += 1
                
                # Benachrichtigung senden
                if self.notification_callback:
                    self.notification_callback("Whitelist-Verstoß", f"Nicht autorisierter Transfer an {truncate_address(recipient)}")
                
                recipient_ata = balance_changes[recipient]['ata']
                await self._freeze_account(recipient_ata, "Empfänger")
                
                if self.freeze_sender_on_violation:
                    self.log_func("→ Option 'Absender ebenfalls einfrieren' ist aktiv.", "info")
                    sender_ata = balance_changes[sender]['ata']
                    await self._freeze_account(sender_ata, "Absender")

        except Exception as e: 
            self.log_func(f"{DesignSystem.ICONS['error']} Fehler bei der Transaktionsanalyse: {e}", "error")
        finally:
            self.log_func("--------------------------------------------------", "header")

    async def run(self):
        while not self.stop_event.is_set():
            self.reload_event.clear()
            accounts_to_watch = set()
            self.log_func("\nBerechne zu überwachende ATAs aus der Whitelist...", "info")
            
            for owner_addr in self.whitelist:
                try: 
                    ata = get_associated_token_address(owner=Pubkey.from_string(owner_addr), mint=self.mint_keypair.pubkey())
                    accounts_to_watch.add(str(ata))
                except ValueError: 
                    self.log_func(f"  - Ungültige Adresse übersprungen: {owner_addr}", "warning")
            
            if not accounts_to_watch:
                self.log_func("⚠️ Whitelist ist leer oder ungültig. Warte 10s.", "warning")
                await asyncio.sleep(10)
                continue

            try:
                async with websockets.connect(self.ws_uri) as websocket:
                    self.log_func(f"🔌 Verbunden mit WebSocket: {self.ws_uri}", "success")
                    req_id_counter = 1
                    sub_id_to_pubkey = {}
                    
                    for acc_str in accounts_to_watch:
                        await websocket.send(json.dumps({
                            "jsonrpc": "2.0", 
                            "id": req_id_counter, 
                            "method": "accountSubscribe", 
                            "params": [acc_str, {"encoding": "jsonParsed", "commitment": "finalized"}]
                        }))
                        
                        try:
                            response = json.loads(await asyncio.wait_for(websocket.recv(), timeout=10.0))
                            if 'result' in response:
                                sub_id_to_pubkey[response['result']] = acc_str
                                self.log_func(f"  → Abo für {truncate_address(acc_str)} bestätigt.", "info")
                            else: 
                                self.log_func(f"  → Fehler beim Abo für {truncate_address(acc_str)}: {response.get('error')}", "error")
                        except asyncio.TimeoutError: 
                            self.log_func(f"  → Timeout beim Abo für {truncate_address(acc_str)}.", "error")
                        req_id_counter += 1

                    if not sub_id_to_pubkey: 
                        await asyncio.sleep(10)
                        continue
                    
                    self.log_func(f"\n{DesignSystem.ICONS['success']} Erfolgreich angemeldet. Warte auf Konto-Änderungen...", "success")
                    
                    while not self.stop_event.is_set() and not self.reload_event.is_set():
                        try:
                            message_str = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                            data = json.loads(message_str)
                            if data.get('method') == 'accountNotification':
                                sub_id = data['params']['subscription']
                                if sub_id in sub_id_to_pubkey:
                                    changed_acc = Pubkey.from_string(sub_id_to_pubkey[sub_id])
                                    sigs_resp = await self.async_http_client.get_signatures_for_address(changed_acc, limit=1)
                                    if sigs_resp.value: 
                                        await self._analyze_transaction(str(sigs_resp.value[0].signature))
                        except asyncio.TimeoutError: 
                            continue
            except Exception as e:
                self.log_func(f"🔌 Fehler: {e}. Versuche in 10s erneut...", "error")
                await asyncio.sleep(10)
        
        self.log_func("--- Monitor-Bot wurde gestoppt. ---", "header")
        await self.async_http_client.close()

# === Verbesserte grafische Benutzeroberfläche ===

class MonitorUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Whitelist Monitor - Verbesserte Version")
        self.geometry("1200x800")
        self.minsize(1000, 600)
        
        # Design-System anwenden
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        # State
        self.log_queue = queue.Queue()
        self.monitor_thread = None
        self.monitor_instance = None
        self.stop_event = None
        self.reload_event = None
        self.stats_update_job = None

        self._create_widgets()
        self.after(200, self.process_log_queue)
        self.update_whitelist_display()
        self._start_stats_updates()

    def _create_widgets(self):
        """Erstellt die Hauptbenutzeroberfläche"""
        # --- Header mit Kontrollen ---
        self._create_header()
        
        # --- Hauptinhalt mit Tabs ---
        self._create_main_content()

    def _create_header(self):
        """Erstellt den Header-Bereich"""
        header_frame = ctk.CTkFrame(self, corner_radius=DesignSystem.RADIUS['lg'])
        header_frame.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], 
                         pady=DesignSystem.SPACING['md'], sticky="ew")
        header_frame.grid_columnconfigure(2, weight=1)
        
        # Titel
        title_label = ctk.CTkLabel(
            header_frame, 
            text=f"{DesignSystem.ICONS['search']} Whitelist Monitor", 
            font=ctk.CTkFont(size=20, weight="bold")
        )
        title_label.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], 
                        pady=DesignSystem.SPACING['md'], sticky="w")
        
        # Kontrollen
        controls_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        controls_frame.grid(row=0, column=1, padx=DesignSystem.SPACING['md'], 
                           pady=DesignSystem.SPACING['md'])
        
        self.start_button = ctk.CTkButton(
            controls_frame, 
            text=f"{DesignSystem.ICONS['start']} Start", 
            command=self.start_monitor,
            fg_color=DesignSystem.COLORS['success']
        )
        self.start_button.pack(side="left", padx=(0, DesignSystem.SPACING['sm']))
        
        self.stop_button = ctk.CTkButton(
            controls_frame, 
            text=f"{DesignSystem.ICONS['stop']} Stop", 
            command=self.stop_monitor, 
            state="disabled",
            fg_color=DesignSystem.COLORS['error']
        )
        self.stop_button.pack(side="left", padx=DesignSystem.SPACING['sm'])
        
        # Status und Optionen
        status_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        status_frame.grid(row=0, column=2, padx=DesignSystem.SPACING['md'], 
                         pady=DesignSystem.SPACING['md'], sticky="e")
        
        self.status_indicator = StatusIndicator(
            status_frame, 
            status="unknown", 
            text="Gestoppt"
        )
        self.status_indicator.pack(side="top", anchor="e")
        
        # Freeze-Option
        self.freeze_sender_check = ctk.CTkCheckBox(
            status_frame, 
            text="Absender bei Verstoß ebenfalls einfrieren"
        )
        self.freeze_sender_check.pack(side="bottom", anchor="e", pady=(DesignSystem.SPACING['sm'], 0))
        self.freeze_sender_check.select()

    def _create_main_content(self):
        """Erstellt den Hauptinhalt mit Tabs"""
        self.tab_view = ctk.CTkTabview(self, corner_radius=DesignSystem.RADIUS['lg'])
        self.tab_view.grid(row=1, column=0, padx=DesignSystem.SPACING['md'], 
                          pady=(0, DesignSystem.SPACING['md']), sticky="nsew")
        
        # Tabs hinzufügen
        self.tab_view.add("📊 Dashboard")
        self.tab_view.add("📋 Live Log")
        self.tab_view.add("📝 Whitelist")
        self.tab_view.add("⚙️ Einstellungen")
        
        self._create_dashboard_tab(self.tab_view.tab("📊 Dashboard"))
        self._create_log_tab(self.tab_view.tab("📋 Live Log"))
        self._create_whitelist_tab(self.tab_view.tab("📝 Whitelist"))
        self._create_settings_tab(self.tab_view.tab("⚙️ Einstellungen"))

    def _create_dashboard_tab(self, tab):
        """Erstellt das Dashboard mit Statistiken"""
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        
        # Statistik-Karten
        stats_frame = ctk.CTkFrame(tab, fg_color="transparent")
        stats_frame.grid(row=0, column=0, columnspan=2, padx=DesignSystem.SPACING['md'], 
                        pady=DesignSystem.SPACING['md'], sticky="ew")
        stats_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)
        
        # Einzelne Statistik-Karten
        self.stats_cards = {}
        
        runtime_card = self._create_stat_card(stats_frame, "⏱️", "Laufzeit", "0s")
        runtime_card.grid(row=0, column=0, padx=DesignSystem.SPACING['sm'], sticky="ew")
        self.stats_cards['runtime'] = runtime_card
        
        tx_card = self._create_stat_card(stats_frame, "📊", "Transaktionen", "0")
        tx_card.grid(row=0, column=1, padx=DesignSystem.SPACING['sm'], sticky="ew")
        self.stats_cards['transactions'] = tx_card
        
        violations_card = self._create_stat_card(stats_frame, "🚨", "Verstöße", "0")
        violations_card.grid(row=0, column=2, padx=DesignSystem.SPACING['sm'], sticky="ew")
        self.stats_cards['violations'] = violations_card
        
        frozen_card = self._create_stat_card(stats_frame, "❄️", "Gesperrt", "0")
        frozen_card.grid(row=0, column=3, padx=DesignSystem.SPACING['sm'], sticky="ew")
        self.stats_cards['frozen'] = frozen_card
        
        # Whitelist-Info
        whitelist_frame = ctk.CTkFrame(tab, corner_radius=DesignSystem.RADIUS['md'])
        whitelist_frame.grid(row=1, column=0, padx=DesignSystem.SPACING['md'], 
                           pady=DesignSystem.SPACING['md'], sticky="nsew")
        whitelist_frame.grid_columnconfigure(0, weight=1)
        whitelist_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(
            whitelist_frame, 
            text="📝 Whitelist Übersicht", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, padx=DesignSystem.SPACING['md'], 
               pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['sm']), sticky="w")
        
        self.whitelist_preview = ctk.CTkTextbox(
            whitelist_frame, 
            state="disabled",
            font=ctk.CTkFont(family="monospace", size=10)
        )
        self.whitelist_preview.grid(row=1, column=0, padx=DesignSystem.SPACING['md'], 
                                   pady=(0, DesignSystem.SPACING['md']), sticky="nsew")
        
        # Aktuelle Aktivität
        activity_frame = ctk.CTkFrame(tab, corner_radius=DesignSystem.RADIUS['md'])
        activity_frame.grid(row=1, column=1, padx=DesignSystem.SPACING['md'], 
                           pady=DesignSystem.SPACING['md'], sticky="nsew")
        activity_frame.grid_columnconfigure(0, weight=1)
        activity_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(
            activity_frame, 
            text="🔄 Aktuelle Aktivität", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, padx=DesignSystem.SPACING['md'], 
               pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['sm']), sticky="w")
        
        self.activity_log = ctk.CTkTextbox(
            activity_frame, 
            state="disabled",
            font=ctk.CTkFont(family="monospace", size=10)
        )
        self.activity_log.grid(row=1, column=0, padx=DesignSystem.SPACING['md'], 
                              pady=(0, DesignSystem.SPACING['md']), sticky="nsew")

        # Tags für Farben im Activity Log hinzufügen
        self.activity_log.tag_config("info", foreground=DesignSystem.COLORS['info'])
        self.activity_log.tag_config("warning", foreground=DesignSystem.COLORS['warning'])
        self.activity_log.tag_config("error", foreground=DesignSystem.COLORS['error'])
        self.activity_log.tag_config("success", foreground=DesignSystem.COLORS['success'])
        self.activity_log.tag_config("header", foreground=DesignSystem.COLORS['text_secondary'])


    def _create_stat_card(self, parent, icon: str, title: str, value: str):
        """Erstellt eine Statistik-Karte"""
        card = ctk.CTkFrame(parent, corner_radius=DesignSystem.RADIUS['md'])
        
        icon_label = ctk.CTkLabel(card, text=icon, font=ctk.CTkFont(size=24))
        icon_label.pack(pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['sm']))
        
        value_label = ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=20, weight="bold"))
        value_label.pack()
        
        title_label = ctk.CTkLabel(
            card, 
            text=title, 
            font=ctk.CTkFont(size=12),
            text_color=DesignSystem.COLORS['text_secondary']
        )
        title_label.pack(pady=(0, DesignSystem.SPACING['md']))
        
        card.value_label = value_label
        card.title_label = title_label
        
        return card

    def _create_log_tab(self, tab):
        """Erstellt den Log-Tab"""
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        
        self.log_textbox = EnhancedTextbox(tab)
        self.log_textbox.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], 
                             pady=DesignSystem.SPACING['md'], sticky="nsew")

    def _create_whitelist_tab(self, tab):
        """Erstellt den Whitelist-Tab"""
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        
        header_frame = ctk.CTkFrame(tab, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], 
                         pady=DesignSystem.SPACING['md'], sticky="ew")
        header_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(
            header_frame, 
            text="📝 Whitelist Verwaltung", 
            font=ctk.CTkFont(size=18, weight="bold")
        ).grid(row=0, column=0, sticky="w")
        
        actions_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        actions_frame.grid(row=0, column=1, sticky="e")
        
        reload_button = ctk.CTkButton(actions_frame, text=f"{DesignSystem.ICONS['refresh']} Neu laden", command=self.reload_whitelist_action, width=120)
        reload_button.pack(side="right", padx=(DesignSystem.SPACING['sm'], 0))
        
        edit_button = ctk.CTkButton(actions_frame, text=f"{DesignSystem.ICONS['edit']} Bearbeiten", command=self._edit_whitelist, width=120)
        edit_button.pack(side="right", padx=(DesignSystem.SPACING['sm'], 0))
        
        import_button = ctk.CTkButton(actions_frame, text=f"{DesignSystem.ICONS['expand']} Importieren", command=self._import_whitelist, width=120)
        import_button.pack(side="right")
        
        self.whitelist_textbox = ctk.CTkTextbox(
            tab, 
            state="disabled", 
            wrap="word",
            font=ctk.CTkFont(family="monospace", size=11)
        )
        self.whitelist_textbox.grid(row=1, column=0, padx=DesignSystem.SPACING['md'], 
                                   pady=(0, DesignSystem.SPACING['md']), sticky="nsew")

    def _create_settings_tab(self, tab):
        """Erstellt den Einstellungen-Tab"""
        tab.grid_columnconfigure(0, weight=1)
        
        monitor_frame = ctk.CTkFrame(tab, corner_radius=DesignSystem.RADIUS['md'])
        monitor_frame.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], 
                          pady=DesignSystem.SPACING['md'], sticky="ew")
        
        ctk.CTkLabel(
            monitor_frame, 
            text=f"{DesignSystem.ICONS['settings']} Monitor-Einstellungen", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(padx=DesignSystem.SPACING['md'], 
               pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), anchor="w")
        
        notifications_frame = ctk.CTkFrame(monitor_frame, fg_color="transparent")
        notifications_frame.pack(fill="x", padx=DesignSystem.SPACING['md'], 
                                 pady=DesignSystem.SPACING['sm'])
        
        self.notifications_enabled = ctk.CTkCheckBox(notifications_frame, text="Desktop-Benachrichtigungen bei Verstößen")
        self.notifications_enabled.pack(side="left")
        
        auto_reload_frame = ctk.CTkFrame(monitor_frame, fg_color="transparent")
        auto_reload_frame.pack(fill="x", padx=DesignSystem.SPACING['md'], 
                              pady=DesignSystem.SPACING['sm'])
        
        self.auto_reload_enabled = ctk.CTkCheckBox(auto_reload_frame, text="Whitelist automatisch neu laden bei Änderungen")
        self.auto_reload_enabled.pack(side="left")
        
        connection_frame = ctk.CTkFrame(tab, corner_radius=DesignSystem.RADIUS['md'])
        connection_frame.grid(row=1, column=0, padx=DesignSystem.SPACING['md'], 
                             pady=DesignSystem.SPACING['md'], sticky="ew")
        
        ctk.CTkLabel(
            connection_frame, 
            text=f"{DesignSystem.ICONS['info']} Verbindungsinformationen", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(padx=DesignSystem.SPACING['md'], 
               pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), anchor="w")
        
        try:
            config = load_config()
            if config:
                rpc_frame = ctk.CTkFrame(connection_frame, fg_color="transparent")
                rpc_frame.pack(fill="x", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'])
                ctk.CTkLabel(rpc_frame, text="RPC Endpunkt:", width=120, anchor="w").pack(side="left")
                CopyableLabel(rpc_frame, text=config['rpc_url']).pack(side="left", fill="x", expand=True)
                
                wallet_frame = ctk.CTkFrame(connection_frame, fg_color="transparent")
                wallet_frame.pack(fill="x", padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['sm'], DesignSystem.SPACING['md']))
                ctk.CTkLabel(wallet_frame, text="Wallet-Ordner:", width=120, anchor="w").pack(side="left")
                CopyableLabel(wallet_frame, text=config['wallet_folder']).pack(side="left", fill="x", expand=True)
        except:
            pass

    # === Event-Handler ===

    def _edit_whitelist(self):
        """Öffnet Whitelist-Editor"""
        try:
            config = load_config()
            if not config: return
            
            whitelist_path = os.path.join(config['wallet_folder'], "whitelist.txt")
            
            editor = WhitelistEditor(self, whitelist_path)
            self.wait_window(editor)
            
            self.update_whitelist_display()
            if self.monitor_instance:
                self.monitor_instance.reload_whitelist()
                
        except Exception as e:
            show_error(self, "Fehler beim Bearbeiten", f"Whitelist konnte nicht bearbeitet werden:\n\n{e}")

    def _import_whitelist(self):
        """Importiert Whitelist aus Datei"""
        try:
            file_path = filedialog.askopenfilename(
                title="Whitelist importieren",
                filetypes=[("Text-Dateien", "*.txt"), ("Alle Dateien", "*.*")]
            )
            
            if not file_path: return
            
            config = load_config()
            if not config: return
            
            whitelist_path = os.path.join(config['wallet_folder'], "whitelist.txt")
            
            if ConfirmDialog.show(self, "Import bestätigen", 
                                "Möchten Sie die aktuelle Whitelist durch die importierte Datei ersetzen?",
                                confirm_text="Importieren", danger=True):
                
                with open(file_path, 'r') as src, open(whitelist_path, 'w') as dst:
                    dst.write(src.read())
                
                show_info(self, "Import erfolgreich", "Whitelist wurde erfolgreich importiert.")
                self.update_whitelist_display()
                
                if self.monitor_instance:
                    self.monitor_instance.reload_whitelist()
                    
        except Exception as e:
            show_error(self, "Import-Fehler", f"Whitelist konnte nicht importiert werden:\n\n{e}")

    def _show_notification(self, title: str, message: str):
        """Zeigt Desktop-Benachrichtigung (falls aktiviert)"""
        if self.notifications_enabled.get():
            self.log(f"🔔 BENACHRICHTIGUNG: {title} - {message}", "warning")

    # === Monitor-Kontrolle ===

    def start_monitor(self):
        """Startet den Monitor"""
        self.log_textbox.clear_text()
        self.log("INFO: Monitor wird gestartet...", "info")
        
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.freeze_sender_check.configure(state="disabled")
        self.status_indicator.set_status("info", "Initialisierung...")

        self.stop_event = threading.Event()
        self.reload_event = threading.Event()
        
        try:
            config = load_config()
            if not config: 
                raise ValueError("Konfiguration konnte nicht geladen werden.")
            
            freeze_sender = self.freeze_sender_check.get()
            self.monitor_instance = WhitelistMonitorBot(
                config, self.log, self.stop_event, self.reload_event, 
                freeze_sender, self._show_notification
            )
            
            self.monitor_thread = threading.Thread(target=self.run_monitor_in_thread, daemon=True)
            self.monitor_thread.start()
            self.status_indicator.set_status("success", "Läuft")
            
        except Exception as e:
            self.log(f"FEHLER: Start fehlgeschlagen - {e}", "error")
            self.stop_monitor()
            show_error(self, "Startfehler", f"Der Monitor konnte nicht gestartet werden:\n\n{e}")
            
    def run_monitor_in_thread(self):
        """Führt Monitor in separatem Thread aus"""
        try:
            asyncio.run(self.monitor_instance.run())
        except Exception as e:
            self.log(f"FEHLER im Monitor-Thread: {e}", "error")
        finally:
            self.after(0, self.stop_monitor)

    def stop_monitor(self):
        """Stoppt den Monitor"""
        if self.stop_event: 
            self.stop_event.set()
        
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.freeze_sender_check.configure(state="normal")
        self.status_indicator.set_status("unknown", "Gestoppt")
        
        self.monitor_instance = None
        self.monitor_thread = None

    # === UI-Updates ===

    def log(self, message, level="info"):
        """Fügt Nachricht zum Log hinzu"""
        self.log_queue.put((message, level))

    def process_log_queue(self):
        """Verarbeitet Log-Nachrichten"""
        try:
            while True:
                message, level = self.log_queue.get_nowait()
                self.log_textbox.append_text(message, level)
                
                # Auch zur Aktivitäts-Anzeige hinzufügen
                if level in ['success', 'error', 'warning', 'info', 'header']:
                    self._add_to_activity(message, level)
                    
        except queue.Empty:
            pass
        finally:
            self.after(200, self.process_log_queue)

    def _add_to_activity(self, message: str, level: str):
        """Fügt Nachricht mit Farbe zur Aktivitäts-Anzeige hinzu."""
        try:
            self.activity_log.configure(state="normal")
            
            # Zeilen-Limit prüfen und ggf. die älteste Zeile löschen
            current_text = self.activity_log.get("1.0", "end-1c")
            lines = current_text.split('\n') if current_text else []
            if len(lines) >= 20:
                self.activity_log.delete("1.0", "2.0")

            # Neue Zeile einfügen
            timestamp = datetime.now().strftime("%H:%M:%S")
            line_to_add = f"[{timestamp}] {message}\n"
            start_pos = self.activity_log.index("end-1c")
            self.activity_log.insert("end", line_to_add)
            end_pos = self.activity_log.index("end-1c")

            # Farbe anwenden
            if level in ['success', 'error', 'warning', 'info', 'header']:
                self.activity_log.tag_add(level, start_pos, end_pos)
            
            self.activity_log.configure(state="disabled")
            self.activity_log.see("end")
        except Exception:
            # UI-Thread bei Log-Fehlern nicht abstürzen lassen
            pass

    def update_whitelist_display(self):
        """Aktualisiert Whitelist-Anzeige"""
        try:
            config = load_config()
            if not config: return
            
            path = os.path.join(config['wallet_folder'], "whitelist.txt")
            
            content = ""
            if os.path.exists(path):
                with open(path, 'r') as f:
                    content = f.read()
            else:
                content = "# Whitelist-Datei nicht gefunden\n# Bitte erstellen Sie eine whitelist.txt im Wallet-Ordner"
            
            self.whitelist_textbox.configure(state="normal")
            self.whitelist_textbox.delete("1.0", "end")
            self.whitelist_textbox.insert("1.0", content)
            self.whitelist_textbox.configure(state="disabled")
            
            preview_lines = content.split("\n")[:10]
            preview = "\n".join(preview_lines)
            if len(content.split("\n")) > 10:
                preview += "\n... (weitere Einträge)"
            
            self.whitelist_preview.configure(state="normal")
            self.whitelist_preview.delete("1.0", "end")
            self.whitelist_preview.insert("1.0", preview)
            self.whitelist_preview.configure(state="disabled")
            
        except Exception as e:
            error_text = f"Fehler beim Laden der Whitelist:\n{e}"
            self.whitelist_textbox.configure(state="normal")
            self.whitelist_textbox.delete("1.0", "end")
            self.whitelist_textbox.insert("1.0", error_text)
            self.whitelist_textbox.configure(state="disabled")

    def reload_whitelist_action(self):
        """Lädt Whitelist neu"""
        self.update_whitelist_display()
        if self.monitor_instance:
            self.monitor_instance.reload_whitelist()

    def _start_stats_updates(self):
        """Startet regelmäßige Statistik-Updates"""
        self._update_stats()
        self.stats_update_job = self.after(2000, self._start_stats_updates)

    def _update_stats(self):
        """Aktualisiert Statistik-Anzeige"""
        if self.monitor_instance:
            stats = self.monitor_instance.get_stats()
            
            runtime_seconds = stats['runtime_seconds']
            if runtime_seconds < 60: runtime_text = f"{runtime_seconds}s"
            elif runtime_seconds < 3600: runtime_text = f"{runtime_seconds // 60}m {runtime_seconds % 60}s"
            else:
                hours = runtime_seconds // 3600
                minutes = (runtime_seconds % 3600) // 60
                runtime_text = f"{hours}h {minutes}m"
            
            self.stats_cards['runtime'].value_label.configure(text=runtime_text)
            self.stats_cards['transactions'].value_label.configure(text=str(stats['transactions_analyzed']))
            self.stats_cards['violations'].value_label.configure(text=str(stats['violations_detected']))
            self.stats_cards['frozen'].value_label.configure(text=str(stats['accounts_frozen']))

    def on_closing(self):
        """Behandelt Fenster-Schließen"""
        if self.stats_update_job:
            self.after_cancel(self.stats_update_job)
        self.stop_monitor()
        self.destroy()

# === Whitelist-Editor ===

class WhitelistEditor(ctk.CTkToplevel):
    """Einfacher Editor für die Whitelist"""
    
    def __init__(self, parent, file_path: str):
        super().__init__(parent)
        
        self.file_path = file_path
        
        self.title("Whitelist bearbeiten")
        self.geometry("600x500")
        self.transient(parent)
        self.grab_set()
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        header_label = ctk.CTkLabel(self, text="📝 Whitelist bearbeiten", font=ctk.CTkFont(size=16, weight="bold"))
        header_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        self.text_editor = ctk.CTkTextbox(self, wrap="word", font=ctk.CTkFont(family="monospace", size=11))
        self.text_editor.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=2, column=0, padx=20, pady=(0, 20))
        
        cancel_button = ctk.CTkButton(button_frame, text="Abbrechen", command=self.destroy, fg_color=DesignSystem.COLORS['secondary'])
        cancel_button.pack(side="left", padx=(0, 10))
        
        save_button = ctk.CTkButton(button_frame, text=f"{DesignSystem.ICONS['save']} Speichern", command=self._save_file, fg_color=DesignSystem.COLORS['success'])
        save_button.pack(side="left")
        
        self._load_file()
        
        self.bind("<Control-s>", lambda e: self._save_file())
        self.bind("<Escape>", lambda e: self.destroy())

    def _load_file(self):
        """Lädt Datei in Editor"""
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, 'r') as f:
                    content = f.read()
            else:
                content = "# Whitelist - Eine Adresse pro Zeile\n# Kommentare beginnen mit #\n\n"
            
            self.text_editor.insert("1.0", content)
        except Exception as e:
            show_error(self, "Fehler beim Laden", f"Datei konnte nicht geladen werden:\n\n{e}")

    def _save_file(self):
        """Speichert Datei"""
        try:
            content = self.text_editor.get("1.0", "end-1c")
            
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            
            with open(self.file_path, 'w') as f:
                f.write(content)
            
            show_info(self, "Gespeichert", "Whitelist wurde erfolgreich gespeichert.")
            self.destroy()
            
        except Exception as e:
            show_error(self, "Fehler beim Speichern", f"Datei konnte nicht gespeichert werden:\n\n{e}")

if __name__ == "__main__":
    app = MonitorUI()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()

