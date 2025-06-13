#!/usr/bin/env python3
# === Solana Advanced Traffic Generator ===
# Erzeugt zufällige und mehrstufige SPL-Token-Transfers, 
# um die Nachverfolgbarkeit zu erschweren.

import time
import json
import os
import sys
import logging
import random
import argparse
import base64
import binascii
from typing import List, Optional

# --- Solana-Bibliotheken ---
try:
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction
    from solders.system_program import transfer, TransferParams
    from solana.rpc.api import Client
    from solana.rpc.types import TxOpts, Commitment
    from solana.rpc.core import RPCException
    from solana.exceptions import SolanaRpcException
    from spl.token.instructions import get_associated_token_address, create_associated_token_account, transfer_checked, TransferCheckedParams
    from spl.token.constants import TOKEN_PROGRAM_ID
except ImportError as e:
    print(f"Fehler: Eine oder mehrere erforderliche Bibliotheken fehlen: {e}.")
    print("Bitte installieren Sie diese mit: pip install solders solana spl-token")
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
CONFIG_WALLET_FOLDER = CONFIG.get("wallet_folder")

# --- Ordner-Konstanten ---
WALLET_SOURCE_FOLDER = "devnet_wallets" # Whitelist-Wallets
LOG_FOLDER = "generic_transactions"
GENERATED_WALLET_FOLDER = os.path.join(LOG_FOLDER, "generated_wallets") # Ordner für neue Wallets
TRANSACTION_LOG_FILE = os.path.join(LOG_FOLDER, "sent_transactions.log")

# --- Logging Setup ---
def setup_logger():
    os.makedirs(LOG_FOLDER, exist_ok=True)
    
    logger = logging.getLogger('traffic_generator')
    logger.setLevel(logging.INFO)
    
    # Verhindert doppelte Handler
    if logger.hasHandlers():
        logger.handlers.clear()

    # Konsolen-Handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    stream_handler.setFormatter(stream_formatter)
    
    # Datei-Handler
    file_handler = logging.FileHandler(TRANSACTION_LOG_FILE, mode='a', encoding='utf-8')
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logger()

# --- Wallet- und Hilfsfunktionen ---
def truncate_address(address: str, chars: int = 4) -> str:
    """Kürzt eine Adresse zur besseren Darstellung."""
    if not isinstance(address, str) or len(address) < chars * 2:
        return address
    return f"{address[:chars]}...{address[-chars:]}"

def load_keypair_from_path(path: str) -> Keypair:
    """Lädt ein Keypair aus einer JSON-Datei (unterstützt altes Listen- und neues Base64-Format)."""
    with open(path, 'r') as f:
        data = json.load(f)

    # Prüfen auf neues Base64-Format (string)
    if isinstance(data, str):
        try:
            b64_secret = data.encode('ascii')
            secret_bytes = base64.b64decode(b64_secret)
            if len(secret_bytes) != 64:
                 raise ValueError(f"Dekodierter Base64-Schlüssel aus {path} hat eine falsche Länge: {len(secret_bytes)}")
            return Keypair.from_bytes(secret_bytes)
        except (ValueError, binascii.Error) as e:
            logger.error(f"Fehler beim Dekodieren des Base64-Schlüssels in {path}: {e}")
            raise e

    # Prüfen auf altes Listen-Format (list of ints)
    elif isinstance(data, list):
        try:
            secret_bytes = bytes(data)
            if len(secret_bytes) == 32:
                kp = Keypair.from_seed(secret_bytes)
                return Keypair.from_bytes(kp.to_bytes()) 
            elif len(secret_bytes) == 64:
                return Keypair.from_bytes(secret_bytes)
            else:
                 raise ValueError(f"Schlüssel aus Liste in {path} hat eine falsche Länge: {len(secret_bytes)}")
        except ValueError as e:
            logger.error(f"Fehler beim Verarbeiten des alten Schlüsselformats in {path}: {e}")
            raise e
            
    # Wenn keines der Formate passt
    else:
        raise TypeError(f"Unbekanntes oder ungültiges Key-Format in {path}.")

