#!/usr/bin/env python3
# === Periodischer Whitelist-Prüfer mit Greylist und lückenloser Kette ===
# Kombiniert kostengünstige, periodische Abfragen mit detaillierter
# Analyse und grafischer Darstellung aller relevanten Transaktionen.
#
# Neu in dieser Version:
# - KORREKTUR (ROBUSTE OPTIMIERUNG): Die Kontostand-Optimierung wurde um einen
#   Sicherheits-Check erweitert. Bei gleichem Kontostand wird zusätzlich
#   die letzte On-Chain-Signatur geprüft, um Race Conditions mit RPC-Knoten
#   und Hin-/Rück-Transaktionen zuverlässig zu erkennen.
# - KORREKTUR (TRANSFERS): Die Transfer-Analyse wurde überarbeitet, um auch
#   komplexe Transaktionen mit mehreren Sendern/Empfängern korrekt zu
#   verarbeiten und keine Verstöße mehr zu übersehen.
# - Greylist-Konzept: Wallets, die Token von überwachten Konten erhalten,
#   werden zur Greylist hinzugefügt und permanent überwacht.
# - Lückenlose Überwachung durch Multi-Pass-Analyse.
# - Validierungs-Check: Vergleicht die Summe der Token-Bestände mit der
#   ausgegebenen Menge zur Konsistenzprüfung.

import time
import json
import os
import sys
import logging
import traceback
import argparse
from collections import defaultdict
from datetime import datetime
from typing import Set, Dict, List, Any

# --- Benötigte Bibliotheken ---
try:
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.signature import Signature
    from solana.rpc.api import Client
    from solana.rpc.types import TxOpts
    from solana.exceptions import SolanaRpcException
    from httpx import HTTPStatusError
    from spl.token.instructions import get_associated_token_address, freeze_account, FreezeAccountParams, thaw_account, ThawAccountParams
    from spl.token.constants import TOKEN_PROGRAM_ID
    from solders.transaction import Transaction
    from pyvis.network import Network
except ImportError as e:
    print(f"Fehler: Eine oder mehrere erforderliche Bibliotheken fehlen: {e}.")
    print("Bitte installieren Sie diese mit: pip install solders solana spl-token pyvis httpx")
    sys.exit(1)

# --- Konfiguration ---
def load_config():
    try:
        with open("config.json", 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print("FEHLER: config.json nicht gefunden. Bitte erstellen Sie die Datei mit 'rpc_url' und 'wallet_folder'.")
        return None
    except json.JSONDecodeError:
        print("FEHLER: config.json ist fehlerhaft formatiert.")
        return None

CONFIG = load_config()
if not CONFIG:
    sys.exit(1)

RPC_URL = CONFIG.get("rpc_url")
WALLET_FOLDER = CONFIG.get("wallet_folder")

# --- Dateipfade im Unterordner "analyse" ---
ANALYSE_FOLDER = "analyse"
STATE_FILE = os.path.join(ANALYSE_FOLDER, "last_signatures.json")
GREYLIST_FILE = os.path.join(ANALYSE_FOLDER, "greylist.json")
TRANSACTION_LOG_FILE = os.path.join(ANALYSE_FOLDER, "transactions.jsonl")
VISUALIZATION_FILE = os.path.join(ANALYSE_FOLDER, "network_visualization.html")
MAIN_LOG_FILE = os.path.join(ANALYSE_FOLDER, "checker_main.log")
TOKEN_DECIMALS = 9

# --- Logging Setup ---
def setup_logger(name, log_file, level=logging.INFO, debug_mode=False):
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if logger.hasHandlers():
        logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.DEBUG if debug_mode else logging.INFO)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.propagate = False
    return logger

main_logger = logging.getLogger('main_checker')

transaction_logger = logging.getLogger('transaction_logger')
if not transaction_logger.hasHandlers():
    transaction_logger.setLevel(logging.INFO)
    os.makedirs(os.path.dirname(TRANSACTION_LOG_FILE), exist_ok=True)
    jsonl_handler = logging.FileHandler(TRANSACTION_LOG_FILE, mode='a', encoding='utf-8')
    transaction_logger.addHandler(jsonl_handler)
    transaction_logger.propagate = False

