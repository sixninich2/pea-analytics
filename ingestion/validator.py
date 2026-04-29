# ingestion/validator.py
"""
Pre-ingestion data validation and source confidence tagging.

Each field in each transaction row is tagged as:
  confirmed  — explicitly present and non-default in the source CSV
  inferred   — absent or defaulted by the system (fee engine, column defaults)
  missing    — required field is null or absent

Used by:
  - CLI (--ingest): prints a report; aborts if required fields are missing
                    unless --force is passed
  - Dashboard (/validate): renders a color-coded review table
"""
import pandas as pd
from datetime import date
from typing import Literal

FieldStatus = Literal["confirmed", "inferred", "missing"]

# Fields that must be non-null to proceed with ingestion
REQUIRED_FIELDS = ["date", "ticker", "quantity", "exec_price", "type"]

# Optional fields — system infers these if absent or at their default value
OPTIONAL_FIELDS_DEFAULTS: dict = {
    "fees":       0.0,         # inferred: fee engine computes if 0
    "name":       None,        # inferred: defaults to ticker string
    "asset_type": "STOCK",     # inferred: default assumption
    "market":     "EURONEXT",  # inferred: default assumption
    "currency":   "EUR",       # inferred: default assumption
}


def validate_transactions(raw_df: pd.DataFrame) -> dict:
    """
    Tag every field in every parsed row with confirmed / inferred / missing.

    Returns a dict:
      rows        — list of per-row field maps {field: {value, status}}
      summary     — {confirmed, inferred, missing, total_rows} counts
      has_missing — True if any REQUIRED field is absent or null
      warnings    — list of human-readable issue strings
    """
    present_cols = set(raw_df.columns.tolist())
    rows: list[dict] = []
    warnings: list[str] = []
    counts: dict[str, int] = {"confirmed": 0, "inferred": 0, "missing": 0}

    for idx, row in raw_df.iterrows():
        label = f"Row {idx + 1} ({row.get('ticker', '?')})"
        field_map: dict = {
            "_row":    idx + 1,
            "_ticker": str(row.get("ticker", "")),
            "_type":   str(row.get("type", "")).upper(),
        }

        # ── Required fields ─────────────────────────────────────────────────
        for field in REQUIRED_FIELDS:
            val = row.get(field)
            is_null = (
                pd.isna(val) if not isinstance(val, str)
                else val.strip() == ""
            )
            if field not in present_cols or is_null:
                status: FieldStatus = "missing"
                warnings.append(
                    f"{label}: required field '{field}' is absent or null"
                )
            else:
                status = "confirmed"
            field_map[field] = {"value": val, "status": status}
            counts[status] += 1

        # ── Optional fields ──────────────────────────────────────────────────
        for field, default in OPTIONAL_FIELDS_DEFAULTS.items():
            val = row.get(field)

            if field not in present_cols:
                status = "inferred"
                val = default
            elif _is_na(val):
                status = "inferred"
                val = default
            elif field == "fees":
                # Three states for fees:
                #   confirmed  — user provided an explicit non-zero fee in the CSV
                #   inferred   — CSV had 0; broker-rule engine computed the real amount
                #   missing    — fees column absent entirely (handled by the outer check)
                csv_fee = 0.0
                try:
                    csv_fee = float(val or 0)
                except (ValueError, TypeError):
                    pass
                if csv_fee > 0:
                    status = "confirmed"
                    # val stays as the CSV-provided fee
                else:
                    status = "inferred"
                    # Show the computed fee, not the CSV 0.0
                    computed = row.get("computed_broker_fee")
                    val = (
                        round(float(computed), 4)
                        if computed is not None and not _is_na(computed)
                        else 0.0
                    )
            elif field == "name":
                # name == ticker means it was not separately provided
                ticker_val = str(row.get("ticker", "")).strip()
                status = "inferred" if str(val).strip() == ticker_val else "confirmed"
            elif (isinstance(val, str)
                  and str(default or "").strip() != ""
                  and val.strip().upper() == str(default).strip().upper()):
                status = "inferred"
            else:
                status = "confirmed"

            field_map[field] = {"value": val, "status": status}
            counts[status] += 1

        # ── Semantic warnings ────────────────────────────────────────────────
        tx_type = field_map["_type"]
        try:
            qty    = float(row.get("quantity",   0) or 0)
            price  = float(row.get("exec_price", 0) or 0)
            tx_date = row.get("date")

            if tx_type in ("BUY", "SELL") and price <= 0:
                warnings.append(f"{label}: exec_price is zero or negative ({price})")
            if tx_type == "BUY" and qty <= 0:
                warnings.append(f"{label}: BUY with non-positive quantity ({qty})")
            if tx_type == "SELL" and qty >= 0:
                warnings.append(
                    f"{label}: SELL quantity should be negative (got {qty})"
                )
            if (tx_date and hasattr(tx_date, "year")
                    and tx_date > date.today()):
                warnings.append(f"{label}: date {tx_date} is in the future")
        except (TypeError, ValueError):
            pass

        # ── Computed TTF (informational — always engine-derived, never from CSV) ─
        computed_ttf = row.get("computed_ttf")
        if computed_ttf is not None and not _is_na(computed_ttf):
            field_map["computed_ttf"] = {
                "value":  round(float(computed_ttf), 4),
                "status": "inferred",
            }

        rows.append(field_map)

    return {
        "rows":        rows,
        "summary":     {**counts, "total_rows": len(raw_df)},
        "has_missing": counts["missing"] > 0,
        "warnings":    warnings,
    }