def load_all_keypairs(folder_path: str) -> List[Keypair]:
    """Lädt alle Keypairs aus einem Ordner."""
    keypairs = []
    if not os.path.isdir(folder_path):
        logger.warning(f"Wallet-Ordner '{folder_path}' nicht gefunden!")
        return []
    
    for filename in os.listdir(folder_path):
        if filename.endswith(".json"):
            try:
                path = os.path.join(folder_path, filename)
                keypairs.append(load_keypair_from_path(path))
            except Exception as e:
                logger.error(f"Konnte {filename} nicht laden, wird übersprungen.")
    return keypairs

def create_and_save_keypair(layer: int) -> Keypair:
    """Erstellt ein neues Keypair und speichert es als Base64-String in einer JSON-Datei."""
    kp = Keypair()
    layer_folder = os.path.join(GENERATED_WALLET_FOLDER, f"layer_{layer}")
    os.makedirs(layer_folder, exist_ok=True)
    
    filepath = os.path.join(layer_folder, f"{kp.pubkey()}.json")
    with open(filepath, 'w') as f:
        secret_bytes = kp.to_bytes()
        b64_secret = base64.b64encode(secret_bytes)
        b64_string = b64_secret.decode('ascii')
        json.dump(b64_string, f)
        
    logger.info(f"Neues Wallet erstellt und gespeichert: {kp.pubkey()} in '{layer_folder}'")
    return kp

def get_token_balance(client: Client, owner_pubkey: Pubkey, mint_pubkey: Pubkey) -> Optional[float]:
    """Ruft den Token-Kontostand mit Wiederholungsversuchen ab, um RPC-Verzögerungen abzufangen."""
    ata = get_associated_token_address(owner_pubkey, mint_pubkey)
    for attempt in range(4): # Versuche es bis zu 4 Mal
        try:
            balance_resp = client.get_token_account_balance(ata)
            if balance_resp.value.ui_amount is None:
                return 0.0
            return balance_resp.value.ui_amount
        except RPCException as e:
            if "Invalid param: could not find account" in str(e):
                if attempt < 3: 
                    logger.warning(f"Versuch {attempt + 1}: Token-Konto {truncate_address(str(ata))} noch nicht gefunden. Warte 5 Sekunden...")
                    time.sleep(5)
                else: 
                    logger.error(f"Konnte Token-Konto {truncate_address(str(ata))} nach mehreren Versuchen nicht finden.")
                    return 0.0
            else:
                logger.error(f"Unerwarteter RPC-Fehler bei get_token_balance: {e}")
                raise e
    return 0.0

def fund_with_sol(client: Client, payer: Keypair, recipient_pubkey: Pubkey, sol_amount: float = 0.003) -> str:
    """Überweist SOL an ein Wallet, um Gebühren zu decken."""
    lamports = int(sol_amount * 1_000_000_000)
    
    instruction = transfer(
        TransferParams(
            from_pubkey=payer.pubkey(),
            to_pubkey=recipient_pubkey,
            lamports=lamports
        )
    )
    
    latest_blockhash_resp = client.get_latest_blockhash()
    transaction = Transaction.new_signed_with_payer(
        [instruction],
        payer.pubkey(),
        [payer],
        latest_blockhash_resp.value.blockhash
    )
    
    resp = client.send_transaction(transaction, opts=TxOpts(skip_confirmation=False, preflight_commitment="confirmed"))
    signature = resp.value
    client.confirm_transaction(signature, commitment=Commitment("confirmed"))
    
    logger.info(f"Wallet {truncate_address(str(recipient_pubkey))} mit {sol_amount} SOL aufgeladen. Signatur: {signature}")
    return str(signature)

