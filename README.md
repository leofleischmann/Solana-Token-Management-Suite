# Solana SPL Token Management Suite

Eine Sammlung von Python-Tools mit grafischer Benutzeroberfläche (GUI) zur einfachen Erstellung, Verwaltung und Überwachung von SPL-Tokens im Solana Devnet. Dieses Projekt ist ideal für Entwickler, die eine visuelle Schnittstelle für Token-Tests, Whitelist-Management und die Interaktion mit Token-Metadaten benötigen, ohne sich tief in die Kommandozeile einarbeiten zu müssen.

## Features

Dieses Projekt besteht aus drei Hauptkomponenten, die nahtlos zusammenarbeiten:

---

## 1. Das Setup-Tool (`setup.py`) im Detail

Das Herzstück für den Einstieg ist das `setup.py`-Skript. Es nimmt dem Benutzer die komplexe und fehleranfällige manuelle Einrichtung ab und erstellt automatisiert eine voll funktionsfähige Token-Umgebung.

### Funktionsweise der Benutzeroberfläche

Die GUI des Setup-Tools ist in drei logische Bereiche unterteilt, um die Konfiguration so intuitiv wie möglich zu gestalten:

#### 1. Wallet-Konfiguration

Hier werden alle für den Test notwendigen Wallets konfiguriert:
-   **Payer/Emittent**: Das Haupt-Wallet, das für Transaktionsgebühren (Gas) und als anfänglicher Besitzer der Token-Authorities dient.
-   **Token Mint**: Dies ist keine Wallet im herkömmlichen Sinne, sondern das Konto, das den Token selbst repräsentiert.
-   **Testnutzer**: Es können bis zu 10 Test-Wallets generiert werden, die mit DEV-SOL und dem neuen Token ausgestattet werden können.
-   **Vanity-Adressen**: Für eine bessere Wiedererkennung können für alle Wallet-Typen "Vanity-Adressen" generiert werden. Gibt man beispielsweise den Präfix `Leo` ein, sucht das Skript so lange nach einem Schlüsselpaar, bis die resultierende Wallet-Adresse mit `Leo...` beginnt. Dieser Prozess kann je nach Länge des Präfixes einige Zeit in Anspruch nehmen.

#### 2. Token-Konfiguration

In diesem Abschnitt werden die fundamentalen Eigenschaften des Tokens festgelegt:
-   **Initialer Token-Vorrat**: Die Menge an Tokens, die zu Beginn erstellt und dem Payer-Wallet gutgeschrieben wird.
-   **Dezimalstellen**: Definiert, in wie viele Nachkommastellen ein Token unterteilt werden kann (z.B. 9 für Standard-SPL-Tokens).
-   **Finanzierung für Testnutzer**: Ein optionaler SOL-Betrag, der vom Payer an jeden erstellten Testnutzer überwiesen wird, damit diese ebenfalls Transaktionen durchführen können.
-   **Widerrufen von Berechtigungen (Authorities)**:
    -   `Mint-Authority widerrufen`: Wenn diese Option gewählt wird, kann nach dem Setup niemand mehr neue Tokens erstellen. Dies ist eine **irreversible** Aktion.
    -   `Freeze-Authority widerrufen`: Wenn diese Option gewählt wird, kann niemand mehr Token-Konten einfrieren ("freezen"). Dies ist ebenfalls **irreversibel**.

#### 3. Token-Metadaten (Metaplex Standard)

Dieser erweiterte Abschnitt ermöglicht die Erstellung von On-Chain-Metadaten, damit der Token in Wallets und auf Explorern korrekt mit Namen, Symbol und Bild angezeigt wird.
-   **Voraussetzung**: Ein **Pinata JWT Token** ist erforderlich. Pinata ist ein IPFS-Dienst, der genutzt wird, um die Metadaten-Datei und das Token-Bild dezentral zu speichern.
-   **Eingabefelder**:
    -   `Token-Name & -Symbol`: z.B. "My Test Token" (MTT). Die Länge ist durch den Metaplex-Standard begrenzt.
    -   `Beschreibung`: Eine kurze Beschreibung des Tokens.
    -   `Token-Bild`: Es kann ein lokales Bild (PNG, JPG) ausgewählt werden, das auf IPFS hochgeladen wird.
    -   `Soziale Links & Tags`: Optionale Links (Website, Twitter etc.) und Tags, die in die Metadaten eingebettet werden.
-   **Update-Authority widerrufen**: Wenn diese Option aktiviert ist, werden die Metadaten nach der Erstellung permanent und können von niemandem mehr geändert werden. Dies ist **irreversibel**.

