# Local Crypto Trading Bot

A local-first, asynchronous crypto trading engine for market data, strategy research, backtesting, realistic paper trading, guarded live execution, and local monitoring.

**Paper trading is always the command-line default.** Running `python run.py` cannot silently enter live mode, even if `TRADING_MODE=live` exists in `.env`.

> This is execution and research software—not financial advice. No included strategy is represented as profitable. Backtests and paper results do not predict live performance. Crypto trading can lose the entire amount committed.

## What is included

- Async exchange adapter built on CCXT, with rate limiting, read retries, exponential backoff, circuit breaking, and normalized data
- CCXT Pro WebSocket OHLCV streaming when the exchange advertises it, with reconnect and REST-polling fallback
- Strict OHLCV validation: missing/duplicate/out-of-order timestamps, NaN/non-finite values, invalid prices, inconsistent highs/lows, and negative volume are rejected
- Plug-in strategy boundary with EMA crossover, RSI threshold recovery, and EMA + RSI + volume confirmation examples
- Signal → risk → position → order → execution pipeline; strategies cannot submit orders
- Event-driven backtesting with next-candle-open fills, fees, slippage, risk sizing, daily loss stops, stop-loss/take-profit handling, conservative same-candle exits, and no future-candle access
- Local paper broker with market and limit orders, configurable partial fills, fees, slippage, balances, positions, stops, take profits, and realized/unrealized P&L
- SQLite/SQLAlchemy persistence in WAL mode for trades, orders, positions, balances, signals, strategy runs, backtests, events, and daily statistics
- Risk sizing by account equity and stop distance, 1% default per-trade risk, 3% daily loss halt, maximum position allocation, open-position limit, and exchange minimum validation
- Rich terminal status and a lightweight FastAPI/Jinja dashboard bound to loopback
- Persistent kill switch, signal/order idempotency, paper-state restoration, and strict live exchange reconciliation
- Explicit live confirmation plus required exchange-side stop-loss support for every new live entry
- Credential-redacting structured logs with local rotation
- 36 automated tests that never contact a real order endpoint

## Safety model

The defaults prioritize not trading over trading incorrectly:

1. No CLI mode flag means **PAPER**.
2. `--live` requires the exact phrase `I UNDERSTAND`.
3. Live settings require an API key and secret.
4. Restarted live execution remains disarmed until local positions/orders match the exchange.
5. Every new live entry must include a stop and the CCXT market feature map must advertise server-side stop-loss support.
6. A server-side protective stop is submitted immediately after an entry fill and persisted as a separate order.
7. If protective-stop submission fails, the persistent kill switch is activated and manual reconciliation is required.
8. Network timeouts during order submission are **never blindly retried**. The order is marked unknown and execution halts for reconciliation.
9. Risk-reducing exits remain allowed after the daily-loss limit; new entries do not.
10. `.env`, databases, logs, uploaded history, and generated reports are excluded from Git.

Use an exchange API key with **trading permission only**. Disable withdrawal permission. Prefer exchange-side IP restrictions where practical.

## Requirements

- Python 3.12 or newer
- Internet access for exchange market data
- No cloud server, hosted database, Redis, Kafka, or SaaS account
- SQLite is bundled with normal Python distributions

Core operation is platform-independent and has no desktop GUI dependency.

## Installation

```bash
git clone <repository-url> crypto-bot
cd crypto-bot
python3.12 -m venv .venv
source .venv/bin/activate                 # Linux/macOS
# .venv\Scripts\activate                  # Windows PowerShell
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env                      # optional; safe defaults work without it
```

Confirm the installation:

```bash
python -m pytest
python run.py --status
```

## Configuration

Configuration comes from local environment variables and `.env`. Pydantic validates ranges, related values, symbols, timeframes, modes, database locality, and the dashboard bind address at startup.

