"""Adapter + categoriser + profile: the synthetic mess must come out clean."""
import pandas as pd

from mygoal.adapters.tabular import parse_amount, parse_date, rows_to_bookings


def test_parse_amount_formats():
    assert parse_amount("1'234.50") == 1234.5
    assert parse_amount("1.234,50", decimal=",") == 1234.5
    assert parse_amount("−42.10") == -42.10
    assert parse_amount("42.10-") == -42.10
    assert parse_amount("CHF 12") == 12
    assert parse_amount("") is None


def test_parse_date_formats():
    assert str(parse_date("31.08.2026", ["%d.%m.%Y"])) == "2026-08-31"
    assert str(parse_date("2026-08-31", ["%d.%m.%Y"])) == "2026-08-31"


def test_split_debit_credit_mapping():
    df = pd.DataFrame([{"Datum": "01.02.2026", "Text": "Einkauf Migros", "Belastung": "12.50", "Gutschrift": ""},
                       {"Datum": "02.02.2026", "Text": "Lohn", "Belastung": "", "Gutschrift": "5'000.00"}])
    m = {"columns": {"booking_date": "Datum", "text": "Text"}, "date_formats": ["%d.%m.%Y"],
         "sign": {"mode": "split", "debit_column": "Belastung", "credit_column": "Gutschrift"}}
    bookings, _ = rows_to_bookings(df, m)
    assert [b.amount for b in bookings] == [-12.5, 5000.0]


def test_lena_profile(svc):
    st = svc.state("lena")
    p = st.profile
    assert "2 exact duplicate rows" in " ".join(n.message for n in p.data_quality)
    assert p.missing_months == ["2026-02"]
    assert p.income.has_13th and 7400 < p.income.salary_net_monthly_avg < 7800
    cats = {f.category: f.monthly for f in p.flows}
    assert 1850 < cats["housing"] < 1950                   # current rent, not the old one
    assert "internal_transfer" not in cats                 # savings transfers are not spending
    assert 600 < p.free_cash_flow_monthly < 1300
    assert p.opaque_monthly > 400 and set(p.opaque_breakdown) >= {"cash", "transfers_p2p", "card_lump"}
    kinds = {h.kind for h in p.hints}
    assert {"car", "no_pillar3a"} <= kinds
    rec = {r.merchant for r in p.recurring if r.active}
    assert {"netflix international", "serafe", "amag leasing"} <= rec
    assert "aldi suisse" not in rec                        # variable shopping is not a subscription
    fallback = sum(1 for b in st.ds.bookings if b.category_source == "fallback")
    assert fallback / len(st.ds.bookings) < 0.02