def validation_to_dataframe(result: dict) -> pd.DataFrame:
    """
    Flatten a validation result into a display DataFrame.

    Cell values are prefixed with status markers for dashboard colour-coding:
      confirmed  → plain value
      inferred   → "[~] value"   (tilde = computed/defaulted by system)
      missing    → "[!] MISSING"

    Fee fields (fees, computed_ttf) are formatted as €X.XXXX so the dashboard
    never collapses small non-zero amounts to 0.0.
    """
    # Fields whose values should be displayed as euro amounts
    EUR_FIELDS = {"fees", "computed_ttf"}

    flat_rows = []
    base_fields = REQUIRED_FIELDS + list(OPTIONAL_FIELDS_DEFAULTS.keys())
    # computed_ttf is appended at the end when present
    all_fields  = base_fields + ["computed_ttf"]

    for row in result["rows"]:
        flat: dict = {
            "#":      row["_row"],
            "ticker": row["_ticker"],
            "type":   row["_type"],
        }
        for field in all_fields:
            if field not in row:
                if field == "computed_ttf":
                    continue   # optional — only shown when the engine produced it
                flat[field] = ""
                continue

            val    = row[field]["value"]
            status = row[field]["status"]

            # Format the display value
            if field in EUR_FIELDS:
                try:
                    fval = float(val) if val is not None else 0.0
                    formatted = _fmt_eur(fval)
                except (TypeError, ValueError):
                    formatted = str(val)
            else:
                formatted = str(val) if val is not None else ""

            if status == "confirmed":
                flat[field] = formatted
            elif status == "inferred":
                flat[field] = f"[~] {formatted}"
            else:
                flat[field] = "[!] MISSING"

        flat_rows.append(flat)

    return pd.DataFrame(flat_rows)


def print_validation_report(result: dict, verbose: bool = True):
    """Print a human-readable validation summary to stdout."""
    s = result["summary"]
    print(f"\n  Validation report:")
    print(f"    Rows parsed:  {s['total_rows']}")
    print(f"    Confirmed:    {s['confirmed']} field values (explicitly in CSV)")
    print(f"    Inferred:     {s['inferred']} field values (system defaults)")
    print(f"    Missing:      {s['missing']} required fields")

    if result["warnings"]:
        print(f"\n  Warnings ({len(result['warnings'])}):")
        for w in result["warnings"]:
            print(f"    [WARN] {w}")

    if result["has_missing"]:
        print(
            f"\n  [ERROR] Missing required fields detected."
            f" Fix the CSV or pass --force to override."
        )
    else:
        print(f"\n  [OK] All required fields present.")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_na(val) -> bool:
    """Return True if val is None or pandas NA, ignoring string."""
    if isinstance(val, str):
        return False
    try:
        return pd.isna(val)
    except (TypeError, ValueError):
        return False


def _fmt_eur(val: float) -> str:
    """
    Format a euro amount with enough decimal places that non-zero values
    never collapse to €0.00.
      ≥ €0.01  → €X.XX   (2dp, standard)
      < €0.01  → €X.XXXX (4dp, preserves small fees)
      exactly 0 → €0.0000 (explicit zero — confirmed-free trade)
    """
    if val == 0.0:
        return "€0.0000"
    if abs(val) < 0.01:
        return f"€{val:.4f}"
    return f"€{val:.4f}"   # always 4dp for fees — precision is the point
