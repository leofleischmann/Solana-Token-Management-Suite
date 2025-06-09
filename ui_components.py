# === ui_components.py: Gemeinsame UI-Komponenten und Design-System ===

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import threading
from typing import Callable, Optional, List, Dict, Any

# === Design-System ===

class DesignSystem:
    """Zentrales Design-System für konsistente UI-Gestaltung"""
    
    # Farben
    COLORS = {
        'primary': '#2563eb',      # Blau
        'primary_hover': '#1d4ed8',
        'secondary': '#64748b',    # Grau
        'success': '#10b981',      # Grün
        'warning': '#f59e0b',      # Orange
        'error': '#ef4444',        # Rot
        'info': '#3b82f6',         # Blau für Info
        'background': '#0f172a',   # Dunkelblau
        'surface': '#1e293b',      # Heller als Background
        'surface_hover': '#334155',
        'text_primary': '#f8fafc', # Weiß
        'text_secondary': '#cbd5e1', # Hellgrau
        'border': '#475569'        # Grau für Rahmen
    }
    
    # Schriftarten
    FONTS = {
        'heading_large': ('Segoe UI', 20, 'bold'),
        'heading_medium': ('Segoe UI', 16, 'bold'),
        'heading_small': ('Segoe UI', 14, 'bold'),
        'body': ('Segoe UI', 12, 'normal'),
        'body_small': ('Segoe UI', 10, 'normal'),
        'monospace': ('Consolas', 11, 'normal'),
        'monospace_small': ('Consolas', 9, 'normal')
    }
    
    # Abstände
    SPACING = {
        'xs': 4,
        'sm': 8,
        'md': 12,
        'lg': 16,
        'xl': 20,
        'xxl': 24
    }
    
    # Eckenradius
    RADIUS = {
        'sm': 6,
        'md': 8,
        'lg': 12,
        'xl': 16
    }
    
    # Icons (Unicode mit besserer Auswahl)
    ICONS = {
        'wallet': '💼',
        'sol': '◎',
        'token': '🪙',
        'send': '📤',
        'receive': '📥',
        'mint': '➕',
        'burn': '🔥',
        'freeze': '❄️',
        'thaw': '☀️',
        'copy': '📋',
        'transfer': '↔️',  # Hinzugefügtes Transfer-Icon
        'execute': '▶️',
        'refresh': '🔄',
        'start': '▶️',
        'stop': '⏹️',
        'settings': '⚙️',
        'info': 'ℹ️',
        'warning': '⚠️',
        'error': '❌',
        'success': '✅',
        'loading': '⏳',
        'edit': '✏️',
        'delete': '🗑️',
        'save': '💾',
        'search': '🔍',
        'filter': '🔽',
        'expand': '📂',
        'collapse': '📁'
    }

# === Erweiterte UI-Komponenten ===

class StatusIndicator(ctk.CTkFrame):
    """Farbiger Status-Indikator mit Text"""
    
    def __init__(self, parent, status: str = "unknown", text: str = "", **kwargs):
        super().__init__(parent, **kwargs)
        
        self.grid_columnconfigure(1, weight=1)
        
        # Status-Punkt
        self.status_label = ctk.CTkLabel(self, text="●", width=20)
        self.status_label.grid(row=0, column=0, padx=(8, 4), pady=8)
        
        # Status-Text
        self.text_label = ctk.CTkLabel(self, text=text, anchor="w")
        self.text_label.grid(row=0, column=1, padx=(0, 8), pady=8, sticky="ew")
        
        self.set_status(status)
    
    def set_status(self, status: str, text: str = None):
        """Setzt den Status und optional den Text"""
        colors = {
            'success': DesignSystem.COLORS['success'],
            'warning': DesignSystem.COLORS['warning'],
            'error': DesignSystem.COLORS['error'],
            'info': DesignSystem.COLORS['primary'],
            'unknown': DesignSystem.COLORS['secondary']
        }
        
        color = colors.get(status, colors['unknown'])
        self.status_label.configure(text_color=color)
        
        if text is not None:
            self.text_label.configure(text=text)

