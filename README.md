# Intraday Momentum Strategy on SPY

Replication of the intraday momentum strategy from Zarattini, Aziz & Barbon (2025), *Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY)*, on 30-minute SPY data from January 2016 to October 2026, with an extension that reduces exposure on calm market days.

## Overview

For each time of day, the strategy estimates a *Noise Area*: the range within which SPY usually moves relative to its open. A price outside this range indicates an imbalance between supply and demand, and the strategy trades in the direction of the move.

- **Long** when the price is above the upper band, **short** when it is below the lower band.
- Positions are checked every 30 minutes (10:00 – 15:30) and closed at 16:00; nothing is held overnight.
- Two extensions from the paper: a **VWAP trailing stop** and **volatility-targeted position sizing**.
- Own extension: **halving the position on calm days** (VIX below its lower tercile).

The backtest includes commissions and slippage and is evaluated on a chronological train/test split (train 2016–2021, test 2022 – Oct 2026).

## Repository structure

```
.
├── momentum_strategy.ipynb  # main analysis: strategy, backtest, evaluation, extension
├── get_data.py              # downloads the data into ./data
├── data/
│   ├── spy_30min.csv        # SPY 30-minute bars, regular trading hours
│   ├── spy_daily.csv        # SPY daily prices (incl. adjusted close)
│   └── vix_daily.csv        # VIX daily prices
├── .gitignore
└── README.md
```

## Data

| File | Source | Content |
|---|---|---|
| `spy_30min.csv` | [Alpaca Market Data API](https://alpaca.markets/) | SPY 30-minute bars (SIP feed, all US exchanges), raw prices, regular trading hours |
| `spy_daily.csv` | Yahoo Finance (`yfinance`) | SPY daily open, high, low, close, adjusted close |
| `vix_daily.csv` | Yahoo Finance (`yfinance`) | VIX daily open, high, low, close |

Intraday data were downloaded with free Alpaca API keys. The free plan provides historical SIP data from 2016 onwards, which determines the start of the sample. Early-close days are identified with Alpaca's market calendar, and only regular-hours bars are kept.

## Getting started

**Requirements:** Python 3.9+

```bash
git clone https://github.com/svettelnova/intraday-momentum-spy.git
cd intraday-momentum-spy
pip install numpy pandas matplotlib statsmodels yfinance alpaca-py
```

**Data.** The CSV files are included in `data/`. To download them again, create a `.env` file in the project folder with your Alpaca keys:

```
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
```

and run:

```bash
python get_data.py
```

The script also prints data checks (missing bars, duplicates, comparison of intraday and daily prices).

**Analysis.**

```bash
jupyter notebook momentum_strategy.ipynb
```

Run all cells; the full notebook runs in about a minute.

## Notebook outline

The analysis is in `momentum_strategy.ipynb`. Each section builds on the previous one.

| Section | What it does |
|---|---|
| **0. Parameters** | Sets commission, slippage, the 14-day lookback, the 2% volatility target, the 4× leverage cap and the train/test dates. All values are taken from the paper. |
| **1. Data** | Loads the 30-minute bars and reshapes them into tables with one row per day and one column per time of day: prices, daily open and close, and the cumulative VWAP since the open. |
| **2. Noise Area** | For each time of day, computes the average absolute move from the open over the previous 14 days and builds the upper and lower bands. Plots 20 January 2022, the example day used in the paper. |
| **3. Signals and positions** | Compares the price with the bands every 30 minutes and sets the position (long, short or flat) for the base strategy and for the version with a VWAP trailing stop. |
| **4. Sizing, costs and backtest** | Converts positions into money: leverage (fixed or volatility-targeted), number of shares, gross P&L, commissions and slippage, and daily compounding of capital. Adds SPY buy and hold as a benchmark. |
| **5. Evaluation** | Computes annualized return, volatility, Sharpe ratio, maximum drawdown and hit ratio for the train and test periods, plots equity curves, and compares the results with SPY and with the paper. |
| **5.1 Split robustness** | Explains the choice of the end-2021 split, repeats the evaluation for alternative split dates and tests for a structural break at the split (Chow test with robust standard errors). |
| **6. Extension** | Tests whether halving the position on calm days (VIX below its lower tercile) improves the strategy: VIX statistics for each period, performance by volatility regime with block-bootstrap confidence intervals, stability over time, backtest of the rule and discussion of the results. |

## Methodology

**Noise Area.** For each time of day $T$, $\sigma_{t,T}$ is the average absolute move from the open over the previous 14 days. The bands are

$$UB_{t,T} = \max(Open_t, Close_{t-1})(1+\sigma_{t,T}), \qquad LB_{t,T} = \min(Open_t, Close_{t-1})(1-\sigma_{t,T}).$$

**Position sizing.** The number of shares is fixed for the day, $N_t = \lfloor AUM_{t-1} L_t / Open_t \rfloor$, with leverage $L_t = \min(4,\ 0.02/\sigma_{SPY,t})$ for the volatility-targeted version, where $\sigma_{SPY,t}$ is the standard deviation of the last 14 daily SPY returns.

**Evaluation.** Annualized return, volatility, Sharpe ratio, maximum drawdown and hit ratio for train and test periods, compared with SPY buy and hold. The extension is assessed with VIX regimes defined by terciles and block-bootstrap confidence intervals.

All parameters (14-day lookback, 2% volatility target, 4× leverage cap, costs) are taken from the paper; none is estimated on the data.

## Assumptions

- Costs: \$0.0035 commission (Interactive Brokers entry tier) and \$0.001 slippage per share, as in the paper.
- Trades are filled at the close of the 30-minute bar ending at the check time.
- No financing costs, since no position is held overnight.
- Sharpe ratio with a risk-free rate of 0.
- 30-minute bars instead of 1-minute data; checks take place at the same times as in the paper (HH:00 and HH:30).

## Reference

Zarattini, C., Aziz, A., & Barbon, A. (2025). *Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY).*

