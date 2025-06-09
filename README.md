# Solana SPL Token Management Suite

Eine Sammlung von Python-Tools mit grafischer Benutzeroberfläche (GUI) zur einfachen Erstellung, Verwaltung und Überwachung von SPL-Tokens im Solana Devnet. Dieses Projekt ist ideal für Entwickler, die eine visuelle Schnittstelle für Token-Tests und Whitelist-Management benötigen, ohne sich mit der Kommandozeile auseinandersetzen zu müssen.


## Features

Dieses Projekt besteht aus drei Hauptkomponenten:

#### 1. Setup-Tool (`setup.py`)
- **Geführte Umgebungserstellung**: Erstellt mit wenigen Klicks eine komplette Testumgebung.
- **Wallet-Generierung**: Erzeugt automatisch ein Payer/Issuer-Wallet, ein Token-Mint-Wallet und eine beliebige Anzahl von Testnutzer-Wallets.
- **Vanity-Adressen**: Unterstützt die Generierung von Adressen mit benutzerdefinierten Präfixen (z.B. `Wlt...`, `Mint...`) für alle Wallet-Typen.
- **Automatischer Airdrop**: Fordert automatisch DEV-SOL für das Payer-Wallet an, um die Transaktionsgebühren zu decken.
- **Token-Erstellung**: Initialisiert einen neuen SPL-Token mit Freeze-Authority.
- **Whitelist-Generierung**: Erstellt eine `whitelist.txt`-Datei, die alle generierten Wallets für den Monitor enthält.

#### 2. Management-Tool (`app.py`)
- **Token- & SOL-Transfers**: Senden Sie SOL und Ihre benutzerdefinierten SPL-Tokens einfach zwischen den erstellten Wallets.
- **Minting & Burning**: Erhöhen (Mint) oder verringern (Burn) Sie den Gesamtvorrat Ihres Tokens.
- **Kontoverwaltung**: Frieren (Freeze) und Tauen (Thaw) Sie Token-Konten direkt von der Benutzeroberfläche aus.
- **Echtzeit-Übersicht**: Zeigt die SOL- und Token-Bilanzen aller Wallets an und aktualisiert diese automatisch.

#### 3. Whitelist-Monitor (`whitelist.py`)
- **Echtzeit-Überwachung**: Verbindet sich über WebSockets mit dem Solana-Cluster und überwacht Token-Transaktionen live.
- **Whitelist-Validierung**: Prüft bei jeder Transaktion, ob der Empfänger in der `whitelist.txt`-Datei aufgeführt ist.
- **Automatische Sanktionen**: Friert bei einem Whitelist-Verstoß automatisch das Token-Konto des Empfängers ein. Optional kann auch das Konto des Senders eingefroren werden.
- **Live-Dashboard**: Zeigt Statistiken wie die Anzahl der analysierten Transaktionen, erkannte Verstöße und ein Live-Aktivitätsprotokoll an.

## Installation

1.  **Repository klonen:**
    ```bash
    git clone [https://github.com/leofleischmann/Solana-Token-Management-Suite.git](https://github.com/leofleischmann/Solana-Token-Management-Suite.git)
    cd <ins Verzeichnis>
    ```

2.  **Abhängigkeiten installieren:**
    Es wird empfohlen, eine virtuelle Umgebung zu verwenden.
    ```bash
    python -m venv venv
    source venv/bin/activate  # Auf Windows: venv\Scripts\activate
    ```
    Installieren Sie die erforderlichen Pakete aus der `requirements.txt`-Datei:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Konfiguration:**
    Die `config.json`-Datei ist bereits für das Solana Devnet vorkonfiguriert.
    ```json
    {
      "rpc_url": "[https://api.devnet.solana.com](https://api.devnet.solana.com)",
      "wallet_folder": "devnet_wallets"
    }
    ```
    Sie können den RPC-Endpunkt ändern, falls Sie einen eigenen verwenden möchten. Der `wallet_folder` gibt an, wo die Wallet-Schlüsseldateien gespeichert werden.

## Verwendung

Führen Sie die Skripte über die Kommandozeile aus. Stellen Sie sicher, dass Ihre virtuelle Umgebung aktiviert ist.

1.  **Umgebung einrichten:**
    Starten Sie zuerst das Setup-Tool, um Ihre Wallets und den Token zu erstellen.
    ```bash
    python setup.py
    ```
    Folgen Sie den Anweisungen in der grafischen Oberfläche.

2.  **Token verwalten:**
    Nach dem Setup können Sie das Management-Tool verwenden, um mit Ihrem Token zu interagieren.
    ```bash
    python app.py
    ```

3.  **Whitelist überwachen:**
    Starten Sie den Monitor, um Transaktionen zu überwachen und die Whitelist durchzusetzen.
    ```bash
    python whitelist.py
    ```