class CopyableLabel(ctk.CTkFrame):
    """Label mit Copy-to-Clipboard Funktionalität"""
    
    def __init__(self, parent, text: str = "", max_length: int = 40, **kwargs):
        super().__init__(parent, **kwargs)
        
        self.full_text = text
        self.max_length = max_length
        
        self.grid_columnconfigure(0, weight=1)
        
        # Text-Label
        display_text = self._truncate_text(text)
        self.text_label = ctk.CTkLabel(
            self, 
            text=display_text, 
            font=ctk.CTkFont(family="monospace", size=10),
            anchor="w"
        )
        self.text_label.grid(row=0, column=0, padx=8, pady=4, sticky="ew")
        
        # Copy-Button
        self.copy_button = ctk.CTkButton(
            self,
            text=DesignSystem.ICONS['copy'],
            width=30,
            height=24,
            command=self._copy_to_clipboard,
            font=ctk.CTkFont(size=12)
        )
        self.copy_button.grid(row=0, column=1, padx=(4, 8), pady=4)
        
        # Tooltip-Funktionalität
        self._create_tooltip()
    
    def _truncate_text(self, text: str) -> str:
        """Kürzt Text wenn zu lang"""
        if len(text) <= self.max_length:
            return text
        return f"{text[:self.max_length//2]}...{text[-self.max_length//2:]}"
    
    def _copy_to_clipboard(self):
        """Kopiert den vollständigen Text in die Zwischenablage"""
        self.clipboard_clear()
        self.clipboard_append(self.full_text)
        
        # Visuelles Feedback
        original_text = self.copy_button.cget("text")
        self.copy_button.configure(text="✓", fg_color=DesignSystem.COLORS['success'])
        self.after(1000, lambda: self.copy_button.configure(
            text=original_text, 
            fg_color=("gray75", "gray25")
        ))
    
    def _create_tooltip(self):
        """Erstellt Tooltip mit vollständigem Text"""
        def on_enter(event):
            if len(self.full_text) > self.max_length:
                # Hier könnte ein echtes Tooltip-Widget implementiert werden
                pass
        
        def on_leave(event):
            pass
        
        self.text_label.bind("<Enter>", on_enter)
        self.text_label.bind("<Leave>", on_leave)
    
    def set_text(self, text: str):
        """Aktualisiert den Text"""
        self.full_text = text
        display_text = self._truncate_text(text)
        self.text_label.configure(text=display_text)

