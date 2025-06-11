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
from collections import deque, defaultdict
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
        freeze_account, FreezeAccountParams,
        thaw_account, ThawAccountParams
    )
    from spl.token.constants import TOKEN_PROGRAM_ID
except ImportError as e:
    messagebox.showerror("Fehler", f"Erforderliche Solana-Bibliotheken fehlen: {e}. Bitte installieren Sie diese.")
    sys.exit(1)

# === Strukturiertes Logging Setup ===
def setup_transaction_logger():
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
    ICONS = {'start': '▶', 'stop': '■', 'refresh': '🔄', 'edit': '✏️', 'save': '💾', 'expand': '📂', 'search': '🔍', 'settings': '⚙️', 'info': 'ℹ️', 'success': '✅', 'error': '❌', 'graph': '🌐', 'debug_on': '🐞✅', 'debug_off': '🐞❌', 'freeze': '❄️', 'thaw': '☀️'}

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
        self.tag_config("debug", foreground=DesignSystem.COLORS['secondary'])

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
    except Exception as e:
        print(f"DEBUG (load_config): Fehler beim Laden von config.json: {e}")
        return None

def load_keypair(wallet_folder: str, filename: str):
    path = os.path.join(wallet_folder, filename)
    if not os.path.exists(path):
        print(f"DEBUG (load_keypair): Wallet-Datei '{path}' nicht gefunden.")
        raise FileNotFoundError(f"Wallet-Datei '{path}' nicht gefunden.")
    with open(path, 'r') as f: return Keypair.from_bytes(bytes(json.load(f)))

def load_whitelist(wallet_folder: str) -> set:
    path = os.path.join(wallet_folder, "whitelist.txt")
    if not os.path.exists(path):
        print(f"DEBUG (load_whitelist): whitelist.txt in '{wallet_folder}' nicht gefunden, leere Whitelist wird verwendet.")
        return set()
    with open(path, 'r', encoding='utf-8') as f: return {line.strip() for line in f if line.strip() and not line.startswith('#')}

