#!/usr/bin/env python3
# === Periodischer Whitelist-Prüfer mit Greylist und lückenloser Kette ===
# Kombiniert kostengünstige, periodische Abfragen mit detaillierter
# Analyse und grafischer Darstellung aller relevanten Transaktionen.
#
# Neu in dieser Version:
# - Greylist-Konzept: Wallets, die Token von überwachten Konten erhalten,
#   werden zur Greylist hinzugefügt und permanent überwacht.
# - Lückenlose Überwachung durch Multi-Pass-Analyse innerhalb eines Laufs,
#   um die gesamte Transaktionskette sofort zu verfolgen.
# - Validierungs-Check: Vergleicht die Summe der Token-Bestände mit der
#   ausgegebenen Menge zur Konsistenzprüfung.

import time
import json
import os
import sys
import logging
import traceback
import argparse
from collections import defaultdict, deque
from datetime import datetime
from typing import Set, Dict

# --- Benötigte Bibliotheken ---
try:
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.signature import Signature
    from solana.rpc.api import Client
    from solana.rpc.types import TxOpts, TokenAccountOpts
    from solana.exceptions import SolanaRpcException
    from httpx import HTTPStatusError
    from spl.token.instructions import get_associated_token_address, freeze_account, FreezeAccountParams
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

    # Verhindern, dass Handler dupliziert werden
    if logger.hasHandlers():
        logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.DEBUG if debug_mode else logging.INFO)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Verhindern, dass Logs an den Root-Logger weitergegeben werden
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

        all_wallets, final_frozen_wallets = set(), set()
        balances = defaultdict(float)
        flows = defaultdict(float)

        with open(self.log_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    tx = json.loads(line)
                    status = tx.get('status')
                    
                    # Verarbeite Transfers für Bilanzen und Flüsse
                    if status in ['VIOLATION', 'AUTHORIZED_TRANSFER']:
                        sender, recipient = tx.get('sender'), tx.get('recipient')
                        amount = tx.get('amount', 0)
                        if sender and recipient and amount > 0:
                            all_wallets.update([sender, recipient])
                            balances[sender] -= amount
                            balances[recipient] += amount
                            flows[(sender, recipient)] += amount
                    
                    # Verarbeite Freeze/Thaw-Events für den finalen Status
                    if 'FROZEN' in status:
                        wallet_to_freeze = tx.get('frozen_wallet')
                        if wallet_to_freeze: 
                            final_frozen_wallets.add(wallet_to_freeze)
                            all_wallets.add(wallet_to_freeze)
                            
                    elif 'THAWED' in status:
                        wallet_to_thaw = tx.get('thawed_wallet')
                        if wallet_to_thaw and wallet_to_thaw in final_frozen_wallets:
                            final_frozen_wallets.remove(wallet_to_thaw)

                except (json.JSONDecodeError, IndexError):
                    continue
        
        net = Network(height="95vh", width="100%", bgcolor="#222222", font_color="white", notebook=False, directed=True)
        
        for wallet in all_wallets:
            color_whitelist = '#22C55E'       # Grün
            color_greylist = '#FBBF24'       # Amber/Gelb
            color_external = '#3B82F6'       # Blau (sollte nicht mehr vorkommen)
            color_frozen = '#EF4444'          # Rot
            color_payer = '#A855F7'           # Lila

            color = color_external # Standard
            status_text = 'Extern'

            if wallet == self.payer_address:
                color = color_payer
                status_text = 'Payer'
            elif wallet in self.whitelist:
                color = color_whitelist
                status_text = 'Whitelist'
            elif wallet in self.greylist:
                color = color_greylist
                status_text = 'Greylist'
            
            if wallet in final_frozen_wallets:
                color = color_frozen
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
        { "nodes": { "font": { "size": 14, "color": "#FFFFFF" } }, "edges": { "arrows": { "to": { "enabled": true, "scaleFactor": 0.7 } }, "color": { "inherit": false, "color": "#848484", "highlight": "#FFFFFF", "hover": "#FFFFFF" }, "font": { "size": 12, "color": "#FFFFFF", "align": "top" }, "smooth": { "type": "continuous" } }, "physics": { "barnesHut": { "gravitationalConstant": -80000, "centralGravity": 0.3, "springLength": 400, "springConstant": 0.09, "damping": 0.09, "avoidOverlap": 1 }, "minVelocity": 0.75, "solver": "barnesHut" }, "interaction": { "tooltipDelay": 200, "hideEdgesOnDrag": true, "hover": true } }
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

    def get_new_signatures_paginated(self, wallet_address: str, last_known_signature_str: str | None) -> list[Signature]:
        all_new_signatures = []
        before_sig = None
        limit = 1000

        try:
            pubkey = Pubkey.from_string(wallet_address)
            last_known_sig = Signature.from_string(last_known_signature_str) if last_known_signature_str else None

            while True:
                signatures_resp = self.client.get_signatures_for_address(pubkey, limit=limit, before=before_sig)
                if not signatures_resp.value: break

                batch_signatures = signatures_resp.value
                found_last_known = False
                for sig_info in batch_signatures:
                    if last_known_sig and sig_info.signature == last_known_sig:
                        found_last_known = True
                        break
                    all_new_signatures.append(sig_info.signature)
                
                if found_last_known or len(batch_signatures) < limit: break
                before_sig = batch_signatures[-1].signature
            
            return list(reversed(all_new_signatures))
        except Exception as e:
            main_logger.error(f"Fehler beim lückenlosen Abrufen der Signaturen für {wallet_address}: {e}")
            return []

    def get_transaction_with_retries(self, signature: Signature, max_retries=3):
        for attempt in range(max_retries):
            try:
                time.sleep(0.35)
                return self.client.get_transaction(signature, max_supported_transaction_version=0, encoding="jsonParsed")
            except SolanaRpcException as e:
                cause = e.__cause__
                if isinstance(cause, HTTPStatusError) and cause.response.status_code == 429:
                    wait_time = 2 ** (attempt + 1)
                    main_logger.warning(f"Ratenbegrenzung bei TX {signature} (Versuch {attempt + 1}/{max_retries}). Warte {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    main_logger.error(f"Nicht behebbarer RPC-Fehler für TX {signature}: {e}")
                    return None
        main_logger.error(f"Konnte TX {signature} nach {max_retries} Versuchen wegen Ratenbegrenzung nicht laden.")
        return None

    def analyze_transaction(self, signature: Signature, monitored_wallets: set):
        tx_resp = self.get_transaction_with_retries(signature)
        
        if not tx_resp:
            main_logger.error(f"Analyse für TX {signature} übersprungen, da Details nicht geladen werden konnten.")
            return

        try:
            if not tx_resp.value or not tx_resp.value.transaction or not tx_resp.value.transaction.meta or tx_resp.value.transaction.meta.err:
                return
            
            tx = tx_resp.value.transaction
            tx_meta = tx.meta

            transfer_found = self._analyze_transfers(signature, tx_meta, monitored_wallets)
            freeze_thaw_found = self._analyze_freeze_thaw(signature, tx, tx_meta)
            
            if self.debug_mode and not transfer_found and not freeze_thaw_found:
                 main_logger.debug(f"-> Keine relevanten Aktionen für unseren Token in TX {signature} gefunden.")
        except Exception:
            main_logger.error(f"Unerwarteter Fehler bei der Analyse von TX {signature}:")
            main_logger.error(traceback.format_exc())

    def _freeze_account(self, wallet_to_freeze_pubkey: Pubkey):
        main_logger.warning(f"Leite Freeze-Aktion für Wallet {wallet_to_freeze_pubkey} ein...")
        try:
            ata_to_freeze = get_associated_token_address(wallet_to_freeze_pubkey, self.mint_pubkey)
            
            ix = freeze_account(FreezeAccountParams(
                program_id=TOKEN_PROGRAM_ID,
                account=ata_to_freeze,
                mint=self.mint_pubkey,
                authority=self.payer_keypair.pubkey()
            ))

            latest_blockhash_resp = self.client.get_latest_blockhash()
            transaction = Transaction.new_signed_with_payer(
                [ix],
                self.payer_keypair.pubkey(),
                [self.payer_keypair],
                latest_blockhash_resp.value.blockhash
            )
            
            resp = self.client.send_transaction(transaction, opts=TxOpts(skip_confirmation=False, preflight_commitment="finalized"))
            signature = resp.value
            
            main_logger.info(f"Freeze-Transaktion gesendet. Signatur: {signature}")
            self.client.confirm_transaction(signature, "finalized")
            main_logger.info(f"✅ Freeze für Wallet {wallet_to_freeze_pubkey} erfolgreich bestätigt.")
            
            self._log_event(str(signature), "ACCOUNT_FROZEN_BY_SCRIPT", frozen_wallet=str(wallet_to_freeze_pubkey))
            return True

        except Exception as e:
            main_logger.error(f"FEHLER beim Einfrieren von {wallet_to_freeze_pubkey}: {e}")
            return False

    def _analyze_transfers(self, signature: Signature, tx_meta, monitored_wallets: set) -> bool:
        if not any(hasattr(b, 'mint') and b.mint == self.mint_pubkey for b in (tx_meta.pre_token_balances or []) + (tx_meta.post_token_balances or [])):
            return False

        owner_balances = defaultdict(lambda: 0)
        for pre in (tx_meta.pre_token_balances or []):
            if hasattr(pre, 'owner') and hasattr(pre, 'mint') and pre.mint == self.mint_pubkey and hasattr(pre, 'ui_token_amount'):
                owner_balances[str(pre.owner)] -= int(pre.ui_token_amount.amount or 0)
        for post in (tx_meta.post_token_balances or []):
            if hasattr(post, 'owner') and hasattr(post, 'mint') and post.mint == self.mint_pubkey and hasattr(post, 'ui_token_amount'):
                owner_balances[str(post.owner)] += int(post.ui_token_amount.amount or 0)
        
        sender, recipient, amount = None, None, 0
        for owner, change in owner_balances.items():
            if change < 0: sender, amount = owner, abs(change) / (10**TOKEN_DECIMALS)
            elif change > 0: recipient = owner
        
        if sender and recipient and amount > 0:
            # Ein Verstoß liegt vor, wenn der Empfänger weder auf der White- noch auf der Greylist ist.
            # Wichtig: `monitored_wallets` ist der aktuelle Stand aus dem jeweiligen Analyse-Pass
            if recipient not in monitored_wallets:
                status = 'VIOLATION'
                main_logger.warning(f"-> VERSTOSS in TX {signature}: {amount:.4f} von {truncate_address(sender)} an {truncate_address(recipient)}")
                main_logger.warning(f"-> Empfänger {recipient} wird zur Greylist hinzugefügt.")
                self.greylist.add(recipient)
                
                if self.freeze_sender_on_violation:
                    self._freeze_account(Pubkey.from_string(sender))
                if self.freeze_recipient_on_violation:
                    self._freeze_account(Pubkey.from_string(recipient))
            else:
                status = 'AUTHORIZED_TRANSFER'
                main_logger.debug(f"-> Transfer ({status}) in TX {signature}: {amount:.4f} von {sender} an {recipient}")
            
            self._log_event(str(signature), status, sender=sender, recipient=recipient, amount=amount)
            return True
        return False

    def _analyze_freeze_thaw(self, signature: Signature, tx, tx_meta) -> bool:
        action_found = False
        for instruction in tx.transaction.message.instructions:
            if not hasattr(instruction, 'program_id') or instruction.program_id != TOKEN_PROGRAM_ID:
                continue
            
            parsed_info = getattr(instruction, 'parsed', None)
            
            instr_type = parsed_info.get('type') if isinstance(parsed_info, dict) else getattr(parsed_info, 'type', None)
            if instr_type not in ['freezeAccount', 'thawAccount']: continue

            info_dict = parsed_info.get('info') if isinstance(parsed_info, dict) else getattr(parsed_info, 'info', None)
            if not info_dict: continue

            mint_addr = info_dict.get('mint') if isinstance(info_dict, dict) else str(getattr(info_dict, 'mint', ''))
            ata_address = info_dict.get('account') if isinstance(info_dict, dict) else str(getattr(info_dict, 'account', ''))

            if str(mint_addr) != str(self.mint_pubkey) or not ata_address: continue

            action_found = True
            owner_address = None
            # Versuche, den Owner aus den Token Balances zu finden (effizienter)
            for tb in (tx_meta.pre_token_balances or []) + (tx_meta.post_token_balances or []):
                # Die account_keys sind als strings (base58) oder Pubkey-Objekte vorhanden
                account_keys_str = [str(k) for k in tx.transaction.message.account_keys]
                if hasattr(tb, 'account_index') and tb.account_index < len(account_keys_str) and account_keys_str[tb.account_index] == ata_address:
                    owner_address = str(getattr(tb, 'owner', None))
                    if owner_address: break
            
            if not owner_address:
                try:
                    main_logger.debug(f"-> Owner für {ata_address} nicht in Metadaten gefunden. Führe RPC-Lookup aus...")
                    info_resp = self.client.get_account_info_json_parsed(Pubkey.from_string(ata_address))
                    if info_resp.value and info_resp.value.data:
                        owner_address = info_resp.value.data.parsed['info']['owner']
                except Exception as e: main_logger.error(f"-> RPC-Lookup für Owner von {ata_address} fehlgeschlagen: {e}")

            if not owner_address:
                main_logger.warning(f"-> Konnte den Owner für Konto {ata_address} in TX {signature} endgültig nicht ermitteln.")
                continue

            status = 'ACCOUNT_FROZEN' if instr_type == 'freezeAccount' else 'ACCOUNT_THAWED'
            main_logger.info(f"-> Aktion '{status}' in TX {signature} für Wallet {owner_address} entdeckt.")
            log_params = {'frozen_wallet': owner_address} if status == 'ACCOUNT_FROZEN' else {'thawed_wallet': owner_address}
            self._log_event(str(signature), status, **log_params)
        
        return action_found

    def _perform_supply_validation(self, monitored_wallets: set):
        main_logger.info("--- Starte optionalen Validierungs-Check der Token-Menge ---")
        
        # 1. Berechne die vom Payer verteilte Menge aus den Logs
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

        # 2. Hole die aktuellen Bestände aller überwachten Wallets via RPC
        total_on_chain_balance = 0
        wallets_with_balance = 0
        main_logger.info(f"[VALIDATION] Frage On-Chain-Bestände für {len(monitored_wallets)} überwachte Wallets ab...")

        for i, wallet_str in enumerate(monitored_wallets):
            try:
                if self.debug_mode or (i % 10 == 0):
                    main_logger.info(f"[VALIDATION] Frage Bestand ab für Wallet {i+1}/{len(monitored_wallets)}...")
                
                wallet_pubkey = Pubkey.from_string(wallet_str)
                ata = get_associated_token_address(wallet_pubkey, self.mint_pubkey)
                balance_resp = self.client.get_token_account_balance(ata)
                
                if balance_resp.value and balance_resp.value.ui_amount is not None:
                    total_on_chain_balance += balance_resp.value.ui_amount
                    wallets_with_balance += 1
                time.sleep(0.1) # Ratenbegrenzung respektieren
            except SolanaRpcException:
                # Konto existiert wahrscheinlich nicht (mehr), was ok ist.
                main_logger.debug(f"[VALIDATION] Token-Konto für {wallet_str} nicht gefunden, Bestand ist 0.")
            except Exception as e:
                main_logger.error(f"[VALIDATION] Fehler beim Abrufen des Saldos für {wallet_str}: {e}")

        main_logger.info(f"[VALIDATION] {wallets_with_balance} von {len(monitored_wallets)} Wallets halten Tokens.")
        main_logger.info(f"[VALIDATION] Summe der On-Chain-Bestände in überwachten Wallets: {total_on_chain_balance:.4f} Tokens.")
        
        # 3. Vergleiche die Werte
        discrepancy = abs(total_distributed - total_on_chain_balance)
        if discrepancy < 1e-4: # Toleranz für Fließkomma-Ungenauigkeiten
            main_logger.info(f"✅ [VALIDATION] ERFOLGREICH: Die verteilte Menge stimmt mit den On-Chain-Beständen überein.")
        else:
            main_logger.error(f"❌ [VALIDATION] FEHLGESCHLAGEN: Diskrepanz von {discrepancy:.4f} Tokens entdeckt!")
        main_logger.info("--- Validierungs-Check abgeschlossen ---")

    def _log_event(self, signature: str, status: str, **kwargs):
        log_entry = {'timestamp': datetime.utcnow().isoformat(), 'signature': signature, 'status': status}
        log_entry.update(kwargs)
        transaction_logger.info(json.dumps(log_entry))

    def run_check(self):
        main_logger.info("="*50)
        main_logger.info(f"Starte Prüfungslauf um {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 1. Initialisierung
        self.whitelist = load_whitelist()
        self.greylist = load_greylist()
        state = load_state()
        
        if not self.whitelist:
            main_logger.warning("Whitelist ist leer. Prüfung wird übersprungen, da kein Startpunkt vorhanden ist.")
            return

        # Sets zur Nachverfolgung des Fortschritts innerhalb dieses Laufs
        scanned_wallets_in_run = set()
        all_signatures_in_run = set()
        processed_signatures_in_run = set()
        
        pass_num = 1
        # 2. Multi-Pass-Schleife: Läuft, solange im vorherigen Pass neue Wallets entdeckt wurden
        while True:
            main_logger.info(f"--- Starte Analyse-Pass #{pass_num} ---")
            
            # 3. Bestimme, welche Wallets in diesem Pass gescannt werden müssen
            current_monitored_set = self.whitelist.union(self.greylist)
            wallets_to_scan_this_pass = current_monitored_set - scanned_wallets_in_run
            
            if not wallets_to_scan_this_pass:
                main_logger.info("Keine neuen Wallets zum Scannen in diesem Pass. Kette ist vollständig analysiert.")
                break
                
            main_logger.info(f"Scanne Signaturen für {len(wallets_to_scan_this_pass)} Wallet(s) in diesem Pass.")

            # 4. Sammle Signaturen für die neuen Wallets
            for wallet_address in wallets_to_scan_this_pass:
                main_logger.debug(f"Prüfe Wallet: {wallet_address}")
                new_signatures = self.get_new_signatures_paginated(wallet_address, state.get(wallet_address))
                
                if new_signatures:
                    main_logger.info(f"-> {len(new_signatures)} neue Transaktion(en) für {wallet_address} gefunden.")
                    all_signatures_in_run.update(new_signatures)
                    state[wallet_address] = str(new_signatures[-1])
                
                scanned_wallets_in_run.add(wallet_address)

            # 5. Analysiere nur die neu hinzugekommenen Signaturen
            signatures_to_analyze_now = all_signatures_in_run - processed_signatures_in_run
            
            if not signatures_to_analyze_now:
                main_logger.info("Keine neuen Transaktionen in diesem Pass zu analysieren.")
                pass_num += 1
                continue
                
            main_logger.info(f"Analysiere {len(signatures_to_analyze_now)} neue, einzigartige Transaktionen...")
            
            initial_greylist_size = len(self.greylist)
            
            total_tx = len(signatures_to_analyze_now)
            sorted_signatures = sorted(list(signatures_to_analyze_now), key=lambda s: str(s))
            
            for i, sig in enumerate(sorted_signatures):
                if not self.debug_mode:
                    progress = (i + 1) / total_tx
                    bar_length = 40
                    filled_length = int(bar_length * progress)
                    bar = '█' * filled_length + '-' * (bar_length - filled_length)
                    sys.stdout.write(f'\rPass #{pass_num} Fortschritt: [{bar}] {i+1}/{total_tx} ({progress:.0%})')
                    sys.stdout.flush()
                else:
                    main_logger.info(f"Analysiere TX {i+1} von {total_tx}: {sig}")

                analysis_monitored_set = self.whitelist.union(self.greylist)
                self.analyze_transaction(sig, analysis_monitored_set)
                processed_signatures_in_run.add(sig)
                
            if not self.debug_mode:
                sys.stdout.write('\n')

            # 6. Prüfe, ob neue Wallets zur Greylist hinzugefügt wurden. Wenn ja, wird die Schleife fortgesetzt.
            if len(self.greylist) == initial_greylist_size:
                main_logger.info("In diesem Pass wurden keine neuen Greylist-Wallets entdeckt. Beende den Prüfungslauf.")
                break
            
            pass_num += 1

        # 7. Aufräumen und Speichern nach Abschluss aller Pässe
        main_logger.info("Alle Analyse-Pässe abgeschlossen. Speichere finalen Status.")
        save_state(state)
        save_greylist(self.greylist)

        main_logger.info("Aktualisiere Netzwerk-Visualisierung...")
        payer_address = str(self.payer_keypair.pubkey())
        visualizer = NetworkVisualizer(TRANSACTION_LOG_FILE, self.whitelist, self.greylist, payer_address)
        visualizer.generate_graph()
        
        if self.perform_validation:
            final_monitored_wallets = self.whitelist.union(self.greylist)
            self._perform_supply_validation(final_monitored_wallets)

        main_logger.info("Prüfungslauf abgeschlossen.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Periodischer Solana Whitelist/Greylist-Prüfer mit lückenloser Nachverfolgung.")
    parser.add_argument("--debug", action="store_true", help="Aktiviert detaillierte Debug-Ausgaben in der Konsole.")
    parser.add_argument("--interval", type=int, default=15, help="Prüfungsintervall in Minuten (Standard: 15).")
    parser.add_argument("--freezesend", action="store_true", help="Friert den Sender bei einem Whitelist/Greylist-Verstoß ein.")
    parser.add_argument("--freezereceive", action="store_true", help="Friert den Empfänger bei einem Verstoß ein.")
    parser.add_argument("--validate", action="store_true", help="Aktiviert den langsamen On-Chain Validierungs-Check am Ende jedes Laufs.")

    args = parser.parse_args()

    # Logger initial einrichten
    main_logger = setup_logger('main_checker', MAIN_LOG_FILE, debug_mode=args.debug)
    os.makedirs(ANALYSE_FOLDER, exist_ok=True)
    
    checker = PeriodicChecker(
        debug_mode=args.debug, 
        freeze_sender=args.freezesend, 
        freeze_recipient=args.freezereceive,
        validate=args.validate
    )
    
    while True:
        try:
            checker.run_check()
            interval = args.interval
            if not args.debug:
                 print(f"\nPrüfung um {datetime.now().strftime('%H:%M:%S')} abgeschlossen. Nächste Prüfung in {interval} Minuten.")
            main_logger.info(f"Warte für {interval} Minuten bis zur nächsten Prüfung.")
            time.sleep(interval * 60)
        except KeyboardInterrupt:
            main_logger.info("\nSkript wird durch Benutzer beendet.")
            sys.exit(0)
        except Exception as e:
            main_logger.critical(f"Ein kritischer Fehler ist in der Hauptschleife aufgetreten: {e}")
            main_logger.critical(traceback.format_exc())
            main_logger.info("Warte für 5 Minuten und versuche es erneut...")
            time.sleep(5 * 60)
