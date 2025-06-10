#!/usr/bin/env python3
# === app.py: Grafische Benutzeroberfläche für das Solana Token Management Tool ===
# Verbesserte Version: Integrierte UI-Komponenten, dynamische Dezimalstellen,
# und benutzerfreundlichere Interaktionen. Skalierungsfähige Schriftarten implementiert.

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import threading
import queue
import os
import sys
import json
import webbrowser
from typing import Dict, List, Optional, Tuple, Callable

# =================================================================================
# === Integrierte UI-Komponenten (wie in setup.py) ===
# =================================================================================

class DesignSystem:
    """Zentrale Konfiguration für das UI-Design."""
    COLORS = {
        "primary": "#2FA85F",
        "primary_hover": "#288F51",
        "background": "#242424",
        "foreground": "#2D2D2D",
        "text": "#FFFFFF",
        "text_secondary": "#B0B0B0",
        "success": "#28A745",
        "success_hover": "#218838",
        "error": "#DC3545",
        "error_hover": "#C82333",
        "warning": "#FFC107",
        "info": "#17A2B8",
        "log_header": "#00A0D2",
    }
    SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24}
    RADIUS = {"sm": 4, "md": 8, "lg": 12}
    ICONS = {
        "settings": "⚙️", "wallet": "💼", "token": "🪙", "sol": "◎",
        "info": "ℹ️", "success": "✅", "error": "❌", "warning": "⚠️",
        "clipboard": "📋", "link": "🔗", "spinner": "⏳", "refresh": "🔄",
        "mint": "✨", "burn": "🔥", "send": "➡️", 
        "freeze": "❄️", "thaw": "☀️", "execute": "▶️"
    }

class StatusIndicator(ctk.CTkFrame):
    """Ein UI-Element zur Anzeige eines Status mit Icon und Text."""
    def __init__(self, master, status="unknown", text=""):
        super().__init__(master, fg_color="transparent")
        self.status_icon = ctk.CTkLabel(self, text="")
        self.status_icon.pack(side="left", padx=(0, DesignSystem.SPACING['sm']))
        self.status_label = ctk.CTkLabel(self, text=text)
        self.status_label.pack(side="left")
        self.set_status(status, text)

    def set_status(self, status, text):
        icon_map = {
            "success": DesignSystem.ICONS['success'], "error": DesignSystem.ICONS['error'],
            "warning": DesignSystem.ICONS['warning'], "info": DesignSystem.ICONS['info'],
            "loading": DesignSystem.ICONS['spinner'], "unknown": "❔"
        }
        color_map = {
            "success": DesignSystem.COLORS['success'], "error": DesignSystem.COLORS['error'],
            "warning": DesignSystem.COLORS['warning'], "info": DesignSystem.COLORS['text_secondary'],
            "loading": DesignSystem.COLORS['info'], "unknown": DesignSystem.COLORS['text_secondary']
        }
        self.status_icon.configure(text=icon_map.get(status, "❔"))
        self.status_label.configure(text=text, text_color=color_map.get(status, "white"))

class CopyableLabel(ctk.CTkFrame):
    """Ein Label mit einem Button zum Kopieren des Inhalts."""
    def __init__(self, master, text, max_length=50):
        super().__init__(master, fg_color="transparent")
        self.text_to_copy = text
        display_text = text if len(text) <= max_length else f"{text[:max_length//2-2]}...{text[-max_length//2+2:]}"
        self.label = ctk.CTkLabel(self, text=display_text, text_color=DesignSystem.COLORS['text_secondary'])
        self.label.pack(side="left", fill="x", expand=True)
        self.copy_button = ctk.CTkButton(self, text=DesignSystem.ICONS['clipboard'], width=30, command=self.copy_to_clipboard)
        self.copy_button.pack(side="right", padx=(DesignSystem.SPACING['sm'], 0))

    def copy_to_clipboard(self):
        self.clipboard_clear()
        self.clipboard_append(self.text_to_copy)
        self.copy_button.configure(text="✅")
        self.after(2000, lambda: self.copy_button.configure(text=DesignSystem.ICONS['clipboard']))

    def set_text(self, text, max_length=50):
        self.text_to_copy = text
        display_text = text if len(text) <= max_length else f"{text[:max_length//2-2]}...{text[-max_length//2+2:]}"
        self.label.configure(text=display_text)

class EnhancedTextbox(ctk.CTkTextbox):
    """Ein Textbox-Widget mit Farb-Tagging-Unterstützung."""
    def __init__(self, master, **kwargs):
        super().__init__(master, state="disabled", **kwargs)
        self.tag_config("success", foreground=DesignSystem.COLORS['success'])
        self.tag_config("error", foreground=DesignSystem.COLORS['error'])
        self.tag_config("warning", foreground=DesignSystem.COLORS['warning'])
        self.tag_config("info", foreground=DesignSystem.COLORS['text_secondary'])
        # font parameter removed for scaling compatibility
        self.tag_config("header", foreground=DesignSystem.COLORS['log_header'])

    def append_text(self, message, level="info"):
        self.configure(state="normal")
        self.insert("end", message + "\n", level)
        self.configure(state="disabled")
        self.see("end")

