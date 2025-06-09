#!/usr/bin/env python3
# === app_ui_improved.py: Verbesserte grafische Benutzeroberfläche für das Solana Token Management Tool ===

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import threading
import queue
import os
import sys
import json
from typing import Dict, List, Optional

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
    from solders.system_program import transfer as system_transfer, TransferParams as SystemTransferParams
    from solders.transaction import Transaction
    from solana.rpc.api import Client
    from solana.exceptions import SolanaRpcException
    from spl.token.instructions import (
        transfer as spl_transfer, TransferParams as SplTransferParams,
        mint_to, MintToParams,
        burn, BurnParams,
        create_associated_token_account, get_associated_token_address,
        freeze_account, FreezeAccountParams,
        thaw_account, ThawAccountParams
    )
    from spl.token.constants import TOKEN_PROGRAM_ID
except ImportError as e:
    print(f"Fehler: Eine oder mehrere erforderliche Python-Bibliotheken fehlen. ({e})")
    print("Bitte installieren Sie die Bibliotheken mit: pip install solders solana spl-token customtkinter")
    sys.exit(1)

# === HILFSFUNKTIONEN ===

def load_config():
    """Lädt die Konfiguration aus der config.json-Datei."""
    try:
        with open("config.json", 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        messagebox.showerror("Fehler", "Kritischer Fehler: 'config.json' nicht gefunden.")
        sys.exit(1)
    except json.JSONDecodeError:
        messagebox.showerror("Fehler", "Kritischer Fehler: 'config.json' ist fehlerhaft formatiert.")
        sys.exit(1)

def load_keypair(wallet_folder: str, filename: str) -> Keypair | None:
    """Lädt ein Keypair aus einer JSON-Datei in einem bestimmten Ordner."""
    path = os.path.join(wallet_folder, filename)
    if not os.path.exists(path):
        messagebox.showerror("Fehler", f"Essentielle Wallet-Datei '{path}' nicht gefunden.\\n\\nBitte zuerst setup.py ausführen.")
        return None
    with open(path, 'r') as f:
        return Keypair.from_bytes(bytes(json.load(f)))

# === HAUPTANWENDUNG ===

class SolanaTokenUI(ctk.CTk):
    TOKEN_DECIMALS = 9
    
    def __init__(self):
        super().__init__()

        # --- Backend-Initialisierung ---
        self.log_queue = queue.Queue()
        self.wallets = {}
        self.wallet_names_map = {}
        self.auto_refresh_enabled = True
        self.refresh_interval = 30000  # 30 Sekunden
        
        if not self._initialize_backend():
            self.after(100, self.destroy)
            return
        
        # --- UI-Konfiguration ---
        self.title("Solana Token Manager - Verbesserte Version")
        self.geometry("1400x900")
        self.minsize(1200, 700)
        
        # Design-System anwenden
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        
        # Layout
        self.grid_columnconfigure(0, weight=1, minsize=400)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        self._create_widgets()
        self._setup_keyboard_shortcuts()
        
        # Starte Hintergrundprozesse
        self.after(250, self.process_log_queue)
        self._update_issuer_recipient_lists()
        self.start_status_refresh()
        self._schedule_auto_refresh()

    def _initialize_backend(self):
        """Initialisiert Backend-Verbindungen und Wallets"""
        try:
            self.config = load_config()
            self.http_client = Client(self.config['rpc_url'])
            if not self.http_client.is_connected():
                raise ConnectionError(f"Keine Verbindung zum RPC-Endpunkt {self.config['rpc_url']}.")

            wallet_folder = self.config['wallet_folder']
            self.wallets['payer'] = load_keypair(wallet_folder, "payer-wallet.json")
            self.wallets['mint'] = load_keypair(wallet_folder, "mint-wallet.json")
            
            if not self.wallets['payer'] or not self.wallets['mint']: 
                return False

            # Lade Testnutzer
            test_user_files = sorted([f for f in os.listdir(wallet_folder) 
                                    if f.startswith("test-user-") and f.endswith(".json")])
            self.wallets['test_users'] = [load_keypair(wallet_folder, f) for f in test_user_files]
            
            # Erstelle Wallet-Namen-Mapping
            self.wallet_names_map = {"Payer/Emittent": self.wallets['payer'].pubkey()}
            for i, user_kp in enumerate(self.wallets['test_users']):
                self.wallet_names_map[f"Nutzer {i+1}"] = user_kp.pubkey()
            
            return True
        except Exception as e:
            show_error(self, "Initialisierungsfehler", f"Ein kritischer Fehler ist aufgetreten:\\n\\n{e}")
            return False

    def _create_widgets(self):
        """Erstellt die Hauptbenutzeroberfläche"""
        # --- Linker Bereich: Status und Informationen ---
        self.status_frame = ctk.CTkFrame(self, corner_radius=DesignSystem.RADIUS['lg'])
        self.status_frame.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], 
                              pady=DesignSystem.SPACING['md'], sticky="nsew")
        self.status_frame.grid_rowconfigure(2, weight=1)
        self.status_frame.grid_columnconfigure(0, weight=1)
        
        self._create_status_header()
        self._create_connection_info()
        self._create_wallet_status_area()
        
        # --- Rechter Bereich: Aktionen und Logs ---
        self.main_content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_content_frame.grid(row=0, column=1, padx=(0, DesignSystem.SPACING['md']), 
                                   pady=DesignSystem.SPACING['md'], sticky="nsew")
        self.main_content_frame.grid_rowconfigure(0, weight=2)
        self.main_content_frame.grid_rowconfigure(1, weight=1)
        self.main_content_frame.grid_columnconfigure(0, weight=1)

        self._create_action_tabs()
        self._create_log_area()

    def _create_status_header(self):
        """Erstellt den Status-Header mit Refresh-Funktionalität"""
        header_frame = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], 
                         pady=DesignSystem.SPACING['md'], sticky="ew")
        header_frame.grid_columnconfigure(0, weight=1)
        
        # Titel
        title_label = ctk.CTkLabel(
            header_frame, 
            text=f"{DesignSystem.ICONS['wallet']} Wallet Status", 
            font=ctk.CTkFont(size=18, weight="bold")
        )
        title_label.grid(row=0, column=0, sticky="w")
        
        # Refresh-Buttons
        button_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        button_frame.grid(row=0, column=1, sticky="e")
        
        self.refresh_button = ctk.CTkButton(
            button_frame, 
            text=DesignSystem.ICONS['refresh'], 
            command=self.start_status_refresh, 
            width=40,
            height=32
        )
        self.refresh_button.pack(side="right", padx=(DesignSystem.SPACING['sm'], 0))
        
        # Auto-Refresh Toggle
        self.auto_refresh_var = tk.BooleanVar(value=True)
        self.auto_refresh_check = ctk.CTkCheckBox(
            button_frame,
            text="Auto",
            variable=self.auto_refresh_var,
            command=self._toggle_auto_refresh,
            width=60
        )
        self.auto_refresh_check.pack(side="right", padx=(0, DesignSystem.SPACING['sm']))

    def _create_connection_info(self):
        """Erstellt Verbindungsinformationen"""
        self.connection_status = StatusIndicator(
            self.status_frame,
            status="success",
            text=f"Verbunden: {self.config['rpc_url']}"
        )
        self.connection_status.grid(row=1, column=0, padx=DesignSystem.SPACING['md'], 
                                  pady=(0, DesignSystem.SPACING['sm']), sticky="ew")

    def _create_wallet_status_area(self):
        """Erstellt den scrollbaren Wallet-Status-Bereich"""
        self.status_scroll_frame = ctk.CTkScrollableFrame(
            self.status_frame, 
            fg_color="transparent",
            corner_radius=DesignSystem.RADIUS['md']
        )
        self.status_scroll_frame.grid(row=2, column=0, sticky="nsew", 
                                    padx=DesignSystem.SPACING['sm'])

    def _create_action_tabs(self):
        """Erstellt die Tab-Ansicht für Aktionen"""
        self.tab_view = ctk.CTkTabview(
            self.main_content_frame, 
            corner_radius=DesignSystem.RADIUS['lg']
        )
        self.tab_view.grid(row=0, column=0, sticky="nsew")
        
        # Tabs hinzufügen
        self.tab_view.add("🏦 Emittent")
        self.tab_view.add("👥 Testnutzer")
        self.tab_view.add("⚙️ Einstellungen")
        
        self._create_issuer_tab(self.tab_view.tab("🏦 Emittent"))
        self._create_user_tab(self.tab_view.tab("👥 Testnutzer"))
        self._create_settings_tab(self.tab_view.tab("⚙️ Einstellungen"))

    def _create_issuer_tab(self, tab):
        """Erstellt den Emittent-Tab mit verbessertem Layout"""
        tab.grid_columnconfigure(0, weight=1)
        
        # Token-Versorgung (Mint & Burn)
        supply_frame = ctk.CTkFrame(tab, corner_radius=DesignSystem.RADIUS['md'])
        supply_frame.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], 
                         pady=DesignSystem.SPACING['md'], sticky="ew")
        supply_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(
            supply_frame, 
            text=f"{DesignSystem.ICONS['token']} Token-Versorgung verwalten", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, columnspan=3, padx=DesignSystem.SPACING['md'], 
               pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), sticky="w")
        
        # Mint-Bereich
        ctk.CTkLabel(supply_frame, text="Neue Tokens erstellen:").grid(
            row=1, column=0, padx=DesignSystem.SPACING['md'], 
            pady=DesignSystem.SPACING['sm'], sticky="w"
        )
        
        self.mint_amount_entry = ctk.CTkEntry(
            supply_frame, 
            placeholder_text="Anzahl Tokens (z.B. 1000)",
            width=200
        )
        self.mint_amount_entry.grid(row=1, column=1, padx=DesignSystem.SPACING['md'], 
                                   pady=DesignSystem.SPACING['sm'], sticky="ew")
        
        self.mint_button = ctk.CTkButton(
            supply_frame, 
            text=f"{DesignSystem.ICONS['mint']} Mint", 
            command=self.on_mint,
            fg_color=DesignSystem.COLORS['success']
        )
        self.mint_button.grid(row=1, column=2, padx=DesignSystem.SPACING['md'], 
                             pady=DesignSystem.SPACING['sm'])
        
        # Burn-Bereich
        ctk.CTkLabel(supply_frame, text="Tokens vernichten:").grid(
            row=2, column=0, padx=DesignSystem.SPACING['md'], 
            pady=DesignSystem.SPACING['sm'], sticky="w"
        )
        
        self.burn_amount_entry = ctk.CTkEntry(
            supply_frame, 
            placeholder_text="Anzahl Tokens (z.B. 500)",
            width=200
        )
        self.burn_amount_entry.grid(row=2, column=1, padx=DesignSystem.SPACING['md'], 
                                   pady=DesignSystem.SPACING['sm'], sticky="ew")
        
        self.burn_button = ctk.CTkButton(
            supply_frame, 
            text=f"{DesignSystem.ICONS['burn']} Burn", 
            command=self.on_burn,
            fg_color=DesignSystem.COLORS['error']
        )
        self.burn_button.grid(row=2, column=2, padx=DesignSystem.SPACING['md'], 
                             pady=(DesignSystem.SPACING['sm'], DesignSystem.SPACING['md']))
        
        # Transfer-Bereiche
        self.issuer_spl_widgets = self._create_transfer_frame(
            tab, f"{DesignSystem.ICONS['token']} Token senden", self.on_spl_transfer
        )
        self.issuer_spl_widgets['frame'].grid(row=1, column=0, padx=DesignSystem.SPACING['md'], 
                                            pady=DesignSystem.SPACING['md'], sticky="ew")

        self.issuer_sol_widgets = self._create_transfer_frame(
            tab, f"{DesignSystem.ICONS['sol']} SOL senden", self.on_sol_transfer
        )
        self.issuer_sol_widgets['frame'].grid(row=2, column=0, padx=DesignSystem.SPACING['md'], 
                                            pady=DesignSystem.SPACING['md'], sticky="ew")

        # Freeze/Thaw-Bereich
        self._create_freeze_thaw_frame(tab)

    def _create_transfer_frame(self, parent, title, command):
        """Erstellt einen verbesserten Transfer-Frame"""
        frame = ctk.CTkFrame(parent, corner_radius=DesignSystem.RADIUS['md'])
        frame.grid_columnconfigure(1, weight=1)
        
        # Titel
        ctk.CTkLabel(
            frame, 
            text=title, 
            font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, columnspan=3, padx=DesignSystem.SPACING['md'], 
               pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), sticky="w")
        
        # Empfänger-Auswahl
        ctk.CTkLabel(frame, text="An:").grid(
            row=1, column=0, padx=DesignSystem.SPACING['md'], 
            pady=DesignSystem.SPACING['sm'], sticky="w"
        )
        
        recipient_dropdown = ctk.CTkOptionMenu(
            frame, 
            values=["-"], 
            corner_radius=DesignSystem.RADIUS['sm'],
            width=200
        )
        recipient_dropdown.grid(row=1, column=1, padx=DesignSystem.SPACING['md'], 
                               pady=DesignSystem.SPACING['sm'], sticky="ew")
        
        # Betrag
        ctk.CTkLabel(frame, text="Betrag:").grid(
            row=2, column=0, padx=DesignSystem.SPACING['md'], 
            pady=DesignSystem.SPACING['sm'], sticky="w"
        )
        
        amount_entry = ctk.CTkEntry(
            frame, 
            placeholder_text="Betrag eingeben",
            width=200
        )
        amount_entry.grid(row=2, column=1, padx=DesignSystem.SPACING['md'], 
                         pady=DesignSystem.SPACING['sm'], sticky="ew")
        
        # Externe Adresse (versteckt)
        external_addr_entry = ctk.CTkEntry(
            frame, 
            placeholder_text="Externe Wallet-Adresse eingeben"
        )
        
        def on_recipient_change(choice):
            if choice == "📝 Externe Adresse...":
                external_addr_entry.grid(row=3, column=0, columnspan=3, 
                                       padx=DesignSystem.SPACING['md'], 
                                       pady=(0, DesignSystem.SPACING['sm']), sticky="ew")
            else:
                external_addr_entry.grid_forget()
        
        recipient_dropdown.configure(command=on_recipient_change)
        
        # Senden-Button
        button = ctk.CTkButton(
            frame, 
            text=f"{DesignSystem.ICONS['send']} Senden", 
            corner_radius=DesignSystem.RADIUS['sm'],
            command=lambda: self._handle_transfer_with_confirmation(
                amount_entry, recipient_dropdown, external_addr_entry, button, command
            )
        )
        button.grid(row=2, column=2, padx=DesignSystem.SPACING['md'], 
                   pady=DesignSystem.SPACING['sm'])
        
        # Spacer
        ctk.CTkLabel(frame, text="").grid(row=4, column=0, pady=DesignSystem.SPACING['sm'])
        
        return {
            'frame': frame, 
            'amount': amount_entry, 
            'recipient': recipient_dropdown, 
            'external': external_addr_entry, 
            'button': button, 
            'visibility_func': on_recipient_change
        }

    def _create_freeze_thaw_frame(self, parent):
        """Erstellt den Freeze/Thaw-Bereich"""
        freeze_frame = ctk.CTkFrame(parent, corner_radius=DesignSystem.RADIUS['md'])
        freeze_frame.grid(row=3, column=0, padx=DesignSystem.SPACING['md'], 
                         pady=DesignSystem.SPACING['md'], sticky="ew")
        freeze_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(
            freeze_frame, 
            text=f"{DesignSystem.ICONS['freeze']} Token-Konto sperren/entsperren", 
            font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, columnspan=3, padx=DesignSystem.SPACING['md'], 
               pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), sticky="w")
        
        ctk.CTkLabel(freeze_frame, text="Token-Konto (ATA):").grid(
            row=1, column=0, padx=DesignSystem.SPACING['md'], 
            pady=DesignSystem.SPACING['sm'], sticky="w"
        )
        
        self.freeze_thaw_ata_entry = ctk.CTkEntry(
            freeze_frame, 
            placeholder_text="Token-Konto Adresse eingeben"
        )
        self.freeze_thaw_ata_entry.grid(row=1, column=1, padx=DesignSystem.SPACING['md'], 
                                       pady=DesignSystem.SPACING['sm'], sticky="ew")
        
        # Aktion auswählen
        self.freeze_thaw_action = ctk.CTkSegmentedButton(
            freeze_frame, 
            values=[f"{DesignSystem.ICONS['freeze']} Sperren", f"{DesignSystem.ICONS['thaw']} Entsperren"],
            corner_radius=DesignSystem.RADIUS['sm']
        )
        self.freeze_thaw_action.set(f"{DesignSystem.ICONS['freeze']} Sperren")
        self.freeze_thaw_action.grid(row=2, column=0, columnspan=2, 
                                   padx=DesignSystem.SPACING['md'], 
                                   pady=DesignSystem.SPACING['sm'], sticky="ew")
        
        self.freeze_thaw_button = ctk.CTkButton(
            freeze_frame, 
            text=f"{DesignSystem.ICONS['execute']} Ausführen", 
            command=self.on_freeze_thaw,
            corner_radius=DesignSystem.RADIUS['sm']
        )
        self.freeze_thaw_button.grid(row=2, column=2, padx=DesignSystem.SPACING['md'], 
                                   pady=DesignSystem.SPACING['sm'])
        
        # Spacer
        ctk.CTkLabel(freeze_frame, text="").grid(row=3, column=0, pady=DesignSystem.SPACING['sm'])

    def _create_user_tab(self, tab):
        """Erstellt den Testnutzer-Tab"""
        tab.grid_columnconfigure(0, weight=1)
        
        if not self.wallets['test_users']:
            no_users_label = ctk.CTkLabel(
                tab, 
                text="Keine Testnutzer gefunden.\\nBitte führen Sie zuerst das Setup aus.", 
                font=ctk.CTkFont(size=14),
                text_color=DesignSystem.COLORS['text_secondary']
            )
            no_users_label.pack(pady=DesignSystem.SPACING['xxl'], padx=DesignSystem.SPACING['md'])
            return

        # Nutzer-Auswahl
        user_selection_frame = ctk.CTkFrame(tab, corner_radius=DesignSystem.RADIUS['md'])
        user_selection_frame.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], 
                                 pady=DesignSystem.SPACING['md'], sticky="ew")
        
        ctk.CTkLabel(
            user_selection_frame, 
            text="Aktionen ausführen als:", 
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(side="left", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'])
        
        user_names = [f"Nutzer {i+1}" for i in range(len(self.wallets['test_users']))]
        self.user_selector = ctk.CTkOptionMenu(
            user_selection_frame, 
            values=user_names, 
            command=self._on_user_selection_change,
            corner_radius=DesignSystem.RADIUS['sm']
        )
        self.user_selector.pack(side="left", padx=DesignSystem.SPACING['md'], 
                               pady=DesignSystem.SPACING['md'])
        
        # Transfer-Frames für Nutzer
        self.user_spl_widgets = self._create_transfer_frame(
            tab, f"{DesignSystem.ICONS['token']} Token senden", self.on_user_spl_transfer
        )
        self.user_spl_widgets['frame'].grid(row=1, column=0, padx=DesignSystem.SPACING['md'], 
                                          pady=DesignSystem.SPACING['md'], sticky="ew")

        self.user_sol_widgets = self._create_transfer_frame(
            tab, f"{DesignSystem.ICONS['sol']} SOL senden", self.on_user_sol_transfer
        )
        self.user_sol_widgets['frame'].grid(row=2, column=0, padx=DesignSystem.SPACING['md'], 
                                          pady=DesignSystem.SPACING['md'], sticky="ew")
        
        # Initialisiere Empfängerlisten
        self._on_user_selection_change(self.user_selector.get())

    def _create_settings_tab(self, tab):
        """Erstellt den Einstellungen-Tab"""
        tab.grid_columnconfigure(0, weight=1)
        
        # Allgemeine Einstellungen
        general_frame = ctk.CTkFrame(tab, corner_radius=DesignSystem.RADIUS['md'])
        general_frame.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], 
                          pady=DesignSystem.SPACING['md'], sticky="ew")
        
        ctk.CTkLabel(
            general_frame, 
            text=f"{DesignSystem.ICONS['settings']} Allgemeine Einstellungen", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), anchor="w")
        
        # Auto-Refresh Intervall
        refresh_frame = ctk.CTkFrame(general_frame, fg_color="transparent")
        refresh_frame.pack(fill="x", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'])
        
        ctk.CTkLabel(refresh_frame, text="Auto-Refresh Intervall:").pack(side="left")
        
        self.refresh_interval_var = tk.StringVar(value="30")
        refresh_entry = ctk.CTkEntry(refresh_frame, textvariable=self.refresh_interval_var, width=60)
        refresh_entry.pack(side="left", padx=DesignSystem.SPACING['sm'])
        
        ctk.CTkLabel(refresh_frame, text="Sekunden").pack(side="left", padx=(DesignSystem.SPACING['sm'], 0))
        
        # Verbindungsinfo
        connection_frame = ctk.CTkFrame(tab, corner_radius=DesignSystem.RADIUS['md'])
        connection_frame.grid(row=1, column=0, padx=DesignSystem.SPACING['md'], 
                             pady=DesignSystem.SPACING['md'], sticky="ew")
        
        ctk.CTkLabel(
            connection_frame, 
            text=f"{DesignSystem.ICONS['info']} Verbindungsinformationen", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), anchor="w")
        
        # RPC URL
        rpc_frame = ctk.CTkFrame(connection_frame, fg_color="transparent")
        rpc_frame.pack(fill="x", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'])
        
        ctk.CTkLabel(rpc_frame, text="RPC Endpunkt:", width=120, anchor="w").pack(side="left")
        CopyableLabel(rpc_frame, text=self.config['rpc_url']).pack(side="left", fill="x", expand=True)
        
        # Wallet-Ordner
        wallet_frame = ctk.CTkFrame(connection_frame, fg_color="transparent")
        wallet_frame.pack(fill="x", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'])
        
        ctk.CTkLabel(wallet_frame, text="Wallet-Ordner:", width=120, anchor="w").pack(side="left")
        CopyableLabel(wallet_frame, text=self.config['wallet_folder']).pack(side="left", fill="x", expand=True)
        
        # Token Mint
        if self.wallets.get('mint'):
            mint_frame = ctk.CTkFrame(connection_frame, fg_color="transparent")
            mint_frame.pack(fill="x", padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['sm'], DesignSystem.SPACING['md']))
            
            ctk.CTkLabel(mint_frame, text="Token Mint:", width=120, anchor="w").pack(side="left")
            CopyableLabel(mint_frame, text=str(self.wallets['mint'].pubkey())).pack(side="left", fill="x", expand=True)

    def _create_log_area(self):
        """Erstellt den erweiterten Log-Bereich"""
        log_frame = ctk.CTkFrame(self.main_content_frame, corner_radius=DesignSystem.RADIUS['lg'])
        log_frame.grid(row=1, column=0, pady=(DesignSystem.SPACING['md'], 0), sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)
        
        # Log-Header
        log_header = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_header.grid(row=0, column=0, sticky="ew", padx=DesignSystem.SPACING['md'], 
                       pady=(DesignSystem.SPACING['md'], 0))
        log_header.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(
            log_header, 
            text="📋 Transaktionsprotokoll", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, sticky="w")
        
        # Erweiterte Textbox mit Suche und Filterung
        self.log_textbox = EnhancedTextbox(log_frame)
        self.log_textbox.grid(row=1, column=0, sticky="nsew", 
                             padx=DesignSystem.SPACING['md'], 
                             pady=(DesignSystem.SPACING['sm'], DesignSystem.SPACING['md']))

    def _setup_keyboard_shortcuts(self):
        """Richtet Tastaturkürzel ein"""
        self.bind("<Control-r>", lambda e: self.start_status_refresh())
        self.bind("<F5>", lambda e: self.start_status_refresh())
        self.bind("<Control-q>", lambda e: self.quit())

    # === Event-Handler ===

    def _handle_transfer_with_confirmation(self, amount_entry, recipient_dropdown, 
                                         external_addr_entry, button, original_command):
        """Behandelt Transfers mit Bestätigungsdialog"""
        try:
            amount = float(amount_entry.get().replace(",", "."))
            if amount <= 0:
                raise ValueError("Betrag muss positiv sein.")
            
            recipient_choice = recipient_dropdown.get()
            if recipient_choice == "📝 Externe Adresse...":
                recipient = external_addr_entry.get().strip()
                if not recipient:
                    raise ValueError("Externe Adresse darf nicht leer sein.")
            else:
                recipient = recipient_choice
            
            # Bestätigungsdialog
            transfer_type = "Token" if "token" in original_command.__name__.lower() else "SOL"
            message = f"Möchten Sie {amount} {transfer_type} an {recipient} senden?"
            
            if ConfirmDialog.show(self, "Transfer bestätigen", message, 
                                confirm_text="Senden", danger=True):
                original_command(amount_entry, recipient_dropdown, external_addr_entry, button)
        
        except ValueError as e:
            show_error(self, "Ungültige Eingabe", str(e))

    def _toggle_auto_refresh(self):
        """Schaltet Auto-Refresh um"""
        self.auto_refresh_enabled = self.auto_refresh_var.get()
        if self.auto_refresh_enabled:
            self._schedule_auto_refresh()

    def _schedule_auto_refresh(self):
        """Plant nächsten Auto-Refresh"""
        if self.auto_refresh_enabled:
            try:
                interval = int(self.refresh_interval_var.get()) * 1000
                self.refresh_interval = max(10000, interval)  # Minimum 10 Sekunden
            except:
                self.refresh_interval = 30000  # Fallback
            
            self.after(self.refresh_interval, self._auto_refresh)

    def _auto_refresh(self):
        """Führt automatischen Refresh aus"""
        if self.auto_refresh_enabled:
            self.start_status_refresh()
            self._schedule_auto_refresh()

    # === UI Update-Methoden ===

    def _update_recipient_list(self, dropdown, sender_name, all_wallet_names):
        """Aktualisiert Empfängerliste in Dropdown"""
        recipients = [name for name in all_wallet_names if name != sender_name]
        full_list = recipients + ["📝 Externe Adresse..."]
        current_selection = dropdown.get()
        dropdown.configure(values=full_list)
        if current_selection in full_list:
            dropdown.set(current_selection)
        elif full_list:
            dropdown.set(full_list[0])
        else:
            dropdown.set("-")

    def _update_issuer_recipient_lists(self):
        """Aktualisiert Empfängerlisten für Emittent"""
        all_names = list(self.wallet_names_map.keys())
        self._update_recipient_list(self.issuer_spl_widgets['recipient'], "Payer/Emittent", all_names)
        self.issuer_spl_widgets['visibility_func'](self.issuer_spl_widgets['recipient'].get())

        self._update_recipient_list(self.issuer_sol_widgets['recipient'], "Payer/Emittent", all_names)
        self.issuer_sol_widgets['visibility_func'](self.issuer_sol_widgets['recipient'].get())

    def _on_user_selection_change(self, selected_user_name: str):
        """Behandelt Änderung der Nutzerauswahl"""
        all_names = list(self.wallet_names_map.keys())
        
        self._update_recipient_list(self.user_spl_widgets['recipient'], selected_user_name, all_names)
        self.user_spl_widgets['visibility_func'](self.user_spl_widgets['recipient'].get())
        
        self._update_recipient_list(self.user_sol_widgets['recipient'], selected_user_name, all_names)
        self.user_sol_widgets['visibility_func'](self.user_sol_widgets['recipient'].get())

    # === Logging ===

    def log(self, message, level="info"):
        """Fügt Nachricht zum Log hinzu"""
        self.log_queue.put((message, level))

    def process_log_queue(self):
        """Verarbeitet Log-Nachrichten"""
        try:
            while True:
                message, level = self.log_queue.get_nowait()
                self.log_textbox.append_text(message, level)
        except queue.Empty:
            pass
        finally:
            self.after(200, self.process_log_queue)

    # === Status-Updates ===

    def start_status_refresh(self):
        """Startet Status-Aktualisierung"""
        self.log(f"{DesignSystem.ICONS['refresh']} Wallet-Status wird aktualisiert...", "info")
        self.refresh_button.configure(state="disabled")
        run_in_thread(self._fetch_wallet_statuses_thread)

    def _fetch_wallet_statuses_thread(self):
        """Holt Wallet-Status im Hintergrund"""
        statuses = []
        all_kps = [self.wallets['payer']] + self.wallets['test_users']
        names = ["Payer/Emittent"] + [f"Nutzer {i+1}" for i in range(len(self.wallets['test_users']))]
        mint_pubkey = self.wallets['mint'].pubkey()

        for name, kp in zip(names, all_kps):
            status = {
                "name": name, 
                "address": str(kp.pubkey()), 
                "sol_balance": "N/A", 
                "token_balance": "N/A", 
                "ata_address": "N/A"
            }
            
            try:
                # SOL Balance
                balance_resp = self.http_client.get_balance(kp.pubkey())
                status["sol_balance"] = format_sol_amount(balance_resp.value)
                
                # Token Balance
                ata = get_associated_token_address(kp.pubkey(), mint_pubkey)
                status["ata_address"] = str(ata)
                
                try:
                    token_balance_resp = self.http_client.get_token_account_balance(ata)
                    ui_amount = token_balance_resp.value.ui_amount or 0.0
                    status["token_balance"] = format_token_amount(ui_amount, 2)
                except SolanaRpcException:
                    status["token_balance"] = "0,00"
                    
            except Exception as e:
                status["sol_balance"] = "Fehler"
                status["token_balance"] = "Fehler"
                self.log(f"Fehler beim Abrufen des Status für {name}: {e}", "error")
            
            statuses.append(status)
        
        self.after(0, self._update_status_ui, statuses)

    def _update_status_ui(self, statuses):
        """Aktualisiert Status-UI mit neuen Daten"""
        # Lösche alte Widgets
        for widget in self.status_scroll_frame.winfo_children():
            widget.destroy()

        for status in statuses:
            # Wallet-Frame
            wallet_frame = ctk.CTkFrame(
                self.status_scroll_frame, 
                corner_radius=DesignSystem.RADIUS['md']
            )
            wallet_frame.pack(fill="x", pady=(0, DesignSystem.SPACING['md']), padx=DesignSystem.SPACING['sm'])
            wallet_frame.grid_columnconfigure(0, weight=1)

            # Name
            name_label = ctk.CTkLabel(
                wallet_frame, 
                text=status['name'], 
                font=ctk.CTkFont(size=14, weight="bold")
            )
            name_label.grid(row=0, column=0, columnspan=2, padx=DesignSystem.SPACING['md'], 
                           pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['sm']), sticky="w")
            
            # Balances
            sol_label = ctk.CTkLabel(
                wallet_frame, 
                text=f"{DesignSystem.ICONS['sol']} {status['sol_balance']} SOL",
                font=ctk.CTkFont(size=12)
            )
            sol_label.grid(row=1, column=0, columnspan=2, padx=DesignSystem.SPACING['md'], 
                          pady=2, sticky="w")
            
            token_label = ctk.CTkLabel(
                wallet_frame, 
                text=f"{DesignSystem.ICONS['token']} {status['token_balance']} Token",
                font=ctk.CTkFont(size=12)
            )
            token_label.grid(row=2, column=0, columnspan=2, padx=DesignSystem.SPACING['md'], 
                            pady=2, sticky="w")

            # Adressen
            addr_label = ctk.CTkLabel(
                wallet_frame, 
                text="Wallet-Adresse:", 
                font=ctk.CTkFont(size=10, weight="bold")
            )
            addr_label.grid(row=3, column=0, columnspan=2, padx=DesignSystem.SPACING['md'], 
                           pady=(DesignSystem.SPACING['sm'], 2), sticky="w")
            
            addr_copyable = CopyableLabel(
                wallet_frame, 
                text=status['address'], 
                max_length=35
            )
            addr_copyable.grid(row=4, column=0, columnspan=2, padx=DesignSystem.SPACING['md'], 
                              pady=2, sticky="ew")
            
            ata_label = ctk.CTkLabel(
                wallet_frame, 
                text="Token-Konto (ATA):", 
                font=ctk.CTkFont(size=10, weight="bold")
            )
            ata_label.grid(row=5, column=0, columnspan=2, padx=DesignSystem.SPACING['md'], 
                          pady=(DesignSystem.SPACING['sm'], 2), sticky="w")
            
            ata_copyable = CopyableLabel(
                wallet_frame, 
                text=status['ata_address'], 
                max_length=35
            )
            ata_copyable.grid(row=6, column=0, columnspan=2, padx=DesignSystem.SPACING['md'], 
                             pady=(2, DesignSystem.SPACING['md']), sticky="ew")
        
        self.refresh_button.configure(state="normal")
        self.log(f"{DesignSystem.ICONS['success']} Status-Aktualisierung abgeschlossen.", "success")

    # === Transaktions-Handler ===

    def on_mint(self):
        """Behandelt Mint-Operation"""
        try:
            amount = float(self.mint_amount_entry.get().replace(",", "."))
            if amount <= 0:
                raise ValueError("Menge muss positiv sein.")
            
            if ConfirmDialog.show(self, "Mint bestätigen", 
                                f"Möchten Sie {amount} neue Token erstellen?",
                                confirm_text="Mint"):
                self.mint_button.configure(state="disabled")
                run_in_thread(self._execute_mint_thread, amount, self.mint_button)
        except ValueError as e:
            show_error(self, "Ungültige Eingabe", str(e))

    def on_burn(self):
        """Behandelt Burn-Operation"""
        try:
            amount = float(self.burn_amount_entry.get().replace(",", "."))
            if amount <= 0:
                raise ValueError("Menge muss positiv sein.")
            
            if ConfirmDialog.show(self, "Burn bestätigen", 
                                f"Möchten Sie {amount} Token unwiderruflich vernichten?",
                                confirm_text="Vernichten", danger=True):
                self.burn_button.configure(state="disabled")
                run_in_thread(self._execute_burn_thread, amount, self.burn_button)
        except ValueError as e:
            show_error(self, "Ungültige Eingabe", str(e))

    def on_freeze_thaw(self):
        """Behandelt Freeze/Thaw-Operation"""
        try:
            ata_str = self.freeze_thaw_ata_entry.get().strip()
            ata_pubkey = Pubkey.from_string(ata_str)
            action_text = self.freeze_thaw_action.get()
            action = "freeze" if DesignSystem.ICONS['freeze'] in action_text else "thaw"
            
            action_german = "sperren" if action == "freeze" else "entsperren"
            if ConfirmDialog.show(self, f"Konto {action_german}", 
                                f"Möchten Sie das Token-Konto wirklich {action_german}?",
                                confirm_text=action_german.capitalize(), danger=(action == "freeze")):
                self.freeze_thaw_button.configure(state="disabled")
                run_in_thread(self._execute_freeze_thaw_thread, action, ata_pubkey, self.freeze_thaw_button)
        except Exception as e:
            show_error(self, "Ungültige Eingabe", f"Bitte eine gültige Token-Konto-Adresse (ATA) eingeben.\\n\\n{e}")

    def _handle_transfer(self, sender_kp, amount_entry, recipient_dropdown, external_addr_entry, button, transfer_type):
        """Behandelt Transfer-Operationen"""
        try:
            amount = float(amount_entry.get().replace(",", "."))
            if amount <= 0:
                raise ValueError("Menge muss positiv sein.")

            recipient_choice = recipient_dropdown.get()
            if recipient_choice == "📝 Externe Adresse...":
                dest_pubkey = Pubkey.from_string(external_addr_entry.get().strip())
            else:
                dest_pubkey = self.wallet_names_map[recipient_choice]

            button.configure(state="disabled")
            run_in_thread(self._execute_transfer_thread, sender_kp, dest_pubkey, amount, button, transfer_type)
        except Exception as e:
            show_error(self, "Fehler bei der Überweisung", str(e))
            button.configure(state="normal")
            
    def on_spl_transfer(self, amount_entry, recipient_dropdown, external_addr_entry, button):
        """Handler für SPL-Token Transfer vom Emittent"""
        self._handle_transfer(self.wallets['payer'], amount_entry, recipient_dropdown, external_addr_entry, button, "spl")

    def on_sol_transfer(self, amount_entry, recipient_dropdown, external_addr_entry, button):
        """Handler für SOL Transfer vom Emittent"""
        self._handle_transfer(self.wallets['payer'], amount_entry, recipient_dropdown, external_addr_entry, button, "sol")

    def on_user_spl_transfer(self, amount_entry, recipient_dropdown, external_addr_entry, button):
        """Handler für SPL-Token Transfer von Testnutzer"""
        user_name = self.user_selector.get()
        user_index = int(user_name.split(" ")[1]) - 1
        self._handle_transfer(self.wallets['test_users'][user_index], amount_entry, recipient_dropdown, external_addr_entry, button, "spl")

    def on_user_sol_transfer(self, amount_entry, recipient_dropdown, external_addr_entry, button):
        """Handler für SOL Transfer von Testnutzer"""
        user_name = self.user_selector.get()
        user_index = int(user_name.split(" ")[1]) - 1
        self._handle_transfer(self.wallets['test_users'][user_index], amount_entry, recipient_dropdown, external_addr_entry, button, "sol")

    # === Worker Threads ===

    def _confirm_and_send_transaction(self, instructions, signers: list[Keypair], label: str):
        """Sendet und bestätigt Transaktion"""
        self.log(f"→ Sende Transaktion: '{label}'...", "info")
        try:
            blockhash_resp = self.http_client.get_latest_blockhash()
            transaction = Transaction.new_signed_with_payer(
                instructions, 
                payer=signers[0].pubkey(), 
                signing_keypairs=signers, 
                recent_blockhash=blockhash_resp.value.blockhash
            )
            result = self.http_client.send_transaction(transaction)
            self.log(f"   Transaktion gesendet, warte auf Bestätigung... Signatur: {result.value}", "info")
            self.http_client.confirm_transaction(result.value, "finalized", sleep_seconds=5.0)
            self.log(f"{DesignSystem.ICONS['success']} ERFOLG '{label}'! Signatur: {result.value}", "success")
            return True
        except Exception as e:
            self.log(f"{DesignSystem.ICONS['error']} FEHLER bei '{label}': {e}", "error")
            return False

    def _execute_mint_thread(self, amount, button):
        """Führt Mint-Operation aus"""
        amount_lamports = int(amount * (10**self.TOKEN_DECIMALS))
        ata = get_associated_token_address(self.wallets['payer'].pubkey(), self.wallets['mint'].pubkey())
        ix = mint_to(MintToParams(TOKEN_PROGRAM_ID, self.wallets['mint'].pubkey(), ata, self.wallets['payer'].pubkey(), amount_lamports))
        
        if self._confirm_and_send_transaction([ix], [self.wallets['payer']], f"{amount} Tokens minten"):
            self.after(0, self.start_status_refresh)
        
        self.after(0, lambda: button.configure(state="normal"))

    def _execute_burn_thread(self, amount, button):
        """Führt Burn-Operation aus"""
        amount_lamports = int(amount * (10**self.TOKEN_DECIMALS))
        ata = get_associated_token_address(self.wallets['payer'].pubkey(), self.wallets['mint'].pubkey())
        ix = burn(BurnParams(TOKEN_PROGRAM_ID, ata, self.wallets['mint'].pubkey(), self.wallets['payer'].pubkey(), amount_lamports))
        
        if self._confirm_and_send_transaction([ix], [self.wallets['payer']], f"{amount} Tokens verbrennen"):
            self.after(0, self.start_status_refresh)
        
        self.after(0, lambda: button.configure(state="normal"))
        
    def _execute_freeze_thaw_thread(self, action, ata_pubkey, button):
        """Führt Freeze/Thaw-Operation aus"""
        mint_pubkey = self.wallets['mint'].pubkey()
        payer_kp = self.wallets['payer']
        
        if action == 'freeze': 
            ix = freeze_account(FreezeAccountParams(TOKEN_PROGRAM_ID, ata_pubkey, mint_pubkey, payer_kp.pubkey()))
        else: 
            ix = thaw_account(ThawAccountParams(TOKEN_PROGRAM_ID, ata_pubkey, mint_pubkey, payer_kp.pubkey()))
        
        self._confirm_and_send_transaction([ix], [payer_kp], f"Aktion '{action}' für {ata_pubkey}")
        self.after(0, lambda: button.configure(state="normal"))

    def _execute_transfer_thread(self, sender_kp, dest_pubkey, amount, button, transfer_type):
        """Führt Transfer-Operation aus"""
        instructions = []
        
        if transfer_type == "spl":
            amount_lamports = int(amount * (10**self.TOKEN_DECIMALS))
            source_ata = get_associated_token_address(sender_kp.pubkey(), self.wallets['mint'].pubkey())
            dest_ata = get_associated_token_address(dest_pubkey, self.wallets['mint'].pubkey())
            
            # Prüfe ob Ziel-ATA existiert
            if self.http_client.get_account_info(dest_ata).value is None:
                self.log("→ Ziel-Token-Konto (ATA) existiert nicht, wird automatisch erstellt.", "info")
                instructions.append(create_associated_token_account(sender_kp.pubkey(), dest_pubkey, self.wallets['mint'].pubkey()))
            
            instructions.append(spl_transfer(SplTransferParams(TOKEN_PROGRAM_ID, source_ata, dest_ata, sender_kp.pubkey(), amount_lamports)))
            label = f"Überweise {amount} Tokens"
        else:
            amount_lamports = int(amount * 10**9)
            instructions.append(system_transfer(SystemTransferParams(from_pubkey=sender_kp.pubkey(), to_pubkey=dest_pubkey, lamports=amount_lamports)))
            label = f"Überweise {amount} SOL"
        
        if self._confirm_and_send_transaction(instructions, [sender_kp], label):
            self.after(0, self.start_status_refresh)
        
        self.after(0, lambda: button.configure(state="normal"))

if __name__ == "__main__":
    try:
        app = SolanaTokenUI()
        if hasattr(app, 'http_client') and app.http_client.is_connected():
            app.mainloop()
    except Exception as e:
        messagebox.showerror("Unerwarteter Fehler", f"Ein schwerwiegender Fehler ist aufgetreten:\\n\\n{e}")