```env
EXCHANGE=binance
API_KEY=
API_SECRET=
API_PASSWORD=

TRADING_MODE=paper
DEFAULT_SYMBOL=BTC/USDT
TIMEFRAME=5m
STRATEGY=combined
POLL_INTERVAL_SECONDS=15
CANDLE_LIMIT=250

INITIAL_PAPER_BALANCE=1000
PAPER_FEE_RATE=0.001
PAPER_SLIPPAGE_BPS=5
PAPER_PARTIAL_FILL_RATIO=1.0

RISK_PER_TRADE=0.01
MAX_DAILY_LOSS=0.03
MAX_OPEN_POSITIONS=3
MAX_POSITION_PERCENT=0.25
STOP_LOSS_PERCENT=1.0
TAKE_PROFIT_PERCENT=2.0

EMA_FAST=20
EMA_SLOW=50
RSI_PERIOD=14
RSI_OVERSOLD=30
RSI_OVERBOUGHT=70
VOLUME_PERIOD=20
VOLUME_MULTIPLIER=1.0

DATABASE_URL=sqlite:///data/bot.db
LOG_LEVEL=INFO
LOG_FILE=logs/bot.log
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8000
REQUEST_TIMEOUT_SECONDS=15
MAX_RETRIES=5
```

Important validation rules include:

- `EMA_FAST < EMA_SLOW`
- `RSI_OVERSOLD < RSI_OVERBOUGHT`
- Live mode requires both key and secret
- Only local `sqlite:///...` database URLs are accepted
- The dashboard accepts only `127.0.0.1`, `localhost`, or `::1`
- Symbols use CCXT `BASE/QUOTE` notation
- Risk, fee, loss, position, and slippage values have conservative bounds

Secrets use Pydantic `SecretStr`, are absent from dashboard/status payloads, and are redacted from console and JSON logs. They are never hardcoded.

## Paper trading

Start with simulated funds and real public market data:

```bash
python run.py
# equivalent:
python run.py --paper
```

The first-run panel shows the mode, exchange, symbol, starting balance, strategy, and risk limits. The engine prefers exchange WebSocket candles when supported. Only closed candles reach a strategy; forming candles are excluded.

Paper orders never call `exchange.create_order`. The paper engine is a separate local execution service with no order-endpoint dependency. Its state is periodically persisted to `data/bot.db` and restored after a restart, including cash, positions, entry fees, and open paper orders.

A previous kill switch is cleared only when a new paper/live trading run is explicitly started. Dashboard and status commands do not clear it.

## Backtesting

### Local CSV

CSV columns must be:

```text
timestamp,open,high,low,close,volume
```

`timestamp` may be an ISO-8601 value, Unix seconds, or Unix milliseconds.

```bash
python run.py --backtest \
  --csv data/historical/BTC-USDT_5m.csv \
  --strategy ema_cross \
  --symbol BTC/USDT \
  --timeframe 5m \
  --start 2025-01-01 \
  --end 2025-06-30 \
  --initial-capital 1000
```

### Download public candles

Omit `--csv` to download through the configured exchange:

```bash
python run.py --backtest --strategy combined --symbol BTC/USDT --timeframe 5m
```

Downloaded data is validated and saved under `data/historical/`. A safety cap prevents a single command from downloading more than 100,000 candles.

Reports are written locally to `backtest_reports/` as JSON plus an equity-curve CSV and recorded in SQLite. Metrics include:

- Initial/final capital and total return
- Total/winning/losing trades and win rate
- Gross P&L, net P&L, and fees
- Profit factor, average trade, average win/loss, expectancy, largest win/loss
- Maximum drawdown, Sharpe ratio, Sortino ratio
- Average holding time

### Backtest execution assumptions

A strategy sees history only through the current candle close. Its signal can fill no earlier than the next candle open. Entry/exit slippage and both sides of fees are charged. If stop-loss and take-profit are both touched within one candle, the stop is chosen conservatively because intrabar ordering is unknowable from OHLCV data.

The model is intentionally not a tick-level exchange simulator. Results can diverge from real fills, liquidity, funding, spreads, outages, and taxes.

## Local dashboard

In a separate terminal:

```bash
python run.py --dashboard
```

Open <http://127.0.0.1:8000>. The dashboard provides:

