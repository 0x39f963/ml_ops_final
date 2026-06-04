"""Streamlit demo for the NBO scoring API."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
from typing import Any

import altair as alt
import pandas as pd
import requests
import streamlit as st


FALLBACK_REF_DATE = "2026Q1"
PRODUCT_FAMILIES = [
    "",
    "software_box",
    "hardware_license",
    "software_cloud",
    "infra",
    "addon",
]
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("DEMO_API_TIMEOUT_SECONDS", "8"))
INN_RE = re.compile(r"^\d{10,12}$")


def api_base_url() -> str:
    configured = os.environ.get("API_BASE_URL")
    if configured:
        return configured.rstrip("/")
    port = os.environ.get("NBO_API_PORT") or os.environ.get("API_PORT") or "8000"
    return f"http://localhost:{port}"


def sample_path() -> Path | None:
    env_path = os.environ.get("SAMPLE_SYNTH_PATH")
    events_path = os.environ.get("EVENTS_PARQUET")
    candidates = []
    if env_path:
        candidates.append(Path(env_path).expanduser())
    if events_path:
        candidates.append(Path(events_path).expanduser())
    root = Path(__file__).resolve().parents[1]
    candidates.extend(
        [
            root / "data" / "sample_synth.parquet",
            Path.cwd().parent / "data" / "sample_synth.parquet",
        ]
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


@st.cache_data(ttl=300)
def load_sample_ids() -> dict[str, list[str]]:
    path = sample_path()
    if path is None:
        return {"scorable": [], "not_scorable": []}

    data = pd.read_parquet(path, columns=["client_id", "product", "inn_is_pseudo"])
    data["client_id"] = data["client_id"].fillna("").astype(str).str.strip()
    counts = (
        data.groupby("client_id", dropna=False)
        .agg(event_count=("product", "size"), inn_is_pseudo=("inn_is_pseudo", "max"))
        .reset_index()
    )
    scorable = counts.loc[
        counts["client_id"].ne("")
        & counts["event_count"].ge(2)
        & ~counts["inn_is_pseudo"].astype(bool),
        "client_id",
    ]
    not_scorable = counts.loc[
        counts["client_id"].ne("")
        & (
            counts["event_count"].lt(2)
            | counts["inn_is_pseudo"].astype(bool)
        ),
        "client_id",
    ]
    return {
        "scorable": scorable.astype(str).head(5).tolist(),
        "not_scorable": not_scorable.astype(str).head(5).tolist(),
    }


def get_health() -> dict[str, Any]:
    url = f"{api_base_url()}/health"
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        return {"_error": f"serving API unavailable - {exc}"}
    if response.status_code != 200:
        return {
            "_error": f"serving API health returned HTTP {response.status_code}",
            "_body": response.text[:500],
        }
    try:
        return response.json()
    except ValueError:
        return {"_error": "serving API health returned non-JSON response"}


def score_client(
    client_id: str,
    reference_date: str | None = None,
    mode: str | None = None,
    product_family: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "client_id": client_id,
        "reference_date": reference_date or FALLBACK_REF_DATE,
    }
    if mode:
        body["mode"] = mode
    if product_family:
        body["product_family"] = product_family

    url = f"{api_base_url()}/score"
    try:
        response = requests.post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        return {"_error": f"serving API unavailable - check nbo-api / API_BASE_URL: {exc}"}

    if response.status_code != 200:
        text = response.text[:500]
        return {
            "_error": f"serving API returned HTTP {response.status_code}",
            "_body": text,
        }
    try:
        return response.json()
    except ValueError:
        return {"_error": "serving API returned non-JSON response"}


def normalize_inn(value: str) -> str:
    """Return digits-only INN string used for the local public projection."""
    return "".join(ch for ch in str(value or "").strip() if ch.isdigit())


def client_id_from_inn(value: str) -> str:
    inn = normalize_inn(value)
    if not INN_RE.fullmatch(inn):
        raise ValueError("INN must contain 10 to 12 digits.")
    return "C" + hashlib.sha1(inn.encode("utf-8")).hexdigest()[:12]


def default_reference_date(health: dict[str, Any]) -> str:
    if isinstance(health, dict) and health.get("data_cutoff"):
        return str(health["data_cutoff"])
    return os.environ.get("DATA_CUTOFF") or FALLBACK_REF_DATE


def show_health(health: dict[str, Any]) -> None:
    if health.get("_error"):
        st.warning(f"API degraded: {health['_error']}")
        return
    status = str(health.get("status", "unknown"))
    model_version = health.get("model_version") or "none"
    champion_alias = health.get("champion_alias") or "champion"
    data_cutoff = health.get("data_cutoff") or "unknown"
    text = (
        f"API status: {status} | model_version: {model_version} | "
        f"champion_alias: {champion_alias} | data_cutoff: {data_cutoff}"
    )
    if status == "ok":
        st.success(text)
    else:
        st.warning(f"API degraded: {text}")


def format_score(data: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(data)
    cols = ["product", "p", "decision", "confidence"]
    frame = frame.loc[:, [col for col in cols if col in frame.columns]].copy()
    if "p" in frame.columns:
        frame["p"] = pd.to_numeric(frame["p"], errors="coerce").clip(0, 1)
        frame = frame.sort_values("p", ascending=False).reset_index(drop=True)
    return frame


def show_score(response: dict[str, Any]) -> None:
    if response.get("_error"):
        st.error(str(response["_error"]))
        if response.get("_body"):
            st.code(str(response["_body"]))
        return

    status = str(response.get("status", "unknown"))
    cols = st.columns(4)
    cols[0].metric("status", status)
    cols[1].metric("segment_id", response.get("segment_id") or "none")
    cols[2].metric("model_version", response.get("model_version") or "none")
    cols[3].metric("client_id", response.get("client_id") or "none")

    action = response.get("recommended_action")
    if action:
        st.write(f"recommended_action: {action}")

    if status != "scorable":
        st.warning("not_scorable: no top-10 is shown because the API returned no score.")
        show_caveats(response.get("caveats") or [])
        return

    score = response.get("score")
    if not score:
        st.info("No product candidates returned for the selected filters.")
        show_caveats(response.get("caveats") or [])
        return

    frame = format_score(score)
    st.dataframe(
        frame.style.format({"p": "{:.3f}"}),
        use_container_width=True,
        hide_index=True,
    )
    chart = (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("p:Q", title="probability", scale=alt.Scale(domain=[0, 1])),
            y=alt.Y("product:N", title="product", sort="-x"),
            color=alt.Color(
                "decision:N",
                title="decision",
                scale=alt.Scale(
                    domain=["recommend", "hold"],
                    range=["#2f6f4e", "#8a6a2f"],
                ),
            ),
            tooltip=["product", alt.Tooltip("p:Q", format=".3f"), "decision", "confidence"],
        )
        .properties(height=max(260, 28 * len(frame)))
    )
    st.altair_chart(chart, use_container_width=True)
    show_caveats(response.get("caveats") or [])


def show_caveats(caveats: list[str]) -> None:
    if not caveats:
        return
    st.write("caveats:")
    for item in caveats:
        st.write(f"- {item}")


def main() -> None:
    st.set_page_config(page_title="NBO demo", layout="wide")
    st.title("NBO demo - top-10 next-best-offer for a client")
    st.caption("Q+1 probabilities are propensity scores, not revenue.")

    health = get_health()
    show_health(health)
    ids = load_sample_ids()
    default_client = ids["scorable"][0] if ids["scorable"] else ""
    default_ref = default_reference_date(health)

    left, mid, right = st.columns([2, 1, 1])
    lookup_mode = left.radio(
        "lookup",
        ["client_id", "inn"],
        horizontal=True,
        help="INN is hashed locally to the public client_id before the API request.",
    )
    if lookup_mode == "inn":
        raw_input = left.text_input("inn", value="", placeholder="10 or 12 digits")
        inn_digits = normalize_inn(raw_input)
        if raw_input:
            if INN_RE.fullmatch(inn_digits):
                left.caption(f"hashed client_id: `{client_id_from_inn(inn_digits)}`")
            else:
                left.caption(f"digits detected: {len(inn_digits)} / expected 10 or 12")
        left.caption("Raw INN is not sent to the API. The demo sends only the hashed client_id.")
    else:
        raw_input = left.text_input("client_id", value=default_client, placeholder="C0004e3cbdfb8")
    reference_date = mid.text_input("reference_date", value=default_ref)
    mode = right.selectbox("mode", ["single", "explain"], index=0)
    product_family = st.selectbox("product_family", PRODUCT_FAMILIES, index=0)
    submitted = st.button("Score")

    examples = []
    if ids["scorable"]:
        examples.append(f"scorable example: {ids['scorable'][0]}")
    if ids["not_scorable"]:
        examples.append(f"not_scorable example: {ids['not_scorable'][0]}")
    if examples:
        st.caption(" | ".join(examples))

    if submitted:
        try:
            client_id = client_id_from_inn(raw_input) if lookup_mode == "inn" else raw_input
        except ValueError as exc:
            st.session_state["last_response"] = {"_error": str(exc)}
        else:
            st.session_state["last_response"] = score_client(
                client_id=client_id,
                reference_date=reference_date,
                mode=mode,
                product_family=product_family or None,
            )

    response = st.session_state.get("last_response")
    if (
        lookup_mode == "inn"
        and response
        and response.get("_error") == "INN must contain 10 to 12 digits."
        and INN_RE.fullmatch(normalize_inn(raw_input))
    ):
        response = None
    if response:
        show_score(response)
        with st.expander("raw response"):
            st.json(response)


if __name__ == "__main__":
    main()