def send_token_transfer(client: Client, payer: Keypair, sender: Keypair, recipient_pubkey: Pubkey, mint_pubkey: Pubkey, amount_raw: int, decimals: int) -> str:
    """Führt eine einzelne SPL-Token-Überweisung durch."""
    if amount_raw <= 0:
        logger.warning("Transfermenge ist Null oder negativ. Überspringe.")
        return ""

    sender_ata = get_associated_token_address(sender.pubkey(), mint_pubkey)
    recipient_ata = get_associated_token_address(recipient_pubkey, mint_pubkey)
    
    instructions = []
    
    recipient_account_info = client.get_account_info(recipient_ata)
    if not recipient_account_info.value:
        logger.info(f"Token-Konto für Empfänger {truncate_address(str(recipient_pubkey))} existiert nicht. Erstelle es...")
        instructions.append(
            create_associated_token_account(
                payer=sender.pubkey(),
                owner=recipient_pubkey,
                mint=mint_pubkey
            )
        )

    instructions.append(
        transfer_checked(
            TransferCheckedParams(
                program_id=TOKEN_PROGRAM_ID,
                source=sender_ata,
                mint=mint_pubkey,
                dest=recipient_ata,
                owner=sender.pubkey(),
                amount=amount_raw,
                decimals=decimals,
                signers=[]
            )
        )
    )
    
    latest_blockhash_resp = client.get_latest_blockhash()
    transaction = Transaction.new_signed_with_payer(
        instructions,
        payer.pubkey(),
        [payer, sender],
        latest_blockhash_resp.value.blockhash
    )
    
    resp = client.send_transaction(transaction, opts=TxOpts(skip_confirmation=False, preflight_commitment="confirmed"))
    signature = resp.value
    client.confirm_transaction(signature, commitment=Commitment("confirmed"))
    
    return str(signature)


# --- Hauptlogik ---
def run_standard_mode(client, payer_keypair, mint_pubkey, decimals, wallets, min_amount, max_amount):
    """Führt den normalen Transfermodus zwischen den Wallets im Pool aus."""
    if len(wallets) < 2:
        logger.warning(f"Nicht genügend Wallets ({len(wallets)}) im Pool für einen Transfer.")
        return

    logger.info(f"Führe Transaktion innerhalb des Netzwerks mit {len(wallets)} Wallets durch...")

    sender_kp = random.choice(wallets)
    recipient_kp = random.choice(wallets)

    if sender_kp.pubkey() == recipient_kp.pubkey():
        return

    sender_balance = get_token_balance(client, sender_kp.pubkey(), mint_pubkey)

    if sender_balance is None or sender_balance <= 0:
        logger.warning(f"Sender {truncate_address(str(sender_kp.pubkey()))} hat keinen positiven Kontostand. Überspringe.")
        return

    actual_max_amount = min(max_amount, sender_balance)
    if actual_max_amount < min_amount:
        logger.warning(f"Sender {truncate_address(str(sender_kp.pubkey()))} hat nicht genug Guthaben ({sender_balance:.4f}) für Mindestüberweisung ({min_amount}).")
        return
    
    random_amount = random.uniform(min_amount, actual_max_amount)
    random_amount_raw = int(random_amount * (10**decimals))
    
    logger.info(f"NETZWERK-HANDEL: Sende {random_amount:.4f} Tokens von {truncate_address(str(sender_kp.pubkey()))} an {truncate_address(str(recipient_kp.pubkey()))}...")

    try:
        sol_balance_resp = client.get_balance(sender_kp.pubkey())
        if sol_balance_resp.value < 2500000:
             fund_with_sol(client, payer_keypair, sender_kp.pubkey())
             time.sleep(5)

        signature = send_token_transfer(client, payer_keypair, sender_kp, recipient_kp.pubkey(), mint_pubkey, random_amount_raw, decimals)
        if signature:
            logger.info(f"✅ ERFOLG! Transaktion im Netzwerk gesendet. Signatur: {signature}")
    except Exception as e:
        logger.error(f"Fehler bei Netzwerk-Transfer: {e}")