# === Netzwerk-Visualisierung ===
class NetworkVisualizer:
    def __init__(self, log_file: str, whitelist: Set[str], output_path: str):
        self.log_file, self.whitelist, self.output_path = log_file, whitelist, output_path

    def generate_graph(self):
        if not os.path.exists(self.log_file):
            print(f"DEBUG (NetworkVisualizer): Log-Datei '{self.log_file}' nicht gefunden.")
            raise FileNotFoundError(f"Log-Datei '{self.log_file}' nicht gefunden.")
        
        all_wallets, balances, flows, final_frozen_wallets = set(), defaultdict(float), defaultdict(float), set()
        with open(self.log_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    tx = json.loads(line)
                    status = tx.get('status')
                    sender, recipient, amount = tx.get('sender'), tx.get('recipient'), tx.get('amount', 0)
                    if sender and recipient and isinstance(amount, (int, float)) and amount > 0:
                        all_wallets.update([sender, recipient]); balances[sender] -= amount; balances[recipient] += amount
                        flows[tuple(sorted((sender, recipient)))] += amount
                    
                    if status == 'VIOLATION_FROZEN': final_frozen_wallets.update(tx.get('frozen_wallets', []))
                    elif status in ['ACCOUNT_FROZEN', 'MANUAL_ACCOUNT_FROZEN']: 
                        wallet = tx.get('frozen_wallet')
                        if wallet: all_wallets.add(wallet); final_frozen_wallets.add(wallet)
                    elif status in ['ACCOUNT_THAWED', 'MANUAL_ACCOUNT_THAWED']: 
                        wallet = tx.get('thawed_wallet')
                        if wallet and wallet in final_frozen_wallets: final_frozen_wallets.remove(wallet)
                except (json.JSONDecodeError, TypeError, ValueError): continue
        
        net = Network(height="95vh", width="100%", bgcolor="#222222", font_color="white", notebook=True, cdn_resources='in_line')
        all_wallets.update(addr for pair in flows for addr in pair); all_wallets.update(final_frozen_wallets)
        for wallet in all_wallets:
            color = DesignSystem.COLORS['error'] if wallet in final_frozen_wallets else (DesignSystem.COLORS['success'] if wallet in self.whitelist else DesignSystem.COLORS['primary'])
            balance_str = f"{balances[wallet]:.4f}".rstrip('0').rstrip('.'); node_title = f"{wallet}<br><b>Berechneter Bestand:</b> {balance_str} Tokens"
            net.add_node(wallet, label=truncate_address(wallet), title=node_title, color=color)
        for (addr1, addr2), total_amount in flows.items():
            amount_str = f"{total_amount:.4f}".rstrip('0').rstrip('.'); edge_title = f"<b>Gesamtvolumen:</b><br>{amount_str} Tokens"
            net.add_edge(addr1, addr2, title=edge_title, value=total_amount, label=f"{amount_str}")
        net.set_options('{"edges": { "font": { "size": 14, "strokeWidth": 0 }, "smooth": { "type": "cubicBezier" } },"physics": { "barnesHut": { "gravitationalConstant": -2500, "centralGravity": 0.1, "springLength": 150 }, "minVelocity": 0.75 }}')
        try:
            with open(self.output_path, 'w', encoding='utf-8') as f: f.write(net.generate_html())
        except Exception as e: raise IOError(f"Fehler beim Speichern der HTML-Visualisierungsdatei: {e}")

# === Whitelist Monitor Logik ===
class WhitelistMonitorBot:
    TOKEN_DECIMALS = 9
    
    def __init__(self, config: dict, log_func, stop_event: threading.Event, reload_event: threading.Event, 
                 freeze_sender: bool, freeze_recipient: bool, transaction_logger, 
                 debug_mode: bool = False, notification_callback=None): 
        self.log_func = log_func 
        self.debug_mode = debug_mode
        
        if self.debug_mode: self.log_func("DEBUG: WhitelistMonitorBot.__init__ gestartet.", "debug")
        
        self.config, self.stop_event, self.reload_event = config, stop_event, reload_event 
        self.freeze_sender_on_violation = freeze_sender
        self.freeze_recipient_on_violation = freeze_recipient
        self.transaction_logger, self.notification_callback = transaction_logger, notification_callback
        
        if not config:
            self.log_func("FEHLER: Konfiguration ist None in WhitelistMonitorBot.__init__", "error")
            raise ValueError("Konfiguration darf nicht None sein.")
            
        self.wallet_folder = config.get('wallet_folder')
        rpc_url = config.get('rpc_url')

        if not self.wallet_folder or not rpc_url:
            msg = f"FEHLER: wallet_folder ('{self.wallet_folder}') oder rpc_url ('{rpc_url}') fehlt in der Konfiguration."
            self.log_func(msg, "error"); raise ValueError(msg)

        self.ws_uri = rpc_url.replace("http", "ws")
        self.stats = {'transactions_analyzed': 0, 'violations_detected': 0, 'accounts_frozen': 0, 'start_time': datetime.now()}
        
        self.log_func("--- Initialisiere Whitelist Monitor ---", "header")
        self.http_client = Client(rpc_url)
        self.async_http_client = AsyncClient(rpc_url)
        
        self.payer_keypair = load_keypair(self.wallet_folder, "payer-wallet.json")
        self.mint_keypair = load_keypair(self.wallet_folder, "mint-wallet.json")
        self.mint_pubkey = self.mint_keypair.pubkey() 
        
        self.whitelist = load_whitelist(self.wallet_folder)
        self.processed_signatures = deque(maxlen=500)

        if self.debug_mode: self.log_func(f"DEBUG: Payer Pubkey: {self.payer_keypair.pubkey()}", "debug")
        if self.debug_mode: self.log_func(f"DEBUG: Monitoring Mint Pubkey: {self.mint_pubkey}", "debug")
        self.log_func(f"{DesignSystem.ICONS['success']} Monitor initialisiert. Token: {self.mint_pubkey}", "success")
        self.log_func(f"👥 {len(self.whitelist)} Adressen auf Whitelist.", "info")
        if self.debug_mode: self.log_func("DEBUG: WhitelistMonitorBot.__init__ beendet.", "debug")

    def set_debug_mode(self, enabled: bool):
        self.debug_mode = enabled
        self.log_func(f"INFO: Debug-Modus {'aktiviert' if enabled else 'deaktiviert'}.", "info")

    def _extract_pubkeys_from_account_keys_raw(self, account_keys_raw, signature_str_for_log: str) -> list[Pubkey]:
        extracted_keys = []
        for k_item in account_keys_raw:
            actual_pubkey_to_add = None
            if isinstance(k_item, Pubkey): 
                actual_pubkey_to_add = k_item
            elif isinstance(k_item, str): 
                try: actual_pubkey_to_add = Pubkey.from_string(k_item)
                except Exception as e: self.log_func(f"WARNUNG (PubkeyExtraktion): Konnte Key String '{k_item}' nicht in Pubkey umwandeln für {signature_str_for_log}: {e}", "warning")
            elif hasattr(k_item, 'pubkey') and isinstance(k_item.pubkey, Pubkey): 
                actual_pubkey_to_add = k_item.pubkey
                if self.debug_mode: self.log_func(f"DEBUG (PubkeyExtraktion): Extrahiere Pubkey {actual_pubkey_to_add} aus Objekt mit pubkey-Attribut für {signature_str_for_log}", "debug")
            else: self.log_func(f"WARNUNG (PubkeyExtraktion): Unerwarteter Typ/Struktur in account_keys_raw für {signature_str_for_log}: {type(k_item)} - Wert: {k_item}. Ignoriert.", "warning")
            if actual_pubkey_to_add: extracted_keys.append(actual_pubkey_to_add)
        return extracted_keys

    def reload_whitelist(self):
        self.log_func("🔄 Lade Whitelist neu...", "info")
        old_count = len(self.whitelist)
        self.whitelist = load_whitelist(self.wallet_folder)
        self.log_func(f"{DesignSystem.ICONS['success']} Whitelist neu geladen. {old_count} → {len(self.whitelist)} Adressen.", "success")
        self.reload_event.set() 

    async def _freeze_account_on_chain(self, ata_to_freeze: Pubkey, owner_address: str, role: str): 
        self.log_func(f"❄️ Friere Konto für {role} ein: {owner_address}...", "error")
        try:
            params = FreezeAccountParams(program_id=TOKEN_PROGRAM_ID, account=ata_to_freeze, mint=self.mint_pubkey, authority=self.payer_keypair.pubkey())
            tx = Transaction.new_signed_with_payer(
                [freeze_account(params)], self.payer_keypair.pubkey(), [self.payer_keypair], 
                self.http_client.get_latest_blockhash().value.blockhash
            )
            self.http_client.send_transaction(tx) 
            self.log_func(f"{DesignSystem.ICONS['success']} ERFOLG '{role} Konto einfrieren'! Wallet: {owner_address}", "success")
            self.stats['accounts_frozen'] += 1
        except Exception as e:
            self.log_func(f"{DesignSystem.ICONS['error']} FEHLER bei '{role} Konto einfrieren': {e}", "error")

    async def _analyze_transaction(self, signature_str: str):
        if self.debug_mode: self.log_func(f"DEBUG: _analyze_transaction gestartet für Signatur: {signature_str}", "debug")
        if signature_str in self.processed_signatures:
            if self.debug_mode: self.log_func(f"DEBUG: Signatur {signature_str} bereits verarbeitet. Überspringe.", "debug")
            return

        try:
            if self.debug_mode: self.log_func(f"DEBUG: Hole Transaktion für Signatur: {signature_str}", "debug")
            sig = Signature.from_string(signature_str)
            tx_resp = await self.async_http_client.get_transaction(sig, max_supported_transaction_version=0, encoding="jsonParsed")
            if not tx_resp or not tx_resp.value or not tx_resp.value.transaction:
                if self.debug_mode: self.log_func(f"DEBUG: Keine gültige Transaktion für {signature_str}.", "debug"); return
            if tx_resp.value.transaction.meta and tx_resp.value.transaction.meta.err:
                if self.debug_mode: self.log_func(f"DEBUG: Transaktion {signature_str} mit Fehler: {tx_resp.value.transaction.meta.err}.", "debug"); return
            if self.debug_mode: self.log_func(f"DEBUG: Transaktion {signature_str} erfolgreich geholt.", "debug")
        except Exception as e:
            if self.debug_mode: self.log_func(f"DEBUG: Fehler beim Holen der Transaktion {signature_str}: {e}", "debug"); return

        tx_meta = tx_resp.value.transaction.meta
        has_mint_in_balances = any(
            hasattr(b, 'mint') and isinstance(b.mint, Pubkey) and b.mint == self.mint_pubkey
            for b in (getattr(tx_meta, 'pre_token_balances', []) or []) + (getattr(tx_meta, 'post_token_balances', []) or [])
        )
        if self.debug_mode: self.log_func(f"DEBUG: has_mint_in_balances: {has_mint_in_balances} für {signature_str}", "debug")
        if self.debug_mode and not has_mint_in_balances: 
             pre_b = getattr(tx_meta, 'pre_token_balances', []) or []
             post_b = getattr(tx_meta, 'post_token_balances', []) or []
             self.log_func(f"DEBUG: Pre-Token Balances Mints: {[str(b.mint) if hasattr(b, 'mint') else 'N/A' for b in pre_b]}", "debug")
             self.log_func(f"DEBUG: Post-Token Balances Mints: {[str(b.mint) if hasattr(b, 'mint') else 'N/A' for b in post_b]}", "debug")

        has_mint_in_instructions = False
        if tx_resp.value.transaction.transaction.message.instructions:
            for instruction_obj in tx_resp.value.transaction.transaction.message.instructions: # Umbenannt zu instruction_obj
                instruction_mint_str = None
                if hasattr(instruction_obj, 'parsed') and instruction_obj.parsed: # Für solders.ParsedInstruction
                    parsed_content = instruction_obj.parsed
                    if hasattr(parsed_content, 'info') and hasattr(getattr(parsed_content, 'info', None), 'mint'):
                        instruction_mint_str = str(getattr(getattr(parsed_content, 'info'), 'mint', ''))
                elif isinstance(instruction_obj, dict) and 'parsed' in instruction_obj: # Fallback für reine Dictionary-Struktur
                    info = instruction_obj.get('parsed', {}).get('info', {})
                    instruction_mint_str = info.get('mint')

                if instruction_mint_str == str(self.mint_pubkey):
                    has_mint_in_instructions = True; break
        
        if self.debug_mode: self.log_func(f"DEBUG: has_mint_in_instructions: {has_mint_in_instructions} für {signature_str}", "debug")
        if self.debug_mode and not has_mint_in_instructions and tx_resp.value.transaction.transaction.message.instructions: 
             instr_mints = []
             for instr in tx_resp.value.transaction.transaction.message.instructions:
                 if hasattr(instr, 'parsed') and instr.parsed and hasattr(instr.parsed, 'info') and hasattr(getattr(instr.parsed, 'info', None), 'mint'):
                     instr_mints.append(str(getattr(getattr(instr.parsed, 'info'), 'mint')))
                 elif isinstance(instr, dict) and 'parsed' in instr:
                     info = instr.get('parsed', {}).get('info', {})
                     if 'mint' in info: instr_mints.append(info['mint'])
             self.log_func(f"DEBUG: Mints in Instructions (Detail): {instr_mints}", "debug")
        
        if not (has_mint_in_balances or has_mint_in_instructions):
            if self.debug_mode: self.log_func(f"DEBUG: Mint {self.mint_pubkey} NICHT in TX {signature_str} gefunden.", "debug"); return
        if self.debug_mode: self.log_func(f"DEBUG: Mint {self.mint_pubkey} GEFUNDEN in TX {signature_str}. Verarbeite...", "debug")

        self.processed_signatures.append(signature_str); self.stats['transactions_analyzed'] += 1
        self.log_func(f"\n--- Analyse: {signature_str[:30]}... ---", "header")
        
        transfer_logged = self._log_transfer_if_present(tx_resp, signature_str)
        freeze_thaw_logged = await self._log_freeze_thaw_if_present(tx_resp, signature_str) 

        if not transfer_logged and not freeze_thaw_logged: 
            self.log_func("→ Keine relevante Aktion für diesen Token gefunden (z.B. Transfer anderer Tokens).", "info")
        self.log_func("------------------------------------------", "header")

    def _log_transfer_if_present(self, tx_resp, signature_str: str) -> bool:
        if self.debug_mode: self.log_func(f"DEBUG: _log_transfer_if_present für {signature_str}", "debug")
        tx_meta = tx_resp.value.transaction.meta
        log_entry = {'timestamp': datetime.utcnow().isoformat(), 'signature': signature_str, 'sender': None, 'recipient': None, 'amount': 0, 'status': 'UNKNOWN', 'frozen_wallets': []}
        try:
            account_keys_raw = tx_resp.value.transaction.transaction.message.account_keys
            account_keys = self._extract_pubkeys_from_account_keys_raw(account_keys_raw, signature_str) 
            if not account_keys: 
                self.log_func(f"FEHLER: Keine gültigen Account Keys für {signature_str} extrahiert. Abbruch Transfer-Analyse.", "error"); return False
            if self.debug_mode: self.log_func(f"DEBUG: Extrahierte Account Keys für {signature_str}: {[str(pk) for pk in account_keys]}", "debug")

            balance_changes = {}
            pre_balances, post_balances = getattr(tx_meta, 'pre_token_balances', []) or [], getattr(tx_meta, 'post_token_balances', []) or []
            for balance_obj in (pre_balances + post_balances):
                if hasattr(balance_obj, 'mint') and isinstance(balance_obj.mint, Pubkey) and balance_obj.mint == self.mint_pubkey:
                    if not hasattr(balance_obj, 'owner') or not hasattr(balance_obj, 'account_index'):
                        self.log_func(f"WARNUNG: Unvollständiges Balance-Objekt in {signature_str}: {balance_obj}", "warning"); continue
                    owner_pubkey, owner_str = balance_obj.owner, str(balance_obj.owner)
                    if balance_obj.account_index >= len(account_keys):
                        self.log_func(f"FEHLER: account_index {balance_obj.account_index} oob für {signature_str}.", "error"); continue 
                    if owner_str not in balance_changes: balance_changes[owner_str] = {'ata': account_keys[balance_obj.account_index], 'pre': 0, 'post': 0}
            for pre in pre_balances:
                if hasattr(pre, 'owner') and str(pre.owner) in balance_changes and hasattr(pre, 'ui_token_amount') and pre.ui_token_amount.amount and hasattr(pre, 'mint') and isinstance(pre.mint, Pubkey) and pre.mint == self.mint_pubkey:
                    balance_changes[str(pre.owner)]['pre'] = int(pre.ui_token_amount.amount)
            for post in post_balances:
                if hasattr(post, 'owner') and str(post.owner) in balance_changes and hasattr(post, 'ui_token_amount') and post.ui_token_amount.amount and hasattr(post, 'mint') and isinstance(post.mint, Pubkey) and post.mint == self.mint_pubkey:
                    balance_changes[str(post.owner)]['post'] = int(post.ui_token_amount.amount)
            for owner, data in balance_changes.items():
                change = data['post'] - data['pre']
                if change < 0: log_entry['sender'] = owner; log_entry['amount'] = abs(change) / (10**self.TOKEN_DECIMALS)
                elif change > 0: log_entry['recipient'] = owner
            sender, recipient = log_entry['sender'], log_entry['recipient']
            if self.debug_mode: self.log_func(f"DEBUG: Determined Sender: {sender}, Recipient: {recipient}, Amount: {log_entry['amount']}", "debug")
            if not sender or not recipient or log_entry['amount'] == 0:
                if self.debug_mode: self.log_func(f"DEBUG: Kein gültiger Transfer in {signature_str}.", "debug"); return False
            self.log_func(f"Absender:    {truncate_address(sender)}", "info"); self.log_func(f"Empfänger:   {truncate_address(recipient)}", "info"); self.log_func(f"Menge:       {log_entry['amount']} Tokens", "info")
            if recipient in self.whitelist: self.log_func("STATUS: ✅ Empfänger ist autorisiert.", "success"); log_entry['status'] = 'AUTHORIZED'
            else:
                self.log_func("STATUS: 🚨 Whitelist-Verstoß! Empfänger nicht autorisiert.", "error"); self.stats['violations_detected'] += 1; log_entry['status'] = 'VIOLATION_FROZEN'
                if self.notification_callback: self.notification_callback("Whitelist-Verstoß", f"Transfer an {truncate_address(recipient)}")
                if self.freeze_recipient_on_violation:
                    if recipient not in balance_changes or 'ata' not in balance_changes[recipient]: self.log_func(f"FEHLER: ATA für Empfänger {recipient} nicht in balance_changes. Freeze nicht möglich.", "error")
                    else: asyncio.create_task(self._freeze_account_on_chain(balance_changes[recipient]['ata'], recipient, "Empfänger (Verstoß)"))
                    log_entry['frozen_wallets'].append(recipient)
                    if self.freeze_sender_on_violation:
                        self.log_func("→ Option 'Absender ebenfalls sperren' aktiv.", "info")
                        if sender not in balance_changes or 'ata' not in balance_changes[sender]: self.log_func(f"FEHLER: ATA für Sender {sender} nicht in balance_changes. Freeze nicht möglich.", "error")
                        else: asyncio.create_task(self._freeze_account_on_chain(balance_changes[sender]['ata'], sender, "Absender (Verstoß)"))
                        if sender not in log_entry['frozen_wallets']: log_entry['frozen_wallets'].append(sender)
                else: self.log_func("→ Option 'Empfänger sperren' ist deaktiviert.", "warning")
            self.transaction_logger.info(json.dumps(log_entry))
            if self.debug_mode: self.log_func(f"DEBUG: Transfer geloggt für {signature_str}", "debug"); return True
        except Exception as e:
            self.log_func(f"{DesignSystem.ICONS['error']} Kritischer Fehler bei Transfer-Analyse für {signature_str}: {e}", "error")
            if self.debug_mode: import traceback; self.log_func(traceback.format_exc(), "debug") 
            return False
        return True 

    async def _log_freeze_thaw_if_present(self, tx_resp, signature_str: str) -> bool: 
        if self.debug_mode: self.log_func(f"DEBUG: _log_freeze_thaw_if_present für {signature_str}", "debug")
        
        if not hasattr(tx_resp.value.transaction.transaction.message, 'instructions') or \
           not tx_resp.value.transaction.transaction.message.instructions:
            if self.debug_mode: self.log_func(f"DEBUG (Freeze/Thaw Check - TX: {signature_str}): Keine Instruktionen in der Transaktion gefunden.", "debug")
            return False
            
        instructions_list = tx_resp.value.transaction.transaction.message.instructions
        logged_something = False
        
        account_keys_raw = tx_resp.value.transaction.transaction.message.account_keys
        account_keys = self._extract_pubkeys_from_account_keys_raw(account_keys_raw, signature_str)
        if not account_keys:
            return False

        if self.debug_mode: self.log_func(f"DEBUG (Freeze/Thaw Check - TX: {signature_str}): Anzahl Instruktionen: {len(instructions_list)}", "debug")

        for instruction_idx, instruction_obj in enumerate(instructions_list): 
            program_id_str = "N/A"; parsed_instr_type = "N/A"; parsed_instr_info_dict = {}; instruction_program_id_obj = None; raw_instruction_content = "N/A"
            
            # <<<< ANPASSUNG FÜR ParsedInstruction OBJEKTE UND VERBESSERTES DEBUGGING >>>>
            if hasattr(instruction_obj, 'program_id') and hasattr(instruction_obj, 'parsed'):
                instruction_program_id_obj = instruction_obj.program_id 
                program_id_str = str(instruction_program_id_obj)
                parsed_content = instruction_obj.parsed
                raw_instruction_content = str(instruction_obj) # Logge das Objekt selbst
                if isinstance(parsed_content, dict):
                     parsed_instr_type = parsed_content.get('type', 'N/A')
                     parsed_instr_info_dict = parsed_content.get('info', {})
                elif hasattr(parsed_content, 'type') and hasattr(parsed_content, 'info'):
                    parsed_instr_type = str(getattr(parsed_content, 'type', 'N/A')) 
                    info_obj = getattr(parsed_content, 'info', None)
                    if info_obj:
                        try:
                            parsed_instr_info_dict = {
                                "account": str(getattr(info_obj, 'account', '')), "mint": str(getattr(info_obj, 'mint', '')),
                                "owner": str(getattr(info_obj, 'owner', '')), "authority": str(getattr(info_obj, 'authority', '')),
                                "freezeAuthority": str(getattr(info_obj, 'freeze_authority', '')),
                            }
                            parsed_instr_info_dict = {k: v for k, v in parsed_instr_info_dict.items() if v}
                        except Exception as e:
                            if self.debug_mode: self.log_func(f"DEBUG (Freeze/Thaw): Fehler beim Extrahieren von Info-Attributen: {e}", "debug")
            elif isinstance(instruction_obj, dict):
                program_id_str = str(instruction_obj.get('programId', 'N/A'))
                if program_id_str != "N/A": 
                    try: instruction_program_id_obj = Pubkey.from_string(program_id_str)
                    except: pass 
                raw_instruction_content = json.dumps(instruction_obj)
                if 'parsed' in instruction_obj:
                    parsed_data = instruction_obj.get('parsed', {})
                    parsed_instr_type = parsed_data.get('type', 'N/A')
                    parsed_instr_info_dict = parsed_data.get('info', {})
                elif self.debug_mode: self.log_func(f"RAW_INSTRUCTION_DEBUG (TX: {signature_str}, Idx: {instruction_idx}): Dict ohne 'parsed' Key!", "debug")
            else: raw_instruction_content = str(instruction_obj)

            if self.debug_mode:
                self.log_func(f"RAW_INSTRUCTION_DEBUG (TX: {signature_str}, Idx: {instruction_idx}): ProgramId: {program_id_str}, ParsedType: {parsed_instr_type}, ParsedInfo: {json.dumps(parsed_instr_info_dict)}, RawContent: {raw_instruction_content[:500]}...", "debug")

            if parsed_instr_type not in ['freezeAccount', 'thawAccount']: 
                # Loggen nur, wenn parsed_instr_type nicht "N/A" war (also ein Typ erkannt wurde, aber nicht der richtige)
                if self.debug_mode and parsed_instr_type != "N/A": self.log_func(f"DEBUG (Freeze/Thaw Check - TX: {signature_str}, Idx: {instruction_idx}): Typ '{parsed_instr_type}' nicht relevant. Überspringe.", "debug")
                continue
            
            if instruction_program_id_obj != TOKEN_PROGRAM_ID:
                if self.debug_mode: self.log_func(f"DEBUG (Freeze/Thaw Check - TX: {signature_str}, Idx: {instruction_idx}): Instruktion {parsed_instr_type} nicht vom Token Programm (ist {program_id_str}). Überspringe.", "debug")
                continue
            
            mint_on_chain_str = parsed_instr_info_dict.get('mint')
            
            if mint_on_chain_str != str(self.mint_pubkey):
                if self.debug_mode: self.log_func(f"DEBUG (Freeze/Thaw Check - TX: {signature_str}, Idx: {instruction_idx}): Mint {mint_on_chain_str} in Instruktion stimmt nicht mit überwachtem Mint {str(self.mint_pubkey)} überein. Info: {json.dumps(parsed_instr_info_dict)}. Überspringe.", "debug")
                continue
            
            if self.debug_mode: self.log_func(f"DEBUG (Freeze/Thaw Check - TX: {signature_str}, Idx: {instruction_idx}): KORREKTE Freeze/Thaw Instruktion für unseren Mint gefunden! ParsedInfo: {json.dumps(parsed_instr_info_dict)}", "debug")

            ata_address_str = parsed_instr_info_dict.get('account') 
            if not ata_address_str:
                if self.debug_mode: self.log_func(f"DEBUG (Freeze/Thaw Check - TX: {signature_str}, Idx: {instruction_idx}): Kein 'account' (ATA) in parsed info. Info: {json.dumps(parsed_instr_info_dict)}", "debug")
                continue

            wallet_owner_address_str = None
            all_token_balances = (getattr(tx_resp.value.transaction.meta, 'pre_token_balances', []) or []) + \
                                 (getattr(tx_resp.value.transaction.meta, 'post_token_balances', []) or [])
            for tb_idx, tb in enumerate(all_token_balances):
                if hasattr(tb, 'account_index') and hasattr(tb, 'owner') and hasattr(tb, 'mint') and \
                   isinstance(tb.mint, Pubkey) and tb.mint == self.mint_pubkey and \
                   tb.account_index < len(account_keys): 
                    if str(account_keys[tb.account_index]) == ata_address_str:
                        wallet_owner_address_str = str(tb.owner)
                        if self.debug_mode: self.log_func(f"DEBUG (Freeze/Thaw Check - TX: {signature_str}, Idx: {instruction_idx}): Owner {wallet_owner_address_str} für ATA {ata_address_str} via TokenBalance Idx {tb_idx} gefunden.", "debug")
                        break 
            
            if not wallet_owner_address_str:
                self.log_func(f"WARNUNG (Freeze/Thaw Check - TX: {signature_str}, Idx: {instruction_idx}): Owner für ATA {ata_address_str} nicht in TokenBalances. Versuche RPC-Lookup...", "warning")
                try:
                    ata_pubkey = Pubkey.from_string(ata_address_str)
                    account_info_resp = self.http_client.get_account_info_json_parsed(ata_pubkey) 
                    if account_info_resp.value and account_info_resp.value.owner == TOKEN_PROGRAM_ID : 
                        account_data = account_info_resp.value.data
                        if isinstance(account_data, dict) and account_data.get("program") == "spl-token":
                            parsed_account_info_rpc = account_data.get("parsed", {}).get("info", {}) 
                            owner_from_rpc = parsed_account_info_rpc.get("owner")
                            if owner_from_rpc:
                                wallet_owner_address_str = owner_from_rpc
                                self.log_func(f"INFO (Freeze/Thaw Check - TX: {signature_str}, Idx: {instruction_idx}): Owner {wallet_owner_address_str} für ATA {ata_address_str} via RPC-Lookup gefunden.", "info")
                            else: self.log_func(f"WARNUNG (Freeze/Thaw Check - TX: {signature_str}, Idx: {instruction_idx}): Owner nicht in geparsten RPC-Daten für ATA {ata_address_str} gefunden. Parsed Info: {parsed_account_info_rpc}", "warning")
                        else: self.log_func(f"WARNUNG (Freeze/Thaw Check - TX: {signature_str}, Idx: {instruction_idx}): RPC-Daten für ATA {ata_address_str} nicht im erwarteten spl-token Format. Data: {account_data}", "warning")
                    else:
                        rpc_owner = account_info_resp.value.owner if account_info_resp.value else 'N/A (kein AccountInfo Value)'
                        self.log_func(f"WARNUNG (Freeze/Thaw Check - TX: {signature_str}, Idx: {instruction_idx}): ATA {ata_address_str} ist kein gültiges Token-Konto (Owner: {rpc_owner}) oder RPC-Call fehlgeschlagen.", "warning")
                except Exception as rpc_e: self.log_func(f"FEHLER (Freeze/Thaw Check - TX: {signature_str}, Idx: {instruction_idx}): Fehler bei RPC-Lookup für ATA {ata_address_str}: {rpc_e}", "error")
                if not wallet_owner_address_str: 
                    if self.debug_mode: self.log_func(f"DEBUG (Freeze/Thaw Check - TX: {signature_str}, Idx: {instruction_idx}): Owner für ATA {ata_address_str} konnte auch via RPC nicht ermittelt werden. Überspringe.", "debug")
                    continue 

            log_entry = {'timestamp': datetime.utcnow().isoformat(), 'signature': signature_str}
            if parsed_instr_type == 'freezeAccount':
                self.log_func(f"ℹ️ Externer Freeze erkannt für Wallet: {truncate_address(wallet_owner_address_str)} (ATA: {truncate_address(ata_address_str)})", "warning")
                log_entry.update({'status': 'ACCOUNT_FROZEN', 'frozen_wallet': wallet_owner_address_str})
            else: 
                self.log_func(f"ℹ️ Externer Thaw erkannt für Wallet: {truncate_address(wallet_owner_address_str)} (ATA: {truncate_address(ata_address_str)})", "info")
                log_entry.update({'status': 'ACCOUNT_THAWED', 'thawed_wallet': wallet_owner_address_str})
            self.transaction_logger.info(json.dumps(log_entry)); logged_something = True
            if self.debug_mode: self.log_func(f"DEBUG (Freeze/Thaw Check - TX: {signature_str}, Idx: {instruction_idx}): Freeze/Thaw geloggt für Wallet: {wallet_owner_address_str}", "debug")
            break 
        return logged_something

    async def run(self):
        if self.debug_mode: self.log_func("DEBUG: WhitelistMonitorBot run() gestartet.", "debug")
        while not self.stop_event.is_set():
            self.reload_event.clear()
            try:
                if self.debug_mode: self.log_func(f"DEBUG: Versuche WebSocket-Verbindung zu {self.ws_uri}", "debug")
                async with websockets.connect(self.ws_uri) as websocket:
                    self.log_func(f"🔌 Verbunden mit WebSocket: {self.ws_uri}", "success")
                    subscription_payload = {"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe", "params": [{"mentions": [str(TOKEN_PROGRAM_ID)]}, {"commitment": "finalized"}]}
                    if self.debug_mode: self.log_func(f"DEBUG: Sende Subscription Payload: {json.dumps(subscription_payload)}", "debug")
                    await websocket.send(json.dumps(subscription_payload))
                    confirmation = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    if self.debug_mode: self.log_func(f"DEBUG: WebSocket Subscription Bestätigung erhalten: {confirmation}", "debug")
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
                                        if self.debug_mode: self.log_func(f"DEBUG: Log-Benachrichtigung für Signatur erhalten: {sig}", "debug")
                                        asyncio.create_task(self._analyze_transaction(sig)) 
                                elif self.debug_mode and log_value: self.log_func(f"DEBUG: Log-Benachrichtigung ohne Signatur oder mit Fehler: {log_value.get('err')}", "debug")
                        except asyncio.TimeoutError: continue
                        except websockets.exceptions.ConnectionClosed as cc_err:
                            self.log_func(f"🔌 WebSocket-Verbindung unerwartet geschlossen ({cc_err}). Versuche erneut...", "error"); break 
            except asyncio.TimeoutError:
                 self.log_func(f"🔌 Timeout beim Verbinden/Bestätigen mit WebSocket {self.ws_uri}. Versuche in 10s erneut...", "error")
                 await asyncio.sleep(10)
            except Exception as e:
                self.log_func(f"🔌 WebSocket-Fehler: {e}. Versuche in 10s erneut...", "error")
                if self.debug_mode: import traceback; self.log_func(traceback.format_exc(), "debug")
                await asyncio.sleep(10)
        
        if self.async_http_client: await self.async_http_client.close()
        self.log_func("--- Monitor-Bot wurde gestoppt. ---", "header")
        if self.debug_mode: self.log_func("DEBUG: WhitelistMonitorBot run() beendet.", "debug")

# === Haupt-UI ===
class MonitorUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Blockchain Monitor")
        self.geometry("1200x800"); self.minsize(1000, 600)
        ctk.set_appearance_mode("Dark"); ctk.set_default_color_theme("blue")
        self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(1, weight=1)
        self.log_queue = queue.Queue()
        self.monitor_thread = None; self.monitor_instance = None
        self.stop_event = None; self.reload_event = None
        self.transaction_logger = setup_transaction_logger()
        self.debug_mode_var = ctk.BooleanVar(value=True) 
        self._create_widgets()
        self.after(200, self.process_log_queue)
        self.update_whitelist_display()
        self.toggle_sender_freeze_option()

    def _create_widgets(self):
        self._create_header(); self._create_main_content()

    def _create_header(self):
        header = ctk.CTkFrame(self); header.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        header.grid_columnconfigure(2, weight=1) 
        ctk.CTkLabel(header, text=f"{DesignSystem.ICONS['search']} Blockchain Monitor", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, padx=10, pady=10, sticky="w")
        controls_frame = ctk.CTkFrame(header, fg_color="transparent"); controls_frame.grid(row=0, column=1, padx=10, pady=10, sticky="w") 
        self.start_button = ctk.CTkButton(controls_frame, text=f"{DesignSystem.ICONS['start']} Start", command=self.start_monitor, fg_color=DesignSystem.COLORS['success']); self.start_button.pack(side="left", padx=5)
        self.stop_button = ctk.CTkButton(controls_frame, text=f"{DesignSystem.ICONS['stop']} Stop", command=self.stop_monitor, state="disabled", fg_color=DesignSystem.COLORS['error']); self.stop_button.pack(side="left", padx=5)
        status_and_options_frame = ctk.CTkFrame(header, fg_color="transparent"); status_and_options_frame.grid(row=0, column=2, padx=10, pady=10, sticky="e")
        self.status_indicator = StatusIndicator(status_and_options_frame, status="unknown", text="Gestoppt"); self.status_indicator.pack(anchor="ne", pady=(0, DesignSystem.SPACING['sm'])) 
        checkbox_frame = ctk.CTkFrame(status_and_options_frame, fg_color="transparent"); checkbox_frame.pack(anchor="se", pady=(DesignSystem.SPACING['sm'], 0)) 
        self.freeze_recipient_check = ctk.CTkCheckBox(checkbox_frame, text="Empfänger bei Verstoß sperren", command=self.toggle_sender_freeze_option); self.freeze_recipient_check.pack(anchor="e", pady=(0,2)); self.freeze_recipient_check.select()
        self.freeze_sender_check = ctk.CTkCheckBox(checkbox_frame, text="Absender ebenfalls sperren"); self.freeze_sender_check.pack(anchor="e"); self.freeze_sender_check.select()

    def _create_main_content(self):
        self.tab_view = ctk.CTkTabview(self); self.tab_view.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        tabs = ["📋 Live Log", "📝 Whitelist", "🌐 Netzwerk Visualisierung", "🛡️ Wallet-Verwaltung", "⚙️ Einstellungen"] 
        for tab_name in tabs: self.tab_view.add(tab_name)
        self._create_log_tab(self.tab_view.tab("📋 Live Log"))
        self._create_whitelist_tab(self.tab_view.tab("📝 Whitelist"))
        self._create_network_tab(self.tab_view.tab("🌐 Netzwerk Visualisierung"))
        self._create_wallet_management_tab(self.tab_view.tab("🛡️ Wallet-Verwaltung")) 
        self._create_settings_tab(self.tab_view.tab("⚙️ Einstellungen"))

    def _create_log_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1); tab.grid_rowconfigure(0, weight=1)
        self.log_textbox = EnhancedTextbox(tab); self.log_textbox.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

    def _create_whitelist_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1); tab.grid_rowconfigure(1, weight=1)
        actions = ctk.CTkFrame(tab, fg_color="transparent"); actions.grid(row=0, column=0, padx=10, pady=10, sticky="e")
        ctk.CTkButton(actions, text=f"{DesignSystem.ICONS['refresh']} Neu laden", command=self.reload_whitelist_action).pack(side="right")
        self.whitelist_textbox = ctk.CTkTextbox(tab, state="disabled", font=ctk.CTkFont(family="monospace", size=11)); self.whitelist_textbox.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

    def _create_network_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tab, text="Interaktive Transaktions-Visualisierung", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, padx=20, pady=(20,10), sticky="w")
        info_frame = ctk.CTkFrame(tab, fg_color="transparent"); info_frame.grid(row=1, column=0, padx=20, pady=(0,10), sticky="nw")
        ctk.CTkLabel(info_frame, text="Klicken Sie auf den Button, um eine interaktive Netzwerkkarte aus den geloggten Transaktionen zu erstellen. Die Karte wird in Ihrem Webbrowser geöffnet.\n\n- Grüne Knoten: Whitelist-Adressen\n- Rote Knoten: Gesperrte Adressen\n- Blaue Knoten: Andere Adressen", wraplength=700, justify="left").pack(anchor="w")
        ctk.CTkLabel(info_frame, text="Wichtiger Hinweis:", font=ctk.CTkFont(weight="bold"), wraplength=700, justify="left").pack(anchor="w", pady=(10,0))
        ctk.CTkLabel(info_frame, text="Die in der Visualisierung angezeigten Token-Bestände sind Schätzungen, die ausschließlich auf den Transaktionen in der Datei 'transactions.jsonl' basieren...", wraplength=700, justify="left").pack(anchor="w")
        self.update_graph_button = ctk.CTkButton(tab, text=f"{DesignSystem.ICONS['graph']} Visualisierung erstellen & öffnen", command=self.generate_and_open_graph, height=40); self.update_graph_button.grid(row=2, column=0, padx=20, pady=20, sticky="w")
        self.graph_status_label = ctk.CTkLabel(tab, text="", text_color=DesignSystem.COLORS['text_secondary']); self.graph_status_label.grid(row=3, column=0, padx=20, pady=10, sticky="w")
        
    def _create_wallet_management_tab(self, tab): 
        tab.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tab, text="Wallet-Status manuell ändern", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, padx=20, pady=(20,10), sticky="w")
        input_frame = ctk.CTkFrame(tab, fg_color="transparent"); input_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        input_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(input_frame, text="Wallet Adresse:").grid(row=0, column=0, padx=(0, DesignSystem.SPACING['md']), pady=DesignSystem.SPACING['md'], sticky="w")
        self.manual_wallet_address_entry = ctk.CTkEntry(input_frame, placeholder_text="Wallet Pubkey eingeben...")
        self.manual_wallet_address_entry.grid(row=0, column=1, pady=DesignSystem.SPACING['md'], sticky="ew")
        button_frame = ctk.CTkFrame(tab, fg_color="transparent"); button_frame.grid(row=2, column=0, padx=20, pady=10, sticky="w")
        self.manual_freeze_button = ctk.CTkButton(button_frame, text=f"{DesignSystem.ICONS['freeze']} Wallet sperren", command=self.manual_freeze_wallet, fg_color=DesignSystem.COLORS['warning'])
        self.manual_freeze_button.pack(side="left", padx=(0, DesignSystem.SPACING['md']))
        self.manual_thaw_button = ctk.CTkButton(button_frame, text=f"{DesignSystem.ICONS['thaw']} Wallet entsperren", command=self.manual_thaw_wallet, fg_color=DesignSystem.COLORS['success'])
        self.manual_thaw_button.pack(side="left")
        ctk.CTkLabel(tab, text="Hinweis: Diese Aktionen interagieren direkt mit der Blockchain und ändern den Freeze-Status des Token-Kontos der Wallet für den spezifischen Token dieses Monitors. Die Aktion wird auch in 'transactions.jsonl' geloggt.", wraplength=700, justify="left").grid(row=3, column=0, padx=20, pady=(20,10), sticky="w")
        
    def _create_settings_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        settings_frame = ctk.CTkFrame(tab); settings_frame.grid(row=0, column=0, padx=10, pady=10, sticky="new")
        settings_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(settings_frame, text=f"{DesignSystem.ICONS['info']} Verbindung", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=10, pady=(10,0))
        config = load_config()
        ctk.CTkLabel(settings_frame, text=f"RPC Endpunkt: {config.get('rpc_url', 'Nicht konfiguriert') if config else 'N/A'}").pack(anchor="w", padx=10, pady=(0,5))
        ctk.CTkLabel(settings_frame, text=f"Wallet-Ordner: {config.get('wallet_folder', 'Nicht konfiguriert') if config else 'N/A'}").pack(anchor="w", padx=10, pady=(0,10))
        
        ctk.CTkLabel(settings_frame, text=f"{DesignSystem.ICONS['settings']} Monitor Optionen", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=10, pady=(20,0))
        self.debug_mode_checkbox = ctk.CTkCheckBox(settings_frame, text="Debug-Modus aktivieren", variable=self.debug_mode_var, command=self.toggle_debug_mode)
        self.debug_mode_checkbox.pack(anchor="w", padx=10, pady=5)

    def _perform_manual_account_action(self, action_type: str): 
        wallet_address_str = self.manual_wallet_address_entry.get()
        if not wallet_address_str: show_error(self, "Eingabefehler", "Bitte Wallet-Adresse eingeben."); return
        try: wallet_pubkey = Pubkey.from_string(wallet_address_str)
        except Exception: show_error(self, "Eingabefehler", "Ungültige Wallet-Adresse."); return

        config = load_config(); 
        if not config: show_error(self, "Konfigurationsfehler", "config.json nicht gefunden."); return
        
        http_client = None # Ensure defined for finally block
        try:
            payer_keypair = load_keypair(config['wallet_folder'], "payer-wallet.json")
            mint_pubkey_obj = load_keypair(config['wallet_folder'], "mint-wallet.json").pubkey() 
            http_client = Client(config['rpc_url'])
        except Exception as e: show_error(self, "Setup-Fehler", f"Fehler bei Wallet-Konfig: {e}"); return
        
        ata_to_modify = get_associated_token_address(wallet_pubkey, mint_pubkey_obj)
        self.log(f"INFO: Manuelle Aktion '{action_type}' für {wallet_address_str} (ATA: {ata_to_modify})", "info")
        try:
            instruction = None 
            if action_type == "freeze":
                params = FreezeAccountParams(TOKEN_PROGRAM_ID, ata_to_modify, mint_pubkey_obj, payer_keypair.pubkey())
                instruction = freeze_account(params)
                log_status, log_key, success_msg = 'MANUAL_ACCOUNT_FROZEN', 'frozen_wallet', "erfolgreich gesperrt."
            elif action_type == "thaw":
                params = ThawAccountParams(TOKEN_PROGRAM_ID, ata_to_modify, mint_pubkey_obj, payer_keypair.pubkey())
                instruction = thaw_account(params)
                log_status, log_key, success_msg = 'MANUAL_ACCOUNT_THAWED', 'thawed_wallet', "erfolgreich entsperrt."
            else: return

            latest_blockhash_resp = http_client.get_latest_blockhash()
            # Korrekte Erstellung der Transaktion
            transaction = Transaction.new_signed_with_payer(
                [instruction], # instructions
                payer_keypair.pubkey(), # payer
                [payer_keypair], # signers
                latest_blockhash_resp.value.blockhash # recent_blockhash
            )
            
            resp = http_client.send_transaction(transaction)
            self.log(f"INFO: Manuelle Tx gesendet: {resp.value}. Warte auf Bestätigung...", "info")
            http_client.confirm_transaction(
                resp.value, 
                commitment="confirmed", 
                last_valid_block_height=latest_blockhash_resp.value.last_valid_block_height
            )
            
            full_success_msg = f"Wallet {truncate_address(wallet_address_str)} {success_msg}"
            self.log(f"ERFOLG: {full_success_msg} Transaktion: {resp.value}", "success")
            show_info(self, "Erfolg", f"{full_success_msg}\nTransaktion: {resp.value}")
            log_entry = {'timestamp': datetime.utcnow().isoformat(), 
                         'signature': f'MANUAL_UI_{action_type.upper()}_{str(resp.value)[:10]}', 
                         'status': log_status, log_key: wallet_address_str}
            self.transaction_logger.info(json.dumps(log_entry))
        except Exception as e:
            self.log(f"FEHLER bei manueller Aktion '{action_type}' für {wallet_address_str}: {e}", "error")
            if self.debug_mode_var.get(): import traceback; self.log(traceback.format_exc(), "debug")
            show_error(self, "Blockchain Fehler", f"Aktion fehlgeschlagen für {wallet_address_str}:\n\n{e}")
        finally: 
            # http_client.close() ist nicht nötig für solana.rpc.api.Client
            pass


    def manual_freeze_wallet(self): self._perform_manual_account_action("freeze")
    def manual_thaw_wallet(self): self._perform_manual_account_action("thaw")

    def toggle_debug_mode(self):
        enabled = self.debug_mode_var.get()
        if self.monitor_instance:
            self.monitor_instance.set_debug_mode(enabled)
        self.log(f"UI: Debug-Modus {'aktiviert' if enabled else 'deaktiviert'}.", "info")

    def start_monitor(self):
        self.log_textbox.clear_text(); self.log("INFO: Monitor wird gestartet...", "info")
        self.start_button.configure(state="disabled"); self.stop_button.configure(state="normal")
        self.freeze_recipient_check.configure(state="disabled"); self.freeze_sender_check.configure(state="disabled")
        self.debug_mode_checkbox.configure(state="disabled") 
        self.status_indicator.set_status("info", "Initialisierung...")
        self.stop_event, self.reload_event = threading.Event(), threading.Event()
        try:
            config = load_config()
            if not config:
                self.log("FEHLER: Konfiguration (config.json) konnte nicht geladen werden oder ist leer. Monitor nicht gestartet.", "error")
                show_error(self, "Konfigurationsfehler", "config.json konnte nicht geladen werden oder ist leer."); self.stop_monitor(); return
            self.monitor_instance = WhitelistMonitorBot(
                config, self.log, self.stop_event, self.reload_event,
                self.freeze_sender_check.get(), self.freeze_recipient_check.get(), 
                self.transaction_logger, debug_mode=self.debug_mode_var.get(), 
                notification_callback=None
            )
            self.monitor_thread = threading.Thread(target=lambda: asyncio.run(self.monitor_instance.run()), daemon=True); self.monitor_thread.start()
            self.status_indicator.set_status("success", "Läuft")
        except Exception as e:
            self.log(f"FEHLER: Start fehlgeschlagen - {e}", "error")
            if self.debug_mode_var.get(): import traceback; self.log(traceback.format_exc(), "debug")
            show_error(self, "Startfehler", f"Monitor konnte nicht starten:\n\n{e}"); self.stop_monitor()

    def stop_monitor(self):
        if self.stop_event: self.stop_event.set()
        self.start_button.configure(state="normal"); self.stop_button.configure(state="disabled")
        self.freeze_recipient_check.configure(state="normal"); self.toggle_sender_freeze_option() 
        self.debug_mode_checkbox.configure(state="normal") 
        self.status_indicator.set_status("unknown", "Gestoppt")
        self.monitor_instance = None; self.monitor_thread = None

    def reload_whitelist_action(self):
        self.update_whitelist_display()
        if self.monitor_instance: self.monitor_instance.reload_whitelist()
        show_info(self, "Whitelist", "Whitelist wurde neu geladen.")

    def generate_and_open_graph(self):
        self.graph_status_label.configure(text="INFO: Erstelle Netzwerk-Visualisierung..."); self.update_graph_button.configure(state="disabled")
        threading.Thread(target=self._run_visualization_task, daemon=True).start()

    def _run_visualization_task(self):
        try:
            config = load_config()
            if not config: self.log("FEHLER: Config nicht gefunden für Visualisierung.", "error"); raise ValueError("Config nicht gefunden")
            visualizer = NetworkVisualizer('transactions.jsonl', load_whitelist(config['wallet_folder']), 'network_visualization.html')
            visualizer.generate_graph(); self.after(0, self._on_graph_generation_success)
        except Exception as e:
            self.log(f"FEHLER bei Visualisierungstask: {e}", "error"); self.after(0, lambda e=e: self._on_graph_generation_error(e))
    
    def _on_graph_generation_success(self):
        self.graph_status_label.configure(text=f"✓ Erfolg! network_visualization.html erstellt. Wird im Browser geöffnet.", text_color=DesignSystem.COLORS['success'])
        webbrowser.open(f"file://{os.path.realpath('network_visualization.html')}"); self.update_graph_button.configure(state="normal")

    def _on_graph_generation_error(self, e):
        show_error(self, "Visualisierungs-Fehler", f"Konnte die Netzwerkkarte nicht erstellen:\n\n{e}")
        self.graph_status_label.configure(text=f"❌ Fehler: {e}", text_color=DesignSystem.COLORS['error']); self.update_graph_button.configure(state="normal")

    def log(self, message, level="info"):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted_message = f"[{timestamp}] [{level.upper()}] {message}"
        if level == "debug":
            bot_debug_active = self.monitor_instance and self.monitor_instance.debug_mode
            ui_debug_active = self.debug_mode_var.get() 
            if not (bot_debug_active or (not self.monitor_instance and ui_debug_active) ):
                return 
        self.log_queue.put((formatted_message, level))

    def process_log_queue(self):
        try:
            while True: message, level = self.log_queue.get_nowait(); self.log_textbox.append_text(message, level) 
        except queue.Empty: pass
        finally: self.after(100, self.process_log_queue) 

    def update_whitelist_display(self):
        try:
            config = load_config()
            if not config: self.log("INFO: Config nicht geladen, Whitelist-Anzeige nicht aktualisiert.", "info"); return
            path = os.path.join(config['wallet_folder'], "whitelist.txt")
            content = open(path, 'r', encoding='utf-8').read() if os.path.exists(path) else "# whitelist.txt nicht gefunden"
            self.whitelist_textbox.configure(state="normal"); self.whitelist_textbox.delete("1.0", "end"); self.whitelist_textbox.insert("1.0", content); self.whitelist_textbox.configure(state="disabled")
        except Exception as e:
            self.log(f"FEHLER beim Laden der Whitelist-Anzeige: {e}", "error")
            self.whitelist_textbox.configure(state="normal"); self.whitelist_textbox.delete("1.0", "end"); self.whitelist_textbox.insert("1.0", f"Fehler beim Laden: {e}"); self.whitelist_textbox.configure(state="disabled")
            
    def toggle_sender_freeze_option(self):
        is_monitor_stopped = self.stop_button.cget("state") == "disabled"
        if is_monitor_stopped:
            if self.freeze_recipient_check.get() == 1: self.freeze_sender_check.configure(state="normal")
            else: self.freeze_sender_check.deselect(); self.freeze_sender_check.configure(state="disabled")
        else: self.freeze_sender_check.configure(state="disabled")

    def on_closing(self):
        self.log("INFO: Anwendung wird geschlossen...", "info")
        self.stop_monitor()
        if self.monitor_thread and self.monitor_thread.is_alive():
            if self.debug_mode_var.get(): self.log("DEBUG: Warte kurz auf Monitor-Thread vor dem Schließen...", "debug")
            self.monitor_thread.join(timeout=1.0) 
            if self.monitor_thread.is_alive(): self.log("WARNUNG: Monitor-Thread nicht innerhalb von 1s beendet.", "warning")
        self.destroy()

if __name__ == "__main__":
    if sys.platform == "win32" and sys.version_info >= (3, 8):
         asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    app = MonitorUI(); app.protocol("WM_DELETE_WINDOW", app.on_closing); app.mainloop()