class ConfirmDialog(ctk.CTkToplevel):
    """Ein modaler Bestätigungsdialog."""
    def __init__(self, parent, title, message, confirm_text="OK", cancel_text="Abbrechen", danger=False):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.result = False
        
        self.message_label = ctk.CTkLabel(self, text=message, wraplength=400, justify="left")
        self.message_label.pack(padx=20, pady=20)
        
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.pack(padx=20, pady=(0, 20), fill="x")
        button_frame.grid_columnconfigure((0, 1), weight=1)
        
        confirm_color = DesignSystem.COLORS['error'] if danger else DesignSystem.COLORS['success']
        self.ok_button = ctk.CTkButton(button_frame, text=confirm_text, command=self.on_confirm, fg_color=confirm_color)
        self.ok_button.grid(row=0, column=1, padx=(10, 0))
        
        self.cancel_button = ctk.CTkButton(button_frame, text=cancel_text, command=self.on_cancel, fg_color=DesignSystem.COLORS['text_secondary'])
        self.cancel_button.grid(row=0, column=0, padx=(0, 10))
        self.wait_window()

    def on_confirm(self):
        self.result = True
        self.destroy()

    def on_cancel(self):
        self.result = False
        self.destroy()

    @staticmethod
    def show(parent, title, message, confirm_text="OK", cancel_text="Abbrechen", danger=False):
        dialog = ConfirmDialog(parent, title, message, confirm_text, cancel_text, danger)
        return dialog.result

def show_error(parent, title, message): messagebox.showerror(title, message, parent=parent)
def show_info(parent, title, message): messagebox.showinfo(title, message, parent=parent)
def run_in_thread(func: Callable, *args): threading.Thread(target=func, args=args, daemon=True).start()
def format_sol_amount(lamports: int) -> str: return f"{(lamports / 10**9):.6f}"
def format_token_amount(amount: float, decimals: int) -> str: return f"{amount:,.{decimals}f}"
def truncate_address(address: str, chars: int = 8) -> str: return f"{address[:chars]}...{address[-chars:]}"

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
        mint_to, MintToParams, burn, BurnParams,
        create_associated_token_account, get_associated_token_address,
        freeze_account, FreezeAccountParams, thaw_account, ThawAccountParams
    )
    from spl.token.constants import TOKEN_PROGRAM_ID
except ImportError as e:
    messagebox.showerror("Fehler: Fehlende Bibliotheken", f"Eine oder mehrere erforderliche Python-Bibliotheken fehlen. ({e})\n\nBitte installieren Sie diese mit:\npip install solders solana spl-token-py customtkinter")
    sys.exit(1)

# === HILFSFUNKTIONEN ===
def load_config():
    """Lädt die Konfiguration aus der config.json-Datei."""
    try:
        with open("config.json", 'r') as f: return json.load(f)
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
        messagebox.showerror("Fehler", f"Essentielle Wallet-Datei '{path}' nicht gefunden.\n\nBitte zuerst setup.py ausführen.")
        return None
    with open(path, 'r') as f: return Keypair.from_bytes(bytes(json.load(f)))