class ProgressDialog(ctk.CTkToplevel):
    """Modaler Dialog mit Fortschrittsanzeige"""
    
    def __init__(self, parent, title: str = "Verarbeitung...", **kwargs):
        super().__init__(parent, **kwargs)
        
        self.title(title)
        self.geometry("400x150")
        self.resizable(False, False)
        
        # Zentrieren
        self.transient(parent)
        self.grab_set()
        
        # Layout
        self.grid_columnconfigure(0, weight=1)
        
        # Titel
        self.title_label = ctk.CTkLabel(
            self, 
            text=title, 
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.title_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        # Status-Text
        self.status_label = ctk.CTkLabel(self, text="Initialisierung...")
        self.status_label.grid(row=1, column=0, padx=20, pady=5)
        
        # Fortschrittsbalken
        self.progress_bar = ctk.CTkProgressBar(self, width=300)
        self.progress_bar.grid(row=2, column=0, padx=20, pady=10)
        self.progress_bar.set(0)
        
        # Abbrechen-Button
        self.cancel_button = ctk.CTkButton(
            self, 
            text="Abbrechen", 
            command=self._on_cancel,
            fg_color=DesignSystem.COLORS['error']
        )
        self.cancel_button.grid(row=3, column=0, padx=20, pady=(0, 20))
        
        self.cancelled = False
        self.cancel_callback = None
    
    def set_progress(self, value: float, status: str = None):
        """Setzt Fortschritt (0.0 - 1.0) und optional Status-Text"""
        self.progress_bar.set(value)
        if status:
            self.status_label.configure(text=status)
    
    def set_cancel_callback(self, callback: Callable):
        """Setzt Callback für Abbrechen-Button"""
        self.cancel_callback = callback
    
    def _on_cancel(self):
        """Behandelt Abbrechen-Button"""
        self.cancelled = True
        if self.cancel_callback:
            self.cancel_callback()
        self.destroy()
    
    def close(self):
        """Schließt den Dialog"""
        self.destroy()

class ConfirmDialog(ctk.CTkToplevel):
    """Bestätigungsdialog mit anpassbaren Optionen"""
    
    def __init__(self, parent, title: str, message: str, 
                 confirm_text: str = "Bestätigen", 
                 cancel_text: str = "Abbrechen",
                 danger: bool = False, **kwargs):
        super().__init__(parent, **kwargs)
        
        self.result = None
        
        self.title(title)
        self.geometry("400x200")
        self.resizable(False, False)
        
        # Zentrieren
        self.transient(parent)
        self.grab_set()
        
        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        # Titel
        title_label = ctk.CTkLabel(
            self, 
            text=title, 
            font=ctk.CTkFont(size=16, weight="bold")
        )
        title_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        # Nachricht
        message_label = ctk.CTkLabel(
            self, 
            text=message, 
            wraplength=350,
            justify="center"
        )
        message_label.grid(row=1, column=0, padx=20, pady=10)
        
        # Button-Frame
        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=2, column=0, padx=20, pady=(0, 20))
        
        # Buttons
        cancel_button = ctk.CTkButton(
            button_frame,
            text=cancel_text,
            command=self._on_cancel,
            fg_color=DesignSystem.COLORS['secondary']
        )
        cancel_button.pack(side="left", padx=(0, 10))
        
        confirm_color = DesignSystem.COLORS['error'] if danger else DesignSystem.COLORS['primary']
        confirm_button = ctk.CTkButton(
            button_frame,
            text=confirm_text,
            command=self._on_confirm,
            fg_color=confirm_color
        )
        confirm_button.pack(side="left")
        
        # Enter/Escape Bindings
        self.bind("<Return>", lambda e: self._on_confirm())
        self.bind("<Escape>", lambda e: self._on_cancel())
        
        # Focus
        confirm_button.focus()
    
    def _on_confirm(self):
        self.result = True
        self.destroy()
    
    def _on_cancel(self):
        self.result = False
        self.destroy()
    
    @staticmethod
    def show(parent, title: str, message: str, **kwargs) -> bool:
        """Zeigt Dialog und gibt Ergebnis zurück"""
        dialog = ConfirmDialog(parent, title, message, **kwargs)
        parent.wait_window(dialog)
        return dialog.result or False

