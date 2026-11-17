# Live Integration Deploy Runbook

Status: credential-gated as of 2026-07-13.

## Preconditions

- `.accounts.env` exists and remains gitignored.
- Alpaca account blocks `ACC1..3` (Nitro, RamJet, RocketFuel) contain paper endpoints only; IDs werden aus `.accounts.env` aufgeloest, nicht hier dokumentiert.
- Discord bot tokens and channel IDs are set for Nitro, RamJet, and RocketFuel.
- cTrader credentials are demo credentials if the cTrader smoke is run.
- Trailing stops are not executed live yet (#167). A deployment whose
  `signal_config.signal_processor_config.trailing_mode` is anything other than `none` is rejected
  when it is created or parsed from YAML. A stored deployment that already has such a value still
  loads (so it stays listed and can be stopped), the daemon logs an error for it at load, and each
  of its signals is refused before it reaches the broker. See `shared/trailing.py` and
  `docs/signal_bots.md`.

## Strategy Promotion Gate (#165)

Only code a named human reviewer promoted to `production` may trade on a
**real-money** account. Paper/demo accounts run `experimental` code without
promotion. There are only these two stages.

### Relation to the demo-only block

The platform already hard-blocks real money: the daemon refuses any broker
adapter that is not provably demo/paper (`_adapter_is_demo`, "refusing
continued use"), and the viewer refuses to activate a deployment unless the
broker reports a demo account. **That block stays.** The promotion gate is an
additional layer under it, not a replacement. Today a promoted strategy on a
real-money account therefore still cannot trade: preflight passes the gate,
but the daemon will not keep a non-demo adapter and the viewer will not arm the
deployment. Lifting the demo-only block is a separate, deliberate step.

### Required evidence and thresholds

| Evidence | Requirement | Default |
|---|---|---|
| Out of sample | Optimization result (#164) with `three_way.overfitting.passed == true`; untouched test segment length and trade count | ≥ 180 days, ≥ 50 trades |
| Paper trading | Paper/demo run duration and trade count, with a report file | ≥ 60 days, ≥ 30 trades |
| Parity | Cross-engine or reference parity: relative deviation of every compared metric | ≤ 2 % |

No max-drawdown bound. Defaults live in
`runner.promotion_gate.PromotionThresholds`; override them with a
`promotion_thresholds.json` at the repository root (keys
`min_test_segment_days`, `min_test_trade_count`, `min_paper_trading_days`,
`min_paper_trade_count`, `max_parity_deviation`). An unknown key or a malformed
file makes nothing `production`. The thresholds in force are applied when a
promotion is recorded **and** every time it is checked, so raising a
threshold demotes promotions that no longer meet it.

For a strategy, the out-of-sample result must be for the same strategy file
name, and its `effective_best_parameters` must equal the bound parameter set.
A signal bot's processor is not what the optimizer runs, so for a bot only the
verdict, window and trade count are checked; name the result that backs the
bot's logic.

### What a promotion is bound to

A promotion is bound to the SHA256 of one file **and** the SHA256 of a
canonical parameter set (JSON, sorted keys, `10` and `10.0` equal). Change one
byte or one parameter and the code is `experimental` again.

| Deployment | Hashed file | Bound parameters |
|---|---|---|
| Strategy (no `signal_processor`) | `strategies/<strategy_name>/<strategy_name>.py` | `STRATEGY_META["parameters"]` defaults |
| Signal bot (`signal_config.signal_processor` set) | `signal_bots/<bot>/processor.py` | processor id, `signal_config.signal_processor_config`, SHA256 of the bot's `config.yaml`, SHA256 of every repository module the processor imports |

A signal bot's import closure is the set of repository modules Python executes to
load its processor: the modules it imports, the packages those modules live in
(their `__init__.py` runs on import, and `signal_bots/__init__.py` imports every
bot), transitively. Standard-library and third-party modules are not bound. A
change to any bound module makes that bot `experimental` again, including a
change to another bot's processor or to a shared model. Imports that are not
static (`importlib`, `__import__`) are not visible to the gate and are a
reviewer responsibility.

No live code path applies per-deployment strategy parameters, so a strategy is
promoted with its `STRATEGY_META` defaults: write optimised parameters into the
file, then promote. A deployment that carries `settings.strategy_parameters` is
refused on real money. Other `settings` keys (risk limits, selection metadata)
are not strategy parameters and are not bound. A Discord deployment without a
`signal_processor` has nothing to hash unless a strategy of the same name
exists, so it is refused on real money.

The ledger is `<file>.promoted.json` next to the hashed file (for example
`strategies/foo/foo.py.promoted.json`) and must be committed: the promotion is
only in force where the ledger is. It follows `runner/approval_gate.py` and
reuses its hashing and atomic-write helpers. A missing, unreadable or malformed
ledger, a missing strategy file or unreadable `STRATEGY_META`, an unknown
processor: all mean `experimental`, and the deployment is refused on real money.

### Recording a promotion (CLI only)

```bash
uv run python -m runner.cli promote \
    --strategy example_sma \
    --promoted-by "Jane Doe" \
    --optimization-result optimizations/opt-123.json \
    --paper-account-id 10105152 --paper-broker ctrader \
    --paper-start 2026-08-01 --paper-end 2026-10-15 --paper-trades 42 \
    --paper-report docs/reports/paper_example_sma.csv \
    --parity-reference lean \
    --parity-deviation total_return=0.012 --parity-deviation sharpe_ratio=0.008 \
    --parity-report docs/reports/parity_example_sma.json
```

For a signal bot use `--signal-processor ramjet` and pass the deployment's
`signal_processor_config` as `--params '{...}'` (`--params` is refused for a
strategy). The out-of-sample evidence is read from the result file, not typed
in. Both report files must exist; their SHA256 is recorded. Every argument is
mandatory, and the command exits non-zero without writing anything if any
evidence is missing or below a threshold.

### Enforcement points (fail closed)

All of them call the one function `live_runner.promotion.enforce_promotion_gate`
with the deployment and their own real-money verdict, taken from the same
source the demo-only block uses there. Unknown means real money.

| Point | Real-money verdict |
|---|---|
| `live_runner.preflight` (every configured deployment) | the paper/demo mode preflight resolved from the credentials |
| Daemon, `prepare_order_with_risk` (every entry order, internal and Discord) | `_adapter_is_demo(adapter)` |
| Viewer `POST /api/live/deployments` (created `ACTIVE`) | broker discovery `is_demo` (asserted) |
| Viewer `PUT /api/live/deployments/{id}/status` → `ACTIVE` | the fresh broker re-verification |
| Viewer `POST /api/live/deployments/ctrader/top5`, dry run included | broker discovery `is_demo` (asserted) |

The viewer answers HTTP 409 with the reason. Exit-only orders are never blocked:
closing a position must not depend on a promotion. The daemon check runs on
every entry, so a deployment edited after activation is caught at order time.

## Provisioning and Rotation

Provision the deployment file from `live_deployments.example.yaml` into the
ignored `live_deployments.yaml`. Replace every environment placeholder with a
value obtained from the broker or Discord administration console; do not copy
account references, channel IDs, or author IDs into the example or any tracked
file.

Keep secrets and account references in the ignored `.accounts.env` and local
deployment file. When a broker account, API key, OAuth token, Discord channel,
or trusted author changes, provision the replacement through the provider,
update the local files, run the non-ordering preflight, and revoke the old
credential or access grant. Keep deployments paused until paper verification is
complete. Account references are routing metadata rather than secrets, but they
must still be rotated when an account is retired or reassigned.

## Non-Ordering Preflight

```bash
uv sync --all-extras
uv run python -m live_runner.preflight --config live_deployments.yaml --accounts-env .accounts.env
uv run python scripts/live_smoke.py --mode discord-replay --reports-dir docs/reports
```

The preflight prints exactly one JSON document on stdout (parseable with `jq`); its log lines go to stderr.

`${VAR}` references in the deployment file expand here with the precedence every
other live_runner component resolves configuration with: a key defined in
`--accounts-env` wins - and a key present there but empty stays empty, so
blanking it disables it - while the process environment fills only keys the file
does not define. A reference that resolves nowhere fails the preflight and names
the variable, so a literal `${...}` never reaches the daemon. Credentials
themselves resolve from the file only, so a credential that exists only in the
process environment is reported as missing rather than borrowed; aligning that
with the daemon's env-filled credential resolution is an open decision, not a
bug.

An accounts env file that exists but cannot be read logs a warning and fails the
preflight with missing credentials. A config that fails to parse or validate is
reported, not crashed on: `deployment_errors` names the error type and the
offending field, and never an expanded value - that value can be a credential,
and `deployment_errors` is printed as JSON. This holds for every exception raised
while parsing, not only validation errors. A YAML syntax error reports its
problem and its line and column, never the source line, which can hold a literal
secret. Redaction covers the values of every accounts env file key and every
process-env key the config references through `${VAR}` or `$VAR`, so a secret
that only lives in the process environment is reported as `${VAR}` too. Process-env
keys the config never names are not redacted. The cTrader `CTRADER_DEMO` error,
which quotes the rejected value, is redacted the same way: every accounts env file
value is redacted there. A missing or unreadable config file is the one case that
still crashes: the JSON document names the path, and the traceback goes to stderr
and the log at ERROR. That traceback, like the JSON document, is redacted with
every accounts env file value and every process-env value, because the config is
not re-read after a crash and its references are unknown. Only the exception type
remains in the JSON if the accounts env file cannot be resolved at all, and then
no traceback is printed.

## Paper Broker Smoke

For Alpaca smoke, first verify every Alpaca account resolves with `paper=True`.
For cTrader smoke, verify the configured cTrader credentials are demo credentials.

```bash
uv run python scripts/live_smoke.py --mode alpaca --accounts-env .accounts.env --reports-dir docs/reports
uv run python scripts/live_smoke.py --mode ctrader --accounts-env .accounts.env --reports-dir docs/reports
```

Both cTrader smoke order paths - the order worker (`--mode ctrader-order-worker`) and the
strategy-e2e worker (`--mode ctrader-e2e-worker`) - anchor on a live price (the close of the latest
M1 trendbar) with a real stop-loss and take-profit 0.5 % away. Each fails with a clear message when
the market is closed (no M1 bar in the last 30 minutes) rather than building an order on an
invented price.

The cTrader smoke registers the demo account in `live_accounts` if it is not there yet (a fresh
database), because its parent deployment row has a foreign key to it. An account that already
exists is left untouched.

## Demo Daemon

Only run after the paper smoke succeeds.

```bash
set -a
. ./.accounts.env
set +a
set -o pipefail
uv run python -m live_runner.daemon 2>&1 | tee "docs/reports/live_daemon_$(date -u +%Y%m%dT%H%M%SZ).log"
```

> NOTE (Stand 2026-09): `daemon.main()` nimmt kein `--config` — Config kommt aus der DB via `shared/database.list_live_deployments`, nicht aus `live_deployments.yaml`.

Keep the daemon running long enough to verify Discord connection, paper order submission, fill handling, and `reconcile_executions`.

## Market-data symbol classification (Alpaca, #122)

`live_runner/symbol_class.py` decides which feed a symbol belongs to, by *asset class* and never by string shape alone: a pair is recognised only when its base currency is in `CRYPTO_BASES` and its quote currency is in `CRYPTO_QUOTES` (that quote list is shared with `shared/alpaca_symbols.py`, so fee backfill and market-data routing cannot drift on it). Share-class equities (`BRK.B`, `BF-B`) are equities, exactly as in the fee backfill.

Anything else is refused, not guessed: `refresh_from_deployments` logs "Refusing to subscribe unclassifiable symbol to market data" with the deployment id and skips it, so that symbol gets no quotes. Fail closed on purpose — a crypto pair routed to the stock feed produces no bars either, but silently. A new coin Alpaca lists has to be added to `CRYPTO_BASES`; an unknown six-letter ticker is a config error, not a fed fallback.

Bars are keyed by canonical pair (`BTC/USD`) in every spelling (`BTCUSD`, `btc-usd`), on the manual/backfill ingest path and on the live `_on_bar` callback alike, so a quote lookup cannot miss bars that arrived in the other form. A bar that still arrives under an unclassified symbol is stored under its own spelling and logged ("Storing market-data bars under an unclassified symbol key") rather than dropped in silence.

## Execution prices and commissions (Alpaca, #124)

- `live_executions.commission` is nullable. `0.0` is a known zero (Alpaca equities); `NULL` means the fee is not known yet. Every reader treats `NULL` as "net PnL incomplete", never as zero: the live stats payload reports `net_pnl: null`, `net_pnl_complete: false` and `commission_unknown_count`, and trade/signal payloads carry `commission: null`.
- Alpaca crypto fees are posted end of day as `CFEE` account activities, so crypto fills are stored with `NULL`. The daemon's hourly `commission-backfill` task reads `FILL`, `CFEE` and `FEE` activities over REST, once a trade date is two UTC days old and for fills up to 30 days back, allocates each (pair, trade date)'s fee pro rata by received quantity, converts it to USD and writes it. Everything it cannot attribute unambiguously stays `NULL` and is logged ("Alpaca commission backfill: leaving ..."); see `live_runner/alpaca_fees.py` for the rules.
- The schema migration rebuilds `live_executions` once to drop the `NOT NULL` and turns the hard-coded `0.0` on existing Alpaca fills into `NULL` unless the symbol is provably an equity (`shared/alpaca_symbols.py`): crypto in either spelling (`BTC/USD`, `BTCUSD`) and anything unclassifiable (options, malformed symbols) become unknown. The backfill logs every unknown-commission execution it skips, with the reason (not crypto, trade date not posted yet).
- `actual_price_observed` labels every Alpaca price: `observed` (stated for this fill), `derived` (computed from broker prices: the order's `filled_avg_price` on a single-fill order, or a reconciled remainder), `sent_bad`/`absent` (no usable price), `derived_unavailable` (the remainder's price could not be derived honestly). A stream event never borrows the order's cumulative average for a partial fill.
- A reconciled fill whose order has no usable `filled_avg_price` is not stored; the next reconciliation pass (adapter connect) retries it. Otherwise the missing QUANTITY is always stored. Its price is `(avg*broker_qty - sum(local price*qty)) / missing_qty`, labelled `derived`, when every local leg has a usable price and the result lies within 10% of the order's average (`REMAINDER_PRICE_MAX_REL_DEVIATION`); otherwise it is stored at `0.0` with `derived_unavailable`, so exit sizing and duplicate-order protection still see the quantity.
- Every PnL reader treats a `sent_bad`/`absent`/`derived_unavailable` (or non-positive) price as unknown: API rows carry `actual_price: null` and `slippage: null`, and live stats report `total_pnl: null`, `pnl_complete: false` and `price_unknown_count`; the frontend shows "incomplete" instead of a number.