# === HAUPTANWENDUNG ===
class SolanaTokenUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        # Backend
        self.log_queue = queue.Queue()
        self.wallets = {}
        self.wallet_names_map = {}
        self.auto_refresh_enabled = True
        self.refresh_interval = 30000

        if not self._initialize_backend():
            self.after(100, self.destroy)
            return
        
        # UI
        self.title("Solana Token Manager")
        self.geometry("1400x900")
        self.minsize(1200, 700)
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        
        self.grid_columnconfigure(0, weight=1, minsize=400)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        self._create_widgets()
        self._setup_keyboard_shortcuts()
        
        # Start
        self.after(250, self.process_log_queue)
        self._update_all_recipient_lists()
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
            if not self.wallets['payer'] or not self.wallets['mint']: return False
            
            # WICHTIG: Dezimalstellen aus der Konfiguration laden
            self.TOKEN_DECIMALS = self.config.get('token_decimals', 9) # Fallback auf 9

            test_user_files = sorted([f for f in os.listdir(wallet_folder) if f.startswith("test-user-") and f.endswith(".json")])
            self.wallets['test_users'] = [load_keypair(wallet_folder, f) for f in test_user_files]
            
            self.wallet_names_map = {"Payer/Emittent": self.wallets['payer'].pubkey()}
            for i, user_kp in enumerate(self.wallets['test_users']):
                self.wallet_names_map[f"Nutzer {i+1}"] = user_kp.pubkey()
            
            return True
        except Exception as e:
            show_error(self, "Initialisierungsfehler", f"Ein kritischer Fehler ist aufgetreten:\n\n{e}")
            return False

    def _create_widgets(self):
        """Erstellt die Hauptbenutzeroberfläche"""
        # Linker Bereich
        self.status_frame = ctk.CTkFrame(self, corner_radius=DesignSystem.RADIUS['lg'])
        self.status_frame.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'], sticky="nsew")
        self.status_frame.grid_rowconfigure(2, weight=1)
        self.status_frame.grid_columnconfigure(0, weight=1)
        self._create_status_header()
        self._create_connection_info()
        self._create_wallet_status_area()
        
        # Rechter Bereich
        self.main_content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_content_frame.grid(row=0, column=1, padx=(0, DesignSystem.SPACING['md']), pady=DesignSystem.SPACING['md'], sticky="nsew")
        self.main_content_frame.grid_rowconfigure(0, weight=2)
        self.main_content_frame.grid_rowconfigure(1, weight=1)
        self.main_content_frame.grid_columnconfigure(0, weight=1)
        self._create_action_tabs()
        self._create_log_area()

    def _create_status_header(self):
        header_frame = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'], sticky="ew")
        header_frame.grid_columnconfigure(0, weight=1)
        # font parameter removed for scaling compatibility
        ctk.CTkLabel(header_frame, text=f"{DesignSystem.ICONS['wallet']} Wallet Status").grid(row=0, column=0, sticky="w")
        button_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        button_frame.grid(row=0, column=1, sticky="e")
        self.refresh_button = ctk.CTkButton(button_frame, text=DesignSystem.ICONS['refresh'], command=self.start_status_refresh, width=40, height=32)
        self.refresh_button.pack(side="right", padx=(DesignSystem.SPACING['sm'], 0))
        self.auto_refresh_var = tk.BooleanVar(value=True)
        self.auto_refresh_check = ctk.CTkCheckBox(button_frame, text="Auto", variable=self.auto_refresh_var, command=self._toggle_auto_refresh, width=60)
        self.auto_refresh_check.pack(side="right", padx=(0, DesignSystem.SPACING['sm']))

    def _create_connection_info(self):
        self.connection_status = StatusIndicator(self.status_frame, status="success", text=f"Verbunden: {self.config['rpc_url']}")
        self.connection_status.grid(row=1, column=0, padx=DesignSystem.SPACING['md'], pady=(0, DesignSystem.SPACING['sm']), sticky="ew")

    def _create_wallet_status_area(self):
        self.status_scroll_frame = ctk.CTkScrollableFrame(self.status_frame, fg_color="transparent", corner_radius=DesignSystem.RADIUS['md'])
        self.status_scroll_frame.grid(row=2, column=0, sticky="nsew", padx=DesignSystem.SPACING['sm'])

    def _create_action_tabs(self):
        self.tab_view = ctk.CTkTabview(self.main_content_frame, corner_radius=DesignSystem.RADIUS['lg'])
        self.tab_view.grid(row=0, column=0, sticky="nsew")
        self.tab_view.add("🏦 Emittent")
        self.tab_view.add("👥 Testnutzer")
        self.tab_view.add("⚙️ Einstellungen")
        self._create_issuer_tab(self.tab_view.tab("🏦 Emittent"))
        self._create_user_tab(self.tab_view.tab("👥 Testnutzer"))
        self._create_settings_tab(self.tab_view.tab("⚙️ Einstellungen"))

    def _create_issuer_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        # Token-Versorgung
        supply_frame = ctk.CTkFrame(tab, corner_radius=DesignSystem.RADIUS['md'])
        supply_frame.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'], sticky="ew")
        supply_frame.grid_columnconfigure(1, weight=1)
        # font parameter removed for scaling compatibility
        ctk.CTkLabel(supply_frame, text=f"{DesignSystem.ICONS['token']} Token-Versorgung verwalten").grid(row=0, column=0, columnspan=3, padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), sticky="w")
        ctk.CTkLabel(supply_frame, text="Neue Tokens erstellen:").grid(row=1, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="w")
        self.mint_amount_entry = ctk.CTkEntry(supply_frame, placeholder_text="Anzahl Tokens", width=200)
        self.mint_amount_entry.grid(row=1, column=1, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="ew")
        self.mint_button = ctk.CTkButton(supply_frame, text=f"{DesignSystem.ICONS['mint']} Mint", command=self.on_mint, fg_color=DesignSystem.COLORS['success'])
        self.mint_button.grid(row=1, column=2, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'])
        ctk.CTkLabel(supply_frame, text="Tokens vernichten:").grid(row=2, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="w")
        self.burn_amount_entry = ctk.CTkEntry(supply_frame, placeholder_text="Anzahl Tokens", width=200)
        self.burn_amount_entry.grid(row=2, column=1, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="ew")
        self.burn_button = ctk.CTkButton(supply_frame, text=f"{DesignSystem.ICONS['burn']} Burn", command=self.on_burn, fg_color=DesignSystem.COLORS['error'])
        self.burn_button.grid(row=2, column=2, padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['sm'], DesignSystem.SPACING['md']))
        
        # Transfer & Freeze/Thaw
        self.issuer_spl_widgets = self._create_transfer_frame(tab, f"{DesignSystem.ICONS['token']} Token senden", self.on_spl_transfer)
        self.issuer_spl_widgets['frame'].grid(row=1, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'], sticky="ew")
        self.issuer_sol_widgets = self._create_transfer_frame(tab, f"{DesignSystem.ICONS['sol']} SOL senden", self.on_sol_transfer)
        self.issuer_sol_widgets['frame'].grid(row=2, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'], sticky="ew")
        self._create_freeze_thaw_frame(tab).grid(row=3, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'], sticky="ew")

    def _create_transfer_frame(self, parent, title, command):
        frame = ctk.CTkFrame(parent, corner_radius=DesignSystem.RADIUS['md'])
        frame.grid_columnconfigure(1, weight=1)
        # font parameter removed for scaling compatibility
        ctk.CTkLabel(frame, text=title).grid(row=0, column=0, columnspan=3, padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), sticky="w")
        ctk.CTkLabel(frame, text="An:").grid(row=1, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="w")
        recipient_dropdown = ctk.CTkOptionMenu(frame, values=["-"], corner_radius=DesignSystem.RADIUS['sm'], width=200)
        recipient_dropdown.grid(row=1, column=1, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="ew")
        ctk.CTkLabel(frame, text="Betrag:").grid(row=2, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="w")
        amount_entry = ctk.CTkEntry(frame, placeholder_text="Betrag eingeben", width=200)
        amount_entry.grid(row=2, column=1, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="ew")
        external_addr_entry = ctk.CTkEntry(frame, placeholder_text="Externe Wallet-Adresse eingeben")
        def on_recipient_change(choice): external_addr_entry.grid(row=3, column=0, columnspan=3, padx=DesignSystem.SPACING['md'], pady=(0, DesignSystem.SPACING['sm']), sticky="ew") if choice == "📝 Externe Adresse..." else external_addr_entry.grid_forget()
        recipient_dropdown.configure(command=on_recipient_change)
        button = ctk.CTkButton(frame, text=f"{DesignSystem.ICONS['send']} Senden", corner_radius=DesignSystem.RADIUS['sm'], command=lambda: self._handle_transfer(command, amount_entry, recipient_dropdown, external_addr_entry, button))
        button.grid(row=2, column=2, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'])
        ctk.CTkLabel(frame, text="").grid(row=4, column=0, pady=2) # Spacer
        return {'frame': frame, 'amount': amount_entry, 'recipient': recipient_dropdown, 'external': external_addr_entry, 'button': button, 'visibility_func': on_recipient_change}

    def _create_freeze_thaw_frame(self, parent):
        """Erstellt den Freeze/Thaw-Bereich mit Dropdown-Menü und externer Adresseingabe."""
        frame = ctk.CTkFrame(parent, corner_radius=DesignSystem.RADIUS['md'])
        frame.grid_columnconfigure(1, weight=1)
        
        # Titel
        # font parameter removed for scaling compatibility
        ctk.CTkLabel(frame, text=f"{DesignSystem.ICONS['freeze']} Token-Konto sperren/entsperren").grid(row=0, column=0, columnspan=3, padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), sticky="w")
        
        # Auswahl des Ziels
        ctk.CTkLabel(frame, text="Wallet / Adresse:").grid(row=1, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="w")
        wallet_names = list(self.wallet_names_map.keys()) + ["📝 Externe Adresse..."]
        self.freeze_thaw_wallet_selector = ctk.CTkOptionMenu(frame, values=wallet_names, corner_radius=DesignSystem.RADIUS['sm'])
        self.freeze_thaw_wallet_selector.grid(row=1, column=1, columnspan=2, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="ew")

        # Eingabefeld für externe Adresse (initial versteckt)
        self.freeze_thaw_external_entry = ctk.CTkEntry(frame, placeholder_text="Externe Wallet-Adresse für ATA eingeben")
        
        # Funktion zum Ein-/Ausblenden des Eingabefelds
        def on_selection_change(choice):
            if choice == "📝 Externe Adresse...":
                self.freeze_thaw_external_entry.grid(row=2, column=0, columnspan=3, padx=DesignSystem.SPACING['md'], pady=(0, DesignSystem.SPACING['sm']), sticky="ew")
            else:
                self.freeze_thaw_external_entry.grid_forget()
        
        self.freeze_thaw_wallet_selector.configure(command=on_selection_change)

        # Segmented Button für Aktion
        self.freeze_thaw_action = ctk.CTkSegmentedButton(frame, values=[f"{DesignSystem.ICONS['freeze']} Sperren", f"{DesignSystem.ICONS['thaw']} Entsperren"], corner_radius=DesignSystem.RADIUS['sm'])
        self.freeze_thaw_action.set(f"{DesignSystem.ICONS['freeze']} Sperren")
        self.freeze_thaw_action.grid(row=3, column=0, columnspan=2, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'], sticky="ew")
        
        # Ausführen-Button
        self.freeze_thaw_button = ctk.CTkButton(frame, text=f"{DesignSystem.ICONS['execute']} Ausführen", command=self.on_freeze_thaw, corner_radius=DesignSystem.RADIUS['sm'])
        self.freeze_thaw_button.grid(row=3, column=2, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'])
        
        # Spacer
        ctk.CTkLabel(frame, text="").grid(row=4, column=0, pady=2)
        return frame

    def _create_user_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        if not self.wallets['test_users']:
            ctk.CTkLabel(tab, text="Keine Testnutzer gefunden.\nBitte führen Sie zuerst das Setup aus.", text_color=DesignSystem.COLORS['text_secondary']).pack(pady=DesignSystem.SPACING['xl'], padx=DesignSystem.SPACING['md'])
            return
        user_selection_frame = ctk.CTkFrame(tab, corner_radius=DesignSystem.RADIUS['md'])
        user_selection_frame.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'], sticky="ew")
        # font parameter removed for scaling compatibility
        ctk.CTkLabel(user_selection_frame, text="Aktionen ausführen als:").pack(side="left", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'])
        user_names = [f"Nutzer {i+1}" for i in range(len(self.wallets['test_users']))]
        self.user_selector = ctk.CTkOptionMenu(user_selection_frame, values=user_names, command=self._on_user_selection_change, corner_radius=DesignSystem.RADIUS['sm'])
        self.user_selector.pack(side="left", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'])
        self.user_spl_widgets = self._create_transfer_frame(tab, f"{DesignSystem.ICONS['token']} Token senden", self.on_user_spl_transfer)
        self.user_spl_widgets['frame'].grid(row=1, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'], sticky="ew")
        self.user_sol_widgets = self._create_transfer_frame(tab, f"{DesignSystem.ICONS['sol']} SOL senden", self.on_user_sol_transfer)
        self.user_sol_widgets['frame'].grid(row=2, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'], sticky="ew")
        self._on_user_selection_change(self.user_selector.get())

    def _create_settings_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        general_frame = ctk.CTkFrame(tab, corner_radius=DesignSystem.RADIUS['md'])
        general_frame.grid(row=0, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'], sticky="ew")
        # font parameter removed for scaling compatibility
        ctk.CTkLabel(general_frame, text=f"{DesignSystem.ICONS['settings']} Allgemeine Einstellungen").pack(padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), anchor="w")
        refresh_frame = ctk.CTkFrame(general_frame, fg_color="transparent")
        refresh_frame.pack(fill="x", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'])
        ctk.CTkLabel(refresh_frame, text="Auto-Refresh Intervall:").pack(side="left")
        self.refresh_interval_var = tk.StringVar(value=str(self.refresh_interval // 1000))
        ctk.CTkEntry(refresh_frame, textvariable=self.refresh_interval_var, width=60).pack(side="left", padx=DesignSystem.SPACING['sm'])
        ctk.CTkLabel(refresh_frame, text="Sekunden").pack(side="left")
        
        connection_frame = ctk.CTkFrame(tab, corner_radius=DesignSystem.RADIUS['md'])
        connection_frame.grid(row=1, column=0, padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['md'], sticky="ew")
        # font parameter removed for scaling compatibility
        ctk.CTkLabel(connection_frame, text=f"{DesignSystem.ICONS['info']} Verbindungsinformationen").pack(padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['md'], DesignSystem.SPACING['lg']), anchor="w")
        rpc_frame = ctk.CTkFrame(connection_frame, fg_color="transparent")
        rpc_frame.pack(fill="x", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'])
        ctk.CTkLabel(rpc_frame, text="RPC Endpunkt:", width=120, anchor="w").pack(side="left")
        CopyableLabel(rpc_frame, text=self.config['rpc_url']).pack(side="left", fill="x", expand=True)
        wallet_frame = ctk.CTkFrame(connection_frame, fg_color="transparent")
        wallet_frame.pack(fill="x", padx=DesignSystem.SPACING['md'], pady=DesignSystem.SPACING['sm'])
        ctk.CTkLabel(wallet_frame, text="Wallet-Ordner:", width=120, anchor="w").pack(side="left")
        CopyableLabel(wallet_frame, text=self.config['wallet_folder']).pack(side="left", fill="x", expand=True)
        if self.wallets.get('mint'):
            mint_frame = ctk.CTkFrame(connection_frame, fg_color="transparent")
            mint_frame.pack(fill="x", padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['sm'], DesignSystem.SPACING['md']))
            ctk.CTkLabel(mint_frame, text="Token Mint:", width=120, anchor="w").pack(side="left")
            CopyableLabel(mint_frame, text=str(self.wallets['mint'].pubkey())).pack(side="left", fill="x", expand=True)

    def _create_log_area(self):
        log_frame = ctk.CTkFrame(self.main_content_frame, corner_radius=DesignSystem.RADIUS['lg'])
        log_frame.grid(row=1, column=0, pady=(DesignSystem.SPACING['md'], 0), sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)
        log_header = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_header.grid(row=0, column=0, sticky="ew", padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['md'], 0))
        log_header.grid_columnconfigure(0, weight=1)
        # font parameter removed for scaling compatibility
        ctk.CTkLabel(log_header, text="📋 Transaktionsprotokoll").grid(row=0, column=0, sticky="w")
        self.log_textbox = EnhancedTextbox(log_frame)
        self.log_textbox.grid(row=1, column=0, sticky="nsew", padx=DesignSystem.SPACING['md'], pady=(DesignSystem.SPACING['sm'], DesignSystem.SPACING['md']))

    def _setup_keyboard_shortcuts(self):
        self.bind("<Control-r>", lambda e: self.start_status_refresh())
        self.bind("<F5>", lambda e: self.start_status_refresh())
        self.bind("<Control-q>", lambda e: self.destroy())

    # === Event-Handler und UI-Logik ===
    def _toggle_auto_refresh(self):
        self.auto_refresh_enabled = self.auto_refresh_var.get()
        if self.auto_refresh_enabled: self._schedule_auto_refresh()

    def _schedule_auto_refresh(self):
        if self.auto_refresh_enabled:
            try: self.refresh_interval = max(10000, int(self.refresh_interval_var.get()) * 1000)
            except: self.refresh_interval = 30000
            self.after(self.refresh_interval, self._auto_refresh)

    def _auto_refresh(self):
        if self.auto_refresh_enabled:
            self.start_status_refresh()
            self._schedule_auto_refresh()

    def _update_recipient_list(self, dropdown, sender_name, all_wallet_names):
        recipients = [name for name in all_wallet_names if name != sender_name]
        full_list = recipients + ["📝 Externe Adresse..."]
        current = dropdown.get()
        dropdown.configure(values=full_list)
        if current in full_list: dropdown.set(current)
        elif full_list: dropdown.set(full_list[0])
        else: dropdown.set("-")

    def _update_all_recipient_lists(self):
        all_names = list(self.wallet_names_map.keys())
        self._update_recipient_list(self.issuer_spl_widgets['recipient'], "Payer/Emittent", all_names)
        self.issuer_spl_widgets['visibility_func'](self.issuer_spl_widgets['recipient'].get())
        self._update_recipient_list(self.issuer_sol_widgets['recipient'], "Payer/Emittent", all_names)
        self.issuer_sol_widgets['visibility_func'](self.issuer_sol_widgets['recipient'].get())
        if hasattr(self, 'user_selector'): self._on_user_selection_change(self.user_selector.get())

    def _on_user_selection_change(self, selected_user_name: str):
        all_names = list(self.wallet_names_map.keys())
        self._update_recipient_list(self.user_spl_widgets['recipient'], selected_user_name, all_names)
        self.user_spl_widgets['visibility_func'](self.user_spl_widgets['recipient'].get())
        self._update_recipient_list(self.user_sol_widgets['recipient'], selected_user_name, all_names)
        self.user_sol_widgets['visibility_func'](self.user_sol_widgets['recipient'].get())

    def log(self, message, level="info"): self.log_queue.put((message, level))

    def process_log_queue(self):
        try:
            while True: self.log_textbox.append_text(*self.log_queue.get_nowait())
        except queue.Empty: pass
        finally: self.after(200, self.process_log_queue)

    # === Status-Updates ===
    def start_status_refresh(self):
        self.log(f"{DesignSystem.ICONS['refresh']} Wallet-Status wird aktualisiert...", "info")
        self.refresh_button.configure(state="disabled")
        run_in_thread(self._fetch_wallet_statuses_thread)

    def _fetch_wallet_statuses_thread(self):
        statuses, all_kps = [], [self.wallets['payer']] + self.wallets['test_users']
        names = ["Payer/Emittent"] + [f"Nutzer {i+1}" for i in range(len(all_kps)-1)]
        mint_pk = self.wallets['mint'].pubkey()
        for name, kp in zip(names, all_kps):
            status = {"name": name, "address": str(kp.pubkey())}
            try:
                status["sol_balance"] = format_sol_amount(self.http_client.get_balance(kp.pubkey()).value)
                ata = get_associated_token_address(kp.pubkey(), mint_pk)
                status["ata_address"] = str(ata)
                try:
                    balance = self.http_client.get_token_account_balance(ata).value
                    status["token_balance"] = format_token_amount(float(balance.ui_amount_string), self.TOKEN_DECIMALS)
                except (SolanaRpcException, AttributeError): status["token_balance"] = format_token_amount(0, self.TOKEN_DECIMALS)
            except Exception as e:
                status["sol_balance"], status["token_balance"] = "Fehler", "Fehler"
                self.log(f"Fehler beim Statusabruf für {name}: {e}", "error")
            statuses.append(status)
        self.after(0, self._update_status_ui, statuses)

    def _update_status_ui(self, statuses):
        for widget in self.status_scroll_frame.winfo_children(): widget.destroy()
        for status in statuses:
            frame = ctk.CTkFrame(self.status_scroll_frame, corner_radius=DesignSystem.RADIUS['md'])
            frame.pack(fill="x", pady=(0, DesignSystem.SPACING['md']), padx=DesignSystem.SPACING['sm'])
            frame.grid_columnconfigure(0, weight=1)
            # font parameter removed for scaling compatibility
            ctk.CTkLabel(frame, text=status['name']).grid(row=0, padx=10, pady=(10,5), sticky="w")
            ctk.CTkLabel(frame, text=f"{DesignSystem.ICONS['sol']} {status['sol_balance']} SOL").grid(row=1, padx=10, pady=2, sticky="w")
            ctk.CTkLabel(frame, text=f"{DesignSystem.ICONS['token']} {status['token_balance']} Token").grid(row=2, padx=10, pady=2, sticky="w")
            # font parameter removed for scaling compatibility
            ctk.CTkLabel(frame, text="Wallet-Adresse:").grid(row=3, padx=10, pady=(5,0), sticky="w")
            CopyableLabel(frame, text=status['address'], max_length=35).grid(row=4, padx=10, pady=2, sticky="ew")
            # font parameter removed for scaling compatibility
            ctk.CTkLabel(frame, text="Token-Konto (ATA):").grid(row=5, padx=10, pady=(5,0), sticky="w")
            CopyableLabel(frame, text=status['ata_address'], max_length=35).grid(row=6, padx=10, pady=(2,10), sticky="ew")
        self.refresh_button.configure(state="normal")
        self.log(f"{DesignSystem.ICONS['success']} Status-Aktualisierung abgeschlossen.", "success")

    # === Transaktions-Handler ===
    def _confirm_and_send_transaction(self, instructions, signers: list[Keypair], label: str):
        self.log(f"→ Sende Transaktion: '{label}'...", "info")
        try:
            tx = Transaction.new_signed_with_payer(instructions, signers[0].pubkey(), signers, self.http_client.get_latest_blockhash().value.blockhash)
            result = self.http_client.send_transaction(tx)
            self.log(f"   Transaktion gesendet, warte auf Bestätigung... Signatur: {result.value}", "info")
            self.http_client.confirm_transaction(result.value, "finalized")
            self.log(f"{DesignSystem.ICONS['success']} ERFOLG '{label}'! Signatur: {result.value}", "success")
            return True
        except Exception as e:
            self.log(f"{DesignSystem.ICONS['error']} FEHLER bei '{label}': {e}", "error")
            return False

    def on_mint(self):
        try:
            amount = float(self.mint_amount_entry.get().replace(",", "."))
            if ConfirmDialog.show(self, "Mint bestätigen", f"Möchten Sie {amount} neue Token erstellen?", confirm_text="Mint"):
                self.mint_button.configure(state="disabled")
                run_in_thread(self._execute_mint_thread, amount, self.mint_button)
        except ValueError: show_error(self, "Ungültige Eingabe", "Bitte eine gültige Zahl eingeben.")

    def on_burn(self):
        try:
            amount = float(self.burn_amount_entry.get().replace(",", "."))
            if ConfirmDialog.show(self, "Burn bestätigen", f"Möchten Sie {amount} Token unwiderruflich vernichten?", confirm_text="Vernichten", danger=True):
                self.burn_button.configure(state="disabled")
                run_in_thread(self._execute_burn_thread, amount, self.burn_button)
        except ValueError: show_error(self, "Ungültige Eingabe", "Bitte eine gültige Zahl eingeben.")

    def on_freeze_thaw(self):
        """Behandelt Freeze/Thaw für interne und externe Adressen."""
        try:
            wallet_name = self.freeze_thaw_wallet_selector.get()
            wallet_pubkey = None
            display_name = wallet_name

            if wallet_name == "📝 Externe Adresse...":
                address_str = self.freeze_thaw_external_entry.get().strip()
                if not address_str:
                    show_error(self, "Eingabefehler", "Bitte eine externe Wallet-Adresse eingeben.")
                    return
                try:
                    wallet_pubkey = Pubkey.from_string(address_str)
                    display_name = truncate_address(address_str)
                except Exception:
                    show_error(self, "Ungültige Adresse", "Die eingegebene externe Adresse ist keine gültige Solana-Adresse.")
                    return
            else:
                wallet_pubkey = self.wallet_names_map[wallet_name]

            ata_pubkey = get_associated_token_address(wallet_pubkey, self.wallets['mint'].pubkey())
            action = "freeze" if DesignSystem.ICONS['freeze'] in self.freeze_thaw_action.get() else "thaw"
            action_german = "sperren" if action == "freeze" else "entsperren"

            if ConfirmDialog.show(self, f"Konto {action_german}", f"Möchten Sie das Token-Konto von '{display_name}' wirklich {action_german}?", confirm_text=action_german.capitalize(), danger=(action == "freeze")):
                self.freeze_thaw_button.configure(state="disabled")
                run_in_thread(self._execute_freeze_thaw_thread, action, ata_pubkey, self.freeze_thaw_button)
        except Exception as e:
            show_error(self, "Fehler", f"Konnte Aktion nicht ausführen:\n{e}")

    def _handle_transfer(self, command, amount_entry, recipient_dropdown, external_addr_entry, button):
        try:
            amount = float(amount_entry.get().replace(",", "."))
            recipient_choice = recipient_dropdown.get()
            if recipient_choice == "📝 Externe Adresse...":
                if not external_addr_entry.get().strip(): raise ValueError("Externe Adresse darf nicht leer sein.")
            if ConfirmDialog.show(self, "Transfer bestätigen", f"Möchten Sie {amount} {'Token' if 'spl' in command.__name__ else 'SOL'} an {recipient_choice} senden?", confirm_text="Senden"):
                command(amount_entry, recipient_dropdown, external_addr_entry, button)
        except ValueError as e: show_error(self, "Ungültige Eingabe", str(e))
    
    def on_spl_transfer(self, amount_entry, recipient_dropdown, external_addr_entry, button): self._execute_transfer(self.wallets['payer'], amount_entry, recipient_dropdown, external_addr_entry, button, "spl")
    def on_sol_transfer(self, amount_entry, recipient_dropdown, external_addr_entry, button): self._execute_transfer(self.wallets['payer'], amount_entry, recipient_dropdown, external_addr_entry, button, "sol")
    def on_user_spl_transfer(self, amount_entry, recipient_dropdown, external_addr_entry, button):
        user_index = int(self.user_selector.get().split(" ")[1]) - 1
        self._execute_transfer(self.wallets['test_users'][user_index], amount_entry, recipient_dropdown, external_addr_entry, button, "spl")
    def on_user_sol_transfer(self, amount_entry, recipient_dropdown, external_addr_entry, button):
        user_index = int(self.user_selector.get().split(" ")[1]) - 1
        self._execute_transfer(self.wallets['test_users'][user_index], amount_entry, recipient_dropdown, external_addr_entry, button, "sol")

    # === Worker Threads ===
    def _execute_transfer(self, sender_kp, amount_entry, recipient_dropdown, external_addr_entry, button, transfer_type):
        button.configure(state="disabled")
        try:
            amount = float(amount_entry.get().replace(",", "."))
            recipient_choice = recipient_dropdown.get()
            dest_pubkey = Pubkey.from_string(external_addr_entry.get().strip()) if recipient_choice == "📝 Externe Adresse..." else self.wallet_names_map[recipient_choice]
            run_in_thread(self._execute_transfer_thread, sender_kp, dest_pubkey, amount, button, transfer_type)
        except Exception as e:
            show_error(self, "Fehler bei der Überweisung", str(e))
            button.configure(state="normal")

    def _execute_mint_thread(self, amount, button):
        amount_lamports = int(amount * (10**self.TOKEN_DECIMALS))
        ata = get_associated_token_address(self.wallets['payer'].pubkey(), self.wallets['mint'].pubkey())
        ix = mint_to(MintToParams(TOKEN_PROGRAM_ID, self.wallets['mint'].pubkey(), ata, self.wallets['payer'].pubkey(), amount_lamports))
        if self._confirm_and_send_transaction([ix], [self.wallets['payer']], f"{amount} Tokens minten"):
            self.after(0, self.start_status_refresh)
        self.after(0, lambda: button.configure(state="normal"))

    def _execute_burn_thread(self, amount, button):
        amount_lamports = int(amount * (10**self.TOKEN_DECIMALS))
        ata = get_associated_token_address(self.wallets['payer'].pubkey(), self.wallets['mint'].pubkey())
        ix = burn(BurnParams(TOKEN_PROGRAM_ID, ata, self.wallets['mint'].pubkey(), self.wallets['payer'].pubkey(), amount_lamports))
        if self._confirm_and_send_transaction([ix], [self.wallets['payer']], f"{amount} Tokens verbrennen"):
            self.after(0, self.start_status_refresh)
        self.after(0, lambda: button.configure(state="normal"))

    def _execute_freeze_thaw_thread(self, action, ata_pubkey, button):
        payer_kp, mint_pk = self.wallets['payer'], self.wallets['mint'].pubkey()
        ix = freeze_account(FreezeAccountParams(TOKEN_PROGRAM_ID, ata_pubkey, mint_pk, payer_kp.pubkey())) if action == 'freeze' else thaw_account(ThawAccountParams(TOKEN_PROGRAM_ID, ata_pubkey, mint_pk, payer_kp.pubkey()))
        self._confirm_and_send_transaction([ix], [payer_kp], f"Aktion '{action}' für {truncate_address(str(ata_pubkey))}")
        self.after(0, lambda: button.configure(state="normal"))

    def _execute_transfer_thread(self, sender_kp, dest_pubkey, amount, button, transfer_type):
        instructions = []
        if transfer_type == "spl":
            amount_lamports = int(amount * (10**self.TOKEN_DECIMALS))
            source_ata = get_associated_token_address(sender_kp.pubkey(), self.wallets['mint'].pubkey())
            dest_ata = get_associated_token_address(dest_pubkey, self.wallets['mint'].pubkey())
            if self.http_client.get_account_info(dest_ata).value is None:
                self.log("→ Ziel-Token-Konto (ATA) existiert nicht, wird automatisch erstellt.", "info")
                instructions.append(create_associated_token_account(sender_kp.pubkey(), dest_pubkey, self.wallets['mint'].pubkey()))
            instructions.append(spl_transfer(SplTransferParams(TOKEN_PROGRAM_ID, source_ata, dest_ata, sender_kp.pubkey(), amount_lamports)))
            label = f"Überweise {amount} Tokens"
        else: # sol
            amount_lamports = int(amount * 10**9)
            instructions.append(system_transfer(SystemTransferParams(from_pubkey=sender_kp.pubkey(), to_pubkey=dest_pubkey, lamports=amount_lamports)))
            label = f"Überweise {amount} SOL"
        if self._confirm_and_send_transaction(instructions, [sender_kp], label):
            self.after(0, self.start_status_refresh)
        self.after(0, lambda: button.configure(state="normal"))

if __name__ == "__main__":
    try:
        app = SolanaTokenUI()
        if hasattr(app, 'http_client'): # Stellt sicher, dass die App überhaupt initialisiert wurde
            app.mainloop()
    except Exception as e:
        messagebox.showerror("Unerwarteter Fehler", f"Ein schwerwiegender Fehler ist aufgetreten:\n\n{e}")

