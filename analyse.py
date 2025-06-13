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
    # from solana.rpc.types import TxOpts, Commitment, GetAccountInfoOpts # For newer solana-py
    from solana.rpc.types import TxOpts, Commitment # Adjusted for solana==0.36.6
    from solana.rpc.core import RPCException
    from solana.exceptions import SolanaRpcException
    from spl.token.instructions import get_associated_token_address, create_associated_token_account, transfer_checked, TransferCheckedParams
    from spl.token.constants import TOKEN_PROGRAM_ID
    import httpx 
except ImportError as e:
    print(f"Fehler: Eine oder mehrere erforderliche Bibliotheken fehlen oder sind nicht kompatibel: {e}.")
    print("Stellen Sie sicher, dass die korrekten Versionen installiert sind. Für die vom Nutzer gewünschten Versionen:")
    print("pip install solders==0.26.0 solana==0.36.6 spl-token==0.6.0 httpx")
    print("Alternativ können Sie versuchen, auf die neuesten Versionen zu aktualisieren (erfordert möglicherweise Code-Anpassungen):")
    print("pip install --upgrade solders solana spl-token httpx")
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
    
    if logger.hasHandlers():
        logger.handlers.clear()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    stream_handler.setFormatter(stream_formatter)
    
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

    elif isinstance(data, list):
        try:
            secret_bytes = bytes(data)
            if len(secret_bytes) == 32: # Old format from_seed
                # In solders 0.26.0, from_seed expects a list of 32 u8s, not bytes directly.
                # Keypair.from_seed expects List[int] or bytes of length 32
                # However, from_bytes(bytes_of_length_64) is more common for full keypairs
                # If it's a 32-byte seed, we need to handle it properly.
                # The original code did: Keypair.from_bytes(Keypair.from_seed(secret_bytes).to_bytes())
                # This seems correct if secret_bytes is a 32-byte seed.
                kp_from_seed = Keypair.from_seed(secret_bytes)
                return Keypair.from_bytes(kp_from_seed.to_bytes())
            elif len(secret_bytes) == 64: # Standard full keypair bytes
                return Keypair.from_bytes(secret_bytes)
            else:
                 raise ValueError(f"Schlüssel aus Liste in {path} hat eine falsche Länge: {len(secret_bytes)}")
        except ValueError as e:
            logger.error(f"Fehler beim Verarbeiten des alten Schlüsselformats in {path}: {e}")
            raise e
    else:
        raise TypeError(f"Unbekanntes oder ungültiges Key-Format in {path}.")

def load_all_keypairs(folder_path: str) -> List[Keypair]:
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
                logger.error(f"Konnte {filename} nicht laden ({e}), wird übersprungen.")
    return keypairs

def create_and_save_keypair(layer: int) -> Keypair:
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
    ata = get_associated_token_address(owner_pubkey, mint_pubkey)
    for attempt in range(4): 
        try:
            balance_resp = client.get_token_account_balance(ata, commitment=Commitment("confirmed"))
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
                logger.error(f"Unerwarteter RPC-Fehler bei get_token_balance für {truncate_address(str(ata))} (Versuch {attempt+1}): {e}")
                if attempt == 3: 
                    raise e 
                time.sleep(5) 
    return 0.0 

def fund_with_sol(client: Client, payer: Keypair, recipient_pubkey: Pubkey, sol_amount: float = 0.003) -> str:
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
    
    tx_opts = TxOpts(skip_confirmation=False, preflight_commitment=Commitment("confirmed"))
    resp = client.send_transaction(transaction, opts=tx_opts)
    signature = resp.value
    client.confirm_transaction(signature, commitment=Commitment("confirmed"))
    
    logger.info(f"Wallet {truncate_address(str(recipient_pubkey))} mit {sol_amount} SOL aufgeladen. Signatur: {signature}")
    return str(signature)