### Der automatisierte Setup-Prozess im Hintergrund

Sobald der Benutzer auf "Setup starten" klickt, führt das Skript die folgenden Schritte in einer exakten Reihenfolge aus:

1.  **Validierung**: Die Konfiguration wird auf Gültigkeit geprüft (z.B. Präfix-Länge, positive Zahlen).
2.  **Wallet-Generierung**: Alle konfigurierten Wallets werden erstellt. Falls Vanity-Präfixe gewählt wurden, läuft der "Grinding"-Prozess, bis passende Adressen gefunden sind.
3.  **Whitelist-Erstellung**: Eine `whitelist.txt`-Datei wird im Wallet-Ordner angelegt und mit den Adressen des Payers und der Testnutzer befüllt.
4.  **Payer-Finanzierung**: Das Skript prüft den Kontostand des Payer-Wallets und fordert bei Bedarf automatisch 2 DEV-SOL per Airdrop an.
5.  **Metadaten-Upload (optional)**: Wenn Metadaten konfiguriert wurden, wird zuerst das Bild und anschließend die finale JSON-Metadatendatei auf Pinata hochgeladen.
6.  **Blockchain-Transaktionen**: Das Skript sendet eine oder mehrere Transaktionen an das Solana Devnet, um:
    a. Das **Token-Mint-Konto** zu erstellen und zu initialisieren (mit Dezimalstellen und Authorities).
    b. Den **Metadaten-Account** zu erstellen und mit der URI der IPFS-Datei zu verknüpfen.
    c. **Assoziierte Token-Konten (ATAs)** für den Payer und alle Testnutzer anzulegen.
    d. **SOL an Testnutzer** zu überweisen (falls konfiguriert).
    e. Den **initialen Token-Vorrat** an das ATA des Payers zu "minten".
    f. Die **Authorities** zu widerrufen (falls konfiguriert).
7.  **Abschluss**: Nach erfolgreichem Abschluss werden alle Wallet-Dateien im konfigurierten Ordner gespeichert und ein Link zum Token im Solana-Explorer angezeigt.


