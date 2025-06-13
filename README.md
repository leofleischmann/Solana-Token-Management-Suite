# Solana SPL Token Management Suite - Detaillierte technische Beschreibung

Diese Dokumentation bietet eine tiefgehende Beschreibung der "Solana SPL Token Management Suite", einer Sammlung von Python-Tools, die entwickelt wurden, um die Erstellung, Verwaltung, Überwachung und Analyse von SPL-Tokens im Solana Devnet/Testnet zu vereinfachen und zu automatisieren. Sie richtet sich an Entwickler und technisch versierte Nutzer, die ein detailliertes Verständnis der Funktionsweise der einzelnen Komponenten wünschen.

## Inhaltsverzeichnis

1.  [Überblick und Architektur](#überblick-und-architektur)
2.  [Setup-Tool (`setup.py`): Vollautomatische Umgebungsinitialisierung](#1-das-setup-tool-setuppy-im-detail-vollautomatische-umgebungsinitialisierung)
    *   [GUI-Komponenten und Konfigurationsmöglichkeiten](#gui-komponenten-und-konfigurationsmöglichkeiten)
    *   [Interner Ablauf des Setup-Prozesses](#interner-ablauf-des-setup-prozesses)
    *   [Technische Details der Wallet- und Token-Erstellung](#technische-details-der-wallet--und-token-erstellung)
3.  [Management-Tool (`app.py`): Interaktive Token-Verwaltung](#2-management-tool-apppy-im-detail-interaktive-token-verwaltung)
    *   [GUI-Layout und Hauptfunktionen](#gui-layout-und-hauptfunktionen)
    *   [Dynamische Datenabfrage und Status-Updates](#dynamische-datenabfrage-und-status-updates)
    *   [Implementierung der Token-Operationen](#implementierung-der-token-operationen)
4.  [Periodisches Analyse-Tool (`analyse.py`): Tiefgehende Transaktionsüberwachung](#3-periodisches-analyse-tool-analysepy-im-detail-tiefgehende-transaktionsüberwachung)
    *   [Kernarchitektur und Datenflüsse](#kernarchitektur-und-datenflüsse-analyse)
    *   [Algorithmus zur lückenlosen Kettenerfassung und Signaturverfolgung](#algorithmus-zur-lückenlosen-kettenerfassung-und-signaturverfolgung)
    *   [Analyse von Token-Transfers und Saldenänderungen](#analyse-von-token-transfers-und-saldenänderungen)
    *   [Whitelist-, Greylist- und Sanktionsmechanismen](#whitelist--greylist--und-sanktionsmechanismen)
    *   [Netzwerk-Visualisierung und Validierungslogik](#netzwerk-visualisierung-und-validierungslogik)
5.  [Traffic Generator (`traffic_generator.py`): Simulation komplexer Transaktionsmuster](#4-traffic-generator-traffic_generatorpy-im-detail-simulation-komplexer-transaktionsmuster)
    *   [Modi: Standard-Modus und Outside-Modus](#modi-standard-modus-und-outside-modus)
    *   [Generierung von Hop-Ketten und Verzweigungsnetzwerken](#generierung-von-hop-ketten-und-verzweigungsnetzwerken)
    *   [Technische Implementierung der Transaktionsgenerierung](#technische-implementierung-der-transaktionsgenerierung)
6.  [Echtzeit Whitelist-Monitor (`whitelist.py`): WebSocket-basierte Überwachung (Vorgänger)](#5-echtzeit-whitelist-monitor-whitelistpy---kurzbeschreibung-vorgänger)
7.  [Gemeinsame Komponenten und Hilfsfunktionen](#gemeinsame-komponenten-und-hilfsfunktionen)
    *   [Konfigurationsmanagement (`config.json`)](#konfigurationsmanagement-configjson)
    *   [Wallet-Verwaltung (Keypair-Handling)](#wallet-verwaltung-keypair-handling)
    *   [RPC-Kommunikation und Fehlerbehandlung](#rpc-kommunikation-und-fehlerbehandlung)
    *   [Logging-Strategie](#logging-strategie)
8.  [Installation und Einrichtung](#installation-und-einrichtung)
9.  [Verwendungsempfehlungen und Anwendungsfälle](#verwendungsempfehlungen-und-anwendungsfälle)

---

## Überblick und Architektur

Die Suite ist modular aufgebaut, wobei jede Python-Datei (`setup.py`, `app.py`, `analyse.py`, `traffic_generator.py`, `whitelist.py`) eine spezifische Funktionalität bereitstellt. Eine zentrale `config.json` dient zur Speicherung von Basiskonfigurationen wie RPC-Endpunkt und Wallet-Speicherort. Die Tools nutzen die `solana-py`, `solders` und `spl-token` Bibliotheken für die Blockchain-Interaktion. GUIs werden mit `customtkinter` erstellt, während `pyvis` für Netzwerkdiagramme in `analyse.py` verwendet wird.

Die Tools sind so konzipiert, dass sie sequenziell oder unabhängig voneinander verwendet werden können:
1.  `setup.py` initialisiert die Umgebung.
2.  `app.py` ermöglicht die manuelle Interaktion mit der erstellten Umgebung.
3.  `analyse.py` oder `whitelist.py` überwachen Transaktionen.
4.  `traffic_generator.py` erzeugt Testdaten/Aktivität.

---

## 1. Das Setup-Tool (`setup.py`) im Detail: Vollautomatische Umgebungsinitialisierung

`setup.py` dient als initialer Konfigurator und Ersteller einer vollständigen SPL-Token-Testumgebung auf dem Solana Devnet. Es reduziert den manuellen Aufwand erheblich und stellt sicher, dass alle Komponenten korrekt initialisiert werden.

### GUI-Komponenten und Konfigurationsmöglichkeiten

Die grafische Benutzeroberfläche ist in thematische Abschnitte unterteilt, die eine granulare Konfiguration ermöglichen:

#### 1. Wallet-Konfiguration (`_create_wallet_config_section`)
   - **Payer/Emittent (`payer_kp`):**
     - Funktion: Dieses Wallet dient als primärer Zahler von Transaktionsgebühren (SOL), finanziert andere Wallets und ist initialer Inhaber der Mint- und Freeze-Authorities des Tokens.
     - Vanity-Option (`payer_vanity_check`, `payer_prefix_entry`): Ermöglicht die Generierung einer Adresse mit einem benutzerdefinierten Präfix (z.B. `Leo...`). Die Generierung erfolgt durch iteratives Erstellen von Keypairs, bis die Pubkey-Bedingung erfüllt ist (`_grind_keypair_ui`).
   - **Token Mint (`mint_kp`):**
     - Funktion: Repräsentiert nicht ein Wallet mit Guthaben, sondern das Mint-Konto des SPL-Tokens selbst. Es speichert token-spezifische Daten wie Dezimalstellen und Authorities.
     - Vanity-Option (`mint_vanity_check`, `mint_prefix_entry`): Analog zum Payer.
   - **Testnutzer (`test_users`):**
     - Anzahl (`test_user_slider`, `test_user_label`): Ermöglicht die Generierung von 0 bis 10 Test-Wallets.
     - Vanity-Option (`test_user_vanity_check`, `test_user_prefix_entry`): Generiert Testnutzer-Adressen mit einem gemeinsamen Präfix, gefolgt von einer Nummer (z.B. `Test1...`, `Test2...`).
     - Funktion: Diese Wallets dienen dazu, Token-Transfers und Interaktionen aus der Perspektive normaler Nutzer zu simulieren.

#### 2. Token-Konfiguration (`_create_token_config_section`)
   - **Initialer Token-Vorrat (`initial_mint_entry`):**
     - Funktion: Die Menge an Tokens, die bei der Initialisierung erstellt und dem Associated Token Account (ATA) des Payer-Wallets gutgeschrieben wird.
     - Format: Fließkommazahl, wird intern unter Berücksichtigung der Dezimalstellen in Lamports umgerechnet.
   - **Dezimalstellen (`token_decimals_entry`):**
     - Funktion: Bestimmt die kleinste Einheit des Tokens (z.B. 9 Dezimalstellen bedeutet, der Token kann bis auf 0.000000001 Einheiten unterteilt werden). Üblich für SPL-Tokens sind 6 oder 9.
   - **Finanzierung für Testnutzer (`sol_for_users_entry`):**
     - Funktion: Gibt an, wie viel SOL (Devnet SOL) vom Payer-Wallet an jedes erstellte Testnutzer-Wallet überwiesen wird, um deren Transaktionsfähigkeit sicherzustellen.
   - **Widerrufen von Berechtigungen (Authorities):**
     - `Mint-Authority widerrufen` (`revoke_mint_check`): Wenn aktiviert, wird nach dem initialen Mint die Berechtigung, weitere Tokens zu erstellen, permanent vom Payer-Wallet (oder wer auch immer die Mint-Authority hält) entfernt. Dies wird durch eine `SetAuthority` Instruktion mit `new_authority=None` für den `AuthorityType.MINT_TOKENS` erreicht. Dies bedeutet, dass die Gesamtmenge des Tokens **endgültig festgelegt** ist und keine neuen Einheiten mehr geschaffen werden können. Dies ist eine wichtige Maßnahme, um Vertrauen bei potenziellen Nutzern zu schaffen, da es eine unkontrollierte Inflation verhindert. **Diese Aktion ist irreversibel.**
     - `Freeze-Authority widerrufen` (`revoke_freeze_check`): Wenn aktiviert, wird die Berechtigung, Token-Konten dieses Mints einzufrieren, permanent entfernt. Implementierung analog via `SetAuthority` für `AuthorityType.FREEZE_ACCOUNT`. Dies bedeutet, dass kein Konto mehr daran gehindert werden kann, Tokens zu senden oder zu empfangen (sofern es nicht durch andere Mechanismen, z.B. Token-2022 Erweiterungen, eingeschränkt ist). Dies ist oft wünschenswert für dezentrale Tokens, bei denen keine zentrale Instanz die Kontrolle über einzelne Konten haben soll. **Diese Aktion ist irreversibel.**

#### 3. Token-Metadaten (Metaplex Standard) (`_create_metadata_config_section`)
   - **Aktivierung (`metadata_check`, `_toggle_metadata`):** Schaltet die gesamte Sektion und die Erstellung von On-Chain-Metadaten ein/aus.
   - **Voraussetzung Pinata JWT (`pinata_jwt_entry`):**
     - Funktion: Ein JSON Web Token von Pinata (ein IPFS Pinning Service) ist erforderlich, um das Token-Bild und die JSON-Metadatendatei dezentral auf IPFS zu speichern. Die resultierenden IPFS-URIs werden in den On-Chain-Metadaten verlinkt. Die JWT wird aus `config.json` gelesen und kann in der UI überschrieben werden.
   - **Eingabefelder für Metadaten:**
     - `Token-Name` (`token_name_entry`): Der volle Name des Tokens (max. 32 Bytes UTF-8).
     - `Token-Symbol` (`token_symbol_entry`): Das Tickersymbol des Tokens (max. 10 Bytes UTF-8).
     - `Beschreibung` (`token_description_entry`): Eine optionale Beschreibung (max. 200 Bytes UTF-8).
     - `Token-Bild` (`select_image_button`, `selected_image_label`, `_select_token_image`): Auswahl einer lokalen Bilddatei (PNG, JPG, GIF; max 100KB, empfohlene Dimensionen 512x512 oder 1024x1024).
     - `Soziale Links` (`token_website_entry`, etc.): Optionale URLs zu Webseite, Twitter, Telegram, Discord.
     - `Tags` (`token_tags_entry`, `_on_tags_change`): Bis zu 5 kommagetrennte Schlagwörter.
   - **Update-Authority widerrufen (`revoke_update_authority_check`):**
     - Funktion: Wenn aktiviert, wird die `isMutable`-Eigenschaft der On-Chain-Metadaten auf `false` gesetzt. Dies stellt sicher, dass die einmal festgelegten Informationen wie Name, Symbol und Bild nicht mehr manipuliert werden können, was die Authentizität und Verlässlichkeit des Tokens erhöht. **Diese Aktion ist irreversibel.**

### Interner Ablauf des Setup-Prozesses (`_setup_worker_thread`)

Der Setup-Prozess wird in einem separaten Thread ausgeführt, um die GUI nicht zu blockieren. Er folgt einer strikten Reihenfolge:

1.  **Validierung (`setup_config.validate()`):** Die in der GUI eingegebenen Konfigurationsparameter werden auf Plausibilität und Format geprüft (z.B. Längenbeschränkungen für Namen/Symbole, positive Zahlenwerte).
2.  **Wallet-Generierung (`_setup_step_wallets`, `_create_wallet_ui_driven`, `_grind_keypair_ui`):**
    - Payer, Mint und Testnutzer-Keypairs werden entweder zufällig oder durch "Grinding" (iterative Suche nach einem passenden Präfix) erstellt.
    - Jedes Keypair wird als JSON-Datei (Liste von Bytes) und als Hex-String in einer `.txt`-Datei im konfigurierten `wallet_folder` gespeichert.
3.  **Whitelist-Erstellung (`_setup_step_whitelist`):**
    - Eine `whitelist.txt` wird im `wallet_folder` angelegt.
    - Die Pubkeys des Payer-Wallets und aller erstellten Testnutzer-Wallets werden in diese Datei geschrieben. Diese Datei dient als Eingabe für die Monitoring-Tools (`analyse.py`, `whitelist.py`).
4.  **Payer-Finanzierung (`_setup_step_funding`, `_fund_payer_wallet`):**
    - Der SOL-Kontostand des Payer-Wallets wird geprüft.
    - Ist der Kontostand unter einem Schwellenwert (0.5 SOL), wird versucht, 2 DEV-SOL per `request_airdrop` anzufordern.
    - Bei Fehlschlag des Airdrops wird der Nutzer aufgefordert, manuell SOL an die Payer-Adresse zu senden, und das Skript wartet auf die Einzahlung.
5.  **Metadaten-Upload (optional) (`_setup_step_metadata`):**
    - Wenn `create_metadata` aktiviert ist:
        a.  Das ausgewählte Token-Bild wird via `_upload_file_to_pinata` zu Pinata/IPFS hochgeladen. Falls kein Bild gewählt oder der Upload fehlschlägt, wird eine Standard-Platzhalter-URI verwendet.
        b.  Eine JSON-Datei wird dynamisch mit Token-Name, Symbol, Beschreibung, der Bild-URI, sozialen Links und Tags erstellt.
        c.  Diese JSON-Datei wird via `_upload_json_to_pinata` zu Pinata/IPFS hochgeladen. Die URI dieser JSON-Datei ist die `token_uri` für die On-Chain-Metadaten.
6.  **Blockchain-Transaktionen (Kern-Setup):** Das Skript sendet eine oder mehrere Transaktionen und wartet auf deren Bestätigung, was je nach Netzwerkauslastung variieren kann.
    a.  **Token-Mint erstellen (`_setup_step_mint`):**
        - Eine Transaktion mit zwei Instruktionen wird gesendet:
            1.  `create_account` (System Program): Erstellt ein neues Konto mit der Adresse des `mint_kp`, finanziert es mit der minimalen rent-exempt Balance für 82 Bytes (Größe eines Mint-Kontos) und setzt den `TOKEN_PROGRAM_ID` als Owner.
            2.  `initialize_mint` (SPL Token Program): Initialisiert das neu erstellte Konto als Token-Mint mit den konfigurierten Dezimalstellen, der Mint-Authority (Payer-Wallet) und der Freeze-Authority (Payer-Wallet).
    b.  **Token-Metadaten On-Chain erstellen (optional) (`_create_metadata_instruction_manually` in `_setup_step_metadata`):**
        - Wenn Metadaten erstellt werden, wird eine komplexe Instruktion manuell mit `borsh_construct` serialisiert und an das Metaplex Token Metadata Program gesendet.
        - Diese Instruktion (`CreateMetadataAccountV3`) erstellt einen Program Derived Address (PDA) Account, der die Metadaten (Name, Symbol, URI, Creators, `isMutable`-Status etc.) speichert.
        - Die Signierer sind der Payer (als Gebührenzahler und Update-Authority).
    c.  **Associated Token Accounts (ATAs) erstellen & Nutzer finanzieren (`_setup_step_token_accounts`):**
        - Eine Transaktion wird erstellt, die für das Payer-Wallet und jedes Testnutzer-Wallet eine `create_associated_token_account`-Instruktion enthält. Diese erstellt die notwendigen Konten, um den spezifischen SPL-Token zu halten.
        - Wenn `sol_for_users > 0`, werden zusätzlich `system_transfer`-Instruktionen hinzugefügt, um SOL vom Payer an jeden Testnutzer zu senden.
    d.  **Initialen Token-Vorrat minten (`_setup_step_initial_mint`):**
        - Eine `mint_to`-Instruktion wird gesendet, um die konfigurierte `initial_mint_amount` an Tokens (umgerechnet unter Berücksichtigung der Dezimalstellen) an das ATA des Payer-Wallets zu minten. Die Mint-Authority (Payer) signiert.
    e.  **Authorities widerrufen (optional) (`_setup_step_revoke_authorities`):**
        - Wenn `revoke_mint_authority` aktiviert ist, wird eine `set_authority`-Instruktion gesendet, um die Mint-Authority auf `None` zu setzen.
        - Wenn `revoke_freeze_authority` aktiviert ist, wird eine `set_authority`-Instruktion gesendet, um die Freeze-Authority auf `None` zu setzen.
        - Wenn Metadaten erstellt wurden und `revoke_update_authority` aktiviert ist, wurde dies bereits durch `isMutable=False` in der Metadaten-Instruktion gehandhabt (die Update-Authority der Metadaten wird auf eine nicht-signierbare PDA gesetzt).
7.  **Abschluss (`_setup_completed`):**
    - Alle Wallet-Dateien sind im `wallet_folder` gespeichert.
    - Eine Erfolgsmeldung wird angezeigt, inklusive eines direkten Links zur Mint-Adresse im Solana Explorer (Devnet).

![Setup-Tool Vorschau](https://github.com/leofleischmann/Solana-Token-Management-Suite/blob/f4e116df408867a4688febeaabdb81e83cfa6cb2/setup.png?raw=true)

### Technische Details der Wallet- und Token-Erstellung
-   **Keypair-Generierung**: Standard Ed25519 Schlüsselpaare mittels `solders.keypair.Keypair()`.
-   **Vanity-Adress-Suche (`_grind_keypair_ui`):** Eine Brute-Force-Methode, die in einer Schleife Keypairs generiert und deren Pubkey-String auf das gewünschte Präfix prüft. Effizienz ist hier sekundär, da es sich um ein Devnet-Tool handelt.
-   **SPL Token Instruktionen**: Standard-Instruktionen aus `spl.token.instructions` werden verwendet.
-   **Metaplex Metadaten (`_create_metadata_instruction_manually`):** Da `spl-token-py` oder `solana-py` keine direkten Helfer für Metaplex `CreateMetadataAccountV3` bieten, wird die Instruktion manuell gemäß der Metaplex-Programmspezifikation mit `borsh_construct` aufgebaut. Dies erfordert genaues Verständnis der Datenstruktur und Serialisierung. Die Struktur umfasst Diskriminator, Name, Symbol, URI, Seller Fee, Creators-Liste, Collection-Details und den `isMutable`-Flag.

---

## 2. Management-Tool (`app.py`) im Detail: Interaktive Token-Verwaltung

`app.py` stellt eine benutzerfreundliche grafische Oberfläche (GUI) bereit, um mit der durch `setup.py` erstellten Token-Umgebung zu interagieren.

### GUI-Layout und Hauptfunktionen

Die GUI ist in mehrere Bereiche aufgeteilt:

-   **Statusbereich (links):**
    -   Zeigt den Verbindungsstatus zum RPC-Endpunkt.
    -   Listet alle relevanten Wallets (Payer, Testnutzer) mit ihren aktuellen SOL- und Token-Salden sowie ihren Adressen (Wallet und ATA) auf.
    -   Bietet manuelle und automatische Aktualisierung der Salden. Die intuitive Oberfläche ermöglicht auch Nutzern ohne tiefgreifende Blockchain-Kenntnisse, grundlegende Token-Operationen sicher durchzuführen.
-   **Aktionsbereich (rechts, mit Tabs):** Aktionen können wahlweise vom Payer/Emittent-Wallet oder von einem der erstellten Testnutzer-Wallets ausgeführt werden, um verschiedene Szenarien zu simulieren.
    -   **Tab "🏦 Emittent":**
        -   *Token-Versorgung verwalten*: Buttons und Eingabefelder zum Minten neuer Tokens (an das ATA des Payers) und zum Verbrennen von Tokens (vom ATA des Payers). Diese Aktionen sind nur aktiv, wenn die Mint-Authority nicht widerrufen wurde.
        -   *Token senden*: Senden des erstellten SPL-Tokens vom Payer-Wallet an andere Setup-Wallets oder eine extern eingegebene Adresse.
        -   *SOL senden*: Senden von SOL vom Payer-Wallet.
        -   *Token-Konto sperren/entsperren*: Führt Freeze/Thaw-Aktionen für das ATA eines ausgewählten Wallets (intern oder extern) aus. Diese Aktion ist nur aktiv, wenn die Freeze-Authority nicht widerrufen wurde.
    -   **Tab "👥 Testnutzer":**
        -   Ermöglicht die Auswahl eines Testnutzers.
        -   Bietet die gleichen Sende-Funktionen (Token und SOL) wie im Emittent-Tab, jedoch ausgeführt vom ausgewählten Testnutzer-Wallet.
    -   **Tab "⚙️ Einstellungen":**
        -   Zeigt aktuelle Verbindungsinformationen (RPC, Wallet-Ordner, Mint-Adresse).
        -   Ermöglicht die Konfiguration des Auto-Refresh-Intervalls für die Statusanzeige.
        -   Zeigt an, ob der Token dem Standard SPL Token Programm oder Token-2022 folgt.
-   **Transaktionsprotokoll (unten rechts):**
    -   Zeigt alle von der GUI initiierten Aktionen, deren Status (gesendet, bestätigt, fehlgeschlagen) und die resultierenden Transaktionssignaturen an. Fehler werden ebenfalls hier geloggt.

![Management-Tool Hauptansicht](https://github.com/leofleischmann/Solana-Token-Management-Suite/blob/f4e116df408867a4688febeaabdb81e83cfa6cb2/app.png?raw=true)
![Management-Tool Aktionen](https://github.com/leofleischmann/Solana-Token-Management-Suite/blob/f4e116df408867a4688febeaabdb81e83cfa6cb2/app2.png?raw=true)

### Dynamische Datenabfrage und Status-Updates (`_fetch_all_statuses_thread`, `_fetch_token_and_authority_info`)

-   **Token-Informationen**: Beim Start und bei jeder manuellen/automatischen Aktualisierung:
    -   Die Mint-Adresse wird von `config.json` bzw. `mint-wallet.json` geladen.
    -   `get_account_info` wird auf die Mint-Adresse ausgeführt, um Dezimalstellen, Mint-Authority-Status und Freeze-Authority-Status direkt von der Blockchain zu lesen. Das Skript parst die rohen Account-Daten (82 Bytes) gemäß der SPL-Token-Mint-Layout-Spezifikation.
    -   Die Token-Program-ID (Standard SPL oder Token-2022) wird aus dem Owner-Feld des Mint-Accounts extrahiert.
    -   Zusätzlich wird versucht, Metadaten (Name, Symbol) über den Metaplex Metadata PDA abzurufen. Die PDA-Adresse wird mit `Pubkey.find_program_address` berechnet. Die Account-Daten des PDA werden geparst, um Name und Symbol zu extrahieren.
    -   Diese Informationen aktualisieren dynamisch Labels und Platzhaltertexte in der GUI.
-   **Wallet-Salden**:
    -   Für jedes Wallet (Payer, Testnutzer) wird `get_balance` (für SOL) und `get_token_account_balance` (für den SPL-Token, via ATA) aufgerufen.
    -   Die Ergebnisse werden formatiert und in der Statusanzeige dargestellt.
-   **Threading**: Alle Blockchain-Abfragen für Status-Updates laufen in einem separaten Thread (`run_in_thread`), um die GUI responsiv zu halten. Die Aktualisierung der UI-Elemente erfolgt dann über `self.after(0, ...)` im Hauptthread.
-   **Authority-basierte UI-Steuerung (`_update_authority_widgets`):** Buttons für Mint/Burn und Freeze/Thaw werden dynamisch aktiviert/deaktiviert, je nachdem, ob die entsprechenden Authorities laut Blockchain-Daten noch beim Payer liegen.

### Implementierung der Token-Operationen

Alle Aktionen werden nach einer Bestätigungsdialogbox (`ConfirmDialog`) ausgeführt und in einem separaten Thread abgearbeitet:

-   **Mint (`on_mint`, `_execute_mint_thread`):**
    - Erstellt eine `mint_to`-Instruktion (SPL Token Program).
    - Ziel ist das ATA des Payer-Wallets. Mint-Authority ist das Payer-Wallet.
-   **Burn (`on_burn`, `_execute_burn_thread`):**
    - Erstellt eine `burn`-Instruktion (SPL Token Program).
    - Quelle ist das ATA des Payer-Wallets. Owner des ATA (und damit der Tokens) ist das Payer-Wallet.
-   **SPL-Token Transfer (`on_spl_transfer`, `on_user_spl_transfer`, `_execute_transfer_thread`):**
    - Ermittelt Quell-ATA (des Senders) und Ziel-ATA (des Empfängers).
    - Prüft, ob das Ziel-ATA existiert. Falls nicht, wird eine `create_associated_token_account`-Instruktion vorangestellt. Payer für diese ATA-Erstellung ist der Sender der aktuellen Transaktion.
    - Erstellt eine `transfer`-Instruktion (SPL Token Program, oft als `spl_transfer` importiert, um Verwechslung mit `system_transfer` zu vermeiden).
-   **SOL Transfer (`on_sol_transfer`, `on_user_sol_transfer`, `_execute_transfer_thread`):**
    - Erstellt eine `transfer`-Instruktion des System Program (`system_transfer`).
-   **Freeze/Thaw (`on_freeze_thaw`, `_execute_freeze_thaw_thread`):**
    - Erstellt eine `freeze_account`- oder `thaw_account`-Instruktion (SPL Token Program).
    - Ziel ist das ATA des ausgewählten Wallets. Freeze-Authority ist das Payer-Wallet.
-   **Transaktionserstellung und -sendung (`_confirm_and_send_transaction`):**
    - Alle Instruktionen für eine Aktion werden gesammelt.
    - Eine neue Transaktion wird mit dem Payer (für Gebühren) und allen weiteren notwendigen Signierern (z.B. Token-Owner bei Burn/Transfer, Mint-Authority bei Mint) erstellt.
    - `get_latest_blockhash` wird für den `recent_blockhash` verwendet.
    - `send_transaction` und `confirm_transaction` (mit Commitment "finalized") werden aufgerufen.

---

## 3. Periodisches Analyse-Tool (`analyse.py`) im Detail: Tiefgehende Transaktionsüberwachung

`analyse.py` ist ein Kommandozeilen-basiertes Tool, das in periodischen Intervallen Token-Transfers auf der Solana-Blockchain analysiert. Es fokussiert sich auf die Überwachung einer Whitelist von Adressen und erweitert diese dynamisch um eine Greylist.

### Kernarchitektur und Datenflüsse (`PeriodicChecker` Klasse)

-   **Zustandsverwaltung (`STATE_FILE`, `GREYLIST_FILE`):**
    -   `last_signatures.json` (`STATE_FILE`): Speichert für jede überwachte Wallet-Adresse (Whitelist und Greylist) die Signatur der zuletzt analysierten Transaktion und den zuletzt bekannten Token-Saldo. Dies ermöglicht es dem Tool, bei jedem Durchlauf nur neue, noch nicht gesehene Transaktionen zu laden.
    -   `greylist.json` (`GREYLIST_FILE`): Persistiert die Menge der Adressen, die zur Greylist hinzugefügt wurden.
-   **Konfiguration:** Liest `RPC_URL` und `WALLET_FOLDER` aus `config.json`. Die `whitelist.txt` wird aus dem `WALLET_FOLDER` geladen.
-   **Hauptschleife (`run_check`):**
    1.  Lädt aktuellen Zustand (Whitelist, Greylist, `last_signatures`).
    2.  Startet einen **Multi-Pass-Analyseprozess**:
        -   In jedem Pass werden neue Transaktionen für alle aktuell überwachten Wallets (Whitelist + Greylist), die im aktuellen Gesamtdurchlauf noch nicht gescannt wurden, abgerufen.
        -   Wenn durch die Analyse dieser Transaktionen neue Wallets zur Greylist hinzugefügt werden, wird ein weiterer Pass gestartet, um auch für diese neuen Greylist-Wallets die Historie abzurufen.
        -   Dieser Prozess wiederholt sich, bis in einem Pass keine neuen Wallets mehr zur Greylist hinzukommen, was bedeutet, dass die "Kette" der relevanten Transaktionen für diesen Lauf vollständig analysiert wurde.
    3.  Aktualisiert die finalen Token-Salden aller überwachten Wallets im `STATE_FILE`.
    4.  Speichert die (potenziell erweiterte) Greylist.
    5.  Generiert eine Netzwerk-Visualisierung.
    6.  Führt optional einen Validierungs-Check durch.
    7.  Wartet das konfigurierte Intervall (`--interval`) bis zum nächsten Durchlauf.

### Algorithmus zur lückenlosen Kettenerfassung und Signaturverfolgung (`get_new_signatures_paginated`)

-   Für jede zu überwachende Wallet-Adresse:
    -   Die letzte bekannte Signatur wird aus dem `state` geladen.
    -   `client.get_signatures_for_address` wird iterativ aufgerufen (paginiert mit `limit=1000`, falls mehr als 1000 Signaturen seit dem letzten Mal).
    -   Die Abfrage erfolgt rückwärts durch die Transaktionshistorie (mittels des `before` Parameters, der auf die letzte Signatur des vorherigen Batches gesetzt wird), bis die `last_known_signature` in einem Batch gefunden wird oder keine Signaturen mehr vorhanden sind. Dies stellt sicher, dass keine Transaktionen übersehen werden, selbst wenn das Tool zwischenzeitlich nicht aktiv war.
    -   Alle Signaturen, die neuer als die `last_known_signature` sind, werden gesammelt und in chronologischer Reihenfolge für die Analyse zurückgegeben.
    -   Die Signatur der neuesten verarbeiteten Transaktion wird im `state` für das nächste Mal gespeichert.

### Analyse von Token-Transfers und Saldenänderungen (`analyze_transaction`, `_analyze_transfers`)

-   Für jede neue Signatur wird die volle Transaktion via `get_transaction_with_retries` (mit exponentieller Backoff-Retry-Logik für Ratenbegrenzung/HTTP 429 Fehler) geholt.
-   Es wird geprüft, ob die Transaktion selbst fehlgeschlagen ist (`tx_resp.value.transaction.meta.err`).
-   **Relevanzprüfung**: Die `pre_token_balances` und `post_token_balances` Sektionen der Transaktions-Metadaten werden untersucht. Nur wenn der überwachte `mint_pubkey` (die Adresse des zu überwachenden Tokens) in diesen Salden vorkommt, wird die Transaktion als relevant für diesen spezifischen Token eingestuft und weiter analysiert.
-   **Saldo-Differenzierung**:
    -   Für jeden `owner` (Wallet-Adresse), dessen Token-Saldo (des überwachten Mints) sich durch die Transaktion geändert hat, wird die Differenz zwischen `post_token_balances` und `pre_token_balances` berechnet.
    -   `owner` mit einer negativen Saldoänderung gelten als Sender des Tokens.
    -   `owner` mit einer positiven Saldoänderung gelten als Empfänger des Tokens.
-   **Transfer-Identifikation**:
    -   **Einfacher Transfer (1 Sender, 1 Empfänger):** Wenn genau ein Sender und ein Empfänger identifiziert werden und die Beträge (annähernd) übereinstimmen, werden Sender, Empfänger und Betrag direkt extrahiert.
    -   **Komplexer Transfer (Multiple Sender/Empfänger):** Wenn z.B. ein Smart Contract Tokens von mehreren Quellen sammelt und an mehrere Ziele verteilt oder wenn mehrere unabhängige Transfers in einer Transaktion gebündelt sind, wird dies erkannt. Für jeden identifizierten Empfänger, der Tokens erhalten hat, wird ein separates Transfer-Event geloggt. Als Sender wird entweder der einzelne tatsächliche Sender (falls eindeutig identifizierbar durch die Saldoänderungen) oder ein "Multiple Sender"-Platzhalter (mit einer Liste der möglichen Sender) verwendet. Diese Logik stellt sicher, dass jeder *Zufluss* zu einem nicht-autorisierten Wallet erfasst wird, auch wenn die genaue Quelle komplex ist oder verschleiert werden soll.
-   **Betragsberechnung**: Die rohen Lamport-Beträge aus den Bilanzen werden durch `10**TOKEN_DECIMALS` (wobei `TOKEN_DECIMALS` auf 9 festgesetzt ist, typisch für viele SPL-Tokens) geteilt, um den für Menschen lesbaren Token-Betrag zu erhalten.

### Whitelist-, Greylist- und Sanktionsmechanismen (`_process_transfer`, `_freeze_account`)

-   **Whitelist-Prüfung**: Bei jedem identifizierten Transfer des überwachten Tokens:
    -   Die Adresse des `recipient` wird gegen die aktuell geladene `whitelist` und die dynamisch erweiterte `greylist` (die Menge aller `monitored_wallets` im aktuellen Analysepass) geprüft.
-   **Verstoßerkennung und Greylist-Erweiterung**:
    -   Ist der `recipient` **nicht** in den `monitored_wallets` (d.h. weder Whitelist noch bereits Greylist), gilt dies als ein Whitelist-Verstoß.
    -   Das Ereignis wird als `VIOLATION` im Transaktionslog (`transactions.jsonl`) protokolliert.
    -   Der `recipient` wird dynamisch zur `greylist` hinzugefügt.
    -   Im `state` (`last_signatures.json`) wird für diesen neu zur Greylist hinzugefügten Wallet die aktuelle Transaktionssignatur als Startpunkt für dessen eigene, zukünftige Historienanalyse im nächsten Analysepass gesetzt. Dieses dynamische Hinzufügen zur Greylist ermöglicht eine adaptive Überwachung, die über eine statische Whitelist hinausgeht und hilft, potenzielle Umgehungsversuche oder indirekte Token-Flüsse zu identifizieren.
-   **Optionale Sanktionen (Token Freeze):**
    -   Wenn das Kommandozeilenargument `--freezereceive` aktiviert ist, wird bei einem Verstoß das Associated Token Account (ATA) des `recipient` für den überwachten Mint eingefroren.
    -   Wenn `--freezesend` aktiviert ist (und ein Verstoß vorliegt), wird zusätzlich das ATA des `sender` eingefroren (falls der Sender eindeutig identifiziert werden konnte und nicht "Multiple" ist).
    -   Die Freeze-Aktion (`_freeze_account`) sendet eine `freeze_account`-Instruktion (aus dem SPL Token Program), die vom Payer-Wallet (`payer-wallet.json`) signiert wird. Dieses Payer-Wallet muss die Freeze-Authority für den überwachten Token besitzen.
-   **Autorisierte Transfers**: Ist der `recipient` bereits Teil der `monitored_wallets`, wird der Transfer als `AUTHORIZED_TRANSFER` geloggt, und es erfolgen keine Sanktionen.

### Analyse von Freeze/Thaw-Aktionen (`_analyze_freeze_thaw`)

-   Das Skript durchsucht zusätzlich die Liste der Instruktionen (`tx.transaction.message.instructions`) jeder relevanten Transaktion nach `freezeAccount`- oder `thawAccount`-Aktionen.
-   Wenn eine solche Instruktion gefunden wird:
    -   Es wird geprüft, ob das `mint`-Feld der Instruktion dem überwachten `mint_pubkey` entspricht.
    -   Falls ja, wird die Adresse des betroffenen Token-Kontos (ATA) aus der Instruktion extrahiert.
    -   Anschließend wird versucht, den tatsächlichen **Owner** (die Wallet-Adresse des Besitzers) dieser ATA-Adresse zu ermitteln. Dies geschieht primär durch Analyse der `pre_token_balances` und `post_token_balances` der aktuellen Transaktion (wenn das ATA dort auftaucht) oder sekundär durch einen direkten `get_account_info_json_parsed`-RPC-Aufruf auf die ATA-Adresse, um deren Owner-Feld zu lesen.
    -   Das Ereignis (Freeze oder Thaw) wird als `ACCOUNT_FROZEN` oder `ACCOUNT_THAWED` im Transaktionslog (`transactions.jsonl`) protokolliert, inklusive der Wallet-Adresse des Owners. Dies erfasst auch Freeze/Thaw-Aktionen, die von externen Parteien (nicht nur vom Skript selbst) initiiert wurden.

### Netzwerk-Visualisierung und Validierungslogik (`NetworkVisualizer` Klasse, `_perform_supply_validation`)

-   **Visualisierung (`NetworkVisualizer.generate_graph`):**
    -   Liest alle geloggten Transaktionsereignisse aus der Datei `transactions.jsonl`.
    -   Aggregiert alle Token-Flüsse (`amount` bei `VIOLATION` oder `AUTHORIZED_TRANSFER`) zwischen den beteiligten Sender- und Empfängeradressen.
    -   Berechnet einen *approximativen* Endsaldo für jedes im Log aufgetauchte Wallet, basierend auf der Summe der Zu- und Abflüsse aus den geloggten Transaktionen. (Hinweis: Dies ist nicht zwingend der exakte On-Chain-Saldo, da nicht alle Transaktionen eines Wallets zwangsläufig den überwachten Token betreffen oder erfasst wurden, sondern eine Schätzung basierend auf den für den *überwachten Token* erfassten Transfers.)
    -   Ermittelt den finalen Freeze-Status von Wallets basierend auf den letzten `ACCOUNT_FROZEN` oder `ACCOUNT_THAWED` Log-Einträgen für das jeweilige Wallet.
    -   Erstellt mit der `pyvis.network.Network`-Bibliothek ein interaktives HTML-Netzwerkdiagramm:
        -   **Knoten**: Repräsentieren Wallet-Adressen. Sie werden farblich kodiert: Payer (lila), Whitelist (grün), Greylist (gelb), Externe/Unbekannte (grau), Gesperrte Wallets (rot, überschreibt andere Farben). Tooltips bei Mouseover zeigen die volle Adresse, den berechneten Saldo und den Status (z.B. "Whitelist / Gesperrt").
        -   **Kanten**: Repräsentieren die aggregierten Token-Flüsse zwischen zwei Wallets. Die Dicke oder der Wert der Kante kann das Volumen andeuten, und die Kante wird mit dem Gesamtvolumen beschriftet.
    -   Die resultierende interaktive HTML-Datei wird unter `analyse/network_visualization.html` gespeichert und kann in jedem Webbrowser geöffnet werden.
-   **Validierungs-Check (`_perform_supply_validation` optional via `--validate`):**
    -   **Schritt 1 (Log-basierte Verteilung)**: Summiert alle Token-Beträge, die laut der Log-Datei `transactions.jsonl` ursprünglich vom Payer-Wallet (definiert in `payer-wallet.json`) an andere Adressen transferiert wurden. Dies repräsentiert die Menge an Tokens, die das Payer-Wallet initial in das überwachte Ökosystem eingebracht hat.
    -   **Schritt 2 (On-Chain-Saldenabfrage)**: Ruft für *jedes* Wallet, das sich aktuell in der kombinierten Menge aus Whitelist und Greylist befindet, den aktuellen On-Chain-Token-Saldo (`get_token_balance`) für den überwachten Mint ab.
    -   **Schritt 3 (Vergleich und Analyse)**:
        -   Berechnet die Summe aller abgerufenen On-Chain-Token-Salden der überwachten Wallets.
        -   Berechnet den "effektiven Token-Umlauf", indem der aktuelle On-Chain-Saldo des Payer-Wallets von der zuvor berechneten Gesamtsumme aller überwachten Wallets abgezogen wird. Die Annahme hierbei ist, dass Tokens im Payer-Wallet noch nicht "im Umlauf" im engeren Sinne sind.
        -   Vergleicht diesen berechneten effektiven Umlauf mit der Summe der log-basierten initialen Verteilung aus Schritt 1. Eine sehr geringe Diskrepanz (kleiner als 1e-4 Tokens) wird als Übereinstimmung gewertet.
        -   Größere Abweichungen werden als Fehler geloggt und deuten auf mögliche Unstimmigkeiten hin, z.B. Tokens, die an Adressen außerhalb des Whitelist/Greylist-Systems transferiert wurden und daher nicht mehr nachverfolgt werden, Fehler in der Erfassungslogik, oder manuelle Token-Burns, die nicht vom Skript erfasst wurden.
    -   Das Ergebnis des Validierungs-Checks (Erfolg oder Fehlschlag mit der Höhe der Diskrepanz) wird im Hauptlog ausgegeben.

### Kontostandsoptimierung mit Sicherheits-Check (Implementiert in der `run_check`-Methode)

-   Für Wallets, die bereits auf der Greylist stehen und für die ein `last_balance` (letzter bekannter Token-Saldo) und eine `last_sig` (letzte verarbeitete Signatur) im `state` (`last_signatures.json`) gespeichert sind:
    1.  Der aktuelle On-Chain-Token-Saldo des Greylist-Wallets wird mit `get_token_balance` abgerufen.
    2.  Wenn der Unterschied zwischen dem aktuellen Saldo und dem `last_balance` vernachlässigbar klein ist (weniger als 1e-9 Tokens, um Fließkomma-Ungenauigkeiten abzufangen):
        - Ein **Sicherheits-Check** wird ausgelöst: `client.get_signatures_for_address` wird mit `limit=1` aufgerufen, um die allerletzte Transaktionssignatur für dieses Wallet direkt von der Blockchain zu holen.
        - Diese neueste On-Chain-Signatur wird mit der im `state` gespeicherten `last_sig` verglichen.
        - **Fall A (Keine neuen relevanten Transaktionen wahrscheinlich):** Sind beide Signaturen identisch (oder beide `None`, falls das Wallet noch keine Transaktionen hatte), wird die aufwändige Tiefenanalyse (das Abrufen *aller* Signaturen seit `last_sig` mittels `get_new_signatures_paginated`) für dieses Wallet in diesem aktuellen Analyse-Durchlauf **übersprungen**. Dies ist eine signifikante Optimierung, die unnötige RPC-Aufrufe und Verarbeitungszeit spart, wenn sich der Zustand eines Wallets wahrscheinlich nicht geändert hat.
        - **Fall B (Potenziell neue, saldo-neutrale Transaktionen):** Unterscheiden sich die Signaturen jedoch (obwohl der Saldo gleich geblieben ist), deutet dies auf mögliche Transaktionen hin, die den Saldo nicht verändert haben (z.B. Hin- und Rücktransfers innerhalb desselben Verarbeitungsblocks, Genehmigungen/Delegationen oder fehlgeschlagene Transaktionen, die dennoch eine Signatur erzeugen) oder auf eine Verzögerung im RPC-Knoten, bei dem der Saldo bereits aktualisiert, die Signaturliste aber noch nicht vollständig konsistent ist. In diesem Fall wird die Tiefenanalyse mittels `get_new_signatures_paginated` **dennoch erzwungen**, um sicherzustellen, dass keine potenziell relevanten (z.B. Freeze/Thaw) Transaktionen übersehen werden.
-   Nach Abschluss eines jeden vollständigen Analyse-Durchlaufs (aller Pässe) werden die `last_balance`-Werte für alle überwachten Wallets im `state` mit den frisch abgerufenen On-Chain-Salden aktualisiert.

![Netzwerk Graph erstellt durch Analyse-Tool (Beispiel)](https://github.com/leofleischmann/Solana-Token-Management-Suite/blob/d8643a08f2968ea695fb08e3e0a3a6c1935797c4/network_graph.png)

---

## 4. Traffic Generator (`traffic_generator.py`) im Detail: Simulation komplexer Transaktionsmuster

`traffic_generator.py` ist ein Kommandozeilen-Tool, das dazu dient, zufällige und mehrstufige SPL-Token-Transfers zu erzeugen. Hauptziel ist es, die Nachverfolgbarkeit von Token-Bewegungen zu erschweren und realistische Netzwerkaktivität für Testzwecke zu simulieren. Neben dem Erschweren der Nachverfolgbarkeit kann das Tool auch genutzt werden, um die Performance von Indexern, Analyse-Dashboards oder RPC-Knoten unter Last mit realitätsnahen, aber synthetischen Transaktionsmustern zu testen.

### Modi: Standard-Modus und Outside-Modus

#### 1. Standard-Modus (`run_standard_mode`)
-   **Aktivierung:** Standardmäßig aktiv, oder wenn `--outside 0` gesetzt ist.
-   **Wallet-Pool:** Verwendet einen Pool von initialen Wallets, die aus dem Ordner `WALLET_SOURCE_FOLDER` (Standard: `devnet_wallets`) geladen werden. Diese Wallets sollten bereits über den zu transferierenden SPL-Token verfügen.
-   **Ablauf pro Aktion:**
    1.  Wählt zufällig ein Sender- (`sender_kp`) und ein Empfänger-Wallet (`recipient_kp`) aus dem Pool (stellt sicher, dass Sender != Empfänger).
    2.  Ruft den Token-Saldo des Senders ab (`get_token_balance`).
    3.  Bestimmt einen zufälligen Transferbetrag zwischen `--min` und `--max` (angepasst an den tatsächlichen Saldo des Senders).
    4.  Überprüft den SOL-Saldo des Senders. Falls zu niedrig (aktuell < 5000 Lamports, was nicht ausreicht, wenn der Payer die Hauptgebühr trägt, der Sender aber ATA erstellen muss), wird das Sender-Wallet vom Haupt-Payer (`payer-wallet.json` aus `CONFIG_WALLET_FOLDER`) mit SOL aufgeladen (`fund_with_sol`).
    5.  Führt den Token-Transfer mittels `send_token_transfer` durch. Der Haupt-Payer (`payer-wallet.json`) bezahlt die Transaktionsgebühr. Der `sender_kp` signiert als Token-Owner und als Payer für eine eventuelle ATA-Erstellung beim Empfänger.
-   **Zweck:** Simulation von Transaktionen innerhalb eines bekannten, etablierten Netzwerks.

#### 2. Outside-Modus (`run_outside_mode`)
-   **Aktivierung:** Durch `--outside N`, wobei `N` die Anzahl der Hops ist.
-   **Phasen pro Durchlauf:**
    1.  **Optionale Aktivität im Handelsnetzwerk:**
        - Mit einer Wahrscheinlichkeit von 30% (wenn `random.random() > 0.3` und `outside_network_wallets` existieren und mindestens 2 Wallets enthalten) wird zunächst `run_standard_mode` aufgerufen. Dieser Modus verwendet dann aber nicht die initialen Wallets, sondern den Pool `outside_network_wallets`. Dieser Pool enthält Wallets, die in der Verzweigungsphase früherer Outside-Modus-Durchläufe erstellt wurden und beim Start des Skripts geladen werden, falls sie noch Token-Guthaben besitzen.
        - Zweck: Simuliert Aktivität in den bereits verschleierten, neu geschaffenen Netzwerken.
    2.  **Hop-Kette (Verschleierung):**
        - Wählt einen initialen Sender aus dem Pool `initial_wallets`.
        - Bestimmt einen Transferbetrag (ein signifikanter Anteil, z.B. 80-100%, des Saldos des initialen Senders, jedoch mindestens der via `--min` festgelegte Betrag und maximal der tatsächliche Saldo).
        - Für jeden der `N` Hops:
            a.  Ein neues temporäres Wallet (`new_recipient_kp`) wird generiert und dessen Schlüsselmaterial in einem `layer_X`-Unterordner gespeichert (`X` ist die aktuelle Hop-Nummer) innerhalb von `generic_transactions/generated_wallets/`.
            b.  Dieses neue Wallet wird vom Haupt-Payer-Wallet mit einer Standardmenge SOL (aktuell 0.005 SOL) aufgeladen (`fund_with_sol`), um sicherzustellen, dass es Transaktionsgebühren für den nächsten Hop oder die Erstellung seines eigenen ATAs bezahlen kann.
            c.  Der zuvor bestimmte Token-Betrag wird vom aktuellen Sender-Wallet (`current_sender_kp`, das entweder das Wallet des vorherigen Hops oder der initiale Sender ist) an das `new_recipient_kp` transferiert (`send_token_transfer`).
            d.  Das `new_recipient_kp` wird zum `current_sender_kp` für den potenziell nächsten Hop.
    3.  **Verzweigung (Distribution & Netzwerkexpansion):**
        - Das Wallet am Ende der Hop-Kette (`distributor_kp = current_sender_kp`) fungiert als Verteiler der angekommenen Tokens.
        - Die Anzahl der neuen Wallets, auf die verteilt wird (`network_size`), wird entweder durch den Kommandozeilenparameter `--network-size` fest vorgegeben oder ist zufällig (Standard: 2-4 Wallets).
        - Das `distributor_kp` wird vom Haupt-Payer-Wallet mit ausreichend SOL aufgeladen, um die Gebühren für die Erstellung der Associated Token Accounts (ATAs) für alle neuen Zweig-Wallets zu decken (geschätzt ca. `network_size * 0.0021` SOL).
        - Der gesamte Token-Saldo des `distributor_kp` wird gleichmäßig auf die festgelegte Anzahl neuer Zweige aufgeteilt.
        - Für jeden Zweig:
            a.  Ein neues Wallet (`branch_wallet_kp`) wird erstellt und im Ordner `generic_transactions/generated_wallets/layer_N+1` gespeichert.
            b.  Der anteilige Token-Betrag wird vom `distributor_kp` an dieses neue `branch_wallet_kp` transferiert.
            c.  Das neu erstellte `branch_wallet_kp` wird ebenfalls vom Haupt-Payer-Wallet mit einer kleinen Menge SOL (Standard 0.003 SOL) für zukünftige Transaktionen ausgestattet.
            d.  Das `branch_wallet_kp` wird zur In-Memory-Liste `outside_network_wallets` hinzugefügt, um in zukünftigen Zyklen dieses Skriptlaufs für die "optionale Aktivität im Handelsnetzwerk" (Phase 1) genutzt zu werden.
-   **Zweck:** Erzeugt komplexe, schwerer nachvollziehbare Transaktionsketten und baut dynamisch neue, kleine Wallet-Netzwerke auf, in denen weitere Aktivität simuliert werden kann.

### Technische Implementierung der Transaktionsgenerierung

-   **Wallet-Erstellung und -Speicherung (`create_and_save_keypair`):**
    -   Neue Keypairs (`solders.keypair.Keypair()`) werden generiert.
    -   Das Secret Key (die vollen 64 Bytes des Schlüsselpaars) wird Base64-kodiert und als JSON-String in einer Datei gespeichert. Der Dateiname ist die öffentliche Adresse (Pubkey) des Wallets. Die Speicherung erfolgt in hierarchischen Ordnern (`generic_transactions/generated_wallets/layer_X`), wobei `X` die Tiefe des Hops oder die Ebene des Verzweigungsnetzwerks darstellt. Die generierten Wallets in `generic_transactions/generated_wallets/layer_X` können so eine spätere manuelle Inspektion oder Wiederverwendung ermöglichen.
-   **Wallet-Laden (`load_keypair_from_path`, `load_all_keypairs`):**
    -   Unterstützt das Laden von Keypairs, die entweder als Base64-String des 64-Byte-Schlüssels (neueres Format, vom Skript selbst erzeugt) oder als Liste von 64 Integern (altes Solana CLI Format für Secret Keys) oder 32 Integern (typischerweise von einem Seed abgeleitet, wird dann zu einem vollen Keypair expandiert) in JSON-Dateien gespeichert sind.
-   **Token-Saldo-Abfrage (`get_token_balance`):**
    -   Ermittelt die Associated Token Account (ATA) Adresse für den gegebenen Wallet-Owner und die Mint-Adresse des Tokens.
    -   Ruft `client.get_token_account_balance` mit dem Commitment-Level "confirmed" ab, um einen bestätigten Saldo zu erhalten.
    -   Implementiert eine Retry-Logik (aktuell 4 Versuche mit jeweils 5 Sekunden Pause), falls das Konto nicht sofort gefunden wird (Fehlermeldung "Invalid param: could not find account"). Dies ist nützlich, da es nach der Erstellung eines ATAs eine kurze Verzögerung geben kann, bis es über alle RPC-Knoten sichtbar ist.
-   **SOL-Finanzierung (`fund_with_sol`):**
    -   Erstellt eine einfache `solders.system_program.transfer`-Instruktion.
    -   Sendet und bestätigt die Transaktion vom Haupt-Payer-Wallet an das Empfänger-Wallet.
-   **SPL-Token-Transfer (`send_token_transfer`):**
    -   **ATA-Ermittlung**: Verwendet `spl.token.instructions.get_associated_token_address` für Sender und Empfänger.
    -   **Empfänger-ATA-Prüfung und -Erstellung**:
        -   Ruft `client.get_account_info` für das Empfänger-ATA mit Commitment "confirmed" ab, um dessen Existenz zu prüfen.
        -   Implementiert eine Retry-Logik (aktuell 4 Versuche, 7 Sekunden Pause) für den `get_account_info`-Aufruf, um transiente RPC-Fehler oder netzwerkbedingte Verzögerungen abzufangen.
        -   Wenn das Konto nicht existiert (`recipient_account_info_value` ist `None` oder enthält keine Daten, was auf ein nicht initialisiertes Konto hindeutet), wird eine `spl.token.instructions.create_associated_token_account`-Instruktion zur Transaktion hinzugefügt. Wichtig: Der Payer für diese ATA-Erstellungs-Instruktion ist der `sender` der aktuellen Token-Transaktion, nicht der globale Haupt-Payer des Skripts.
    -   **Transfer-Instruktion**: Erstellt eine `spl.token.instructions.transfer_checked`-Instruktion. Diese ist sicherer als ein einfacher `transfer`, da sie den Betrag und die Anzahl der Dezimalstellen des Mints gegen die auf der Chain gespeicherten Werte prüft.
    -   **Transaktionserstellung und Signierung**: Bündelt alle notwendigen Instruktionen (ggf. ATA-Erstellung + Transfer). Der Haupt-Payer des Skripts (`payer`) zahlt die Netzwerkgebühr der Transaktion. Der `sender` der Token (das aktuelle Hop- oder Verteiler-Wallet) muss die Transaktion ebenfalls signieren, da er der Owner der zu transferierenden Tokens ist und ggf. die Gebühr für die ATA-Erstellung des Empfängers bezahlt.
    -   Sendet und bestätigt die Transaktion mit Commitment "confirmed".
-   **RPC-Client-Initialisierung (`main`):**
    -   Für Kompatibilität mit der spezifizierten älteren `solana-py==0.36.6` Version wird der `Client` ohne das `httpx_client_kwargs`-Argument initialisiert. Dies bedeutet, dass die Standard-HTTP-Timeouts der zugrundeliegenden `httpx`-Bibliothek verwendet werden. Neuere Versionen von `solana-py` würden hier eine explizite Konfiguration längerer Timeouts erlauben, um die Robustheit gegenüber langsamen RPC-Antworten zu erhöhen.
-   **Logging (`setup_logger`):**
    -   Konfiguriert einen Logger, der sowohl auf die Konsole (StreamHandler) als auch in eine Datei (`generic_transactions/sent_transactions.log` via FileHandler) schreibt.
    -   Protokolliert detailliert erstellte Wallets, Parameter von gesendeten Transaktionen (Sender, Empfänger, Betrag), resultierende Transaktionssignaturen, aufgetretene Fehler und allgemeine Statusinformationen des Skriptablaufs.
-   **Konfiguration (`config.json` und Kommandozeilenparameter):**
    -   `config.json`: Wird verwendet, um die `RPC_URL` und den `CONFIG_WALLET_FOLDER` (Pfad zum Haupt-Payer- und Mint-Wallet) zu laden.
    -   Kommandozeilenargumente: `--delay` (Pause in Sekunden zwischen den Hauptaktionen des Generators), `--min` und `--max` (minimale und maximale Token-Menge pro Transfer), `--outside` (Anzahl der Hops im Outside-Modus, 0 für Standard-Modus), `--network-size` (feste Anzahl der Wallets im Verzweigungsnetzwerk, 0 für zufällige Größe).

---

## 5. Echtzeit Whitelist-Monitor (`whitelist.py`) - Kurzbeschreibung (Vorgänger)

`whitelist.py` war ein früherer Ansatz zur Live-Überwachung von Token-Transaktionen mittels WebSockets und diente der Durchsetzung einer statischen Whitelist.

### Kernfunktionen
-   **Echtzeit-Überwachung via WebSockets**: Lauschte auf `logsSubscribe`-Events für das `TOKEN_PROGRAM_ID` auf dem konfigurierten RPC-Endpunkt (umgewandelt in einen WebSocket-URI).
-   **Whitelist-Validierung**: Bei Erhalt einer Log-Benachrichtigung wurde die Transaktion geholt und analysiert. Empfängeradressen wurden mit einer in `whitelist.txt` definierten Liste verglichen.
-   **Automatische Sanktionen (Freeze)**: Bei Verstößen gegen die Whitelist konnte das Tool automatisch die Token-Konten (ATAs) der nicht autorisierten Empfänger (und optional der Sender) einfrieren, indem es eine `FreezeAccount`-Transaktion sendete.
-   **GUI-Dashboard**: Eine `customtkinter`-basierte Oberfläche zeigte Live-Logs der überwachten Transaktionen, Statistiken (analysierte Transaktionen, Verstöße) und ermöglichte das Starten/Stoppen des Monitors sowie das manuelle Sperren/Entsperren von Token-Konten.

### Limitationen im Vergleich zu `analyse.py`
-   **Keine Persistenz des Verarbeitungszustands**: Bei einem Neustart des Skripts oder einer Unterbrechung der WebSocket-Verbindung gingen Informationen über bereits verarbeitete Transaktionen verloren. Dies konnte dazu führen, dass Transaktionen, die während der Offline-Zeit stattfanden, übersehen wurden.
-   **Kein Greylist-Konzept**: Die Überwachung beschränkte sich strikt auf die in `whitelist.txt` definierten Adressen. Es gab keine dynamische Erweiterung der Überwachung auf nachgelagerte Empfänger, die Tokens von Whitelist-Adressen erhielten.
-   **Anfälligkeit für WebSocket-Unterbrechungen**: Kürzere Netzwerkprobleme oder Instabilitäten des RPC-Knotens konnten zu Datenverlust führen, da WebSockets keine garantierte Zustellung bieten.
-   **Weniger robuste Transaktionsanalyse**: Die Analyse basierte oft auf dem direkten Parsen von Instruktionen innerhalb der Transaktionslogs. Diese Methode kann bei komplexen Transaktionen (z.B. Interaktionen mit Smart Contracts, die intern Token bewegen) weniger zuverlässig sein als die Methode der Saldo-Differenzanalyse, die in `analyse.py` verwendet wird.

Obwohl `whitelist.py` eine funktionale Echtzeitüberwachung bot, wurde es durch `analyse.py` ersetzt. Letzteres bietet eine umfassendere, robustere und tiefgehendere Analyse mit besserer Fehlerbehandlung, Persistenz des Verarbeitungszustands und dem erweiterten Greylist-Konzept, was zu einer zuverlässigeren und vollständigeren Überwachung führt.

![Whitelist-Monitor Vorschau (Vorgänger)](https://github.com/leofleischmann/Solana-Token-Management-Suite/blob/f4e116df408867a4688febeaabdb81e83cfa6cb2/whitelist.png?raw=true)

---

## Gemeinsame Komponenten und Hilfsfunktionen

Einige Funktionalitäten und Konzepte werden von mehreren Tools in der Suite genutzt:

### Konfigurationsmanagement (`config.json`)
-   Eine zentrale JSON-Datei zur Speicherung von Basiskonfigurationen:
    -   `rpc_url`: Der HTTP-Endpunkt des zu verwendenden Solana RPC-Knotens (z.B. `https://api.devnet.solana.com`).
    -   `wallet_folder`: Der Name des Ordners, in dem wichtige Wallet-Dateien (Payer, Mint, `whitelist.txt`) erwartet oder gespeichert werden (z.B. `devnet_wallets` oder `config_wallets`).
    -   `pinata_jwt` (optional, für `setup.py`): JWT-Token für die Authentifizierung bei Pinata IPFS-Diensten.
-   Jedes Tool lädt diese Konfiguration beim Start (`load_config` Funktion).

### Wallet-Verwaltung (Keypair-Handling)
-   **Laden von Keypairs (`load_keypair` in `setup.py`/`app.py`/`analyse.py`, `load_keypair_from_path` in `traffic_generator.py`):**
    -   Funktionen zum Laden von Solana-Keypairs aus JSON-Dateien.
    -   Unterstützung für das alte Solana CLI Format (Liste von 64 Byte-Werten als Zahlen) und das neuere Base64-kodierte String-Format des 64-Byte Secret Keys. `traffic_generator.py` unterstützt zusätzlich das Laden aus 32-Byte Seeds.
    -   Verwendung von `solders.keypair.Keypair.from_bytes()`.
-   **Speichern von Keypairs (`create_and_save_keypair` in `traffic_generator.py`, intern in `_create_wallet_ui_driven` in `setup.py`):**
    -   Neu generierte Keypairs werden typischerweise als JSON-Datei gespeichert, wobei der Dateiname oft der Pubkey ist und der Inhalt der Base64-kodierte Secret Key oder eine Liste von Bytes.

### RPC-Kommunikation und Fehlerbehandlung
-   **Client-Initialisierung**: `solana.rpc.api.Client` wird für synchrone Aufrufe verwendet. `analyse.py` und `whitelist.py` nutzen zusätzlich `solana.rpc.async_api.AsyncClient` für asynchrone Operationen bzw. `websockets` für Echtzeit-Streams.
-   **Commitment-Level**: Für kritische Operationen und Zustandsabfragen wird in der Regel das Commitment-Level `"confirmed"` oder `"finalized"` verwendet, um sicherzustellen, dass die gelesenen Daten einen hohen Grad an Bestätigung im Netzwerk haben.
-   **Fehlerbehandlung**:
    -   Spezifische `SolanaRpcException` und allgemeinere `Exception` werden abgefangen.
    -   Retry-Mechanismen sind in einigen Funktionen implementiert (z.B. `get_transaction_with_retries` in `analyse.py`, `get_token_balance` in `traffic_generator.py`), insbesondere um auf Ratenbegrenzungen (`HTTPStatusError 429`) oder transiente Netzwerkprobleme zu reagieren.
    -   GUIs verwenden `messagebox.showerror` zur Anzeige von Fehlern. Kommandozeilen-Tools loggen Fehler ausführlich.

### Logging-Strategie
-   **Standard Python `logging` Modul**: Wird für die Protokollierung in Dateien und auf der Konsole verwendet.
-   **Mehrere Logger**: Oft werden separate Logger für Hauptaktivitäten und spezifische Daten (z.B. `transaction_logger` für JSONL-Transaktionslogs in `analyse.py` und `whitelist.py`) eingesetzt.
-   **Formatierung**: Log-Einträge enthalten Zeitstempel, Loglevel und die Nachricht.
-   **Debug-Modus**: Viele Tools bieten einen `--debug` Schalter oder eine UI-Option, um detailliertere Log-Ausgaben zu aktivieren, die bei der Fehlersuche helfen.
-   **Strukturierte Logs (`.jsonl`):** `analyse.py` und `whitelist.py` schreiben Transaktionsereignisse als einzelne JSON-Objekte pro Zeile in eine `.jsonl`-Datei. Dies ermöglicht eine einfache maschinelle Weiterverarbeitung und dient als Datenquelle für die Visualisierung.

---

## Installation und Einrichtung

1.  **Repository klonen:**
    ```bash
    git clone https://github.com/DEIN_BENUTZERNAME/Solana-Token-Management-Suite.git
    cd Solana-Token-Management-Suite
    ```
2.  **Virtuelle Umgebung erstellen (Empfohlen):**
    ```bash
    # macOS/Linux:
    python3 -m venv venv && source venv/bin/activate
    # Windows:
    python -m venv venv && venv\Scripts\activate
    ```
3.  **Abhängigkeiten installieren:**
    Die Datei `requirements.txt` listet alle notwendigen Python-Pakete mit getesteten Versionen auf.
    ```bash
    pip install -r requirements.txt
    ```
4.  **Konfigurationsdatei `config.json` anpassen:**
    - Erstellen oder bearbeiten Sie `config.json` im Hauptverzeichnis.
    - Tragen Sie Ihre Solana `rpc_url` ein (z.B. von QuickNode, Helius oder `https://api.devnet.solana.com`).
    - Legen Sie einen `wallet_folder` fest (z.B. `devnet_wallets`). Dieser Ordner wird von `setup.py` erstellt und befüllt, bzw. von den anderen Tools verwendet.
    - Falls Sie Metadaten mit `setup.py` erstellen möchten, fügen Sie Ihren `pinata_jwt` hinzu.
    ```json
    {
      "rpc_url": "IHRE_SOLANA_RPC_URL",
      "wallet_folder": "devnet_wallets",
      "pinata_jwt": "IHR_PINATA_JWT_FALLS_METADATEN_GENUTZT_WERDEN"
    }
    ```

## Verwendungsempfehlungen und Anwendungsfälle

1.  **Umgebung initialisieren:** Starten Sie `python setup.py`. Konfigurieren Sie Ihre Token-Parameter, Wallets und optional Metadaten über die GUI. Dieser Schritt erstellt alle notwendigen Konten und Dateien.
2.  **Token verwalten:** Nutzen Sie `python app.py`, um mit dem erstellten Token zu interagieren: Senden, Empfangen, Minten, Burnen, Kontostände prüfen, Konten sperren/entsperren.
3.  **Transaktionsanalyse (periodisch):** Führen Sie `python analyse.py` (ggf. mit Optionen wie `--interval`, `--freezesend`, `--validate`) im Hintergrund oder als geplanten Task aus, um Token-Bewegungen zu überwachen, die Whitelist durchzusetzen und detaillierte Visualisierungen der Transaktionsflüsse zu erhalten.
4.  **Netzwerkaktivität simulieren:** Verwenden Sie `python traffic_generator.py` mit verschiedenen Parametern (`--outside`, `--delay`, etc.), um komplexe Transaktionsmuster auf dem Devnet zu erzeugen, z.B. zum Testen von Monitoring-Tools, Indexern oder zur Untersuchung von Anonymisierungsmustern.
5.  **Echtzeit-Überwachung (alternativ):** `python whitelist.py` kann für eine direktere Live-Überwachung genutzt werden, ist aber weniger robust als `analyse.py`.

Diese Suite ist besonders nützlich für:
-   **Entwickler von SPL-Tokens:** Schnelles Prototyping und Testen von Token-Funktionalitäten.
-   **Smart Contract Entwickler:** Testen von Interaktionen mit benutzerdefinierten Tokens.
-   **Sicherheitsforscher:** Analyse von Transaktionsmustern und Überwachungsstrategien.
-   **Technische Ausbilder und Studenten:** Erlernen der Grundlagen von SPL-Tokens und Blockchain-Interaktionen in einer kontrollierten Umgebung.

**Wichtiger Hinweis:** Alle Tools sind primär für das Solana Devnet und Testnet konzipiert. Eine Verwendung auf dem Mainnet erfolgt auf eigene Gefahr und kann reale finanzielle Konsequenzen haben.
