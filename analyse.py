#!/usr/bin/env python3
# === Periodischer Whitelist-Prüfer mit Kaskadierendem Freeze ===
# Kombiniert kostengünstige, periodische Abfragen mit detaillierter
# Analyse und grafischer Darstellung aller relevanten Transaktionen.

import time
import json
import os
import sys
import logging
import traceback
import argparse
from collections import defaultdict, deque
from datetime import datetime
from typing import Set

# --- Benötigte Bibliotheken ---
try:
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.signature import Signature
    from solana.rpc.api import Client
    from solana.rpc.types import TxOpts
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

    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.DEBUG if debug_mode else logging.INFO)

    if not logger.handlers:
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger

main_logger = logging.getLogger('main_checker')

transaction_logger = logging.getLogger('transaction_logger')
transaction_logger.setLevel(logging.INFO)
if not transaction_logger.handlers:
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
    def __init__(self, log_file: str, whitelist: set, payer_address: str):
        self.log_file = log_file
        self.whitelist = whitelist
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
                    
                    if status in ['VIOLATION', 'AUTHORIZED_TRANSFER']:
                        sender, recipient = tx.get('sender'), tx.get('recipient')
                        amount = tx.get('amount', 0)
                        if sender and recipient and amount > 0:
                            all_wallets.update([sender, recipient])
                            balances[sender] -= amount
                            balances[recipient] += amount
                            flows[(sender, recipient)] += amount
                    
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
            color_whitelist = '#22C55E'
            color_external = '#3B82F6'
            color_frozen_external = '#EF4444'
            color_frozen_whitelist = '#FF8C00'
            color_payer = '#FFD700'

            color = color_external

            if wallet == self.payer_address:
                color = color_payer
            elif wallet in final_frozen_wallets:
                color = color_frozen_whitelist if wallet in self.whitelist else color_frozen_external
            elif wallet in self.whitelist:
                color = color_whitelist
            
            balance_str = f"{balances[wallet]:.4f}".rstrip('0').rstrip('.')
            status_text = 'Payer' if wallet == self.payer_address else ('Gesperrt' if wallet in final_frozen_wallets else ('Whitelist' if wallet in self.whitelist else 'Extern'))
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
    def __init__(self, debug_mode=False, freeze_sender=False, freeze_recipient=False):
        self.debug_mode = debug_mode
        self.freeze_sender_on_violation = freeze_sender
        self.freeze_recipient_on_violation = freeze_recipient
        
        self.client = Client(RPC_URL)
        main_logger.info(f"Verbunden mit RPC-Endpunkt: {RPC_URL}")
        self.payer_keypair = load_keypair("payer-wallet.json")
        self.mint_keypair = load_keypair("mint-wallet.json")
        self.mint_pubkey = self.mint_keypair.pubkey()
        
        self.processed_in_chain = set()

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

    def analyze_transaction(self, signature: Signature, whitelist: set):
        tx_resp = self.get_transaction_with_retries(signature)
        
        if not tx_resp:
            main_logger.error(f"Analyse für TX {signature} übersprungen, da Details nicht geladen werden konnten.")
            return

        try:
            if not tx_resp.value or not tx_resp.value.transaction or not tx_resp.value.transaction.meta or tx_resp.value.transaction.meta.err:
                return
            
            tx = tx_resp.value.transaction
            tx_meta = tx.meta

            transfer_found = self._analyze_transfers(signature, tx_meta, whitelist)
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

    def _analyze_transfers(self, signature: Signature, tx_meta, whitelist: set, is_chain_trace=False) -> bool:
        """Analysiert eine Transaktion auf Transfers und gibt True zurück, wenn ein relevanter Transfer gefunden wurde."""
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
            if recipient not in whitelist:
                status = 'VIOLATION'
                main_logger.warning(f"-> VERSTOSS in TX {signature}: {amount:.4f} von {sender} an {recipient}")
                
                # Nur bei der initialen Analyse die Freeze-Aktionen auslösen, nicht in der Kettenverfolgung selbst
                if not is_chain_trace:
                    if self.freeze_sender_on_violation:
                        self._freeze_account(Pubkey.from_string(sender))
                    if self.freeze_recipient_on_violation:
                        self._trace_and_freeze_violation_chain(recipient, whitelist)
            else:
                status = 'AUTHORIZED_TRANSFER'
                main_logger.debug(f"-> Transfer ({status}) in TX {signature}: {amount:.4f} von {sender} an {recipient}")
            
            self._log_event(str(signature), status, sender=sender, recipient=recipient, amount=amount)
            return True
        return False

    def _trace_and_freeze_violation_chain(self, initial_recipient: str, whitelist: set):
        """Verfolgt die Kette einer nicht autorisierten Transaktion und friert alle beteiligten Konten ein."""
        main_logger.warning(f"Starte Kettenverfolgung für initialen Empfänger: {initial_recipient}")
        
        queue_to_process = deque([initial_recipient])
        
        while queue_to_process:
            current_wallet_address = queue_to_process.popleft()
            
            if current_wallet_address in self.processed_in_chain:
                continue

            self.processed_in_chain.add(current_wallet_address)
            
            main_logger.info(f"Kettenverfolgung: Verarbeite Wallet {current_wallet_address}")
            self._freeze_account(Pubkey.from_string(current_wallet_address))
            
            main_logger.info(f"Kettenverfolgung: Rufe Historie für {current_wallet_address} ab...")
            wallet_signatures = self.get_new_signatures_paginated(current_wallet_address, None)
            
            for sig in wallet_signatures:
                tx_resp = self.get_transaction_with_retries(sig)
                if not tx_resp or not tx_resp.value or not tx_resp.value.transaction: continue
                
                # Finde Weiterleitungen von der aktuellen Wallet und logge sie
                # Die `_analyze_transfers`-Methode wird mit `is_chain_trace=True` aufgerufen,
                # um sie zu loggen, aber keine weitere Kettenverfolgung zu starten.
                tx_meta = tx_resp.value.transaction.meta
                self._analyze_transfers(sig, tx_meta, whitelist, is_chain_trace=True)

                # Finde neue, nicht autorisierte Empfänger und füge sie der Warteschlange hinzu
                if not any(hasattr(b, 'mint') and b.mint == self.mint_pubkey for b in (tx_meta.pre_token_balances or [])):
                    continue

                tx_owner_balances = defaultdict(lambda: 0)
                for pre in (tx_meta.pre_token_balances or []):
                    if hasattr(pre, 'owner') and hasattr(pre, 'mint') and pre.mint == self.mint_pubkey and hasattr(pre, 'ui_token_amount'):
                        tx_owner_balances[str(pre.owner)] -= int(pre.ui_token_amount.amount or 0)
                for post in (tx_meta.post_token_balances or []):
                    if hasattr(post, 'owner') and hasattr(post, 'mint') and post.mint == self.mint_pubkey and hasattr(post, 'ui_token_amount'):
                        tx_owner_balances[str(post.owner)] += int(post.ui_token_amount.amount or 0)

                tx_sender, tx_recipient = None, None
                for owner, change in tx_owner_balances.items():
                    if change < 0: tx_sender = owner
                    elif change > 0: tx_recipient = owner

                if tx_sender == current_wallet_address and tx_recipient and tx_recipient not in whitelist:
                    main_logger.warning(f"Kettenverfolgung: {current_wallet_address} hat Tokens an weitere nicht-autorisierte Adresse {tx_recipient} gesendet.")
                    if tx_recipient not in self.processed_in_chain:
                        queue_to_process.append(tx_recipient)


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
            for tb in (tx_meta.pre_token_balances or []) + (tx_meta.post_token_balances or []):
                account_keys = tx.transaction.message.account_keys
                if hasattr(tb, 'account_index') and tb.account_index < len(account_keys) and str(account_keys[tb.account_index]) == ata_address:
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
            self._log_event(str(signature), status, frozen_wallet=owner_address, thawed_wallet=owner_address)
        
        return action_found

    def _log_event(self, signature: str, status: str, **kwargs):
        log_entry = {'timestamp': datetime.utcnow().isoformat(), 'signature': signature, 'status': status}
        log_entry.update(kwargs)
        transaction_logger.info(json.dumps(log_entry))

    def run_check(self):
        main_logger.info("Starte periodische Prüfung...")
        self.processed_in_chain.clear()
        whitelist = load_whitelist()
        state = load_state()
        
        if not whitelist:
            main_logger.warning("Whitelist ist leer. Prüfung wird übersprungen.")
            return

        all_new_signatures = []
        for wallet_address in whitelist:
            main_logger.debug(f"Prüfe Wallet: {wallet_address}")
            new_signatures = self.get_new_signatures_paginated(wallet_address, state.get(wallet_address))
            
            if not new_signatures:
                main_logger.debug(f"-> Keine neuen Transaktionen für {wallet_address} gefunden.")
                continue

            main_logger.info(f"-> {len(new_signatures)} neue Transaktion(en) für {wallet_address} gefunden.")
            all_new_signatures.extend(new_signatures)
            state[wallet_address] = str(new_signatures[-1])
        
        unique_new_signatures = sorted(list(set(all_new_signatures)), key=lambda s: str(s))
        if unique_new_signatures:
            total_tx = len(unique_new_signatures)
            main_logger.info(f"Verarbeite insgesamt {total_tx} einzigartige neue Transaktionen...")
            for i, sig in enumerate(unique_new_signatures):
                if not self.debug_mode:
                    progress = (i + 1) / total_tx
                    bar_length = 40
                    filled_length = int(bar_length * progress)
                    bar = '█' * filled_length + '-' * (bar_length - filled_length)
                    sys.stdout.write(f'\rAnalyse-Fortschritt: [{bar}] {i+1}/{total_tx} ({progress:.0%})')
                    sys.stdout.flush()
                else:
                    main_logger.info(f"Analysiere TX {i+1} von {total_tx}: {sig}")
                
                self.analyze_transaction(sig, whitelist)

            if not self.debug_mode:
                sys.stdout.write('\n')

        save_state(state)
        main_logger.info("Prüfung abgeschlossen.")
        
        payer_address = str(self.payer_keypair.pubkey())
        visualizer = NetworkVisualizer(TRANSACTION_LOG_FILE, whitelist, payer_address)
        visualizer.generate_graph()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Periodischer Solana Whitelist-Prüfer mit Netzwerk-Visualisierung.")
    parser.add_argument("--debug", action="store_true", help="Aktiviert detaillierte Debug-Ausgaben in der Konsole.")
    parser.add_argument("--interval", type=int, default=15, help="Prüfungsintervall in Minuten (Standard: 15).")
    parser.add_argument("--freezesend", action="store_true", help="Friert den Sender bei einem Whitelist-Verstoß ein.")
    parser.add_argument("--freezereceive", action="store_true", help="Friert den Empfänger und alle nachfolgenden nicht-autorisierten Empfänger bei einem Verstoß ein.")
    args = parser.parse_args()

    main_logger = setup_logger('main_checker', MAIN_LOG_FILE, debug_mode=args.debug)
    os.makedirs(ANALYSE_FOLDER, exist_ok=True)
    
    checker = PeriodicChecker(debug_mode=args.debug, freeze_sender=args.freezesend, freeze_recipient=args.freezereceive)
    
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
            main_logger.info("Warte für 5 Minuten und versuche es erneut...")
            time.sleep(5 * 60)