![Setup-Tool Vorschau](https://github.com/leofleischmann/Solana-Token-Management-Suite/blob/f4e116df408867a4688febeaabdb81e83cfa6cb2/setup.png?raw=true)

---

### 2. Management-Tool (`app.py`)

Das Management-Tool ist die zentrale Steuerungseinheit, um mit dem erstellten Token und den Wallets zu interagieren.

-   **Dynamische Token-Daten**: Liest Token-Informationen wie Name, Symbol und Dezimalstellen direkt von der Blockchain, um immer aktuelle Daten anzuzeigen.
-   **Token- & SOL-Transfers**: Ermöglicht das einfache Senden von SOL und benutzerdefinierten SPL-Tokens zwischen den erstellten Wallets oder an externe Adressen.
-   **Versorgungs-Management**: Erhöhen (Mint) oder verringern (Burn) Sie den Gesamtvorrat Ihres Tokens.
-   **Kontoverwaltung**: Frieren (Freeze) und Tauen (Thaw) Sie Token-Konten direkt von der Benutzeroberfläche aus.
-   **Echtzeit-Übersicht**: Zeigt die SOL- und Token-Bilanzen aller Wallets an und aktualisiert diese in regelmäßigen Abständen automatisch.
-   **Token-2022 Unterstützung**: Bietet grundlegende Kompatibilität für Interaktionen mit dem neueren Token-2022-Programm.

![Management-Tool Hauptansicht](https://github.com/leofleischmann/Solana-Token-Management-Suite/blob/f4e116df408867a4688febeaabdb81e83cfa6cb2/app.png?raw=true)
![Management-Tool Aktionen](https://github.com/leofleischmann/Solana-Token-Management-Suite/blob/f4e116df408867a4688febeaabdb81e83cfa6cb2/app2.png?raw=true)

---

### 3. Whitelist-Monitor (`whitelist.py`)

Der Whitelist-Monitor ist ein leistungsstarkes Werkzeug zur Überwachung und Durchsetzung von Transferregeln in Echtzeit.

-   **Echtzeit-Überwachung**: Verbindet sich über WebSockets mit dem Solana-Cluster und überwacht Token-Transaktionen live.
-   **Whitelist-Validierung**: Prüft bei jeder erkannten Token-Transaktion, ob der Empfänger in der `whitelist.txt`-Datei aufgeführt ist.
-   **Automatische Sanktionen**: Friert bei einem Whitelist-Verstoß automatisch das Token-Konto des **Empfängers** ein, um weitere Transfers zu unterbinden.
-   **Optionale Sender-Sanktion**: Bietet die Möglichkeit, bei einem Verstoß zusätzlich das Token-Konto des **Senders** einzufrieren.
-   **Live-Dashboard**: Zeigt Statistiken wie die Anzahl der analysierten Transaktionen, erkannte Verstöße und ein Live-Aktivitätsprotokoll an.

![Whitelist-Monitor Vorschau](https://github.com/leofleischmann/Solana-Token-Management-Suite/blob/f4e116df408867a4688febeaabdb81e83cfa6cb2/whitelist.png?raw=true)

---

# Solana Advanced Traffic Generator

Ein Python-basiertes Kommandozeilen-Tool zur Erzeugung von komplexen und mehrstufigen SPL-Token-Transfers im Solana-Netzwerk. Das Tool dient dazu, Transaktionsmuster zu generieren, die die Nachverfolgbarkeit von Token-Bewegungen durch zufällige Operationen und die dynamische Erstellung von Wallets erschweren. Es ist primär für den Einsatz auf Devnet oder Testnet konzipiert.

## Kernfunktionalität und Modi

Das Tool operiert hauptsächlich durch die Simulation von Token-Transfers, wobei es zwischen zwei grundlegenden Modi unterscheidet:

### 1. Standard-Modus (Interner Netzwerkverkehr)

*   **Aktivierung:** Wird verwendet, wenn der Parameter `--outside` auf `0` gesetzt ist oder nicht explizit angegeben wird.
*   **Funktionsweise:**
    1.  **Wallet-Auswahl:** Wählt zufällig ein Sender-Wallet und ein Empfänger-Wallet aus einem vordefinierten Pool von Wallets. Diese initialen Wallets werden aus dem Ordner `devnet_wallets` geladen.
    2.  **Guthabenprüfung:** Überprüft, ob das Sender-Wallet über ausreichend SPL-Token-Guthaben für den Mindesttransfer verfügt.
    3.  **Betragsermittlung:** Bestimmt eine zufällige Menge an Tokens für den Transfer, die zwischen den über die Kommandozeilenparameter `--min` und `--max` definierten Grenzen liegt.
    4.  **SOL-Prüfung und -Finanzierung:** Überprüft das SOL-Guthaben des Sender-Wallets. Falls es für die Transaktionsgebühren (insbesondere wenn das Payer-Wallet nicht alle Gebühren übernimmt oder für ATA-Erstellung) zu niedrig ist, wird es vom Haupt-Payer-Wallet (`payer-wallet.json`) mit einer kleinen Menge SOL aufgeladen.
    5.  **ATA-Management:** Vor dem Transfer wird geprüft, ob das Empfänger-Wallet bereits ein Associated Token Account (ATA) für den betreffenden SPL-Token besitzt. Ist dies nicht der Fall, wird automatisch ein ATA für den Empfänger erstellt. Die Gebühr hierfür wird vom Sender-Wallet getragen (daher die SOL-Finanzierung).
    6.  **Token-Transfer:** Führt den SPL-Token-Transfer (`transfer_checked`) vom Sender-ATA zum Empfänger-ATA durch. Die Transaktionsgebühr wird vom Haupt-Payer-Wallet bezahlt.
    7.  **Logging:** Alle Aktionen, insbesondere die Transaktionssignaturen, werden protokolliert.
*   **Zweck:** Simuliert kontinuierliche, interne Handelsaktivität oder Bewegungen innerhalb eines bekannten Wallet-Netzwerks.

### 2. Outside-Modus (Mehrstufige Verschleierung und Netzwerkexpansion)

*   **Aktivierung:** Wird durch den Parameter `--outside N` aktiviert, wobei `N` die Anzahl der gewünschten "Hops" angibt.
*   **Funktionsweise:** Dieser Modus ist in mehrere Phasen unterteilt:

    *   **Phase 0: Zufällige Aktivität im bestehenden Handelsnetzwerk (optional)**
        *   Mit einer gewissen Wahrscheinlichkeit (aktuell 70% Chance, *keine* neue Kette zu starten, wenn ein Handelsnetzwerk existiert) führt das Tool zuerst einen Transfer im "Standard-Modus" durch, jedoch unter Verwendung der Wallets, die in früheren "Outside-Modus"-Durchläufen in der Verzweigungsphase erstellt wurden (gespeichert in `generic_transactions/generated_wallets/layer_N+1`). Dies simuliert Aktivität in den bereits etablierten, "verschleierten" Netzwerken.

    *   **Phase 1: Hop-Kette (Verschleierung)**
        1.  **Initialer Sender:** Wählt ein zufälliges Wallet aus dem initialen Pool (`devnet_wallets`) als Startpunkt.
        2.  **Betragsermittlung:** Bestimmt einen signifikanten Anteil (zufällig zwischen 50-90%) des Token-Guthabens des initialen Senders für die Hop-Kette.
        3.  **Iterative Hops:** Für jede der `N` Hops:
            *   Ein **neues temporäres Wallet** (`Keypair`) wird generiert und dessen Schlüsselmaterial in einem `layer_X`-Unterordner gespeichert (`X` ist die Hop-Nummer).
            *   Dieses neue Wallet wird vom Haupt-Payer-Wallet mit SOL aufgeladen, um zukünftige Transaktionsgebühren (für den nächsten Hop oder die ATA-Erstellung) zu decken.
            *   Der zuvor bestimmte Token-Betrag wird vom Wallet des vorherigen Hops an dieses neu erstellte Hop-Wallet transferiert. Dabei wird bei Bedarf ein ATA für das neue Hop-Wallet erstellt (bezahlt vom sendenden Hop-Wallet).
            *   Das neu erstellte Wallet wird zum Sender für den nächsten Hop.
        4.  **Ergebnis:** Nach `N` Hops befindet sich der Token-Betrag in einem Wallet, das `N` Schritte vom ursprünglichen Sender entfernt ist, wobei jeder Zwischenschritt über ein frisch erstelltes Wallet lief.

    *   **Phase 2: Verzweigung (Distribution & Netzwerkexpansion)**
        1.  **Verteiler-Wallet:** Das Wallet am Ende der Hop-Kette (`layer_N`) fungiert nun als "Verteiler"-Wallet.
        2.  **Netzwerkgröße:** Die Anzahl der neuen Wallets, auf die verteilt wird, wird entweder durch `--network-size` fest vorgegeben oder zufällig bestimmt (Standard: 2-4).
        3.  **SOL-Finanzierung des Verteilers:** Das Verteiler-Wallet wird vom Haupt-Payer-Wallet mit ausreichend SOL aufgeladen, um die Gebühren für die Erstellung der ATAs für alle neuen Zweig-Wallets zu decken.
        4.  **Token-Aufteilung:** Das gesamte Token-Guthaben des Verteiler-Wallets wird gleichmäßig auf die festgelegte Anzahl neuer Zweige aufgeteilt.
        5.  **Erstellung der Zweig-Wallets:** Für jeden Zweig:
            *   Ein **neues Wallet** (`Keypair`) wird erstellt und im Ordner `generic_transactions/generated_wallets/layer_N+1` gespeichert.
            *   Der anteilige Token-Betrag wird vom Verteiler-Wallet an dieses neue Zweig-Wallet transferiert. Dabei wird ein ATA für das Zweig-Wallet erstellt (bezahlt vom Verteiler-Wallet).
            *   Das neu erstellte Zweig-Wallet wird ebenfalls vom Haupt-Payer-Wallet mit einer kleinen Menge SOL für zukünftige Transaktionen ausgestattet.
            *   Diese neu erstellten Zweig-Wallets werden dem Pool `outside_network_wallets` hinzugefügt, um in zukünftigen Läufen für die "zufällige Aktivität" (Phase 0 des Outside-Modus) genutzt zu werden.

*   **Zweck:** Erzeugt komplexe Transaktionspfade, die schwerer zu verfolgen sind, und baut dynamisch neue kleine Netzwerke von Wallets auf, in denen weitere Aktivität simuliert werden kann.

## Technische Details und Hilfsfunktionen

*   **Wallet-Management (`load_keypair_from_path`, `create_and_save_keypair`, `load_all_keypairs`):**
    *   Kann Solana-Keypairs aus JSON-Dateien laden, die entweder im alten Format (Liste von Bytes) oder im neueren Base64-String-Format vorliegen.
    *   Generiert neue Keypairs und speichert sie als Base64-String des 64-Byte-Schlüssels in einer JSON-Datei, benannt nach dem Pubkey des Wallets.
    *   Verwaltet das Laden ganzer Wallet-Sammlungen aus Ordnern.

*   **Token-Operationen (`get_token_balance`, `send_token_transfer`):**
    *   `get_token_balance`: Ruft den SPL-Token-Kontostand eines Wallets ab. Implementiert eine Retry-Logik, falls das zugehörige Token-Konto (ATA) nicht sofort gefunden wird (z.B. aufgrund von RPC-Verzögerungen nach der Erstellung).
    *   `send_token_transfer`: Ist die Kernfunktion für SPL-Token-Überweisungen.
        *   Ermittelt die ATAs für Sender und Empfänger.
        *   Prüft, ob das ATA des Empfängers existiert. Falls nicht, wird eine `create_associated_token_account`-Instruktion zur Transaktion hinzugefügt. Die Gebühr für die ATA-Erstellung wird vom `sender` (nicht vom globalen `payer`) der `send_token_transfer`-Funktion getragen.
        *   Fügt die `transfer_checked`-Instruktion hinzu.
        *   Bündelt die Instruktionen, signiert die Transaktion mit dem Haupt-`payer` (für die Netzwerkgebühr) und dem `sender` (als Token-Owner und ggf. Payer der ATA-Erstellung) und sendet sie.
        *   Bestätigt die Transaktion und gibt die Signatur zurück.
        *   Enthält eine Retry-Logik für den Abruf der Kontoinformationen des Empfänger-ATAs.

*   **SOL-Finanzierung (`fund_with_sol`):**
    *   Überweist eine konfigurierbare Menge SOL vom Haupt-Payer-Wallet an ein Ziel-Wallet. Dies ist notwendig, damit neu erstellte Wallets Transaktionsgebühren bezahlen oder ATAs erstellen können.

*   **RPC-Kommunikation und Fehlerbehandlung:**
    *   Verwendet die `solana-py`-Bibliothek für die Interaktion mit einem Solana RPC-Knoten.
    *   Verwendet konsistent das Commitment-Level `"confirmed"` für das Senden von Transaktionen und das Abrufen von Zustandsdaten, um Konsistenz zu gewährleisten.
    *   Die Initialisierung des RPC-Clients ist für ältere Versionen von `solana-py` (z.B. 0.36.6) angepasst, die keine expliziten erweiterten Timeout-Konfigurationen im Konstruktor erlauben.
    *   Eine globale Schleife im `main`-Teil fängt allgemeine Fehler und spezifische `SolanaRpcException` ab, wartet eine gewisse Zeit und versucht dann, den Zyklus fortzusetzen.

*   **Logging (`setup_logger`, `TRANSACTION_LOG_FILE`):**
    *   Alle wichtigen Aktionen, erstellte Wallets, gesendete Transaktionen (mit Signaturen) und Fehler werden sowohl auf der Konsole ausgegeben als auch in die Datei `generic_transactions/sent_transactions.log` geschrieben.
    *   Neu erstellte Wallets werden in strukturierten Unterordnern unter `generic_transactions/generated_wallets/layer_X` gespeichert.

*   **Konfiguration (`config.json`, Kommandozeilenargumente):**
    *   Grundlegende Konfigurationen wie RPC-URL und der Pfad zum Ordner mit Payer-/Mint-Wallet erfolgen über `config.json`.
    *   Dynamische Parameter wie Verzögerungen, Transferbeträge und Modus-spezifische Einstellungen (Hops, Netzwerkgröße) werden über Kommandozeilenargumente gesteuert.

Dieses Tool bietet eine flexible Möglichkeit, verschiedene Szenarien von Token-Bewegungen auf der Solana-Blockchain zu simulieren und zu untersuchen.

![Management-Tool Hauptansicht](https://github.com/leofleischmann/Solana-Token-Management-Suite/blob/f4e116df408867a4688febeaabdb81e83cfa6cb2/network_graph.png?raw=true)

---

## Installation

Folgen Sie diesen Schritten, um das Projekt lokal einzurichten.

1.  **Repository klonen:**
    ```bash
    git clone https://github.com/leofleischmann/Solana-Token-Management-Suite.git
    cd Solana-Token-Management-Suite
    ```
   

2.  **Virtuelle Umgebung erstellen (Empfohlen):**
    ```bash
    # Für macOS/Linux
    python3 -m venv venv
    source venv/bin/activate

    # Für Windows
    python -m venv venv
    venv\Scripts\activate
    ```
   

3.  **Abhängigkeiten installieren:**
    Installieren Sie alle erforderlichen Pakete aus der `requirements.txt`-Datei.
    ```bash
    pip install -r requirements.txt
    ```
   

## Konfiguration

Die `config.json`-Datei enthält die grundlegende Konfiguration für das Projekt.

```json
{
  "rpc_url": "[https://api.devnet.solana.com](https://api.devnet.solana.com)",
  "wallet_folder": "devnet_wallets"
}