def send_token_transfer(client: Client, payer: Keypair, sender: Keypair, recipient_pubkey: Pubkey, mint_pubkey: Pubkey, amount_raw: int, decimals: int) -> str:
    if amount_raw <= 0:
        logger.warning("Transfermenge ist Null oder negativ. Überspringe.")
        return ""

    sender_ata = get_associated_token_address(sender.pubkey(), mint_pubkey)
    recipient_ata = get_associated_token_address(recipient_pubkey, mint_pubkey)
    
    instructions = []
    
    recipient_account_info_value = None
    max_retries = 4
    retry_delay = 7 

    for attempt in range(max_retries):
        try:
            logger.info(f"Versuch {attempt + 1}/{max_retries}: Rufe Kontoinformationen für ATA {truncate_address(str(recipient_ata))} ab...")
            # MODIFIED for solana==0.36.6: Pass commitment directly
            resp = client.get_account_info(recipient_ata, commitment=Commitment("confirmed"))
            recipient_account_info_value = resp.value
            logger.info(f"Kontoinformationen für ATA {truncate_address(str(recipient_ata))} erfolgreich abgerufen (Versuch {attempt + 1}).")
            break 
        except SolanaRpcException as e:
            error_message = f"SolanaRpcException bei Versuch {attempt + 1}/{max_retries} für ATA {truncate_address(str(recipient_ata))}: {str(e)[:200]}."
            if "Invalid param: TokenAccount not found" in str(e) or "could not find account" in str(e): # More specific checks for non-existent account
                logger.info(f"ATA {truncate_address(str(recipient_ata))} existiert nicht (Versuch {attempt+1}). Wird erstellt.")
                break # Exit retry loop, account will be created
            elif attempt < max_retries - 1:
                logger.warning(f"{error_message} Wiederholung in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                logger.error(f"{error_message} Alle Wiederholungen fehlgeschlagen.")
                raise 
        except Exception as e: 
            error_message = f"Unerwarteter Fehler bei Versuch {attempt + 1}/{max_retries} für ATA {truncate_address(str(recipient_ata))}: {e}."
            if attempt < max_retries - 1:
                logger.warning(f"{error_message} Wiederholung in {retry_delay}s...", exc_info=False)
                time.sleep(retry_delay)
            else:
                logger.error(f"{error_message} Alle Wiederholungen fehlgeschlagen.", exc_info=True)
                raise

    # If recipient_account_info_value is still None (e.g., after "TokenAccount not found" or if retries failed but didn't raise)
    # or if it's an account object that signifies it's empty/uninitialized (depends on exact return of older solana-py)
    # A robust check is if recipient_account_info_value is None, or if it is an Account object whose `data` field is empty or indicates no SPL token account.
    # For simplicity, if it's None, we assume it needs creation.
    if not recipient_account_info_value: 
        logger.info(f"Token-Konto (ATA) {truncate_address(str(recipient_ata))} für Empfänger {truncate_address(str(recipient_pubkey))} existiert nicht oder konnte nicht verifiziert werden. Erstelle es...")
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
    
    tx_opts = TxOpts(skip_confirmation=False, preflight_commitment=Commitment("confirmed"))
    resp = client.send_transaction(transaction, opts=tx_opts)
    signature = resp.value
    client.confirm_transaction(signature, commitment=Commitment("confirmed"))
    
    return str(signature)

# --- Hauptlogik --- (run_standard_mode and run_outside_mode remain largely the same, minor logging adjustments for decimals)
def run_standard_mode(client, payer_keypair, mint_pubkey, decimals, wallets, min_amount, max_amount):
    if len(wallets) < 2:
        logger.warning(f"Nicht genügend Wallets ({len(wallets)}) im Pool für einen Transfer.")
        return

    logger.info(f"Führe Transaktion innerhalb des Netzwerks mit {len(wallets)} Wallets durch...")

    sender_kp = random.choice(wallets)
    possible_recipients = [w for w in wallets if w.pubkey() != sender_kp.pubkey()]
    if not possible_recipients:
        logger.warning(f"Kein gültiger Empfänger für Sender {truncate_address(str(sender_kp.pubkey()))} gefunden.")
        return
    recipient_kp = random.choice(possible_recipients)
    
    sender_balance = get_token_balance(client, sender_kp.pubkey(), mint_pubkey)

    if sender_balance is None or sender_balance <= 0:
        logger.warning(f"Sender {truncate_address(str(sender_kp.pubkey()))} hat keinen positiven Kontostand ({sender_balance if sender_balance is not None else 'Fehler'}). Überspringe.")
        return

    actual_max_amount = min(max_amount, sender_balance)
    if actual_max_amount < min_amount:
        # Use f-string formatting for decimals if decimals > 0
        balance_str = f"{sender_balance:.{decimals}f}" if decimals > 0 else str(int(sender_balance))
        min_amount_str = f"{min_amount:.{decimals}f}" if decimals > 0 else str(int(min_amount))
        logger.warning(f"Sender {truncate_address(str(sender_kp.pubkey()))} hat nicht genug Guthaben ({balance_str}) für Mindestüberweisung ({min_amount_str}).")
        return
    
    random_amount = random.uniform(min_amount, actual_max_amount)
    random_amount_raw = int(random_amount * (10**decimals))

    amount_str = f"{random_amount:.{decimals}f}" if decimals > 0 else str(int(random_amount))
    logger.info(f"NETZWERK-HANDEL: Sende {amount_str} Tokens von {truncate_address(str(sender_kp.pubkey()))} an {truncate_address(str(recipient_kp.pubkey()))}...")

    try:
        sol_balance_resp = client.get_balance(sender_kp.pubkey(), commitment=Commitment("confirmed"))
        if sol_balance_resp.value < 5000: 
             logger.info(f"Lade Sender-Wallet {truncate_address(str(sender_kp.pubkey()))} mit SOL auf (aktuell: {sol_balance_resp.value} Lamports).")
             fund_with_sol(client, payer_keypair, sender_kp.pubkey()) 
             time.sleep(10)

        signature = send_token_transfer(client, payer_keypair, sender_kp, recipient_kp.pubkey(), mint_pubkey, random_amount_raw, decimals)
        if signature:
            logger.info(f"✅ ERFOLG! Transaktion im Netzwerk gesendet. Signatur: {signature}")
    except Exception as e:
        logger.error(f"Fehler bei Netzwerk-Transfer von {truncate_address(str(sender_kp.pubkey()))} zu {truncate_address(str(recipient_kp.pubkey()))}: {e}", exc_info=True)

def run_outside_mode(client, payer_keypair, mint_pubkey, decimals, initial_wallets, args, outside_network_wallets):
    if outside_network_wallets and len(outside_network_wallets) >= 2 and random.random() > 0.3:
        logger.info(f"Führe Standard-Modus innerhalb des 'outside_network_wallets' Pools ({len(outside_network_wallets)} Wallets) durch.")
        run_standard_mode(client, payer_keypair, mint_pubkey, decimals, outside_network_wallets, args.min, args.max)
        return

    logger.info(f"Starte neuen Outside-Durchlauf: {args.outside} Hops und dann Verzweigung.")
    
    if not initial_wallets:
        logger.error("OUTSIDE: Keine initialen Wallets zum Starten des Outside-Modus vorhanden.")
        return
        
    sender_kp = random.choice(initial_wallets)
    sender_balance = get_token_balance(client, sender_kp.pubkey(), mint_pubkey)
    
    sender_balance_str = f"{sender_balance or 0.0:.{decimals}f}" if decimals > 0 else str(int(sender_balance or 0.0))
    min_amount_str = f"{args.min:.{decimals}f}" if decimals > 0 else str(int(args.min))

    if sender_balance is None or sender_balance < args.min:
        logger.warning(f"OUTSIDE: Initialer Sender {truncate_address(str(sender_kp.pubkey()))} hat nicht genug Guthaben ({sender_balance_str} < {min_amount_str}). Überspringe Runde.")
        return

    min_transfer_fraction = 0.5 
    max_transfer_fraction = 0.9 
    transfer_fraction = random.uniform(min_transfer_fraction, max_transfer_fraction)
    
    transfer_amount = max(args.min, sender_balance * transfer_fraction)
    transfer_amount = min(transfer_amount, sender_balance) 

    if transfer_amount < args.min : 
        transfer_amount_str = f"{transfer_amount:.{decimals}f}" if decimals > 0 else str(int(transfer_amount))
        logger.warning(f"OUTSIDE: Berechnete Transfermenge {transfer_amount_str} für {truncate_address(str(sender_kp.pubkey()))} ist unter Minimum {min_amount_str}. Überspringe.")
        return

    transfer_amount_raw = int(transfer_amount * (10**decimals))
    
    current_sender_kp = sender_kp
    
    try:
        for i in range(1, args.outside + 1):
            hop_num = i
            logger.info(f"--- Hop {hop_num}/{args.outside} ---")
            
            new_recipient_kp = create_and_save_keypair(layer=hop_num)
            fund_with_sol(client, payer_keypair, new_recipient_kp.pubkey(), sol_amount=0.005) 
            time.sleep(10) 
            
            current_amount_str = f"{transfer_amount:.{decimals}f}" if decimals > 0 else str(int(transfer_amount))
            logger.info(f"OUTSIDE Hop {hop_num-1} ({truncate_address(str(current_sender_kp.pubkey()))}) -> Hop {hop_num} ({truncate_address(str(new_recipient_kp.pubkey()))}): Sende {current_amount_str} Tokens...")
            
            signature = send_token_transfer(client, payer_keypair, current_sender_kp, new_recipient_kp.pubkey(), mint_pubkey, transfer_amount_raw, decimals)
            logger.info(f"✅ HOP {hop_num} ERFOLGREICH! Signatur: {signature}")

            current_sender_kp = new_recipient_kp 
            time.sleep(args.delay if args.delay > 5 else 7) 

        distributor_kp = current_sender_kp
        logger.info(f"Alle {args.outside} Hops abgeschlossen. Verteiler-Wallet: {truncate_address(str(distributor_kp.pubkey()))}")
        logger.info("Starte Verzweigungsphase...")

        distributor_balance = get_token_balance(client, distributor_kp.pubkey(), mint_pubkey)
        dist_balance_str = f"{distributor_balance or 0.0:.{decimals}f}" if decimals > 0 else str(int(distributor_balance or 0.0))
        if distributor_balance is None or distributor_balance <= 0.000001: 
            logger.error(f"Verteiler-Wallet {truncate_address(str(distributor_kp.pubkey()))} hat kein Guthaben ({dist_balance_str}) für die Verzweigung.")
            return

        network_size = args.network_size if args.network_size > 0 else random.randint(2, 4)
        if network_size <= 0: network_size = 1 
        
        sol_per_branch_ata_creation = 0.0021 
        funding_amount_sol = network_size * sol_per_branch_ata_creation
        logger.info(f"Lade Verteiler-Wallet {truncate_address(str(distributor_kp.pubkey()))} für {network_size} Zweige mit {funding_amount_sol:.4f} SOL auf...")
        fund_with_sol(client, payer_keypair, distributor_kp.pubkey(), sol_amount=funding_amount_sol)
        time.sleep(10) 

        amount_per_branch = distributor_balance / network_size
        amount_per_branch_str = f"{amount_per_branch:.{decimals}f}" if decimals > 0 else str(int(amount_per_branch))
        
        # Compare amount_per_branch with args.min, not args.min / (10**decimals)
        if amount_per_branch < args.min and amount_per_branch > 0: 
             logger.warning(f"Betrag pro Zweig ({amount_per_branch_str}) ist sehr klein im Vergleich zum Minimum von {args.min}. Erwägen Sie eine Reduzierung der Netzwerkgröße oder mehr Token im Verteiler.")
        
        amount_per_branch_raw = int(amount_per_branch * (10**decimals))
        if amount_per_branch_raw <= 0:
            logger.error(f"Verteiler-Wallet {truncate_address(str(distributor_kp.pubkey()))} hat nicht genug Token ({dist_balance_str}) für {network_size} Zweige. Betrag pro Zweig wäre <= 0.")
            return

        trading_layer = args.outside + 1 
        newly_created_wallets_for_pool = []

        for i in range(network_size):
            logger.info(f"Erstelle Zweig {i+1}/{network_size}...")
            branch_wallet_kp = create_and_save_keypair(layer=trading_layer)
            
            branch_amount_str = f"{amount_per_branch:.{decimals}f}" if decimals > 0 else str(int(amount_per_branch))
            logger.info(f"Überweise {branch_amount_str} Tokens an Zweig {i+1} ({truncate_address(str(branch_wallet_kp.pubkey()))})...")
            signature = send_token_transfer(client, payer_keypair, distributor_kp, branch_wallet_kp.pubkey(), mint_pubkey, amount_per_branch_raw, decimals)
            
            if signature:
                logger.info(f"✅ Zweig {i+1} erfolgreich erstellt. Signatur: {signature}")
                newly_created_wallets_for_pool.append(branch_wallet_kp)
                fund_with_sol(client, payer_keypair, branch_wallet_kp.pubkey(), sol_amount=0.003) 
                time.sleep(args.delay if args.delay > 5 else 7) 
            else:
                logger.error(f"Fehler bei der Erstellung von Zweig {i+1} (Token-Transfer fehlgeschlagen).")

        outside_network_wallets.extend(newly_created_wallets_for_pool)
        logger.info(f"{len(newly_created_wallets_for_pool)} neue Wallets zum externen Handelspool hinzugefügt.")

    except Exception as e:
        logger.error(f"Fehler während des Outside-Modus: {e}", exc_info=True)

# ... (alle imports und Funktionen bis main) ...

def main(args):
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
        logger.error(f"Kritischer Fehler beim Laden der Start-Wallets: {e}", exc_info=True)
        sys.exit(1)

    if not initial_wallets:
        logger.error(f"Keine operativen Wallets im '{WALLET_SOURCE_FOLDER}'-Ordner gefunden (nach Filterung von Payer/Mint).")
        sys.exit(1)

    # MODIFIED for solana==0.36.6:
    # Initialize Client without httpx_client_kwargs or a direct timeout in constructor
    logger.info(f"Initialisiere RPC Client für {RPC_URL} (solana-py 0.36.6 verwendet Standard-HTTP-Timeouts)")
    client = Client(RPC_URL) 
    
    decimals = 0 # Default, will be updated
    try:
        # Fetch token info once
        token_supply_resp = client.get_token_supply(mint_pubkey, commitment=Commitment("confirmed"))
        decimals = token_supply_resp.value.decimals
    except Exception as e:
        logger.error(f"Konnte Token-Informationen für Mint {mint_pubkey} nicht abrufen: {e}", exc_info=True)
        logger.error("Konnte Dezimalstellen nicht ermitteln. Das Skript kann nicht fortfahren.")
        sys.exit(1)


    logger.info(f"{len(initial_wallets)} initiale Wallets geladen. Starte Traffic-Generierung...")
    logger.info(f"Payer: {payer_keypair.pubkey()}")
    logger.info(f"Token Mint: {mint_pubkey} (Dezimalstellen: {decimals})")

    if args.outside > 0:
        logger.info(f"Modus: --outside aktiviert mit {args.outside} Hops.")
        if args.network_size > 0: 
            logger.info(f"Netzwerkgröße pro Verzweigung: {args.network_size}")
        else: 
            logger.info(f"Netzwerkgröße pro Verzweigung: zufällig (2-4)")
    
    outside_network_wallets = [] 
    if args.outside > 0:
        trading_layer = args.outside + 1
        trading_network_folder = os.path.join(GENERATED_WALLET_FOLDER, f"layer_{trading_layer}")
        if os.path.exists(trading_network_folder):
            logger.info(f"Lade existierende Wallets aus dem Handelsnetzwerk-Ordner: '{trading_network_folder}'")
            loaded_trading_wallets = load_all_keypairs(trading_network_folder)
            
            verified_wallets = []
            if loaded_trading_wallets:
                logger.info(f"{len(loaded_trading_wallets)} potenzielle Wallets aus '{trading_network_folder}' geladen. Überprüfe Guthaben...")
                for wallet_kp in loaded_trading_wallets:
                    try:
                        sol_bal = client.get_balance(wallet_kp.pubkey(), commitment=Commitment("confirmed")).value
                        token_bal = get_token_balance(client, wallet_kp.pubkey(), mint_pubkey)
                        
                        token_bal_str = f"{token_bal:.{decimals}f}" if decimals > 0 and token_bal is not None else str(int(token_bal or 0))

                        if token_bal is not None and token_bal > 0 and sol_bal > 10000: 
                            logger.info(f"Aktives Wallet {truncate_address(str(wallet_kp.pubkey()))} mit {token_bal_str} Tokens und {sol_bal} Lamports gefunden.")
                            verified_wallets.append(wallet_kp)
                        else:
                            logger.debug(f"Wallet {truncate_address(str(wallet_kp.pubkey()))} hat unzureichendes Guthaben (Tokens: {token_bal_str}, SOL: {sol_bal}).")
                    except Exception as e:
                        logger.warning(f"Fehler beim Überprüfen von Wallet {truncate_address(str(wallet_kp.pubkey()))}: {e}. Wird ignoriert.")
            
            outside_network_wallets = verified_wallets
            if outside_network_wallets:
                 logger.info(f"{len(outside_network_wallets)} aktive Wallets im Handelsnetzwerk initialisiert.")
            else:
                 logger.info("Keine aktiven Wallets im bestehenden Handelsnetzwerk gefunden.")

    loop_count = 0
    while True:
        loop_count += 1
        logger.info(f"--- Starte Aktionszyklus {loop_count} ---")
        try:
            if args.outside > 0:
                run_outside_mode(client, payer_keypair, mint_pubkey, decimals, initial_wallets, args, outside_network_wallets)
            else: 
                if len(initial_wallets) < 2:
                    logger.error("Für den Standardmodus werden mindestens 2 Wallets im Quellordner benötigt.")
                    break 
                run_standard_mode(client, payer_keypair, mint_pubkey, decimals, initial_wallets, args.min, args.max)
            
            logger.info(f"Aktionszyklus {loop_count} beendet. Warte {args.delay} Sekunden bis zur nächsten Aktion...")
            time.sleep(args.delay)

        except KeyboardInterrupt:
            logger.info("Skript wird durch Benutzer beendet.")
            sys.exit(0)
        except SolanaRpcException as e: 
            # Check if the error message indicates a timeout, which is more likely without explicit timeout control
            if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                logger.error(f"Solana RPC Timeout im Hauptzyklus: {e}", exc_info=False) # exc_info=False for cleaner timeout log
                logger.info("RPC Timeout. Warte 90 Sekunden und versuche es erneut...")
                time.sleep(90) # Longer wait for timeouts
            else:
                logger.error(f"Solana RPC Fehler im Hauptzyklus: {e}", exc_info=True)
                logger.info("Warte 60 Sekunden und versuche es erneut...")
                time.sleep(60)
        except Exception as e: 
            logger.error(f"Ein unerwarteter Hauptfehler ist aufgetreten: {e}", exc_info=True)
            logger.info("Warte 30 Sekunden und versuche es erneut...")
            time.sleep(30)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Solana Advanced Traffic Generator.")
    parser.add_argument("--delay", type=int, default=7, help="Verzögerung in Sekunden zwischen den Aktionen (Standard: 7).")
    parser.add_argument("--min", type=float, default=1.0, help="Mindestmenge an Tokens pro Transfer (Standard: 1.0).")
    parser.add_argument("--max", type=float, default=100.0, help="Höchstmenge an Tokens pro Transfer (Standard: 100.0).")
    parser.add_argument("--outside", type=int, default=0, help="Aktiviert den 'Outside'-Modus. Gibt die Anzahl der Hops an (0 deaktiviert).")
    parser.add_argument("--network-size", type=int, default=0, help="Feste Anzahl der Wallets im neuen Handelsnetzwerk nach Verzweigung. (Standard: zufällig 2-4, wenn 0 angegeben)")
    
    args = parser.parse_args()

    if args.min <= 0 or args.max <= 0 or args.max < args.min:
        print("Fehler: --min und --max müssen positiv sein, und --max muss >= --min sein.")
        sys.exit(1)
    if args.delay < 0:
        print("Fehler: --delay darf nicht negativ sein.")
        sys.exit(1)
    if args.outside < 0:
        print("Fehler: --outside darf nicht negativ sein.")
        sys.exit(1)
    if args.network_size < 0:
        print("Fehler: --network-size darf nicht negativ sein.")
        sys.exit(1)
        
    main(args)