def run_outside_mode(client, payer_keypair, mint_pubkey, decimals, initial_wallets, args, outside_network_wallets):
    """Führt einen mehrstufigen Transfer und die Verzweigung in ein neues Netzwerk durch."""
    
    if len(outside_network_wallets) >= 2 and random.random() > 0.3:
        run_standard_mode(client, payer_keypair, mint_pubkey, decimals, outside_network_wallets, args.min, args.max)
        return

    logger.info(f"Starte neuen Outside-Durchlauf: {args.outside} Hops und dann Verzweigung.")
    
    sender_kp = random.choice(initial_wallets)
    sender_balance = get_token_balance(client, sender_kp.pubkey(), mint_pubkey)
    
    if sender_balance is None or sender_balance < args.min:
        logger.warning(f"OUTSIDE: Initialer Sender {truncate_address(str(sender_kp.pubkey()))} hat nicht genug Guthaben ({sender_balance or 0.0:.4f}). Überspringe Runde.")
        return

    transfer_amount = sender_balance * random.uniform(0.8, 1.0)
    transfer_amount_raw = int(transfer_amount * (10**decimals))
    
    current_sender_kp = sender_kp
    
    try:
        # --- PHASE 1: Hop-Kette ---
        for i in range(1, args.outside + 1):
            hop_num = i
            logger.info(f"--- Hop {hop_num}/{args.outside} ---")
            
            new_recipient_kp = create_and_save_keypair(layer=hop_num)
            fund_with_sol(client, payer_keypair, new_recipient_kp.pubkey())
            time.sleep(5)
            
            logger.info(f"OUTSIDE: Sende {transfer_amount:.4f} Tokens von Hop {hop_num-1} zu Hop {hop_num}...")
            
            signature = send_token_transfer(client, payer_keypair, current_sender_kp, new_recipient_kp.pubkey(), mint_pubkey, transfer_amount_raw, decimals)
            logger.info(f"✅ HOP {hop_num} ERFOLGREICH! Signatur: {signature}")

            current_sender_kp = new_recipient_kp
            time.sleep(5)

        # --- PHASE 2: Verzweigung / Distribution ---
        distributor_kp = current_sender_kp
        logger.info(f"Alle Hops abgeschlossen. Verteiler-Wallet: {distributor_kp.pubkey()}")
        logger.info("Starte Verzweigungsphase...")

        distributor_balance = get_token_balance(client, distributor_kp.pubkey(), mint_pubkey)
        if distributor_balance is None or distributor_balance <= 0:
            logger.error("Verteiler-Wallet hat kein Guthaben für die Verzweigung.")
            return

        network_size = args.network_size if args.network_size > 0 else random.randint(2, 4)
        if network_size <= 0: network_size = 1 # Fallback
        
        funding_amount = network_size * 0.0025 # ~0.0021 pro ATA + Puffer
        logger.info(f"Lade Verteiler-Wallet für {network_size} Zweige mit {funding_amount} SOL auf...")
        fund_with_sol(client, payer_keypair, distributor_kp.pubkey(), sol_amount=funding_amount)
        time.sleep(5)

        amount_per_branch_raw = int((distributor_balance * (10**decimals)) / network_size)
        trading_layer = args.outside + 1
        newly_created_wallets = []

        for i in range(network_size):
            logger.info(f"Erstelle Zweig {i+1}/{network_size}...")
            branch_wallet_kp = create_and_save_keypair(layer=trading_layer)
            
            logger.info(f"Überweise an Zweig {i+1}...")
            signature = send_token_transfer(client, payer_keypair, distributor_kp, branch_wallet_kp.pubkey(), mint_pubkey, amount_per_branch_raw, decimals)
            
            if signature:
                logger.info(f"✅ Zweig {i+1} erfolgreich erstellt. Signatur: {signature}")
                newly_created_wallets.append(branch_wallet_kp)
                time.sleep(5)
            else:
                logger.error(f"Fehler bei der Erstellung von Zweig {i+1}.")

        outside_network_wallets.extend(newly_created_wallets)
        logger.info(f"{len(newly_created_wallets)} neue Wallets zum externen Netzwerk hinzugefügt.")

    except Exception as e:
        logger.error(f"Fehler während des Outside-Modus: {e}", exc_info=True)


