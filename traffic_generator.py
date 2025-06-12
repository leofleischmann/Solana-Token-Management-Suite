#!/usr/bin/env python3
# === Solana Generic Traffic Generator ===
# Erzeugt zufällige SPL-Token-Transfers zwischen Wallets in einem Ordner.

import time
import json
import os
import sys
import logging
import random
import argparse
from typing import List

# --- Solana-Bibliotheken ---
try:
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction # KORREKTUR: Import aus solders
    from solana.rpc.api import Client
    from solana.rpc.types import TxOpts
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

# Ordner für die zu verwendenden Wallets und für die Logs
WALLET_SOURCE_FOLDER = "devnet_wallets"
LOG_FOLDER = "generic_transactions"
TRANSACTION_LOG_FILE = os.path.join(LOG_FOLDER, "sent_transactions.log")

# --- Logging Setup ---
def setup_logger():
    os.makedirs(LOG_FOLDER, exist_ok=True)
    
    logger = logging.getLogger('traffic_generator')
    logger.setLevel(logging.INFO)
    
    # Konsolen-Handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_formatter = logging.Formatter('%(asctime)s - %(message)s')
    stream_handler.setFormatter(stream_formatter)
    
    # Datei-Handler
    file_handler = logging.FileHandler(TRANSACTION_LOG_FILE, mode='a', encoding='utf-8')
    file_formatter = logging.Formatter('%(asctime)s - %(message)s')
    file_handler.setFormatter(file_formatter)

    if not logger.handlers:
        logger.addHandler(stream_handler)
        logger.addHandler(file_handler)
    
    return logger

logger = setup_logger()

# --- Hilfsfunktionen ---
def truncate_address(address: str, chars: int = 4) -> str:
    if not isinstance(address, str) or len(address) < chars * 2:
        return address
    return f"{address[:chars]}...{address[-chars:]}"

def load_keypair_from_path(path: str) -> Keypair:
    with open(path, 'r') as f:
        return Keypair.from_bytes(bytes(json.load(f)))

def load_all_keypairs(folder_path: str) -> List[Keypair]:
    keypairs = []
    if not os.path.isdir(folder_path):
        logger.error(f"Wallet-Quellordner '{folder_path}' nicht gefunden!")
        return []
    
    for filename in os.listdir(folder_path):
        if filename.endswith(".json"):
            try:
                path = os.path.join(folder_path, filename)
                keypairs.append(load_keypair_from_path(path))
            except Exception as e:
                logger.error(f"Fehler beim Laden von {filename}: {e}")
    return keypairs

def get_token_balance(client: Client, owner_pubkey: Pubkey, mint_pubkey: Pubkey):
    try:
        ata = get_associated_token_address(owner_pubkey, mint_pubkey)
        balance_resp = client.get_token_account_balance(ata)
        return balance_resp.value
    except Exception:
        # Wenn das Konto nicht existiert, ist der Saldo 0
        return None

