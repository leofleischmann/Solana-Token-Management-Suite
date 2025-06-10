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