- Local status, mode, balance, equity, P&L, positions, and win rate
- Position marks, quantities, stops, take profits, and unrealized P&L
- Trade history with fees and net P&L
- Active strategy/risk configuration
- Browser-based local CSV backtesting (10 MB upload cap)
- Persisted bot events and backtest history

The dashboard reads the same local SQLite database. It never renders credentials, has no cloud API, and refuses non-loopback binds. Starting the dashboard does not start the trading engine.

## Live trading

1. Create a trading-only API key. **Do not grant withdrawal access.**
2. Put the credentials in local `.env`.
3. Confirm the exchange, symbol, account type, minimum order rules, and CCXT support yourself.
4. Run:

```bash
python run.py --live
```

The application displays a real-money warning and requires:

```text
I UNDERSTAND
```

Live startup then loads markets and compares local open orders/positions with the exchange. Any mismatch or failed state query leaves execution disarmed. For spot exchanges without a positions endpoint, the configured symbol's base-asset total is compared with local state; unrelated holdings can therefore trigger a conservative mismatch. Resolve the account/local database state manually rather than bypassing the check.

### Live protection boundaries

Protective entry and stop submission cannot be atomic through a portable, generic CCXT interface. The implementation narrows that gap by refusing markets that do not advertise `stopLossPrice`, then placing and persisting an exchange-side stop immediately after a fill. If that second submission fails, the bot records the filled entry, activates the kill switch, and requires reconciliation.

Take-profit exits are locally monitored. Network outages can delay them. Exchange-specific OCO/bracket behavior differs and is not falsely presented as portable. Test exchange behavior with minimal capital after extensive paper testing. Do not assume exchange feature metadata guarantees identical order semantics.

## Commands

```bash
python run.py                # PAPER
python run.py --paper        # PAPER explicitly
python run.py --live         # guarded LIVE request
python run.py --backtest     # event-driven backtest
python run.py --dashboard    # loopback dashboard
python run.py --status       # persisted local status
python run.py --kill         # immediately reject all new execution
python -m pytest             # test suite; no live endpoints
```

`--kill` atomically creates `data/KILL_SWITCH`. Every execution service checks this file immediately before an order, and a running engine monitors it four times per second. Existing exchange orders are not blindly canceled: doing so without confirmed exchange state could create additional risk. Inspect and reconcile them manually.

## Crash recovery

### Paper

On restart, the engine loads the most recent cash snapshot, open positions, entry-fee state, open local orders, cumulative fees, and realized P&L from SQLite. Client-order IDs and deterministic signal IDs prevent duplicate submissions for the same closed candle.

### Live

Before arming, the engine:

1. Loads local positions and open/unknown orders.
2. Queries exchange balances, open orders, and positions where supported.
3. Compares order IDs and quantities.
4. Arms only if they match.

Unknown submission outcomes, missing protective stops, or local/exchange differences are fail-closed conditions. The discrepancy is written to logs and `bot_events`; execution does not silently continue.

## Strategy system

All strategies implement:

```python
from app.strategy.base import Strategy

class MyStrategy(Strategy):
    name = "my_strategy"
    warmup_period = 100

    def generate_signal(self, market_data, symbol):
        # market_data contains only current/past validated candles
        # return TradingSignal(BUY, SELL, or HOLD)
        ...
```

Add the module under `app/strategy/`, then register its factory in `StrategyManager`. The execution, position, risk, exchange, paper, database, and backtest engines do not need modification.

Included strategies:

- `ema_cross`: BUY when fast EMA crosses above slow EMA; SELL on the inverse cross
- `rsi`: BUY when RSI recovers above oversold; SELL when it falls below overbought
- `combined`: EMA cross plus RSI range and rolling-volume confirmation

All periods and thresholds come from `.env`. These are examples for exercising the engine, not recommendations.

## Project layout