# --- Hauptlogik ---
def run_generator(delay: int, min_amount: float, max_amount: float):
    # Lade Payer, Mint und die Pool-Wallets
    try:
        payer_keypair = load_keypair_from_path(os.path.join(CONFIG_WALLET_FOLDER, "payer-wallet.json"))
        mint_pubkey = load_keypair_from_path(os.path.join(CONFIG_WALLET_FOLDER, "mint-wallet.json")).pubkey()
        wallets = load_all_keypairs(WALLET_SOURCE_FOLDER)
        # Filtere Payer und Mint aus der Liste der Wallets, um Probleme zu vermeiden
        wallets = [w for w in wallets if w.pubkey() not in [payer_keypair.pubkey(), mint_pubkey]]
    except FileNotFoundError as e:
        logger.error(f"Kritischer Fehler beim Laden der Wallets: {e}")
        sys.exit(1)

    if len(wallets) < 2:
        logger.error("Es werden mindestens 2 Wallets im 'devnet_wallets'-Ordner benötigt, um Transfers durchzuführen.")
        sys.exit(1)

    client = Client(RPC_URL)
    
    # Token-Dezimalstellen einmalig abrufen
    try:
        token_info = client.get_token_supply(mint_pubkey)
        decimals = token_info.value.decimals
    except Exception as e:
        logger.error(f"Konnte Token-Informationen für Mint {mint_pubkey} nicht abrufen: {e}")
        sys.exit(1)

    logger.info(f"{len(wallets)} Wallets geladen. Starte Traffic-Generierung...")
    logger.info(f"Payer: {payer_keypair.pubkey()}")
    logger.info(f"Token Mint: {mint_pubkey}")

    while True:
        try:
            # 1. Wähle zufälligen Sender und Empfänger
            sender_kp = random.choice(wallets)
            recipient_kp = random.choice(wallets)

            if sender_kp.pubkey() == recipient_kp.pubkey():
                continue

            # 2. Prüfe den Kontostand des Senders
            sender_balance = get_token_balance(client, sender_kp.pubkey(), mint_pubkey)
            sender_balance_ui = sender_balance.ui_amount if sender_balance else 0.0

            if sender_balance_ui is None or sender_balance_ui <= 0:
                logger.warning(f"Sender {sender_kp.pubkey()} hat keinen positiven Kontostand. Überspringe.")
                time.sleep(delay)
                continue

            # 3. Wähle eine zufällige Menge
            actual_max_amount = min(max_amount, sender_balance_ui)
            if actual_max_amount < min_amount:
                logger.warning(f"Sender {sender_kp.pubkey()} hat nicht genug Guthaben ({sender_balance_ui}) für die Mindestüberweisung ({min_amount}).")
                time.sleep(delay)
                continue
            
            random_amount = random.uniform(min_amount, actual_max_amount)
            random_amount_raw = int(random_amount * (10**decimals))
            
            logger.info(f"Versuche, {random_amount:.4f} Tokens von {truncate_address(str(sender_kp.pubkey()))} an {truncate_address(str(recipient_kp.pubkey()))} zu senden...")

            # 4. Erstelle und sende die Transaktion
            sender_ata = get_associated_token_address(sender_kp.pubkey(), mint_pubkey)
            recipient_ata = get_associated_token_address(recipient_kp.pubkey(), mint_pubkey)
            
            instructions = []
            
            # Prüfen, ob das Empfängerkonto existiert, sonst erstellen
            recipient_account_info = client.get_account_info(recipient_ata)
            if not recipient_account_info.value:
                logger.info(f"Token-Konto für Empfänger {recipient_kp.pubkey()} existiert nicht. Erstelle es...")
                instructions.append(
                    create_associated_token_account(
                        payer=payer_keypair.pubkey(),
                        owner=recipient_kp.pubkey(),
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
                        owner=sender_kp.pubkey(),
                        amount=random_amount_raw,
                        decimals=decimals,
                        signers=[]
                    )
                )
            )
            
            # Transaktion korrekt erstellen und signieren
            latest_blockhash_resp = client.get_latest_blockhash()
            transaction = Transaction.new_signed_with_payer(
                instructions,
                payer_keypair.pubkey(),
                [payer_keypair, sender_kp],
                latest_blockhash_resp.value.blockhash
            )
            
            # Senden der bereits signierten Transaktion
            resp = client.send_transaction(transaction, opts=TxOpts(skip_confirmation=False, preflight_commitment="confirmed"))
            signature = resp.value
            
            logger.info(f"✅ ERFOLG! Transaktion gesendet. Signatur: {signature}")
            
            time.sleep(delay)

        except KeyboardInterrupt:
            logger.info("Skript wird durch Benutzer beendet.")
            sys.exit(0)
        except Exception as e:
            # KORREKTUR: Spezifische Fehlerbehandlung für gesperrte Konten
            error_str = str(e).lower()
            if "account is frozen" in error_str or "custom program error: 0x11" in error_str:
                logger.warning(f"FEHLER: Konto {truncate_address(str(sender_kp.pubkey()))} ist gesperrt. Transfer wird übersprungen.")
                time.sleep(delay) # Normale Verzögerung abwarten und dann weitermachen
            else:
                logger.error(f"Ein Fehler ist aufgetreten: {e}")
                logger.info("Warte 10 Sekunden und versuche es erneut...")
                time.sleep(10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Solana Generic Traffic Generator.")
    parser.add_argument("--delay", type=int, default=10, help="Verzögerung in Sekunden zwischen den Transaktionen (Standard: 10).")
    parser.add_argument("--min", type=float, default=1.0, help="Mindestmenge an Tokens pro Transfer (Standard: 1.0).")
    parser.add_argument("--max", type=float, default=200.0, help="Höchstmenge an Tokens pro Transfer (Standard: 200.0).")
    args = parser.parse_args()

    run_generator(delay=args.delay, min_amount=args.min, max_amount=args.max)
