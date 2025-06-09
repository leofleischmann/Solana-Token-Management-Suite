#!/usr/bin/env python3
# === setup_ui_improved.py: Verbesserte grafische Benutzeroberfläche für das Solana Setup-Skript ===

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
import threading
import queue
import time
import os
import sys
import json
from typing import Dict, List, Optional, Tuple

# Import der gemeinsamen UI-Komponenten
from ui_components import (
    DesignSystem, StatusIndicator, CopyableLabel, ProgressDialog, 
    ConfirmDialog, EnhancedTextbox, show_error, show_info, run_in_thread,
    format_sol_amount, format_token_amount, truncate_address
)

# --- Solana-Bibliotheken ---
try:
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.system_program import CreateAccountParams, create_account, transfer as system_transfer, TransferParams as SystemTransferParams
    from solders.transaction import Transaction
    from solana.rpc.api import Client
    from solana.exceptions import SolanaRpcException
    from spl.token.instructions import (
        get_associated_token_address,
        create_associated_token_account,
        mint_to, MintToParams,
        initialize_mint, InitializeMintParams
    )
    from spl.token.constants import TOKEN_PROGRAM_ID
except ImportError:
    messagebox.showerror("Fehler", "Eine oder mehrere Solana-Bibliotheken fehlen. Bitte installieren Sie diese (z.B. mit `pip install solana solders spl-token`).")
    sys.exit(1)

# --- Metadaten-Bibliothek (Optional) ---
try:
    from mpl_token_metadata.instructions import create_metadata_account_v3, CreateMetadataAccountV3InstructionArgs
    from mpl_token_metadata.accounts import Metadata
    from mpl_token_metadata.types import DataV2
    METADATA_LIB_AVAILABLE = True
except ImportError:
    METADATA_LIB_AVAILABLE = False

# --- Hilfsfunktionen für Transaktionen ---
def confirm_and_send_transaction(http_client: Client, instructions, signers: list[Keypair], label: str, log_func):
    """Baut, sendet und bestätigt eine Transaktion mit UI-Feedback."""
    log_func(f"→ Sende Transaktion: '{label}'...", "info")
    try:
        blockhash_resp = http_client.get_latest_blockhash()
        transaction = Transaction.new_signed_with_payer(
            instructions,
            payer=signers[0].pubkey(),
            signing_keypairs=signers,
            recent_blockhash=blockhash_resp.value.blockhash,
        )
        result = http_client.send_transaction(transaction)
        log_func(f"   Transaktion gesendet, warte auf Bestätigung... Signatur: {result.value}", "info")
        http_client.confirm_transaction(result.value, "finalized", sleep_seconds=5.0)
        log_func(f"{DesignSystem.ICONS['success']} ERFOLG '{label}'! Signatur: {result.value}", "success")
        return True
    except Exception as e:
        log_func(f"{DesignSystem.ICONS['error']} FEHLER bei '{label}': {e}", "error")
        raise e

# === Setup-Konfiguration ===

class SetupConfig:
    """Konfigurationsklasse für Setup-Parameter"""
    
    def __init__(self):
        # Payer
        self.payer_vanity = False
        self.payer_prefix = ""
        # Mint
        self.mint_vanity = False
        self.mint_prefix = ""
        # Test Users
        self.test_user_count = 3
        self.test_user_vanity = False
        self.test_user_prefix = ""
        self.sol_for_users = 0.05
        # Token
        self.initial_mint_amount = 1000000.0
        self.create_metadata = False
        self.token_name = ""
        self.token_symbol = ""
        self.token_uri = ""
        
    def validate(self) -> Tuple[bool, str]:
        """Validiert die Konfiguration"""
        if self.payer_vanity and not self.payer_prefix.strip():
            return False, "Payer-Präfix darf nicht leer sein."
        if self.mint_vanity and not self.mint_prefix.strip():
            return False, "Mint-Präfix darf nicht leer sein."
        if self.test_user_vanity and not self.test_user_prefix.strip():
            return False, "Testnutzer-Präfix darf nicht leer sein."
        
        if self.payer_vanity and not self.payer_prefix.isalnum():
            return False, "Payer-Präfix darf nur Buchstaben und Zahlen enthalten."
        if self.mint_vanity and not self.mint_prefix.isalnum():
            return False, "Mint-Präfix darf nur Buchstaben und Zahlen enthalten."
        if self.test_user_vanity and not self.test_user_prefix.isalnum():
            return False, "Testnutzer-Präfix darf nur Buchstaben und Zahlen enthalten."

        if self.initial_mint_amount <= 0:
            return False, "Initialer Token-Vorrat muss positiv sein."
        if self.sol_for_users < 0:
            return False, "SOL-Betrag für Nutzer darf nicht negativ sein."
        if self.test_user_count < 0 or self.test_user_count > 20:
            return False, "Anzahl Testnutzer muss zwischen 0 und 20 liegen."
        
        if self.create_metadata:
            if not self.token_name.strip():
                return False, "Token-Name ist erforderlich für Metadaten."
            if not self.token_symbol.strip():
                return False, "Token-Symbol ist erforderlich für Metadaten."
        
        return True, ""
    
    def get_summary(self) -> List[str]:
        """Erstellt eine Zusammenfassung der Konfiguration"""
        summary = []
        
        # Wallets
        payer_desc = f"Payer/Emittent: {'Vanity (' + self.payer_prefix + ')' if self.payer_vanity else 'Zufällig'}"
        mint_desc = f"Token Mint: {'Vanity (' + self.mint_prefix + ')' if self.mint_vanity else 'Zufällig'}"
        users_desc = f"Testnutzer: {self.test_user_count} Wallets"
        if self.test_user_vanity:
            users_desc += f" (Vanity mit Präfix '{self.test_user_prefix}')"
        
        summary.extend([payer_desc, mint_desc, users_desc])
        
        # Token
        summary.append(f"Initialer Vorrat: {self.initial_mint_amount:,.0f} Tokens")
        if self.test_user_count > 0:
            summary.append(f"Finanzierung Nutzer: {self.sol_for_users} SOL pro Nutzer")
        
        if self.create_metadata:
            summary.append(f"Metadaten: {self.token_name} ({self.token_symbol})")
        else:
            summary.append("Metadaten: Keine")
        
        return summary