# --- Hilfsfunktionen ---
def load_keypair(filename: str):
    path = os.path.join(WALLET_FOLDER, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Wallet-Datei '{path}' nicht gefunden.")
    with open(path, 'r') as f:
        return Keypair.from_bytes(bytes(json.load(f)))

def load_whitelist() -> set:
    path = os.path.join(WALLET_FOLDER, "whitelist.txt")
    if not os.path.exists(path):
        main_logger.warning("whitelist.txt nicht gefunden, leere Whitelist wird verwendet.")
        return set()
    with open(path, 'r', encoding='utf-8') as f:
        return {line.strip() for line in f if line.strip() and not line.startswith('#')}

def load_greylist() -> set:
    if not os.path.exists(GREYLIST_FILE):
        return set()
    try:
        with open(GREYLIST_FILE, 'r') as f:
            return set(json.load(f))
    except (json.JSONDecodeError, TypeError):
        main_logger.error(f"{GREYLIST_FILE} ist korrupt. Eine neue Greylist wird erstellt.")
        return set()

def save_greylist(greylist_data: set):
    with open(GREYLIST_FILE, 'w') as f:
        json.dump(sorted(list(greylist_data)), f, indent=4)

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        main_logger.error(f"{STATE_FILE} ist korrupt. Ein neuer Status wird erstellt.")
        return {}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)

def truncate_address(address: str, chars: int = 4) -> str:
    if not isinstance(address, str) or len(address) < chars * 2: return address
    return f"{address[:chars]}...{address[-chars:]}"