def main(args):
    """Hauptfunktion des Generators."""
    try:
        payer_path = os.path.join(CONFIG_WALLET_FOLDER, "payer-wallet.json")
        mint_path = os.path.join(CONFIG_WALLET_FOLDER, "mint-wallet.json")
        
        if not os.path.exists(payer_path) or not os.path.exists(mint_path):
             logger.error(f"Kritischer Fehler: 'payer-wallet.json' oder 'mint-wallet.json' nicht im Ordner '{CONFIG_WALLET_FOLDER}' gefunden.")
             sys.exit(1)

        payer_keypair = load_keypair_from_path(payer_path)
        mint_pubkey = load_keypair_from_path(mint_path).pubkey()
        initial_wallets = load_all_keypairs(WALLET_SOURCE_FOLDER)
        initial_wallets = [w for w in initial_wallets if w.pubkey() not in [payer_keypair.pubkey(), mint_pubkey]]
    except Exception as e:
        logger.error(f"Kritischer Fehler beim Laden der Start-Wallets: {e}")
        sys.exit(1)

    if not initial_wallets:
        logger.error(f"Keine Wallets im '{WALLET_SOURCE_FOLDER}'-Ordner gefunden.")
        sys.exit(1)

    client = Client(RPC_URL)
    
    try:
        token_info = client.get_token_supply(mint_pubkey)
        decimals = token_info.value.decimals
    except Exception as e:
        logger.error(f"Konnte Token-Informationen für Mint {mint_pubkey} nicht abrufen: {e}")
        sys.exit(1)

    logger.info(f"{len(initial_wallets)} initiale Wallets geladen. Starte Traffic-Generierung...")
    logger.info(f"Payer: {payer_keypair.pubkey()}")
    logger.info(f"Token Mint: {mint_pubkey}")
    if args.outside > 0:
        logger.info(f"Modus: --outside aktiviert mit {args.outside} Hops.")
        if args.network_size > 0:
            logger.info(f"Netzwerkgröße pro Verzweigung: {args.network_size}")
    
    outside_network_wallets = []
    if args.outside > 0:
        trading_layer = args.outside + 1
        trading_network_folder = os.path.join(GENERATED_WALLET_FOLDER, f"layer_{trading_layer}")
        if os.path.exists(trading_network_folder):
            loaded_wallets = load_all_keypairs(trading_network_folder)
            logger.info(f"{len(loaded_wallets)} potenzielle Wallets aus dem Handelsnetzwerk (layer_{trading_layer}) geladen. Überprüfe Guthaben...")
            
            # KORREKTUR: Filtere Wallets heraus, die kein Token-Guthaben haben.
            verified_wallets = []
            for wallet in loaded_wallets:
                # Wir rufen hier den Kontostand ab, aber ohne die Wiederholungslogik, um den Start zu beschleunigen.
                # Wenn ein Konto existiert, wird es sofort gefunden. Wenn nicht, ist es wahrscheinlich leer.
                try:
                    ata = get_associated_token_address(wallet.pubkey(), mint_pubkey)
                    balance_resp = client.get_token_account_balance(ata)
                    if balance_resp.value.ui_amount and balance_resp.value.ui_amount > 0:
                        verified_wallets.append(wallet)
                    else:
                         logger.warning(f"Entferne Wallet {wallet.pubkey()} aus dem Pool, da es kein positives Token-Guthaben hat.")
                except RPCException:
                    logger.warning(f"Entferne Wallet {wallet.pubkey()} aus dem Pool, da kein Token-Konto gefunden wurde.")

            outside_network_wallets = verified_wallets
            logger.info(f"{len(outside_network_wallets)} aktive Wallets im Handelsnetzwerk gefunden.")

    while True:
        try:
            if args.outside > 0:
                run_outside_mode(client, payer_keypair, mint_pubkey, decimals, initial_wallets, args, outside_network_wallets)
            else:
                if len(initial_wallets) < 2:
                    logger.error("Für den Standardmodus werden mindestens 2 Wallets benötigt.")
                    break
                run_standard_mode(client, payer_keypair, mint_pubkey, decimals, initial_wallets, args.min, args.max)
            
            logger.info(f"Warte {args.delay} Sekunden bis zur nächsten Aktion...")
            time.sleep(args.delay)

        except KeyboardInterrupt:
            logger.info("Skript wird durch Benutzer beendet.")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Ein unerwarteter Hauptfehler ist aufgetreten: {e}", exc_info=True)
            logger.info("Warte 30 Sekunden und versuche es erneut...")
            time.sleep(30)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Solana Advanced Traffic Generator.")
    parser.add_argument("--delay", type=int, default=15, help="Verzögerung in Sekunden zwischen den Aktionen (Standard: 15).")
    parser.add_argument("--min", type=float, default=1.0, help="Mindestmenge an Tokens pro Transfer (Standard: 1.0).")
    parser.add_argument("--max", type=float, default=100.0, help="Höchstmenge an Tokens pro Transfer (Standard: 100.0).")
    parser.add_argument("--outside", type=int, default=0, help="Aktiviert den 'Outside'-Modus. Gibt die Anzahl der Hops an.")
    parser.add_argument("--network-size", type=int, default=0, help="Anzahl der Wallets im neuen Handelsnetzwerk. (Standard: zufällig 2-4)")
    
    args = parser.parse_args()
    main(args)