# === Hauptanwendung ===

class SetupUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # --- UI-Konfiguration ---
        self.title("Solana Environment Setup - Verbesserte Version")
        self.geometry("1000x800")
        self.minsize(900, 700)
        
        # Design-System anwenden
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("green")

        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        # State
        self.log_queue = queue.Queue()
        self.http_client = None
        self.config = {}
        self.setup_config = SetupConfig()
        self.setup_cancelled = False
        self.setup_exists = False

        self._create_widgets()
        self.after(200, self.process_log_queue)
        self.load_and_display_config()

    def _create_widgets(self):
        """Erstellt die Hauptbenutzeroberfläche"""
        # --- Header ---
        self._create_header()
        
        # --- Hauptinhalt mit Tabs ---
        self._create_main_content()

    def _create_header(self):
        """Erstellt den Header-Bereich"""
        header_frame = ctk.CTkFrame(self, corner_radius=DesignSystem.RADIUS['lg'])
        header_frame.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], 
                         pady=DesignSystem.SPACING['md'], sticky="ew")
        header_frame.grid_columnconfigure(1, weight=1)
        
        # Titel und Icon
        title_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_frame.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], 
                        pady=DesignSystem.SPACING['md'], sticky="w")
        
        ctk.CTkLabel(
            title_frame, 
            text=f"{DesignSystem.ICONS['settings']} Solana Environment Setup", 
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left")
        
        # Status und Aktionen
        actions_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        actions_frame.grid(row=0, column=1, padx=DesignSystem.SPACING['md'], 
                          pady=DesignSystem.SPACING['md'], sticky="e")
        
        self.connection_status = StatusIndicator(
            actions_frame, 
            status="unknown", 
            text="Nicht verbunden"
        )
        self.connection_status.pack(side="top", anchor="e")
        
        # Haupt-Setup-Button
        self.start_button = ctk.CTkButton(
            actions_frame, 
            text=f"{DesignSystem.ICONS['start']} Setup starten", 
            command=self._start_setup_with_confirmation,
            font=ctk.CTkFont(size=14, weight="bold"), 
            height=40,
            fg_color=DesignSystem.COLORS['success']
        )
        self.start_button.pack(side="bottom", anchor="e", pady=(DesignSystem.SPACING['sm'], 0))

    def _create_main_content(self):
        """Erstellt den Hauptinhalt mit Tabs"""
        self.tab_view = ctk.CTkTabview(self, corner_radius=DesignSystem.RADIUS['lg'])
        self.tab_view.grid(row=1, column=0, padx=DesignSystem.SPACING['md'], 
                          pady=(0, DesignSystem.SPACING['md']), sticky="nsew")
        
        # Tabs hinzufügen
        self.tab_view.add("⚙️ Konfiguration")
        self.tab_view.add("📋 Vorschau")
        self.tab_view.add("📊 Fortschritt")
        self.tab_view.add("ℹ️ Info")
        
        self.config_tab = self.tab_view.tab("⚙️ Konfiguration")
        self._create_config_tab(self.config_tab)
        self._create_preview_tab(self.tab_view.tab("📋 Vorschau"))
        self._create_progress_tab(self.tab_view.tab("📊 Fortschritt"))
        self._create_info_tab(self.tab_view.tab("ℹ️ Info"))

    def _create_config_tab(self, tab):
        """Erstellt den Konfiguration-Tab"""
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        
        # Platzhalter für "Setup existiert"-Nachricht
        self.existing_setup_frame = ctk.CTkFrame(tab, fg_color="transparent")
        
        # Scrollbarer Bereich
        self.scroll_frame = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.scroll_frame.grid(row=1, column=0, sticky="nsew", padx=DesignSystem.SPACING['md'], 
                               pady=DesignSystem.SPACING['md'])
        self.scroll_frame.grid_columnconfigure(0, weight=1)
        
        # Wallet-Konfiguration
        self._create_wallet_config_section(self.scroll_frame)
        
        # Token-Konfiguration
        self._create_token_config_section(self.scroll_frame)
        
        # Metadaten-Konfiguration
        self._create_metadata_config_section(self.scroll_frame)

    def _create_wallet_config_section(self, parent):
        """Erstellt die Wallet-Konfigurationssektion"""
        wallet_frame = ctk.CTkFrame(parent, corner_radius=DesignSystem.RADIUS['md'])
        wallet_frame.grid(row=0, column=0, sticky="ew", pady=(0, DesignSystem.SPACING['lg']))
        wallet_frame.grid_columnconfigure(0, weight=1)
        
        # Header
        ctk.CTkLabel(
            wallet_frame, 
            text=f"{DesignSystem.ICONS['wallet']} Wallet-Konfiguration", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, padx=DesignSystem.SPACING['md'], 
               pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), sticky="w")
        
        # Payer/Emittent
        payer_frame = ctk.CTkFrame(wallet_frame, fg_color="transparent")
        payer_frame.grid(row=1, column=0, sticky="ew", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'])
        payer_frame.grid_columnconfigure(1, weight=1)
        
        self.payer_vanity_check = ctk.CTkCheckBox(payer_frame, text="Vanity-Adresse für Payer/Emittent", command=self._toggle_vanity_payer)
        self.payer_vanity_check.grid(row=0, column=0, sticky="w")
        self.payer_prefix_entry = ctk.CTkEntry(payer_frame, placeholder_text="Präfix (z.B. 'Leo')", width=150)
        self.payer_prefix_entry.bind("<KeyRelease>", self._on_config_change)
        
        # Mint
        mint_frame = ctk.CTkFrame(wallet_frame, fg_color="transparent")
        mint_frame.grid(row=2, column=0, sticky="ew", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'])
        mint_frame.grid_columnconfigure(1, weight=1)
        
        self.mint_vanity_check = ctk.CTkCheckBox(mint_frame, text="Vanity-Adresse für Token Mint", command=self._toggle_vanity_mint)
        self.mint_vanity_check.grid(row=0, column=0, sticky="w")
        self.mint_prefix_entry = ctk.CTkEntry(mint_frame, placeholder_text="Präfix (z.B. 'Mint')", width=150)
        self.mint_prefix_entry.bind("<KeyRelease>", self._on_config_change)

        # Testnutzer
        users_frame = ctk.CTkFrame(wallet_frame, fg_color="transparent")
        users_frame.grid(row=3, column=0, sticky="ew", padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['sm'], DesignSystem.SPACING['md']))
        users_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(users_frame, text="Anzahl Testnutzer:").grid(row=0, column=0, sticky="w")
        self.test_user_slider = ctk.CTkSlider(users_frame, from_=0, to=10, number_of_steps=10, command=self._on_slider_change)
        self.test_user_slider.set(3)
        self.test_user_slider.grid(row=0, column=1, padx=DesignSystem.SPACING['md'], sticky="ew")
        self.test_user_label = ctk.CTkLabel(users_frame, text="3", width=30)
        self.test_user_label.grid(row=0, column=2, padx=(DesignSystem.SPACING['sm'], 0))
        
        # Testnutzer Vanity
        user_vanity_frame = ctk.CTkFrame(wallet_frame, fg_color="transparent")
        user_vanity_frame.grid(row=4, column=0, sticky="ew", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'])
        user_vanity_frame.grid_columnconfigure(1, weight=1)

        self.test_user_vanity_check = ctk.CTkCheckBox(user_vanity_frame, text="Vanity-Adressen für Testnutzer", command=self._toggle_vanity_users)
        self.test_user_vanity_check.grid(row=0, column=0, sticky="w")
        self.test_user_prefix_entry = ctk.CTkEntry(user_vanity_frame, placeholder_text="Präfix (z.B. 'User')", width=150)
        self.test_user_prefix_entry.bind("<KeyRelease>", self._on_config_change)

    def _create_token_config_section(self, parent):
        """Erstellt die Token-Konfigurationssektion"""
        token_frame = ctk.CTkFrame(parent, corner_radius=DesignSystem.RADIUS['md'])
        token_frame.grid(row=1, column=0, sticky="ew", pady=(0, DesignSystem.SPACING['lg']))
        token_frame.grid_columnconfigure(1, weight=1)
        
        # Header
        ctk.CTkLabel(
            token_frame, 
            text=f"{DesignSystem.ICONS['token']} Token-Konfiguration", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, columnspan=2, padx=DesignSystem.SPACING['md'], 
               pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), sticky="w")
        
        # Initialer Vorrat
        ctk.CTkLabel(token_frame, text="Initialer Token-Vorrat:").grid(row=1, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="w")
        self.initial_mint_entry = ctk.CTkEntry(token_frame, placeholder_text="z.B. 1000000", width=200)
        self.initial_mint_entry.insert(0, "1000000")
        self.initial_mint_entry.grid(row=1, column=1, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="w")
        self.initial_mint_entry.bind("<KeyRelease>", self._on_config_change)

        # SOL für Nutzer
        ctk.CTkLabel(token_frame, text="SOL-Finanzierung für Testnutzer:").grid(row=2, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="w")
        self.sol_for_users_entry = ctk.CTkEntry(token_frame, placeholder_text="z.B. 0.05", width=200)
        self.sol_for_users_entry.insert(0, "0.05")
        self.sol_for_users_entry.grid(row=2, column=1, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="w")
        self.sol_for_users_entry.bind("<KeyRelease>", self._on_config_change)
        
        # Spacer
        ctk.CTkLabel(token_frame, text="").grid(row=3, column=0, pady=DesignSystem.SPACING['sm'])

    def _create_metadata_config_section(self, parent):
        """Erstellt die Metadaten-Konfigurationssektion"""
        metadata_frame = ctk.CTkFrame(parent, corner_radius=DesignSystem.RADIUS['md'])
        metadata_frame.grid(row=2, column=0, sticky="ew")
        metadata_frame.grid_columnconfigure(1, weight=1)
        
        # Header
        ctk.CTkLabel(
            metadata_frame, 
            text=f"{DesignSystem.ICONS['info']} Token-Metadaten", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, columnspan=2, padx=DesignSystem.SPACING['md'], 
               pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), sticky="w")
        
        # Metadaten aktivieren
        self.metadata_check = ctk.CTkCheckBox(metadata_frame, text="Token-Metadaten erstellen", command=self._toggle_metadata)
        self.metadata_check.grid(row=1, column=0, columnspan=2, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="w")
        if not METADATA_LIB_AVAILABLE:
            self.metadata_check.configure(state="disabled", text="Token-Metadaten erstellen (mpl-token-metadata nicht gefunden)")
        
        # Metadaten-Felder (versteckt)
        self.token_name_entry = ctk.CTkEntry(metadata_frame, placeholder_text="Token Name (z.B. 'My Token')")
        self.token_name_entry.bind("<KeyRelease>", self._on_config_change)
        self.token_symbol_entry = ctk.CTkEntry(metadata_frame, placeholder_text="Token Symbol (z.B. 'MTK')")
        self.token_symbol_entry.bind("<KeyRelease>", self._on_config_change)
        self.token_uri_entry = ctk.CTkEntry(metadata_frame, placeholder_text="Metadaten URI (URL zu JSON-Datei)")
        self.token_uri_entry.bind("<KeyRelease>", self._on_config_change)

    def _create_preview_tab(self, tab):
        """Erstellt den Vorschau-Tab"""
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        
        # Header
        header_frame = ctk.CTkFrame(tab, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'])
        header_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(header_frame, text="📋 Setup-Vorschau", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, sticky="w")
        
        # Validierungs-Status
        self.validation_status = StatusIndicator(header_frame, status="unknown", text="Konfiguration prüfen...")
        self.validation_status.grid(row=0, column=1, sticky="e")
        
        # Vorschau-Inhalt
        self.preview_textbox = ctk.CTkTextbox(tab, state="disabled", font=ctk.CTkFont(size=12, family="monospace"))
        self.preview_textbox.grid(row=1, column=0, sticky="nsew", padx=DesignSystem.SPACING['md'], pady=(0, DesignSystem.SPACING['md']))

    def _create_progress_tab(self, tab):
        """Erstellt den Fortschritt-Tab"""
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(tab, text="📊 Setup-Fortschritt", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'], sticky="w")
        
        self.log_textbox = EnhancedTextbox(tab)
        self.log_textbox.grid(row=1, column=0, sticky="nsew", padx=DesignSystem.SPACING['md'], pady=(0, DesignSystem.SPACING['md']))

    def _create_info_tab(self, tab):
        """Erstellt den Info-Tab"""
        tab.grid_columnconfigure(0, weight=1)
        
        config_frame = ctk.CTkFrame(tab, corner_radius=DesignSystem.RADIUS['md'])
        config_frame.grid(row=0, column=0, sticky="ew", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'])
        ctk.CTkLabel(config_frame, text=f"{DesignSystem.ICONS['info']} Aktuelle Konfiguration", font=ctk.CTkFont(size=16, weight="bold")).pack(padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), anchor="w")
        
        rpc_frame = ctk.CTkFrame(config_frame, fg_color="transparent")
        rpc_frame.pack(fill="x", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'])
        ctk.CTkLabel(rpc_frame, text="RPC Endpunkt:", width=120, anchor="w").pack(side="left")
        self.rpc_label = CopyableLabel(rpc_frame, text="-")
        self.rpc_label.pack(side="left", fill="x", expand=True)
        
        wallet_frame = ctk.CTkFrame(config_frame, fg_color="transparent")
        wallet_frame.pack(fill="x", padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['sm'], DesignSystem.SPACING['md']))
        ctk.CTkLabel(wallet_frame, text="Wallet-Ordner:", width=120, anchor="w").pack(side="left")
        self.wallet_folder_label = CopyableLabel(wallet_frame, text="-")
        self.wallet_folder_label.pack(side="left", fill="x", expand=True)
        
        help_frame = ctk.CTkFrame(tab, corner_radius=DesignSystem.RADIUS['md'])
        help_frame.grid(row=1, column=0, sticky="ew", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'])
        ctk.CTkLabel(help_frame, text="💡 Tipps und Hinweise", font=ctk.CTkFont(size=16, weight="bold")).pack(padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), anchor="w")
        
        help_text = "• Vanity-Adressen: Adressen mit Präfixen dauern länger zu generieren.\n• Testnutzer: Erstellt Wallets für Tests. Diese werden mit etwas SOL finanziert.\n• Explorer Link: Nach dem Setup wird ein Link zur Token-Mint angezeigt.\n• Backup: Alle Wallet-Dateien werden im konfigurierten Ordner gespeichert."
        ctk.CTkLabel(help_frame, text=help_text, justify="left", font=ctk.CTkFont(size=11)).pack(padx=DesignSystem.SPACING['md'], pady=(0, DesignSystem.SPACING['md']), anchor="w")

    # === Event-Handler ===
    def _toggle_vanity_payer(self):
        if self.payer_vanity_check.get(): self.payer_prefix_entry.grid(row=0, column=1, padx=DesignSystem.SPACING['md'], sticky="w")
        else: self.payer_prefix_entry.grid_forget()
        self._on_config_change()

    def _toggle_vanity_mint(self):
        if self.mint_vanity_check.get(): self.mint_prefix_entry.grid(row=0, column=1, padx=DesignSystem.SPACING['md'], sticky="w")
        else: self.mint_prefix_entry.grid_forget()
        self._on_config_change()

    def _toggle_vanity_users(self):
        if self.test_user_vanity_check.get(): self.test_user_prefix_entry.grid(row=0, column=1, padx=DesignSystem.SPACING['md'], sticky="w")
        else: self.test_user_prefix_entry.grid_forget()
        self._on_config_change()

    def _toggle_metadata(self):
        if self.metadata_check.get():
            self.token_name_entry.grid(row=2, column=0, columnspan=2, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="ew")
            self.token_symbol_entry.grid(row=3, column=0, columnspan=2, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="ew")
            self.token_uri_entry.grid(row=4, column=0, columnspan=2, padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['sm'], DesignSystem.SPACING['md']), sticky="ew")
        else:
            self.token_name_entry.grid_forget()
            self.token_symbol_entry.grid_forget()
            self.token_uri_entry.grid_forget()
        self._on_config_change()

    def _on_slider_change(self, value):
        self.test_user_label.configure(text=str(int(value)))
        self._on_config_change()

    def _on_config_change(self, event=None):
        if not self.setup_exists:
            self._update_config_from_ui()
            self._update_preview()

    def _update_config_from_ui(self):
        """Aktualisiert Setup-Konfiguration aus UI"""
        cfg = self.setup_config
        cfg.payer_vanity = self.payer_vanity_check.get()
        cfg.payer_prefix = self.payer_prefix_entry.get().strip()
        cfg.mint_vanity = self.mint_vanity_check.get()
        cfg.mint_prefix = self.mint_prefix_entry.get().strip()
        cfg.test_user_count = int(self.test_user_slider.get())
        cfg.test_user_vanity = self.test_user_vanity_check.get()
        cfg.test_user_prefix = self.test_user_prefix_entry.get().strip()
        
        try: cfg.initial_mint_amount = float(self.initial_mint_entry.get().replace(",", "."))
        except (ValueError, TypeError): cfg.initial_mint_amount = 0.0
        try: cfg.sol_for_users = float(self.sol_for_users_entry.get().replace(",", "."))
        except (ValueError, TypeError): cfg.sol_for_users = 0.0
        
        cfg.create_metadata = self.metadata_check.get()
        cfg.token_name = self.token_name_entry.get().strip()
        cfg.token_symbol = self.token_symbol_entry.get().strip()
        cfg.token_uri = self.token_uri_entry.get().strip()

    def _update_preview(self):
        """Aktualisiert die Vorschau"""
        is_valid, error_msg = self.setup_config.validate()
        
        if is_valid: self.validation_status.set_status("success", "Konfiguration gültig")
        else: self.validation_status.set_status("error", f"Fehler: {error_msg}")
        
        preview_lines = ["=== SETUP-VORSCHAU ===\n"]
        if is_valid:
            preview_lines.extend(self.setup_config.get_summary())
        else:
            preview_lines.append(f"❌ Konfigurationsfehler:\n{error_msg}")
        
        self.preview_textbox.configure(state="normal")
        self.preview_textbox.delete("1.0", "end")
        self.preview_textbox.insert("1.0", "\n".join(preview_lines))
        self.preview_textbox.configure(state="disabled")

    # === Setup-Ausführung ===
    def _start_setup_with_confirmation(self):
        self._update_config_from_ui()
        is_valid, error_msg = self.setup_config.validate()
        if not is_valid:
            show_error(self, "Konfigurationsfehler", error_msg)
            return
        
        summary = "\n".join(self.setup_config.get_summary())
        message = f"Möchten Sie das Setup mit folgender Konfiguration starten?\n\n{summary}"
        if ConfirmDialog.show(self, "Setup starten?", message, confirm_text="Setup starten"):
            self._start_setup()

    def _start_setup(self):
        self.setup_cancelled = False
        self._set_ui_state(is_enabled=False)
        self.tab_view.set("📊 Fortschritt")
        self.log_textbox.clear_text()
        run_in_thread(self._setup_worker_thread)

    def _setup_worker_thread(self):
        """Führt den gesamten Setup-Prozess im Hintergrund aus"""
        try:
            self.log("=== SOLANA ENVIRONMENT SETUP GESTARTET ===", "header")
            rpc_url = self.config.get("rpc_url")
            self.http_client = Client(rpc_url)
            if not self.http_client.is_connected():
                raise ConnectionError(f"Verbindung zum RPC-Endpunkt {rpc_url} fehlgeschlagen.")
            self.log(f"{DesignSystem.ICONS['success']} Verbunden mit: {rpc_url}", "success")

            wallet_folder = self.config.get("wallet_folder")
            os.makedirs(wallet_folder, exist_ok=True)
            self.log(f"Wallet-Ordner: {wallet_folder}", "info")
            
            steps = [
                ("Wallets erstellen", self._setup_step_wallets),
                ("Whitelist generieren", self._setup_step_whitelist),
                ("Payer finanzieren", self._setup_step_funding),
                ("Token-Mint erstellen", self._setup_step_mint),
                ("Token-Konten erstellen & Nutzer finanzieren", self._setup_step_token_accounts),
                ("Initiale Tokens minten", self._setup_step_initial_mint)
            ]
            if self.setup_config.create_metadata and METADATA_LIB_AVAILABLE:
                steps.insert(-1, ("Token-Metadaten erstellen", self._setup_step_metadata))
            
            total_steps = len(steps)
            for i, (step_name, step_func) in enumerate(steps):
                if self.setup_cancelled:
                    self.log("❌ Setup wurde abgebrochen.", "error")
                    return
                self.log(f"\n--- Schritt {i+1}/{total_steps}: {step_name} ---", "header")
                step_func()
            
            self.log(f"\n{DesignSystem.ICONS['success']} === SETUP ERFOLGREICH ABGESCHLOSSEN ===", "success")
            self.after(0, self._setup_completed)
        except Exception as e:
            self.log(f"\n{DesignSystem.ICONS['error']} === SETUP FEHLGESCHLAGEN ===", "error")
            self.log(f"Fehler: {e}", "error")
            self.after(0, self._setup_failed, str(e))
        finally:
            self.after(0, lambda: self._set_ui_state(True))

    def _setup_step_wallets(self):
        wallet_folder = self.config.get("wallet_folder")
        cfg = self.setup_config
        
        self.payer_kp = self._create_wallet_ui_driven(wallet_folder, "payer-wallet.json", "Payer/Emittent", cfg.payer_vanity, cfg.payer_prefix)
        self.mint_kp = self._create_wallet_ui_driven(wallet_folder, "mint-wallet.json", "Token Mint", cfg.mint_vanity, cfg.mint_prefix)
        
        self.test_users = []
        for i in range(cfg.test_user_count):
            if self.setup_cancelled: return
            prefix = f"{cfg.test_user_prefix}{i+1}" if cfg.test_user_vanity else ""
            user_kp = self._create_wallet_ui_driven(wallet_folder, f"test-user-{i+1}.json", f"Testnutzer {i+1}", cfg.test_user_vanity, prefix)
            self.test_users.append(user_kp)

    def _setup_step_whitelist(self):
        wallet_folder = self.config.get("wallet_folder")
        whitelist_path = os.path.join(wallet_folder, "whitelist.txt")
        with open(whitelist_path, 'w') as f:
            f.write("# Diese Datei wurde automatisch generiert.\n")
            f.write("# Haupt-Wallet (Payer/Emittent)\n")
            f.write(str(self.payer_kp.pubkey()) + '\n\n')
            if self.test_users:
                f.write("# Testnutzer-Wallets\n")
                for wallet in self.test_users:
                    f.write(str(wallet.pubkey()) + '\n')
        total_addresses = 1 + len(self.test_users)
        self.log(f"{DesignSystem.ICONS['success']} whitelist.txt mit {total_addresses} Adressen erstellt.", "success")

    def _setup_step_funding(self):
        self.log(f"Finanziere Payer-Wallet ({truncate_address(str(self.payer_kp.pubkey()))})", "info")
        self._fund_payer_wallet(self.payer_kp)

    def _setup_step_mint(self):
        lamports = self.http_client.get_minimum_balance_for_rent_exemption(82).value
        ix1 = create_account(
            CreateAccountParams(
                from_pubkey=self.payer_kp.pubkey(),
                to_pubkey=self.mint_kp.pubkey(),
                lamports=lamports,
                space=82,
                owner=TOKEN_PROGRAM_ID
            )
        )
        ix2 = initialize_mint(
            InitializeMintParams(
                program_id=TOKEN_PROGRAM_ID,
                mint=self.mint_kp.pubkey(),
                decimals=9,
                mint_authority=self.payer_kp.pubkey(),
                freeze_authority=self.payer_kp.pubkey()
            )
        )
        confirm_and_send_transaction(self.http_client, [ix1, ix2], [self.payer_kp, self.mint_kp], "Token-Mint erstellen", self.log)

    def _setup_step_metadata(self):
        metadata_pda, _ = Metadata.find_pda(self.mint_kp.pubkey())
        data_v2 = DataV2(
            name=self.setup_config.token_name, 
            symbol=self.setup_config.token_symbol, 
            uri=self.setup_config.token_uri, 
            seller_fee_basis_points=0, 
            creators=None, 
            collection=None, 
            uses=None
        )
        ix_args = CreateMetadataAccountV3InstructionArgs(
            data=data_v2, 
            is_mutable=True, 
            collection_details=None
        )
        ix = create_metadata_account_v3(
            args=ix_args,
            metadata_account=metadata_pda,
            mint=self.mint_kp.pubkey(),
            mint_authority=self.payer_kp.pubkey(),
            payer=self.payer_kp.pubkey(),
            update_authority=self.payer_kp.pubkey()
        )
        confirm_and_send_transaction(self.http_client, [ix], [self.payer_kp], "Token-Metadaten erstellen", self.log)

    def _setup_step_token_accounts(self):
        instructions = []
        all_wallets = [self.payer_kp] + self.test_users
        for wallet in all_wallets:
            instructions.append(create_associated_token_account(
                payer=self.payer_kp.pubkey(), 
                owner=wallet.pubkey(), 
                mint=self.mint_kp.pubkey()
            ))
        
        if self.test_users and self.setup_config.sol_for_users > 0:
            self.log(f"→ Füge {self.setup_config.sol_for_users} SOL-Transfers für Testnutzer hinzu...", "info")
            lamports_for_user = int(self.setup_config.sol_for_users * 10**9)
            for user in self.test_users:
                instructions.append(system_transfer(
                    SystemTransferParams(
                        from_pubkey=self.payer_kp.pubkey(), 
                        to_pubkey=user.pubkey(), 
                        lamports=lamports_for_user
                    )
                ))
        
        if instructions:
            confirm_and_send_transaction(self.http_client, instructions, [self.payer_kp], "ATAs erstellen & Nutzer finanzieren", self.log)

    def _setup_step_initial_mint(self):
        amount_lamports = int(self.setup_config.initial_mint_amount * (10**9))
        ata = get_associated_token_address(owner=self.payer_kp.pubkey(), mint=self.mint_kp.pubkey())
        ix = mint_to(
            MintToParams(
                program_id=TOKEN_PROGRAM_ID,
                mint=self.mint_kp.pubkey(),
                dest=ata,
                mint_authority=self.payer_kp.pubkey(),
                amount=amount_lamports
            )
        )
        confirm_and_send_transaction(self.http_client, [ix], [self.payer_kp], f"{self.setup_config.initial_mint_amount:,.0f} Tokens minten", self.log)

    def _create_wallet_ui_driven(self, wallet_folder, filename, wallet_type, use_vanity, prefix):
        self.log(f"→ Erstelle '{wallet_type}'-Wallet...", "info")
        if use_vanity and prefix and prefix.isalnum():
            keypair = self._grind_keypair_ui(prefix, wallet_type)
        else:
            if use_vanity: self.log(f"   ⚠️ Ungültiger Präfix für {wallet_type}. Erstelle zufälliges Wallet.", "warning")
            keypair = Keypair()
        
        with open(os.path.join(wallet_folder, filename), 'w') as f:
            json.dump(list(bytes(keypair)), f)
        self.log(f"   {DesignSystem.ICONS['success']} Wallet gespeichert: {truncate_address(str(keypair.pubkey()))}", "success")
        return keypair

    def _grind_keypair_ui(self, prefix, wallet_type):
        count = 0
        start_time = time.time()
        self.log(f"   ⏳ Suche nach Adresse mit Präfix '{prefix}' für {wallet_type}...", "info")
        while True:
            if self.setup_cancelled: raise Exception("Setup wurde abgebrochen")
            keypair = Keypair()
            count += 1
            if str(keypair.pubkey()).lower().startswith(prefix.lower()):
                duration = time.time() - start_time
                self.log(f"   {DesignSystem.ICONS['success']} Gefunden nach {count:,} Versuchen in {duration:.2f}s!", "success")
                return keypair
            if count % 100000 == 0:
                self.log(f"      ... {count:,} Adressen durchsucht ...", "info")

    def _fund_payer_wallet(self, payer_kp):
        try: balance = self.http_client.get_balance(payer_kp.pubkey()).value
        except SolanaRpcException: balance = 0
        self.log(f"Aktueller Kontostand: {format_sol_amount(balance)}", "info")
        
        if balance < 0.5 * 10**9:
            self.log("→ Kontostand niedrig. Versuche Airdrop von 2 SOL...", "info")
            try:
                airdrop_resp = self.http_client.request_airdrop(payer_kp.pubkey(), 2 * 10**9)
                self.log(f"→ Airdrop-Anforderung gesendet: {airdrop_resp.value}", "info")
                self.http_client.confirm_transaction(airdrop_resp.value, "finalized", sleep_seconds=5.0)
                final_balance = self.http_client.get_balance(payer_kp.pubkey()).value
                self.log(f"{DesignSystem.ICONS['success']} Airdrop erfolgreich! Neuer Kontostand: {format_sol_amount(final_balance)}", "success")
            except Exception as e:
                self.log(f"{DesignSystem.ICONS['error']} Automatischer Airdrop fehlgeschlagen: {e}", "error")
                self.log("\n--- MANUELLE AKTION ERFORDERLICH ---", "warning")
                self.log(f"Bitte überweisen Sie DEV-SOL an: {payer_kp.pubkey()}", "warning")
                self.log("Nutzen Sie ein Faucet wie https://solfaucet.com/ (Devnet).", "info")
                self.log("Warte auf Einzahlung...", "info")
                for i in range(30): # Warte bis zu 60s
                    if self.setup_cancelled: raise Exception("Setup abgebrochen")
                    try:
                        if self.http_client.get_balance(payer_kp.pubkey()).value > balance:
                            self.log(f"{DesignSystem.ICONS['success']} Guthaben gefunden!", "success")
                            return
                    except SolanaRpcException: pass
                    time.sleep(2)
                raise TimeoutError("Guthaben nach 60s nicht gefunden.")
        else:
            self.log(f"{DesignSystem.ICONS['success']} Ausreichend Guthaben vorhanden.", "success")

    # === UI-Hilfsmethoden ===
    def _set_ui_state(self, is_enabled: bool):
        state = "normal" if is_enabled else "disabled"
        self.start_button.configure(state=state)
        
        widgets_to_toggle = [
            self.payer_vanity_check, self.payer_prefix_entry, self.mint_vanity_check, 
            self.mint_prefix_entry, self.test_user_slider, self.test_user_vanity_check, 
            self.test_user_prefix_entry, self.initial_mint_entry, self.sol_for_users_entry,
            self.metadata_check, self.token_name_entry, self.token_symbol_entry, self.token_uri_entry
        ]
        for widget in widgets_to_toggle:
            try: widget.configure(state=state)
            except: pass

    def _setup_completed(self):
        self.after(0, self._check_for_existing_setup) # Refresh UI to show "already configured"
        mint_address = str(self.mint_kp.pubkey())
        explorer_url = f"https://explorer.solana.com/address/{mint_address}?cluster=devnet"
        self.log(f"🔗 Token Explorer Link: {explorer_url}", "info")
        show_info(self, "Setup abgeschlossen", 
                 f"Das Setup wurde erfolgreich abgeschlossen!\n\n"
                 f"Token Mint Adresse:\n{mint_address}\n\n"
                 f"Klicken Sie auf den Link im Log, um den Token im Explorer zu sehen.")

    def _setup_failed(self, error_message: str):
        show_error(self, "Setup fehlgeschlagen", f"Das Setup konnte nicht abgeschlossen werden:\n\n{error_message}")

    def log(self, message, level="info"):
        self.log_queue.put((message, level))

    def process_log_queue(self):
        try:
            while True:
                message, level = self.log_queue.get_nowait()
                self.log_textbox.append_text(message, level)
        except queue.Empty: pass
        finally: self.after(200, self.process_log_queue)

    def load_and_display_config(self):
        try:
            with open("config.json", 'r') as f: self.config = json.load(f)
            rpc_url = self.config.get('rpc_url', 'Nicht gefunden')
            wallet_folder = self.config.get('wallet_folder', 'Nicht gefunden')
            self.rpc_label.set_text(rpc_url)
            self.wallet_folder_label.set_text(wallet_folder)
            
            try:
                test_client = Client(rpc_url)
                if test_client.is_connected(): self.connection_status.set_status("success", f"Verbunden")
                else: self.connection_status.set_status("error", "Verbindung fehlgeschlagen")
            except: self.connection_status.set_status("error", "Verbindung fehlgeschlagen")
            
            self._check_for_existing_setup()
            self._on_config_change() # Initial preview update
        except Exception as e:
            show_error(self, "Config Fehler", f"config.json konnte nicht geladen werden: {e}")
            self.connection_status.set_status("error", "Konfiguration fehlt")

    def _check_for_existing_setup(self):
        wallet_folder = self.config.get("wallet_folder")
        if not wallet_folder: return
        
        payer_path = os.path.join(wallet_folder, "payer-wallet.json")
        mint_path = os.path.join(wallet_folder, "mint-wallet.json")

        if os.path.exists(payer_path) and os.path.exists(mint_path):
            self.setup_exists = True
            self.scroll_frame.grid_forget() # Hide config options
            
            self.existing_setup_frame.grid(row=1, column=0, sticky="nsew", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'])
            self.existing_setup_frame.grid_columnconfigure(0, weight=1)
            
            status_frame = ctk.CTkFrame(self.existing_setup_frame, corner_radius=DesignSystem.RADIUS['lg'])
            status_frame.pack(fill="x", expand=True, padx=20, pady=20)

            StatusIndicator(status_frame, status="success", text="Ein Setup existiert bereits!").pack(fill="x", pady=(10, 10), padx=10)
            
            try:
                with open(mint_path, 'r') as f:
                    mint_kp = Keypair.from_bytes(bytes(json.load(f)))
                mint_address = str(mint_kp.pubkey())
                explorer_url = f"https://explorer.solana.com/address/{mint_address}?cluster=devnet"

                ctk.CTkLabel(status_frame, text="Token Mint Adresse:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(10,0))
                CopyableLabel(status_frame, text=mint_address, max_length=100).pack(fill="x", padx=10, pady=(0, 10))
                
                ctk.CTkLabel(status_frame, text="Solana Explorer Link:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10)
                CopyableLabel(status_frame, text=explorer_url, max_length=100).pack(fill="x", padx=10, pady=(0, 10))

            except Exception as e:
                ctk.CTkLabel(status_frame, text=f"Fehler beim Laden der Wallet-Infos: {e}", text_color="red").pack(padx=10, pady=10)

            self._set_ui_state(is_enabled=False)
            self.start_button.configure(text="Setup existiert", state="disabled")


if __name__ == "__main__":
    app = SetupUI()
    app.mainloop()

