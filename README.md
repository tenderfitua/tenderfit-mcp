<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo-light.svg" alt="TenderFit" width="360">
  </picture>
</p>

# TenderFit MCP

**MCP server for Prozorro: Ukrainian public procurement data for Claude, Cursor and any MCP client.**
Search tenders, read the full tender card, see why a buyer rejects bids, check official State Audit Service risk indicators, and look up products in the localization list. No API key needed.

One file, Python 3.9+ standard library only. Uses open public endpoints of Prozorro.

[Українською ↓](#українською)

## Tools

| Tool | What it answers |
|---|---|
| `search_tenders` | Find tenders by text, CPV, buyer/bidder EDRPOU, status, procedure type, announcement date |
| `get_tender` | Full card: buyer and contact, value, deadlines, lots, items, payment terms, criteria, documents with links, Q&A, awards with rejection reasons, contracts |
| `buyer_rejections` | How often a buyer rejects bids, top legal grounds, real wording from recent procedures |
| `buyer_risks` | Official DASU (State Audit Service) risk indicators for a buyer: rejecting several bidders, rejecting without the "24 hours" correction, ignoring appeal decisions, contract amendments |
| `tender_risks` | DASU risk indicators triggered for one tender |
| `tender_monitorings` | DASU monitorings of a tender: reasons, violation found or not, conclusion |
| `search_localized_products` | Product catalogue incl. the localization list (Ukrainian content share, Resolution 861): localization %, vendor, expiry |

## Quick start

```bash
curl -O https://raw.githubusercontent.com/tenderfitua/tenderfit-mcp/main/tenderfit_mcp.py
```

**Claude Code**

```bash
claude mcp add tenderfit -- python3 /absolute/path/tenderfit_mcp.py
```

**Claude Desktop**: Settings → Developer → Edit Config, then add:

```json
{
  "mcpServers": {
    "tenderfit": {
      "command": "python3",
      "args": ["/absolute/path/tenderfit_mcp.py"]
    }
  }
}
```

**Cursor** (`~/.cursor/mcp.json`): the same `mcpServers` block.

On Windows use `python` instead of `python3`.

## Try asking

- "Find open tenders for diesel generators over 1 million UAH with bids due in November."
- "Get tender UA-2026-09-30-010497-a. What documents do I need and when is the deadline for questions?"
- "Before I bid: how often does buyer 22927045 reject bids, and on what grounds? Any DASU risk indicators?"
- "Which products in the localization list match 'генератор дизельний' and when do their entries expire?"

## Data sources

| Endpoint | Used for |
|---|---|
| `prozorro.gov.ua/api/search` | tender and product search |
| `public-api.prozorro.gov.ua/api/2.5` | full tender data |
| `risks.prozorro.gov.ua` | DASU risk indicators ([source code](https://github.com/ProzorroUKR/prozorro-risks)) |
| `audit-api.prozorro.gov.ua` | DASU monitorings |

Limits worth knowing:
- `prozorro.gov.ua` allows about 60 requests a minute. The server paces itself, so `buyer_rejections` takes 1–2 seconds per procedure.
- Search returns at most 10 000 results per query, 20 per page.
- The risk service lists only procedures with at least one triggered indicator.
- The exact rejection reason is often only in the PDF protocol. `get_tender` gives you the document links.

This is an independent project. It is not affiliated with SE "Prozorro" or the State Audit Service. "Prozorro" is used only to name the data source.

## About

Made by [TenderFit](https://t.me/tenderfit): we check tender bids before submission so they are not rejected.
Need a check of your bid? Write to [@TenderFit_bot](https://t.me/TenderFit_bot).

Issues and pull requests are welcome. MIT License.

---

## Українською

**MCP-сервер для Prozorro: дані публічних закупівель для Claude, Cursor та інших MCP-клієнтів.** Пошук тендерів, повна картка закупівлі, причини відхилень у замовника, офіційні індикатори ризику ДАСУ, Перелік локалізованих товарів. Ключ API не потрібен.

Один файл, лише стандартна бібліотека Python 3.9+.

| Інструмент | Що дає |
|---|---|
| `search_tenders` | пошук за текстом, CPV, ЄДРПОУ замовника чи учасника, статусом, типом процедури, датою |
| `get_tender` | картка: замовник і контакт, вартість, строки, лоти, позиції, умови оплати, критерії, документи з посиланнями, питання й відповіді, рішення з причинами відхилень, договори |
| `buyer_rejections` | як часто замовник відхиляє, найчастіші підстави, формулювання з останніх процедур |
| `buyer_risks` | індикатори ризику ДАСУ по замовнику: відхилив 2+ учасників, не дав «24 години», не виконав рішення АМКУ, додаткові угоди |
| `tender_risks` | індикатори ДАСУ по одному тендеру |
| `tender_monitorings` | моніторинги ДАСУ: підстави, чи встановлено порушення, висновок |
| `search_localized_products` | каталог і Перелік локалізованих товарів: % локалізації, постачальник, строк дії запису |

Підключення — як вище: `claude mcp add tenderfit -- python3 /шлях/tenderfit_mcp.py`.

Спитайте, наприклад: «Перед подачею: як часто замовник 22927045 відхиляє пропозиції і з яких підстав? Чи є індикатори ризику ДАСУ?»

Незалежний проєкт, не пов'язаний з ДП «Прозорро» чи ДАСУ.

Зробили в [TenderFit](https://t.me/tenderfit): перевіряємо тендерні пропозиції до подачі, щоб їх не відхилили. Перевірка вашої пропозиції — [@TenderFit_bot](https://t.me/TenderFit_bot).