class EnhancedTextbox(ctk.CTkFrame):
    """Erweiterte Textbox mit Suche und Filterung"""
    
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        # Toolbar
        toolbar = ctk.CTkFrame(self)
        toolbar.grid(row=0, column=0, sticky="ew", padx=5, pady=(5, 0))
        toolbar.grid_columnconfigure(1, weight=1)
        
        # Such-Entry
        self.search_entry = ctk.CTkEntry(
            toolbar, 
            placeholder_text="Suchen...",
            width=200
        )
        self.search_entry.grid(row=0, column=0, padx=5, pady=5)
        self.search_entry.bind("<KeyRelease>", self._on_search)
        
        # Filter-Dropdown
        self.filter_var = tk.StringVar(value="Alle")
        self.filter_dropdown = ctk.CTkOptionMenu(
            toolbar,
            variable=self.filter_var,
            values=["Alle", "Info", "Warnung", "Fehler", "Erfolg"],
            command=self._on_filter_change,
            width=100
        )
        self.filter_dropdown.grid(row=0, column=2, padx=5, pady=5)
        
        # Clear-Button
        clear_button = ctk.CTkButton(
            toolbar,
            text=DesignSystem.ICONS['delete'],
            width=30,
            command=self._clear_text
        )
        clear_button.grid(row=0, column=3, padx=5, pady=5)
        
        # Textbox
        self.textbox = ctk.CTkTextbox(
            self,
            state="disabled",
            wrap="word",
            font=ctk.CTkFont(family="monospace", size=10)
        )
        self.textbox.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        
        # Tags für Farben
        self.textbox.tag_config("info", foreground=DesignSystem.COLORS['primary'])
        self.textbox.tag_config("warning", foreground=DesignSystem.COLORS['warning'])
        self.textbox.tag_config("error", foreground=DesignSystem.COLORS['error'])
        self.textbox.tag_config("success", foreground=DesignSystem.COLORS['success'])
        self.textbox.tag_config("highlight", background=DesignSystem.COLORS['warning'])
        
        self.all_lines = []  # Speichert alle Zeilen für Filterung
    
    def append_text(self, text: str, tag: str = None):
        """Fügt Text mit optionalem Tag hinzu"""
        self.all_lines.append((text, tag))
        self._update_display()
    
    def clear_text(self):
        """Löscht allen Text"""
        self.all_lines.clear()
        self._update_display()
    
    def _clear_text(self):
        """Button-Handler für Clear"""
        self.clear_text()
    
    def _update_display(self):
        """Aktualisiert die Anzeige basierend auf Filter und Suche"""
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        
        search_term = self.search_entry.get().lower()
        filter_type = self.filter_var.get()
        
        for text, tag in self.all_lines:
            # Filter anwenden
            if filter_type != "Alle":
                if tag and tag.lower() != filter_type.lower():
                    continue
            
            # Suche anwenden
            if search_term and search_term not in text.lower():
                continue
            
            # Text einfügen
            start_pos = self.textbox.index("end-1c")
            self.textbox.insert("end", f"{text}\n")
            
            # Tag anwenden
            if tag:
                end_pos = self.textbox.index("end-1c")
                self.textbox.tag_add(tag, start_pos, end_pos)
            
            # Suche hervorheben
            if search_term:
                self._highlight_search_term(text, search_term, start_pos)
        
        self.textbox.configure(state="disabled")
        self.textbox.see("end")
    
    def _highlight_search_term(self, text: str, search_term: str, start_pos: str):
        """Hebt Suchbegriffe hervor"""
        text_lower = text.lower()
        search_lower = search_term.lower()
        
        start = 0
        while True:
            pos = text_lower.find(search_lower, start)
            if pos == -1:
                break
            
            # Berechne Position im Text-Widget
            line_num = int(start_pos.split('.')[0])
            char_start = pos
            char_end = pos + len(search_term)
            
            start_index = f"{line_num}.{char_start}"
            end_index = f"{line_num}.{char_end}"
            
            self.textbox.tag_add("highlight", start_index, end_index)
            start = pos + 1
    
    def _on_search(self, event=None):
        """Handler für Suche"""
        self._update_display()
    
    def _on_filter_change(self, value):
        """Handler für Filter-Änderung"""
        self._update_display()

# === Utility-Funktionen ===

def show_error(parent, title: str, message: str):
    """Zeigt eine benutzerfreundliche Fehlermeldung"""
    messagebox.showerror(title, message, parent=parent)

def show_info(parent, title: str, message: str):
    """Zeigt eine Informationsmeldung"""
    messagebox.showinfo(title, message, parent=parent)

def show_warning(parent, title: str, message: str):
    """Zeigt eine Warnmeldung"""
    messagebox.showwarning(title, message, parent=parent)

def run_in_thread(func: Callable, *args, **kwargs):
    """Führt Funktion in separatem Thread aus"""
    thread = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
    thread.start()
    return thread

def format_sol_amount(lamports: int) -> str:
    """Formatiert SOL-Betrag benutzerfreundlich"""
    sol = lamports / 10**9
    return f"{sol:,.6f}".replace(",", " ").replace(".", ",")

def format_token_amount(amount: float, decimals: int = 9) -> str:
    """Formatiert Token-Betrag benutzerfreundlich"""
    return f"{amount:,.{decimals}f}".replace(",", " ").replace(".", ",")

def truncate_address(address: str, start_chars: int = 8, end_chars: int = 8) -> str:
    """Kürzt Blockchain-Adressen für bessere Lesbarkeit"""
    if len(address) <= start_chars + end_chars + 3:
        return address
    return f"{address[:start_chars]}...{address[-end_chars:]}"