```text
app/
├── backtest/       event loop, metrics, reports
├── config/         validated settings and redacted logging
├── database/       SQLAlchemy models, SQLite setup, repositories
├── exchange/       exchange contract, CCXT adapter, market validation/streams
├── notifications/  optional notifier interface and no-op default
├── paper/          isolated local paper broker
├── risk/           sizing and daily/account limits
├── strategy/       indicators and plug-in strategies
├── trading/        signals, orders, positions, recovery, execution gates
└── utils/          time, validation, terminal UI
dashboard/          Jinja templates and static assets
data/               ignored database and historical files
logs/               ignored structured logs
run.py              command-line entry point
tests/              unit/integration tests with exchange mocks
```

## Android / Termux

Install Termux from a maintained source, then:

```bash
pkg update
pkg install python git clang libffi openssl
termux-wake-lock                       # optional for a long paper session
git clone <repository-url> crypto-bot
cd crypto-bot
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt
cp .env.example .env
python run.py --paper
```

The engine and terminal UI need no display server. On lower-memory devices, reduce `CANDLE_LIMIT`. Keep Android battery optimization from suspending Termux during a session. The dashboard remains at `127.0.0.1:8000` and is visible only on that device by default.

Some Android/Python combinations may need to compile NumPy, pandas, or cryptography and therefore require the Termux compiler packages above. Use current Termux repositories and Python 3.12+.

## Logs and local data

- Structured rotating JSON log: `logs/bot.log`
- SQLite database: `data/bot.db`
- Historical data: `data/historical/`
- Backtest output: `backtest_reports/`
- Persistent kill switch: `data/KILL_SWITCH`

UTC is used internally. The database enables foreign keys, WAL journaling, normal synchronous mode, a busy timeout, and connection health checks.

## Testing

```bash
python -m pytest
```

The suite covers configuration, BUY/SELL/HOLD signals, malformed market data, mocked exchange mapping, minimum orders, ambiguous submissions, position sizing, maximum positions, daily-loss halts, paper buys/sells/limits/partial fills/fees/P&L, database insertion and state, recovery mismatches, dashboard secret isolation, next-candle backtesting, and guarded server-side live stops.

Automated tests do not send real orders and do not require API credentials.

## Troubleshooting

### Exchange connection fails

- Verify normal network and DNS access.
- Confirm that the exchange serves your jurisdiction and that `EXCHANGE` is a valid CCXT identifier.
- Check the exchange status page and local clock.
- Increase `REQUEST_TIMEOUT_SECONDS` for slow links.
- Market-data reads retry with backoff; persistent failure is surfaced rather than hidden.

### `BadSymbol` or no market

Use the exchange's CCXT unified symbol, usually `BTC/USDT`. Markets differ by exchange and account type.

### Bot says there is insufficient candle history

Increase `CANDLE_LIMIT` to exceed the largest indicator warmup (EMA 50 by default plus one prior candle).

### Live reconciliation fails

Do not delete state just to suppress the warning. Compare exchange balances/open orders with `python run.py --status`, the local dashboard, and exchange UI. Resolve/cancel orders safely, then restart. Spot base-asset holdings unrelated to the bot intentionally cause a mismatch for the configured symbol.

### Live entry says server-side stop loss is unsupported

The exchange/market did not advertise the CCXT `stopLossPrice` feature. The bot fails closed. Use paper mode or implement and test an exchange-specific protected-order adapter; do not bypass the guard casually.

### Dashboard is unreachable from another device

That is the secure default. It binds only to loopback and intentionally cannot be exposed by setting `0.0.0.0`. Use it on the same computer/device.

### SQLite is locked

Only one trading engine should write a given database. The dashboard may read it concurrently. Stop duplicate engines and retry; WAL and a five-second busy timeout are already enabled.

### Native package installation fails on Termux

Update Termux, install `clang libffi openssl`, upgrade `pip`/`wheel`, and use a Python version for which dependencies provide compatible builds.

## Deliberate non-features

- No cloud backend, hosted database, telemetry, or public dashboard bind
- No withdrawal support
- No profitability claims or parameter optimization claims
- No blind retry of order submission
- No fake promise that local monitoring can eliminate exchange/network risk
- No Redis, Kafka, Kubernetes, or heavyweight frontend

The software provides local execution controls and transparent accounting. Strategy profitability remains an unproven, separate concern.
