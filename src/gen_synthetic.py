# Generated at: 2026-05-31 20:37:33 MSK
"""Generate synthetic public event data for local boot and CI."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd


PRODUCTS = [f"PROD_{idx:02d}" for idx in range(1, 40)]
FAMILIES = [
    "FAM_BOX",
    "FAM_SUBSCRIPTION",
    "FAM_DEVICE",
    "FAM_ADDON",
    "FAM_SERVICE",
    "FAM_MIGRATION",
]
FAMILY_PRODUCTS = {
    "FAM_BOX": PRODUCTS[:24],
    "FAM_SUBSCRIPTION": PRODUCTS[24:30],
    "FAM_DEVICE": PRODUCTS[30:33],
    "FAM_ADDON": PRODUCTS[33:36],
    "FAM_SERVICE": PRODUCTS[36:37],
    "FAM_MIGRATION": PRODUCTS[37:39],
}
SEGMENTS = [f"SEG_{idx}" for idx in range(7)]
LIFECYCLE_ROLES = [
    "primary",
    "renewal",
    "replacement",
    "migration",
    "test",
    "special",
]
START_YEAR = 2019
END_YEAR = 2025
QUARTERS = (END_YEAR - START_YEAR + 1) * 4


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _share(value: str) -> float:
    parsed = float(value)
    if parsed < 0 or parsed > 1:
        raise argparse.ArgumentTypeError("share must be in [0, 1]")
    return parsed


def _fake_client_id(seed: int, idx: int) -> str:
    digest = hashlib.sha1(f"{seed}-{idx}".encode()).hexdigest()[:12]
    return f"C{digest}"


def _client_counts(rows: int, rng: np.random.Generator) -> np.ndarray:
    client_count = max(1, min(rows, int(rows * 0.32)))
    counts = np.ones(client_count, dtype=int)
    remaining = rows - client_count
    if remaining > 0:
        weights = rng.gamma(shape=0.55, scale=1.0, size=client_count)
        weights = weights / weights.sum()
        counts += rng.multinomial(remaining, weights)
    return counts


def _exact_flags(rows: int, share: float, rng: np.random.Generator) -> np.ndarray:
    flags = np.zeros(rows, dtype=bool)
    true_count = int(round(rows * share))
    if true_count:
        flags[rng.choice(rows, size=true_count, replace=False)] = True
    return flags


def _family_targets(rows: int, box_share: float) -> dict[str, int]:
    box_count = int(round(rows * box_share))
    rest_count = rows - box_count
    rest_weights = np.array([0.35, 0.22, 0.18, 0.14, 0.11], dtype=float)
    raw_counts = rest_weights / rest_weights.sum() * rest_count
    rest_counts = np.floor(raw_counts).astype(int)
    rest_counts[-1] += rest_count - int(rest_counts.sum())

    targets = {"FAM_BOX": box_count}
    targets.update(
        {
            family: int(count)
            for family, count in zip(FAMILIES[1:], rest_counts)
        }
    )
    return targets


def _pick_family(
    preferred: str,
    targets: dict[str, int],
    rng: np.random.Generator,
) -> str:
    available = [family for family, count in targets.items() if count > 0]
    if preferred in available and rng.random() < 0.72:
        return preferred

    weights = np.array([targets[family] for family in available], dtype=float)
    weights = weights / weights.sum()
    return str(rng.choice(available, p=weights))


def _pick_product(
    family: str,
    favorites: dict[str, list[str]],
    rng: np.random.Generator,
) -> str:
    products = FAMILY_PRODUCTS[family]
    family_favorites = favorites[family]
    if family_favorites and rng.random() < 0.72:
        return str(rng.choice(family_favorites))
    return str(rng.choice(products))


def _client_profile(
    client_idx: int,
    seed: int,
    rng: np.random.Generator,
) -> dict[str, object]:
    segment = str(
        rng.choice(
            SEGMENTS,
            p=np.array([0.28, 0.20, 0.16, 0.12, 0.10, 0.08, 0.06]),
        )
    )
    segment_family = {
        "SEG_0": "FAM_BOX",
        "SEG_1": "FAM_BOX",
        "SEG_2": "FAM_SUBSCRIPTION",
        "SEG_3": "FAM_DEVICE",
        "SEG_4": "FAM_ADDON",
        "SEG_5": "FAM_SERVICE",
        "SEG_6": "FAM_MIGRATION",
    }[segment]
    preferred_family = str(
        rng.choice(
            [segment_family, "FAM_BOX"],
            p=[0.82, 0.18] if segment_family != "FAM_BOX" else [1.0, 0.0],
        )
    )
    favorites = {}
    for family, products in FAMILY_PRODUCTS.items():
        size = min(len(products), 2)
        favorites[family] = list(rng.choice(products, size=size, replace=False))

    return {
        "client_id": _fake_client_id(seed, client_idx),
        "segment": segment,
        "preferred_family": preferred_family,
        "favorites": favorites,
    }


def _quarter_sequence(count: int, rng: np.random.Generator) -> list[int]:
    start_max = max(1, QUARTERS - min(count, 8))
    quarter = int(rng.integers(0, start_max))
    values = [quarter]
    for _ in range(1, count):
        if quarter < QUARTERS - 1 and rng.random() < 0.56:
            quarter += 1
        elif quarter < QUARTERS - 4 and rng.random() < 0.25:
            quarter += 4
        elif quarter < QUARTERS - 1:
            quarter = int(rng.integers(quarter + 1, QUARTERS))
        values.append(quarter)
    return values


def _ts_in_quarter(quarter_idx: int, rng: np.random.Generator) -> pd.Timestamp:
    year = START_YEAR + quarter_idx // 4
    quarter = quarter_idx % 4 + 1
    period = pd.Period(f"{year}Q{quarter}", freq="Q")
    days = (period.end_time.normalize() - period.start_time).days + 1
    return (
        period.start_time
        + pd.Timedelta(days=int(rng.integers(0, days)))
        + pd.Timedelta(seconds=int(rng.integers(0, 24 * 60 * 60)))
    )


def _build_rows(
    rows: int,
    seed: int,
    box_share: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    targets = _family_targets(rows, box_share)
    records = []

    for client_idx, count in enumerate(_client_counts(rows, rng)):
        profile = _client_profile(client_idx, seed, rng)
        prev_product = None
        prev_family = None
        prev_quarter = None

        for quarter_idx in _quarter_sequence(int(count), rng):
            product = None
            family = None
            role = None
            is_next_quarter = (
                prev_quarter is not None and quarter_idx == prev_quarter + 1
            )
            if (
                is_next_quarter
                and prev_family is not None
                and targets.get(prev_family, 0) > 0
                and rng.random() < 0.78
            ):
                family = prev_family
                product = prev_product
                role = "renewal"

            if family is None or product is None:
                family = _pick_family(
                    str(profile["preferred_family"]),
                    targets,
                    rng,
                )
                product = _pick_product(
                    family,
                    profile["favorites"],  # type: ignore[arg-type]
                    rng,
                )
                role = str(
                    rng.choice(
                        LIFECYCLE_ROLES,
                        p=np.array([0.66, 0.15, 0.07, 0.05, 0.05, 0.02]),
                    )
                )

            targets[family] -= 1
            ts = _ts_in_quarter(quarter_idx, rng)
            records.append(
                {
                    "client_id": str(profile["client_id"]),
                    "ts": ts,
                    "year": int(ts.year),
                    "quarter": int(ts.quarter),
                    "product": product,
                    "product_family": family,
                    "segment": str(profile["segment"]),
                    "lifecycle_role": role,
                }
            )
            prev_product = product
            prev_family = family
            prev_quarter = quarter_idx

    data = pd.DataFrame.from_records(records)
    if len(data) > rows:
        data = data.sample(n=rows, random_state=seed).reset_index(drop=True)
    return data.sort_values(["client_id", "ts", "product"]).reset_index(drop=True)


def _add_pseudo_flags(
    data: pd.DataFrame,
    pseudo_share: float,
    empty_client_share: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    if empty_client_share > pseudo_share:
        raise ValueError("empty_client_share must be <= pseudo_share")

    data = data.copy()
    flags = _exact_flags(len(data), pseudo_share, rng)
    data["inn_is_pseudo"] = flags

    empty_count = int(round(len(data) * empty_client_share))
    if empty_count:
        pseudo_idx = np.flatnonzero(flags)
        empty_count = min(empty_count, len(pseudo_idx))
        chosen = rng.choice(pseudo_idx, size=empty_count, replace=False)
        data.loc[chosen, "client_id"] = ""
    return data


def _add_revenue_proxy(data: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    data = data.copy()
    revenue_proxy = np.full(len(data), np.nan, dtype=float)
    filled = _exact_flags(len(data), 0.08, rng)
    revenue_proxy[filled] = np.round(
        rng.lognormal(mean=8.0, sigma=0.6, size=int(filled.sum())),
        2,
    )
    data["revenue_proxy"] = revenue_proxy
    return data


def _recurrence_stats(data: pd.DataFrame) -> tuple[int, int]:
    events = data.loc[data["client_id"] != "", ["client_id", "product", "year", "quarter"]]
    events = events.drop_duplicates().copy()
    events["q_idx"] = (events["year"] - START_YEAR) * 4 + events["quarter"] - 1
    events = events.sort_values(["client_id", "product", "q_idx"])
    prev = events.groupby(["client_id", "product"])["q_idx"].shift(1)
    events["is_recur_next_q"] = events["q_idx"].sub(prev).eq(1)
    per_product = events.loc[events["is_recur_next_q"]].groupby("product").size()
    return int((per_product >= 15).sum()), int(events["is_recur_next_q"].sum())


def build_synthetic(
    rows: int,
    seed: int,
    box_share: float,
    pseudo_share: float,
    empty_client_share: float,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = _build_rows(rows, seed, box_share, rng)
    data = _add_pseudo_flags(data, pseudo_share, empty_client_share, rng)
    data = _add_revenue_proxy(data, rng)
    return data[
        [
            "client_id",
            "ts",
            "year",
            "quarter",
            "product",
            "product_family",
            "segment",
            "lifecycle_role",
            "inn_is_pseudo",
            "revenue_proxy",
        ]
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic public event data.",
    )
    parser.add_argument("--rows", type=_positive_int, default=40000)
    parser.add_argument("--out", default="data/sample_synth.parquet")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--box-share", type=_share, default=0.85)
    parser.add_argument("--pseudo-share", type=_share, default=0.22)
    parser.add_argument("--empty-client-share", type=_share, default=0.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = build_synthetic(
        rows=args.rows,
        seed=args.seed,
        box_share=args.box_share,
        pseudo_share=args.pseudo_share,
        empty_client_share=args.empty_client_share,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(out, engine="pyarrow", index=False)
    recur_products, recur_pairs = _recurrence_stats(data)

    print(f"path={out}")
    print(f"rows={len(data)}")
    print(f"unique_client_id={data['client_id'].nunique()}")
    print(f"fam_box_share={(data['product_family'] == 'FAM_BOX').mean():.4f}")
    print(f"inn_is_pseudo_share={data['inn_is_pseudo'].mean():.4f}")
    print(f"products_recurrence_ge_15={recur_products}")
    print(f"next_quarter_positive_pairs={recur_pairs}")


if __name__ == "__main__":
    main()
