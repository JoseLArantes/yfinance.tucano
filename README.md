# Tucano yfinance REST API Wrapper

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Kubernetes](https://img.shields.io/badge/Kubernetes-326CE5?style=for-the-badge&logo=kubernetes&logoColor=white)
![Helm](https://img.shields.io/badge/Helm-0F1626?style=for-the-badge&logo=helm&logoColor=white)
[![API Status](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fyfinance.tucano.beakcloud.com%2Fhealth&query=%24.status&label=Tucano%20Release%20Status&style=for-the-badge&color=success)](https://yfinance.tucano.beakcloud.com/health)

A production-grade, highly-performant REST API wrapper for `yfinance` built with **FastAPI**, **PostgreSQL** (via SQLAlchemy), and **Docker**.

This service acts as an idempotent stock data importer and dynamic cache, offering **one REST endpoint per yfinance attribute and method** (over 90+ dynamically generated endpoints) mapped automatically and documented in the OpenAPI/Swagger interface.

---

## Features

- **Dynamic API Generation**: Automatically generates GET routes for all standard `yfinance.Ticker` properties and methods (e.g. `/info`, `/calendar`, `/balance_sheet`, `/options`, `/option_chain`, etc.) on startup.
- **Idempotent Import Session**: The `/api/v1/tickers/fetch` POST endpoint fetches comprehensive data (history and attributes) and updates the registry with a distinct `sync_date`. It runs atomically in a single database transaction, preventing duplicates.
- **On-the-Fly Caching**: If a dynamic endpoint is requested but the key isn't already cached in the database, the API dynamically pulls it from Yahoo Finance on-the-fly, caches it, and returns the result.
- **Token Security**: REST API endpoints are protected using OAuth2 Bearer token authentication.
- **Production-Ready Deployments**: Fully containerized with Docker, configured with Docker Compose, and deployable to Kubernetes using Helm charts with secrets separation.

---

## Local Development (Docker)

To run the application locally using Docker Compose, follow these steps:

### 1. Configure Environment
Create a `.env` file in the root of the project (see `.env.example`):
```bash
DATABASE_URL="postgresql://tucano-yfinance:password@db:5432/tucano-yfinance"
DEFAULT_API_USERNAME="admin"
DEFAULT_API_TOKEN="apitoken"
HOST="0.0.0.0"
PORT="8009"
DEBUG="True"
```

### 2. Start the Stack
Build and run the container:
```bash
docker compose up --build -d
```

### 3. Access OpenAPI Docs
Open your browser and navigate to:
* **Swagger UI**: [http://localhost:8009/docs](http://localhost:8009/docs)
* **ReDoc**: [http://localhost:8009/redoc](http://localhost:8009/redoc)

---

## Kubernetes Deployment (Helm)

The chart is configured to pull secrets securely from a Kubernetes Secret object.

### 1. Set Up Kubernetes Secrets
Define your secrets in `deploy/helm/tucano-yfinance/templates/secrets.yaml` under `stringData` or apply the secret manually inside the `tucano-services` namespace:
```bash
kubectl create secret generic yfinance-secret \
  --from-literal=DATABASE_URL="postgresql://tucano-yfinance:password@ds.beakcloud.com:5432/tucano-yfinance" \
  --from-literal=DEFAULT_API_TOKEN="hardtofindapitoken123456" \
  --namespace tucano-services
```

If using a private container registry, configure the image pull credentials:
```bash
kubectl create secret docker-registry registry-cred \
  --docker-server=registry.beakcloud.com \
  --docker-username=registryuser \
  --docker-password=yourpassword \
  --namespace tucano-services
```

### 2. Deploy Using Helm
Run the deployment command from the project root:
```bash
helm upgrade --install tucano-yfinance deploy/helm/tucano-yfinance \
  --namespace tucano-services \
  --create-namespace
```

---

## API Usage & Endpoints

All calls (excluding `/health`) require the Bearer token in the `Authorization` header:

```bash
Authorization: Bearer <your-api-token>
```

### Endpoints Overview

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/api/v1/tickers/fetch` | Idempotently import ticker history and cache eager properties. |
| **GET** | `/api/v1/tickers` | List all unique imported tickers. |
| **GET** | `/api/v1/tickers/{ticker}/historical` | Get paginated structured historical prices. |
| **GET** | `/api/v1/tickers/{ticker}/info` | Retrieve the `info` attribute. |
| **GET** | `/api/v1/tickers/{ticker}/get_info` | Alias method to retrieve `info`. |
| **GET** | `/api/v1/tickers/{ticker}/balancesheet` | Alias to retrieve `balance_sheet`. |
| **GET** | `/api/v1/tickers/{ticker}/option_chain` | Dynamic on-the-fly retrieval of option chains. |

*(For a complete list of the 90+ endpoints and aliases, run the server and view `/docs`.)*

---

### Main attributes

- `actions`
- `analyst_price_targets`
- `balance_sheet` (alias: `balancesheet`)
- `calendar`
- `capital_gains`
- `cash_flow` (alias: `cashflow`)
- `dividends`
- `earnings`
- `earnings_dates`
- `earnings_estimate`
- `earnings_history`
- `eps_revisions`
- `eps_trend`
- `fast_info`
- `financials`
- `funds_data`
- `growth_estimates`
- `history_metadata`
- `income_stmt` (alias: `incomestmt`)
- `info`
- `insider_purchases`
- `insider_roster_holders`
- `insider_transactions`
- `institutional_holders`
- `isin`
- `major_holders`
- `mutualfund_holders`
- `news`
- `options`
- `quarterly_balance_sheet` (alias: `quarterly_balancesheet`)
- `quarterly_cash_flow` (alias: `quarterly_cashflow`)
- `quarterly_earnings`
- `quarterly_financials`
- `quarterly_income_stmt` (alias: `quarterly_incomestmt`)
- `recommendations`
- `recommendations_summary`
- `revenue_estimate`
- `sec_filings`
- `shares`
- `splits`
- `sustainability`
- `ttm_financials`
- `ttm_income_stmt` (alias: `ttm_incomestmt`)
- `upgrades_downgrades`
- `valuation`

### Main methods

- `get_actions()`
- `get_analyst_price_targets()`
- `get_balance_sheet()`
- `get_balancesheet()`
- `get_calendar()`
- `get_capital_gains()`
- `get_cash_flow()`
- `get_cashflow()`
- `get_dividends()`
- `get_earnings()`
- `get_earnings_dates()`
- `get_earnings_estimate()`
- `get_earnings_history()`
- `get_eps_revisions()`
- `get_eps_trend()`
- `get_fast_info()`
- `get_financials()`
- `get_funds_data()`
- `get_growth_estimates()`
- `get_history_metadata()`
- `get_income_stmt()`
- `get_incomestmt()`
- `get_info()`
- `get_insider_purchases()`
- `get_insider_roster_holders()`
- `get_insider_transactions()`
- `get_institutional_holders()`
- `get_isin()`
- `get_major_holders()`
- `get_mutualfund_holders()`
- `get_news()`
- `get_option_chain()`
- `get_recommendations()`
- `get_recommendations_summary()`
- `get_revenue_estimate()`
- `get_sec_filings()`
- `get_shares()`
- `get_splits()`
- `get_sustainability()`
- `get_ttm_financials()`
- `get_ttm_income_stmt()`
- `get_upgrades_downgrades()`
- `get_valuation()`
- `history()`
- `option_chain()`

---

## Official yfinance Resources

For more detailed information regarding the underlying library capabilities, check the official resources:
- **Official Source Code (GitHub)**: [https://github.com/ranaroussi/yfinance](https://github.com/ranaroussi/yfinance)
- **Official Documentation**: [https://ranaroussi.github.io/yfinance/reference/index.html](https://ranaroussi.github.io/yfinance/reference/index.html)