# --- Visualisierung ---
class NetworkVisualizer:
    def __init__(self, log_file: str, whitelist: set, greylist: set, payer_address: str):
        self.log_file = log_file
        self.whitelist = whitelist
        self.greylist = greylist
        self.payer_address = payer_address

    def generate_graph(self):
        if not os.path.exists(self.log_file):
            main_logger.info("Keine Log-Datei für Visualisierung gefunden. Überspringe.")
            return

        all_wallets = set()
        balances = defaultdict(float)
        flows = defaultdict(float)
        wallet_freeze_status = {}

        log_entries = []
        with open(self.log_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    log_entries.append(json.loads(line))
                except (json.JSONDecodeError, IndexError):
                    continue

        log_entries.sort(key=lambda x: x.get('timestamp', ''))

        for tx in log_entries:
            try:
                status = tx.get('status')
                timestamp = tx.get('timestamp')

                if status in ['VIOLATION', 'AUTHORIZED_TRANSFER']:
                    sender, recipient = tx.get('sender'), tx.get('recipient')
                    amount = tx.get('amount', 0)
                    if sender and recipient and amount > 0 and "Multiple" not in sender:
                        all_wallets.update([sender, recipient])
                        balances[sender] -= amount
                        balances[recipient] += amount
                        flows[(sender, recipient)] += amount
                
                wallet = None
                if 'FROZEN' in status:
                    wallet = tx.get('frozen_wallet')
                    wallet_freeze_status[wallet] = {'status': 'FROZEN', 'timestamp': timestamp}
                elif 'THAWED' in status:
                    wallet = tx.get('thawed_wallet')
                    wallet_freeze_status[wallet] = {'status': 'THAWED', 'timestamp': timestamp}
                
                if wallet: all_wallets.add(wallet)

            except Exception:
                continue
        
        final_frozen_wallets = {w for w, d in wallet_freeze_status.items() if d['status'] == 'FROZEN'}
        
        net = Network(height="95vh", width="100%", bgcolor="#222222", font_color="white", notebook=False, directed=True)
        
        all_wallets.add(self.payer_address)
        for wallet in all_wallets:
            color, status_text = '#848484', 'Extern'
            if wallet == self.payer_address: color, status_text = '#A855F7', 'Payer'
            elif wallet in self.whitelist: color, status_text = '#22C55E', 'Whitelist'
            elif wallet in self.greylist: color, status_text = '#FBBF24', 'Greylist'
            
            if wallet in final_frozen_wallets:
                color = '#EF4444'
                status_text += ' / Gesperrt'

            balance_str = f"{balances[wallet]:.4f}".rstrip('0').rstrip('.')
            title = (f"Wallet: {wallet}<br>"
                     f"<b>Berechneter Kontostand: {balance_str} Tokens</b><br>"
                     f"Status: {status_text}")
            net.add_node(wallet, label=truncate_address(wallet), title=title, color=color)

        for (sender, recipient), total_amount in flows.items():
            amount_str = f"{total_amount:.4f}".rstrip('0').rstrip('.')
            title = f"Gesamtvolumen: {amount_str} Tokens"
            net.add_edge(sender, recipient, title=title, label=amount_str, value=total_amount)

        net.set_options("""
        {"nodes":{"font":{"size":14,"color":"#FFFFFF"}},"edges":{"arrows":{"to":{"enabled":true,"scaleFactor":0.7}},"color":{"inherit":false,"color":"#848484","highlight":"#FFFFFF","hover":"#FFFFFF"},"font":{"size":12,"color":"#FFFFFF","align":"top"},"smooth":{"type":"continuous"}},"physics":{"barnesHut":{"gravitationalConstant":-80000,"centralGravity":0.3,"springLength":400,"springConstant":0.09,"damping":0.09,"avoidOverlap":1},"minVelocity":0.75,"solver":"barnesHut"},"interaction":{"tooltipDelay":200,"hideEdgesOnDrag":true,"hover":true}}
        """)

        try:
            net.save_graph(VISUALIZATION_FILE)
            main_logger.info(f"Netzwerk-Visualisierung aktualisiert: {VISUALIZATION_FILE}")
        except Exception as e:
            main_logger.error(f"Fehler beim Speichern der Visualisierung: {e}")

# --- Kernlogik ---
class PeriodicChecker:
    def __init__(self, debug_mode=False, freeze_sender=False, freeze_recipient=False, validate=False):
        self.debug_mode = debug_mode
        self.freeze_sender_on_violation = freeze_sender
        self.freeze_recipient_on_violation = freeze_recipient
        self.perform_validation = validate
        
        self.client = Client(RPC_URL)
        main_logger.info(f"Verbunden mit RPC-Endpunkt: {RPC_URL}")
        self.payer_keypair = load_keypair("payer-wallet.json")
        self.mint_keypair = load_keypair("mint-wallet.json")
        self.mint_pubkey = self.mint_keypair.pubkey()
        
        self.whitelist: Set[str] = set()
        self.greylist: Set[str] = set()

    def get_token_balance(self, wallet_str: str) -> float | None:
        try:
            wallet_pubkey = Pubkey.from_string(wallet_str)
            ata = get_associated_token_address(wallet_pubkey, self.mint_pubkey)
            balance_resp = self.client.get_token_account_balance(ata)
            return balance_resp.value.ui_amount if balance_resp.value else 0.0
        except SolanaRpcException:
            return 0.0
        except Exception as e:
            main_logger.error(f"Kritischer Fehler beim Abrufen des Saldos für {wallet_str}: {e}")
            return None

    def get_new_signatures_paginated(self, wallet_address: str, last_known_signature_str: str | None) -> List:
        all_new_sig_infos = []
        before_sig = None
        limit = 1000
        try:
            pubkey = Pubkey.from_string(wallet_address)
            last_known_sig = Signature.from_string(last_known_signature_str) if last_known_signature_str else None

            while True:
                signatures_resp = self.client.get_signatures_for_address(pubkey, limit=limit, before=before_sig)
                if not signatures_resp.value: break
                batch = signatures_resp.value
                found_last = any(last_known_sig and si.signature == last_known_sig for si in batch)
                
                for si in batch:
                    if last_known_sig and si.signature == last_known_sig: break
                    all_new_sig_infos.append(si)
                
                if found_last or len(batch) < limit: break
                before_sig = batch[-1].signature
            
            return list(reversed(all_new_sig_infos))
        except Exception as e:
            main_logger.error(f"Fehler beim lückenlosen Abrufen der Signaturen für {wallet_address}: {e}")
            return []

    def get_transaction_with_retries(self, signature: Signature, max_retries=3):
        for attempt in range(max_retries):
            try:
                time.sleep(0.35)
                return self.client.get_transaction(signature, max_supported_transaction_version=0, encoding="jsonParsed")
            except SolanaRpcException as e:
                if isinstance(e.__cause__, HTTPStatusError) and e.__cause__.response.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    main_logger.warning(f"Ratenbegrenzung bei TX {signature}. Warte {wait}s...")
                    time.sleep(wait)
                else:
                    main_logger.error(f"RPC-Fehler für TX {signature}: {e}")
                    return None
        main_logger.error(f"Konnte TX {signature} nach {max_retries} Versuchen nicht laden.")
        return None

    def analyze_transaction(self, signature: Signature, block_time: int | None, monitored_wallets: set, state: dict):
        tx_resp = self.get_transaction_with_retries(signature)
        if not (tx_resp and tx_resp.value and tx_resp.value.transaction and tx_resp.value.transaction.meta):
            main_logger.error(f"Analyse für TX {signature} übersprungen: Details nicht geladen.")
            return
        if tx_resp.value.transaction.meta.err: return

        try:
            tx = tx_resp.value.transaction
            tx_meta = tx.meta
            final_block_time = tx_resp.value.block_time or block_time
            self._analyze_transfers(signature, tx_meta, final_block_time, monitored_wallets, state)
            self._analyze_freeze_thaw(signature, tx, final_block_time)
        except Exception:
            main_logger.error(f"Unerwarteter Fehler bei der Analyse von TX {signature}:\n{traceback.format_exc()}")

    def _freeze_account(self, wallet_to_freeze_pubkey: Pubkey):
        main_logger.warning(f"Leite Freeze-Aktion für Wallet {wallet_to_freeze_pubkey} ein...")
        try:
            ata = get_associated_token_address(wallet_to_freeze_pubkey, self.mint_pubkey)
            ix = freeze_account(FreezeAccountParams(program_id=TOKEN_PROGRAM_ID, account=ata, mint=self.mint_pubkey, authority=self.payer_keypair.pubkey()))
            latest_hash = self.client.get_latest_blockhash().value.blockhash
            tx = Transaction.new_signed_with_payer([ix], self.payer_keypair.pubkey(), [self.payer_keypair], latest_hash)
            sig = self.client.send_transaction(tx, opts=TxOpts(skip_confirmation=False)).value
            self.client.confirm_transaction(sig, "finalized")
            main_logger.info(f"✅ Freeze für Wallet {wallet_to_freeze_pubkey} bestätigt. Signatur: {sig}")
            self._log_event(str(sig), "ACCOUNT_FROZEN_BY_SCRIPT", None, frozen_wallet=str(wallet_to_freeze_pubkey))
        except Exception as e:
            main_logger.error(f"FEHLER beim Einfrieren von {wallet_to_freeze_pubkey}: {e}")

    def _process_transfer(self, signature: str, block_time: int | None, monitored: set, state: dict, sender: str, recipient: str, amount: float):
        if recipient not in monitored:
            status = 'VIOLATION'
            main_logger.warning(f"-> VERSTOSS in TX {signature}: {amount:.4f} von {truncate_address(sender)} an {truncate_address(recipient)}")
            main_logger.warning(f"-> Empfänger {recipient} wird zur Greylist hinzugefügt.")
            self.greylist.add(recipient)
            
            if recipient not in state or not isinstance(state.get(recipient), dict):
                state[recipient] = {}
            state[recipient]['last_sig'] = signature
            main_logger.info(f"-> Setze Startpunkt für neue Greylist-Wallet {truncate_address(recipient)} auf TX {signature}")
            
            if self.freeze_sender_on_violation and "Multiple" not in sender:
                self._freeze_account(Pubkey.from_string(sender))
            if self.freeze_recipient_on_violation:
                self._freeze_account(Pubkey.from_string(recipient))
        else:
            status = 'AUTHORIZED_TRANSFER'
            main_logger.debug(f"-> Transfer ({status}) in TX {signature}: {amount:.4f} von {sender} an {recipient}")
        
        self._log_event(signature, status, block_time, sender=sender, recipient=recipient, amount=amount)

    def _analyze_transfers(self, signature: Signature, tx_meta, block_time: int | None, monitored: set, state: dict):
        if not any(hasattr(b, 'mint') and str(b.mint) == str(self.mint_pubkey) for b in (tx_meta.pre_token_balances or []) + (tx_meta.post_token_balances or [])):
            return

        owner_balances = defaultdict(int)
        for tb in (tx_meta.pre_token_balances or []):
            if hasattr(tb, 'owner') and str(getattr(tb, 'mint', '')) == str(self.mint_pubkey):
                owner_balances[str(tb.owner)] -= int(getattr(tb.ui_token_amount, 'amount', 0))
        for tb in (tx_meta.post_token_balances or []):
            if hasattr(tb, 'owner') and str(getattr(tb, 'mint', '')) == str(self.mint_pubkey):
                owner_balances[str(tb.owner)] += int(getattr(tb.ui_token_amount, 'amount', 0))
        
        senders = {owner: -change for owner, change in owner_balances.items() if change < 0}
        recipients = {owner: change for owner, change in owner_balances.items() if change > 0}
        
        if not senders or not recipients: return

        sig_str = str(signature)
        if len(senders) == 1 and len(recipients) == 1:
            sender, s_amt = list(senders.items())[0]
            recipient, r_amt = list(recipients.items())[0]
            if abs(s_amt - r_amt) < 1:
                self._process_transfer(sig_str, block_time, monitored, state, sender, recipient, float(r_amt) / (10**TOKEN_DECIMALS))
        else:
            main_logger.debug(f"-> Komplexe TX {sig_str}: {len(senders)} Sender, {len(recipients)} Empfänger.")
            all_sender_keys = ", ".join([truncate_address(s) for s in senders.keys()])
            sender_str = list(senders.keys())[0] if len(senders) == 1 else f"Multiple ({all_sender_keys})"
            for recipient, amount_raw in recipients.items():
                self._process_transfer(sig_str, block_time, monitored, state, sender_str, recipient, float(amount_raw) / (10**TOKEN_DECIMALS))

    def _analyze_freeze_thaw(self, signature: Signature, tx, block_time: int | None):
        for instruction in tx.transaction.message.instructions:
            parsed = getattr(instruction, 'parsed', None)
            instr_type = parsed.get('type') if isinstance(parsed, dict) else getattr(parsed, 'type', None)
            if instr_type not in ['freezeAccount', 'thawAccount']: continue

            info = parsed.get('info') if isinstance(parsed, dict) else getattr(parsed, 'info', None)
            if not info or str(info.get('mint') if isinstance(info, dict) else getattr(info, 'mint', '')) != str(self.mint_pubkey): continue

            ata_address = info.get('account') if isinstance(info, dict) else str(getattr(info, 'account', ''))
            owner_address = None
            try:
                info_resp = self.client.get_account_info_json_parsed(Pubkey.from_string(ata_address))
                if info_resp.value and info_resp.value.data:
                    owner_address = info_resp.value.data.parsed['info']['owner']
            except Exception as e: main_logger.error(f"-> RPC-Lookup für Owner von {ata_address} fehlgeschlagen: {e}")

            if not owner_address:
                main_logger.warning(f"-> Konnte Owner für {ata_address} in TX {signature} nicht ermitteln.")
                continue

            status = 'ACCOUNT_FROZEN' if instr_type == 'freezeAccount' else 'ACCOUNT_THAWED'
            main_logger.info(f"-> Aktion '{status}' in TX {signature} für Wallet {owner_address} entdeckt.")
            log_params = {'frozen_wallet': owner_address} if status == 'ACCOUNT_FROZEN' else {'thawed_wallet': owner_address}
            self._log_event(str(signature), status, block_time, **log_params)

    def _perform_supply_validation(self, monitored_wallets: set):
        main_logger.info("--- Starte optionalen Validierungs-Check der Token-Menge ---")
        
        total_distributed = 0
        payer_address = str(self.payer_keypair.pubkey())
        if os.path.exists(TRANSACTION_LOG_FILE):
            with open(TRANSACTION_LOG_FILE, 'r') as f:
                for line in f:
                    try:
                        log = json.loads(line)
                        if log.get('status') in ['VIOLATION', 'AUTHORIZED_TRANSFER'] and log.get('sender') == payer_address:
                            total_distributed += log.get('amount', 0)
                    except json.JSONDecodeError:
                        continue
        main_logger.info(f"[VALIDATION] Laut Log-Datei wurden {total_distributed:.4f} Tokens vom Payer verteilt.")

        total_on_chain_balance = 0
        payer_on_chain_balance = 0
        wallets_with_balance = 0
        main_logger.info(f"[VALIDATION] Frage On-Chain-Bestände für {len(monitored_wallets)} überwachte Wallets ab...")

        for i, wallet_str in enumerate(sorted(list(monitored_wallets))):
            try:
                if self.debug_mode or (i % 10 == 0):
                    main_logger.info(f"[VALIDATION] Frage Bestand ab für Wallet {i+1}/{len(monitored_wallets)}...")
                
                current_balance = self.get_token_balance(wallet_str)
                if current_balance is not None:
                    total_on_chain_balance += current_balance
                    if current_balance > 0:
                        wallets_with_balance += 1
                
                if wallet_str == payer_address:
                    payer_on_chain_balance = current_balance if current_balance is not None else 0
                time.sleep(0.1)
            except Exception as e:
                main_logger.error(f"[VALIDATION] Fehler beim Abrufen des Saldos für {wallet_str}: {e}")

        main_logger.info(f"[VALIDATION] {wallets_with_balance} von {len(monitored_wallets)} Wallets halten Tokens.")
        main_logger.info(f"[VALIDATION] Summe der On-Chain-Bestände: {total_on_chain_balance:.4f} Tokens.")
        main_logger.info(f"[VALIDATION] Davon liegen {payer_on_chain_balance:.4f} Tokens noch im Payer-Wallet.")
        
        circulating_supply = total_on_chain_balance - payer_on_chain_balance
        main_logger.info(f"[VALIDATION] Effektiver Token-Umlauf (ohne Payer): {circulating_supply:.4f} Tokens.")

        discrepancy = abs(total_distributed - circulating_supply)
        if discrepancy < 1e-4:
            main_logger.info(f"✅ [VALIDATION] ERFOLGREICH: Die verteilte Menge stimmt mit dem effektiven Umlauf überein.")
        else:
            main_logger.error(f"❌ [VALIDATION] FEHLGESCHLAGEN: Diskrepanz von {discrepancy:.4f} Tokens entdeckt!")
        main_logger.info("--- Validierungs-Check abgeschlossen ---")

    def _log_event(self, signature: str, status: str, block_time: int | None, **kwargs):
        ts = datetime.utcfromtimestamp(block_time).isoformat() + "Z" if block_time else datetime.utcnow().isoformat() + "Z"
        log_entry = {'timestamp': ts, 'signature': signature, 'status': status, **kwargs}
        transaction_logger.info(json.dumps(log_entry))

    def run_check(self):
        main_logger.info(f"{'='*50}\nStarte Prüfungslauf um {datetime.now():%Y-%m-%d %H:%M:%S}")
        self.whitelist, self.greylist, state = load_whitelist(), load_greylist(), load_state()
        if not self.whitelist:
            main_logger.warning("Whitelist leer. Prüfung übersprungen.")
            return

        wallets_scanned_in_run, signatures_found_in_run, signatures_processed_in_run = set(), {}, set()
        pass_num = 1
        while True:
            main_logger.info(f"--- Starte Analyse-Pass #{pass_num} ---")
            monitored_now = self.whitelist.union(self.greylist)
            wallets_to_scan = monitored_now - wallets_scanned_in_run
            if not wallets_to_scan:
                main_logger.info("Keine neuen Wallets zum Scannen. Kette vollständig analysiert.")
                break

            main_logger.info(f"Scanne {len(wallets_to_scan)} Wallet(s) in diesem Pass.")
            for wallet in sorted(list(wallets_to_scan)):
                state_entry = state.get(wallet, {})
                last_sig = state_entry.get('last_sig') if isinstance(state_entry, dict) else state_entry
                
                if wallet in self.greylist and isinstance(state_entry, dict) and "last_balance" in state_entry:
                    last_bal = state_entry.get("last_balance")
                    current_bal = self.get_token_balance(wallet)
                    if current_bal is not None and abs(current_bal - last_bal) < 1e-9:
                        main_logger.debug(f"-> Kontostand für {truncate_address(wallet)} gleich. Führe Sicherheits-Check der Signatur durch...")
                        try:
                            sig_resp = self.client.get_signatures_for_address(Pubkey.from_string(wallet), limit=1)
                            latest_sig_on_chain = str(sig_resp.value[0].signature) if sig_resp.value else None
                            if latest_sig_on_chain == last_sig or (latest_sig_on_chain is None and last_sig is None):
                                main_logger.info(f"-> Signatur unverändert. Überspringe Tiefenanalyse für {truncate_address(wallet)}.")
                                wallets_scanned_in_run.add(wallet)
                                continue
                            else:
                                main_logger.warning(f"-> Kontostand gleich, aber neue Signatur gefunden! Erzwinge Tiefenanalyse für {truncate_address(wallet)}.")
                        except Exception as e:
                            main_logger.error(f"-> Fehler bei Sicherheits-Check für {wallet}: {e}. Erzwinge Tiefenanalyse.")
                
                main_logger.debug(f"Führe Tiefenanalyse für Wallet aus: {wallet}")
                new_sigs = self.get_new_signatures_paginated(wallet, last_sig)
                if new_sigs:
                    main_logger.info(f"-> {len(new_sigs)} neue Transaktion(en) für {wallet} gefunden.")
                    for s in new_sigs: signatures_found_in_run[s.signature] = s
                    if not isinstance(state.get(wallet), dict): state[wallet] = {}
                    state[wallet]['last_sig'] = str(new_sigs[-1].signature)
                wallets_scanned_in_run.add(wallet)

            new_signatures_to_process = set(signatures_found_in_run.keys()) - signatures_processed_in_run
            if not new_signatures_to_process:
                main_logger.info("Keine neuen Transaktionen in diesem Pass zu analysieren.")
                if pass_num > 1: break 
                pass_num += 1; continue
            
            main_logger.info(f"Analysiere {len(new_signatures_to_process)} neue, einzigartige Transaktionen...")
            initial_greylist_size = len(self.greylist)
            sorted_sigs = sorted([signatures_found_in_run[s] for s in new_signatures_to_process], key=lambda si: si.block_time or 0)
            
            total_tx = len(sorted_sigs)
            for i, sig_info in enumerate(sorted_sigs):
                if not self.debug_mode:
                    progress = (i + 1) / total_tx
                    bar = '█' * int(40 * progress) + '-' * (40 - int(40 * progress))
                    sys.stdout.write(f'\rPass #{pass_num} Fortschritt: [{bar}] {i+1}/{total_tx} ({progress:.0%})')
                    sys.stdout.flush()
                main_logger.debug(f"Analysiere TX {i+1}/{len(sorted_sigs)}: {sig_info.signature}")
                self.analyze_transaction(sig_info.signature, sig_info.block_time, monitored_now, state)
                signatures_processed_in_run.add(sig_info.signature)
            
            if not self.debug_mode: sys.stdout.write('\n')
            if len(self.greylist) == initial_greylist_size:
                main_logger.info("Keine neuen Greylist-Wallets entdeckt. Beende den Prüfungslauf.")
                break
            pass_num += 1

        main_logger.info("Alle Pässe abgeschlossen. Aktualisiere finale Kontostände im Status...")
        final_monitored = self.whitelist.union(self.greylist)
        for wallet in sorted(list(final_monitored)):
            balance = self.get_token_balance(wallet)
            if balance is not None:
                if not isinstance(state.get(wallet), dict):
                    state[wallet] = {'last_sig': state.get(wallet), 'last_balance': None}
                state[wallet]['last_balance'] = balance
        
        save_state(state)
        save_greylist(self.greylist)
        visualizer = NetworkVisualizer(TRANSACTION_LOG_FILE, self.whitelist, self.greylist, str(self.payer_keypair.pubkey()))
        visualizer.generate_graph()
        if self.perform_validation: self._perform_supply_validation(final_monitored)
        main_logger.info("Prüfungslauf abgeschlossen.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Periodischer Solana Whitelist/Greylist-Prüfer.")
    parser.add_argument("--debug", action="store_true", help="Aktiviert detaillierte Debug-Ausgaben.")
    parser.add_argument("--interval", type=int, default=15, help="Prüfungsintervall in Minuten (Standard: 15).")
    parser.add_argument("--freezesend", action="store_true", help="Friert den Sender bei einem Verstoß ein.")
    parser.add_argument("--freezereceive", action="store_true", help="Friert den Empfänger bei einem Verstoß ein.")
    parser.add_argument("--validate", action="store_true", help="Aktiviert optionalen On-Chain Validierungs-Check.")
    args = parser.parse_args()

    main_logger = setup_logger('main_checker', MAIN_LOG_FILE, debug_mode=args.debug)
    os.makedirs(ANALYSE_FOLDER, exist_ok=True)
    checker = PeriodicChecker(debug_mode=args.debug, freeze_sender=args.freezesend, freeze_recipient=args.freezereceive, validate=args.validate)
    
    while True:
        try:
            checker.run_check()
            interval = args.interval
            print(f"\nPrüfung um {datetime.now():%H:%M:%S} abgeschlossen. Nächste Prüfung in {interval} Minuten.")
            time.sleep(interval * 60)
        except KeyboardInterrupt:
            main_logger.info("\nSkript wird durch Benutzer beendet.")
            sys.exit(0)
        except Exception as e:
            main_logger.critical(f"Ein kritischer Fehler in der Hauptschleife aufgetreten: {e}\n{traceback.format_exc()}")
            main_logger.info("Warte 5 Minuten und versuche es erneut...")
            time.sleep(300)
