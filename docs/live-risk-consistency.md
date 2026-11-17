# Live Risk Konsistenz

## Problem

Die Position-Sizing-Logik ist in zwei Modulen implementiert:

| Modul | Zweck | Unterschiede |
|-------|-------|--------------|
| `risk/engine.py` | Backtest-Risk-Engine | Vollständige RiskEngine-Klasse mit konfigurierbarem RiskConfig |
| `risk/live.py` | Live-Signal-Sizing | Wrapper-Funktion `size_live_signal()` die auf RiskEngine aufbaut |

## Kritische Unterschiede

### 1. Stop-Direction Enforcement

**Backtest (`risk/engine.py`):**
```python
enforce_stop_direction = bool(signal.metadata.get("enforce_stop_direction", False))
```
Standard: `False` (nicht erzwungen)

**Live (`risk/live.py`):**
```python
"enforce_stop_direction": True,  # hardcoded
```
Live erzwingt immer, dass Stop-Loss in die richtige Richtung zeigt.

### 2. RiskConfig Defaults

Beide Pfade verwenden dieselben Defaults aus `RiskConfig`:
- `max_risk_per_trade: 0.01` (1%)
- `max_total_exposure: 0.05` (5%)
- `max_positions: 5`
- `default_sl_atr_multiplier: 2.0`
- `fallback_stop_pct: 0.02` (2%)

### 3. Sizing-Formel

Beide Pfade verwenden dieselbe Formel:
```
position_size = risk_amount / (risk_distance * pip_value)
```

Dabei ist:
- `risk_amount = balance * risk_percent`
- `risk_percent = min(max_risk_per_trade, max_total_exposure - current_exposure)`
- `position_size = min(position_size, max_notional_per_trade * balance / entry_price)`
  (Notional-Obergrenze, `max_notional_per_trade` als Bruchteil des Balances, Default 0.20)

## Einheiten-Contract (Cleanup 20-A)

Alle Risk-Limits sind Bruchteile des Account-Balance (fraction of balance):

| Größe | Einheit |
|-------|---------|
| `max_risk_per_trade` | Bruchteil des Balances (max. Verlust pro Trade) |
| `max_total_exposure` / `current_exposure` | Bruchteil des Balances (aggregates Open-Risk) |
| `max_notional_per_trade` | Bruchteil des Balances (Notional-Obergrenze pro Position) |
| `SizedOrder.position_size` / `qty` | Account-Währungseinheiten des Symbols (Shares/Lots) |

Vertrauensgrenze: Signal-Metadata ist **unvertrautes** Publisher-Payload. Sie darf
nur Handels-Deskriptoren liefern (Entry-Price, Stop, Take-Profit, ATR, Timeframe,
Pip-Value). Nie aus Metadata gelesen werden: `qty`/`explicit_qty` (Mengen-Override),
`max_risk_per_trade`, `max_total_exposure`, `max_positions`, `current_positions`,
`current_exposure`. Risk-Policy kommt ausschliesslich aus Deployment-/Runtime-Config
(`RiskConfig`), State (`current_positions`, `current_exposure`) aus dem
Portfolio-/Broker-Source-of-Truth. Der früher `qty`/`explicit_qty`-Bypass um die
komplette Risk-Engine ist entfernt; `risk.live.size_live_signal` size't jeden
Signal durch `RiskEngine`.

## Commission-Vorzeichen (#184 Finding 14)

`live_executions.commission` ist bei **allen** Brokern ein **positiver Kostenwert**
(Gebühr = positiv, Rebate = negativ, bekannt-null = `0.0`; ein Rebate kann nur der
cTrader-Pfad speichern, `apply_live_execution_commissions` (Alpaca-CFEE) lehnt negative Werte ab). Net-PnL ist überall
`gross - commission` (Viewer, `net_pnl`, Alpaca-CFEE-Backfill aus #143).
Adapter normalisieren vor dem Speichern: cTrader meldet `ProtoOADeal.commission`
als vorzeichenbehafteten Cashflow (Gebühr negativ) und wird über
`base_adapter.commission_cost` negiert; Alpaca meldet keine Commission (bekannte Null `0.0` oder NULL, siehe #124) und
backfillt CFEE als positive Kosten.
Bereits gespeicherte cTrader-Zeilen (vor dieser Änderung) trugen das rohe negative
Vorzeichen; `init_db` wandelt sie einmalig per Migration
(`_migrate_ctrader_commission_to_cost`, `abs` des gespeicherten Werts) in einen positiven
Kostenwert um. Nur Konten mit Broker `ctrader` sind betroffen, NULL (unbekannt) und `0.0`
bleiben. Die Migration ist in `schema_data_migrations` vermerkt und läuft genau einmal:
ein erneutes `abs` würde einen vom korrigierten Adapter gespeicherten Rebate (negativ)
in eine Gebühr verwandeln. Ein vor der Änderung gespeicherter cTrader-Rebate (roh positiv)
ist von einer neuen Gebühr nicht unterscheidbar und bleibt positiv.
`commission_cost` lehnt nicht-endliche Werte mit `ValueError` ab (kein stilles `0.0`).
Deploy-Hinweis: Daemon vor dem ersten Start des neuen Builds stoppen (siehe
`docs/live-deploy-runbook.md`); ein alter Build, der nach dem Migrationsvermerk noch eine
rohe negative Gebühr schreibt, wird nicht mehr umgewandelt.

## Broker-Raster (Alpaca)

Alpaca nimmt Bracket-/OTO-Entries nur in ganzen Stück und mit SL/TP auf dem
Preisraster an (0.01 ab 1 USD, 0.0001 darunter). `AlpacaLiveAdapter` normalisiert
jede Entry vor dem Persistieren: die risk-gesizte `qty` wird auf ganze Stück
**abgerundet** (unter 1 Stück → abgelehnt), SL und TP werden **zum Entry hin**
gerundet. Damit liegt das tatsächliche Risiko nie über dem gesizten Budget. Exit-only
Orders (simple) bleiben unverändert.

Vor dem Persistieren werden zusätzlich abgelehnt (ValueError, kein Signal-Row, keine
Order): SL/TP auf der falschen Seite des Entry, SL/TP innerhalb eines Ticks vom Entry,
fehlende/ungültige SL/TP-Level, Extended-Hours-Brackets und Crypto-Symbole (Alpaca
kennt keine Bracket-/OTO-Orders für Crypto).

## Implizite Divergenz

Der Unterschied bei `enforce_stop_direction` führt dazu, dass:

1. **Backtest**: Trades mit "falsch herum" gesetzten Stops werden akzeptiert und unterschiedlich gestartet
2. **Live**: Solche Trades werden mit `position_size=0` abgelehnt

Das verhindert unrealistische P&L im Live-Trading, erzeugt aber Abweichungen zwischen Backtest und Realität.

## Empfehlung

Der aktuelle Ansatz ist beabsichtigt: Live-Trading soll strengere Validierung haben als Backtests. Die Dokumentation hierfür ist nun vorhanden.

## Tests

Ein parametrierter Test in `tests/test_risk_consistency.py` sollte folgende Fälle abdecken:

1. Identische Inputs → identische Outputs zwischen `engine.size_*` und `live.size_*`
2. Strikter Stop-Direction Check wird im Live-Pfad erzwungen
3. ATR-basierter Fallback wird in beiden Pfaden gleich berechnet