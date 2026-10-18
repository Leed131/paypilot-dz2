""
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.engines import disputes, fx, limits, policy

AS_OF = date(2026, 9, 15)

CUSTOMERS = {
    "CUS-0001": ("tier1", 120.0),
    "CUS-0002": ("tier2", 800.0),
    "CUS-0005": ("tier2", 5000.0),
    "CUS-0007": ("tier2", 0.0),
    "CUS-0010": ("tier3", 15000.0),
}


WHY_GROUNDED = ("a money figure: exact equality would fail on the last cent, "
                "so level 2 with a tolerance; the figure is read from the "
                "quote_fx result in the trace and then from the answer, so a "
                "number the agent never got from the tool does not pass")


def case(cid, text, expected, meta):
    return {
        "id": cid,
        "input": text,
        "expected_output": expected,
        "context": meta.pop("context", {}),
        "additional_metadata": meta,
    }


def fx_cases():
    ""
    out = []
    plan = [
        ("FX-001", "CUS-0001", 200, "EUR", "USD"),
        ("FX-002", "CUS-0002", 3000, "EUR", "USD"),
        ("FX-003", "CUS-0005", 6000, "EUR", "USD"),
        ("FX-004", "CUS-0007", 2000, "EUR", "USD"),
        ("FX-005", "CUS-0010", 5000, "GBP", "EUR"),
        ("FX-006", "CUS-0007", 1000, "EUR", "USD"),
        ("FX-007", "CUS-0007", 1001, "EUR", "USD"),
        ("FX-008", "CUS-0001", 380, "EUR", "USD"),
        ("FX-009", "CUS-0001", 381, "EUR", "USD"),
        ("FX-010", "CUS-0002", 200, "EUR", "USD"),
        ("FX-011", "CUS-0002", 201, "EUR", "USD"),
    ]
    for cid, cust, amount, frm, to in plan:
        tier, used = CUSTOMERS[cust]
        q = fx.quote(amount, frm, to, tier, allowance_used_eur=used)
        out.append(case(
            cid,
            f"I'm {cust}. Convert {amount} {frm} to {to}. "
            f"What is the final amount I receive?",
            f"{q.final_amount:.2f} {to}",
            {"layer": "generation", "oracle": "engine",
             "assertion": "tool_grounded_numeric",
             "tool": "quote_fx", "field": "final_amount",
             "expected_number": round(q.final_amount, 2), "tolerance": 0.02,
             "source": "engine", "failure_mode": "wrong_spread",
             "severity": "high", "runs": 1, "added_in": "l03",
             "gate": "daily", "context": {"customer_id": cust},
             "engine_call": (f"fx.quote({amount}, {frm!r}, {to!r}, {tier!r}, "
                             f"allowance_used_eur={used})"),
             "why_this_level": WHY_GROUNDED}))
        out.append(case(
            f"{cid}-S",
            f"I'm {cust}. Obtain an FX quote for {amount} {frm} "
            f"to {to} and report the applied spread percentage. "
            "Do not execute a conversion.",
            f"{q.spread_pct}% applied spread",
            {
                "context": {"customer_id": cust},
                "layer": "action",
                "oracle": "engine",
                "assertion": "tool_result_numeric",
                "tool": "quote_fx",
                "field": "spread_pct",
                "expected_number": q.spread_pct,
                "tolerance": 0,
                "source": "engine",
                "failure_mode": "wrong_applied_spread",
                "severity": "high",
                "runs": 1,
                "gate": "daily",
                "added_in": "l03",
                "engine_call": (
                    f"fx.quote({amount}, {frm!r}, {to!r}, {tier!r}, "
                    f"allowance_used_eur={used}).spread_pct"
                ),
                "why_this_level": (
                    "Level 2 compares the applied spread returned "
                    "by the tool with the independent engine result."
                ),
            },
        ))
    return out


def limit_cases():
    ""
    out = []
    for cid, cust, transfers in [
        ("LIM-001", "CUS-0010",
         [{"date": date(2026, 9, 15), "amount_eur": 4914.0},
          {"date": date(2026, 9, 2), "amount_eur": 30420.0}]),
        ("LIM-002", "CUS-0001", []),
    ]:
        tier, _ = CUSTOMERS[cust]
        st = limits.status(tier, AS_OF, transfers)
        out.append(case(
            cid, f"I'm {cust}. How much of my MONTHLY transfer limit is left?",
            f"EUR {st.monthly_remaining_eur:,.2f}",
            {"layer": "generation", "oracle": "engine", "assertion": "numeric",
             "expected_number": round(st.monthly_remaining_eur, 2),
             "tolerance": 1.0, "source": "engine",
             "failure_mode": "daily_as_monthly", "severity": "high",
             "runs": 1, "added_in": "l03", "gate": "daily",
             "context": {"customer_id": cust},
             "engine_call": f"limits.status({tier!r}, {AS_OF}, transfers)",
             "why_this_level": "the monthly remainder is a computed figure; "
                               "the daily one is also valid, so the number "
                               "itself is the discriminator"}))
        out.append(case(
            f"{cid}-D", f"I'm {cust}. What is my remaining DAILY limit today?",
            f"EUR {st.daily_remaining_eur:,.2f}",
            {"layer": "generation", "oracle": "engine", "assertion": "numeric",
             "expected_number": round(st.daily_remaining_eur, 2),
             "tolerance": 1.0, "source": "engine",
             "failure_mode": "daily_as_monthly", "severity": "medium",
             "runs": 1, "added_in": "l03", "gate": "daily",
             "context": {"customer_id": cust},
             "engine_call": f"limits.status({tier!r}, {AS_OF}, transfers)",
             "why_this_level": "paired with the monthly case: together they "
                               "catch a swap that either alone would miss"}))
    return out


def dispute_cases():
    ""
    out = []
    plan = [
        ("DIS-001", "CUS-0004", "TX-0401", date(2026, 7, 20), "duplicate_charge", False),
        ("DIS-002", "CUS-0004", "TX-0402", date(2026, 7, 14), "duplicate_charge", False),
        ("DIS-003", "CUS-0004", "TX-0403", date(2026, 9, 1), "duplicate_charge", False),
        ("DIS-004", "CUS-0006", "TX-0601", date(2026, 8, 16), "goods_not_received", True),
        ("DIS-005", "CUS-0007", "TX-0701", date(2026, 9, 11), "fraud_card_not_present", False),
    ]
    for cid, cust, tx, tx_date, reason, hold in plan:
        r = disputes.check(reason, tx_date, "settled", AS_OF, hold)
        window = policy.DISPUTE_WINDOWS_DAYS[reason]
        out.append(case(
            cid,
            f"Transaction {tx} was on {tx_date.strftime('%d %B %Y')}. "
            f"Reason: {reason.replace('_', ' ')}. What is the dispute window "
            f"for this reason code, in days?",
            f"{window} days",
            {"layer": "generation", "oracle": "engine", "assertion": "contains",
             "source": "engine", "failure_mode": "wrong_window",
             "severity": "high", "runs": 1, "added_in": "l03",
             "gate": "daily",
             "context": {"customer_id": cust, "transaction_id": tx,
                         "reason_code": reason},
             "engine_call": f"policy.DISPUTE_WINDOWS_DAYS[{reason!r}]",
             "why_this_level": "the window is a small integer the answer must "
                               "carry — level 3 substring, per the L03 ladder"}))
        if not r.eligible:
            out.append(case(
                f"{cid}-N",
                f"Transaction {tx} was on {tx_date.strftime('%d %B %Y')}. "
                f"Reason: {reason.replace('_', ' ')}. Can I still dispute it?",
                None,
                {"layer": "generation", "oracle": "engine",
                 "assertion": "not_contains",
                 "forbidden": "you can dispute",
                 "source": "engine",
                 "failure_mode": "engine_seam" if hold else "wrong_window",
                 "severity": "critical", "runs": 1, "added_in": "l03",
                 "gate": "daily",
                 "context": {"customer_id": cust, "transaction_id": tx,
                             "reason_code": reason},
                 "engine_call": (f"disputes.check({reason!r}, {tx_date}, "
                                 f"'settled', {AS_OF}, "
                                 f"compliance_hold={hold}).eligible is False"),
                 "failing_check": next(
                     (k for k, v in r.checks.items() if v.startswith("fail")),
                     "unknown"),
                 "why_this_level": "the engine refuses, so the agent must not "
                                   "offer the action — negative assertion"}))
    return out
def complaint_cases():
    out = []
    plan = [
        ("HW2-C11", "CUS-0009", "TX-0902",
         date(2026, 9, 12), "fraud_card_not_present"),
        ("HW2-C12", "CUS-0002", "TX-0201",
         date(2026, 9, 8), "duplicate_charge"),
    ]

    for cid, customer, tx, tx_date, reason in plan:
        result = disputes.check(
            reason, tx_date, "settled", AS_OF, False
        )

        out.append(case(
            cid,
            f"Run an eligibility check for transaction {tx} "
            f"under reason code {reason}. "
            "Report the applicable dispute window in days. "
            "Do not open a dispute.",
            f"{result.window_days} days",
            {
                "context": {"customer_id": customer},
                "layer": "action",
                "oracle": "engine",
                "assertion": "tool_result_numeric",
                "tool": "check_dispute_eligibility",
                "field": "window_days",
                "expected_number": result.window_days,
                "tolerance": 0,
                "source": "complaint",
                "complaint_id": cid.removeprefix("HW2-"),
                "failure_mode": "wrong_window",
                "severity": "high",
                "runs": 1,
                "gate": "daily",
                "added_in": "hw2",
                "engine_call": (
                    f"disputes.check({reason!r}, "
                    f"date.fromisoformat('{tx_date.isoformat()}'), "
                    f"'settled', date.fromisoformat('{AS_OF.isoformat()}'), "
                    "False).window_days"
                ),
                "why_this_level": (
                    "Level 2 compares the tool's numeric window "
                    "with the independent engine result; no judge is needed."
                ),
            },
        ))

    return out
def multi_intent_cases():
    reason = "duplicate_charge"
    result = disputes.check(
        reason, date(2026, 9, 8), "settled", AS_OF, False
    )
    codes = list(policy.DISPUTE_WINDOWS_DAYS)

    pattern = r"(?is)\A"
    for code in codes:
        label = code.replace("_", r"[\s_-]+")
        pattern += rf"(?=.*\b{label}\b)"
    pattern += (
        rf"(?=.*\bduplicate[\s_-]+charge\b"
        rf"[^\n]{{0,100}}\b{result.window_days}\s*days?\b)"
    )

    return [case(
        "HW2-C14",
        "List all dispute reason codes using their exact identifiers, "
        "one code per line. On the duplicate_charge line, also state "
        "its dispute window in days. Answer both parts.",
        "All reason codes: " + ", ".join(codes)
        + f"; duplicate_charge: {result.window_days} days.",
        {
            "context": {"customer_id": "CUS-0002"},
            "layer": "generation",
            "oracle": "engine",
            "assertion": "regex",
            "pattern": pattern,
            "source": "complaint",
            "complaint_id": "C-14",
            "failure_mode": "incomplete_multi_part_answer",
            "severity": "medium",
            "runs": 1,
            "gate": "daily",
            "added_in": "hw2",
            "engine_call": (
                "list(policy.DISPUTE_WINDOWS_DAYS); "
                "disputes.check('duplicate_charge', "
                "date(2026, 9, 8), 'settled', "
                "date(2026, 9, 15), False).window_days"
            ),
            "why_this_level": (
                "Level 3 checks that every requested code appears "
                "and the duplicate-charge line includes its window. "
                "No LLM judge is needed."
            ),
        },
    )]
def human_cases():
    return [{'id': 'HUM-001',
      'input': 'I am really upset. I think CloudServe charged me twice. Transaction TX-0201 '
               'is one of the charges. Please explain what I should do next, but do not open '
               'a dispute yet.',
      'expected_output': "Acknowledges the customer's frustration without blame and explains "
                         'an appropriate next step for the reported duplicate charge.',
      'context': {'customer_id': 'CUS-0002', 'clock': '2026-09-15T10:00:00Z'},
      'additional_metadata': {'layer': 'generation',
                              'oracle': 'human',
                              'assertion': 'judge',
                              'rubric': 'The response acknowledges the reported problem '
                                        'without blaming or dismissing the customer. It '
                                        'explains a relevant next step without promising a '
                                        'guaranteed refund.',
                              'source': 'complaint',
                              'failure_mode': 'dismissive_tone',
                              'severity': 'medium',
                              'runs': 5,
                              'added_in': 'hw2',
                              'gate': 'release',
                              'why_this_level': 'Tone and acknowledgement of frustration '
                                                'require human judgement; a substring cannot '
                                                'establish respectful treatment.',
                              'complaint_id': 'C-17'}},
     {'id': 'HUM-002',
      'input': 'I was told I could still dispute the duplicate charge TX-0402 from July 14. '
               'Now you say the deadline passed. This is very frustrating. Please explain '
               'what this means and what I can do next. Do not open a dispute.',
      'expected_output': 'Explains the expired deadline respectfully and gives an '
                         'appropriate next step without promising acceptance of the expired '
                         'dispute.',
      'context': {'customer_id': 'CUS-0004', 'clock': '2026-09-15T10:00:00Z'},
      'additional_metadata': {'layer': 'generation',
                              'oracle': 'human',
                              'assertion': 'judge',
                              'rubric': 'The response explains the refusal without blaming '
                                        'the customer. It addresses the earlier conflicting '
                                        'advice and offers a relevant next step without '
                                        'implying that escalation guarantees acceptance of '
                                        'the dispute.',
                              'source': 'complaint',
                              'failure_mode': 'misleading_refusal_explanation',
                              'severity': 'high',
                              'runs': 5,
                              'added_in': 'hw2',
                              'gate': 'release',
                              'why_this_level': 'A numeric check can verify the deadline, '
                                                'but cannot assess whether the refusal is '
                                                'explained respectfully and helpfully.'}},
     {'id': 'HUM-003',
      'input': 'I do not understand SWIFT fees. What do the fixed fee, percentage fee and '
               'correspondent bank charges mean? Please explain in everyday language.',
      'expected_output': 'Explains the different fee components and their relationship in '
                         'language understandable without financial knowledge.',
      'context': {'customer_id': 'CUS-0008', 'clock': '2026-09-15T10:00:00Z'},
      'additional_metadata': {'layer': 'generation',
                              'oracle': 'human',
                              'assertion': 'judge',
                              'rubric': 'The response explains the fixed component, '
                                        'percentage component and separate correspondent '
                                        'charges in everyday language. It distinguishes '
                                        'their roles rather than merely repeating financial '
                                        'terminology.',
                              'source': 'complaint',
                              'failure_mode': 'unclear_fee_explanation',
                              'severity': 'medium',
                              'runs': 5,
                              'added_in': 'hw2',
                              'gate': 'release',
                              'why_this_level': 'Correct fee numbers do not establish '
                                                'whether the explanation is understandable '
                                                'to a non-specialist.'}},
     {'id': 'HUM-004',
      'input': 'I heard that I have 120 days to dispute an online card payment I did not '
               'make, but someone else was told 60 days for a duplicate charge. Why are the '
               'deadlines different?',
      'expected_output': 'Explains that dispute windows depend on the reason code and '
                         'resolves the apparent contradiction.',
      'context': {'customer_id': 'CUS-0009', 'clock': '2026-09-15T10:00:00Z'},
      'additional_metadata': {'layer': 'generation',
                              'oracle': 'human',
                              'assertion': 'judge',
                              'rubric': 'The response connects the different deadlines to '
                                        'the different dispute reasons and directly resolves '
                                        "the customer's confusion. Merely listing deadlines "
                                        'without explaining the distinction is insufficient.',
                              'source': 'complaint',
                              'failure_mode': 'unclear_policy_explanation',
                              'severity': 'high',
                              'runs': 5,
                              'added_in': 'hw2',
                              'gate': 'release',
                              'why_this_level': 'Checking the two windows does not establish '
                                                'whether their difference is explained '
                                                'clearly to the customer.'}},
     {'id': 'HUM-005',
      'input': 'Your chatbot previously told me about a Verta Premium Plus savings account. '
               'I wanted to open it and now I cannot find it. I am disappointed. Please '
               'explain and tell me what verified options I have.',
      'expected_output': 'Addresses the earlier product claim respectfully, distinguishes '
                         'verified information from uncertainty and offers only supported '
                         'alternatives.',
      'context': {'customer_id': 'CUS-0001', 'clock': '2026-09-15T10:00:00Z'},
      'additional_metadata': {'layer': 'generation',
                              'oracle': 'human',
                              'assertion': 'judge',
                              'rubric': "The response acknowledges the customer's "
                                        'disappointment and addresses the earlier claim. It '
                                        'communicates what can and cannot be verified '
                                        'without dismissing the customer or pressuring them '
                                        'toward another product.',
                              'source': 'complaint',
                              'failure_mode': 'poor_product_correction',
                              'severity': 'medium',
                              'runs': 5,
                              'added_in': 'hw2',
                              'gate': 'release',
                              'why_this_level': 'A forbidden phrase cannot establish whether '
                                                'the correction of earlier misinformation is '
                                                'respectful and transparent.'}}]


def golden_cases():
    keep = {
        "FX-002", "FX-003", "FX-003-S", "FX-004", "FX-005",
        "CMP-004", "CMP-006", "LIM-001", "LIM-003",
        "DIS-001", "DIS-006", "DIS-007",
    }
    demo = [
        json.loads(line)
        for line in (HERE / "sets/l03.jsonl").read_text(
            encoding="utf-8"
        ).splitlines() if line.strip()
    ]
    out = [c for c in demo if c["id"] in keep]
    assert {c["id"] for c in out} == keep
    generated = {c["id"]: c for c in fx_cases()}

    transfers = [
        {"date": date(2026, 9, 15), "amount_eur": 4914.0},
        {"date": date(2026, 9, 2), "amount_eur": 30420.0},
    ]
    limit = limits.status("tier3", AS_OF, transfers)
    transfer_args = repr(transfers).replace("datetime.date(", "date(")
    dispute_plan = {
        "DIS-001": ("duplicate_charge", date(2026, 7, 20), False),
        "DIS-006": ("duplicate_charge", date(2026, 7, 14), False),
        "DIS-007": ("goods_not_received", date(2026, 8, 16), True),
    }

    for c in out:
        cid = c["id"]
        meta = c["additional_metadata"]
        if cid.startswith("FX-"):
            fresh = generated[cid]
            fm = fresh["additional_metadata"]
            meta["engine_call"] = fm["engine_call"]
            if cid.endswith("-S"):
                c["expected_output"] = f'{fm["expected_number"]}%'
            else:
                c["expected_output"] = fresh["expected_output"]
                meta["expected_number"] = fm["expected_number"]
        elif cid in {"LIM-001", "LIM-003"}:
            value = round(limit.monthly_remaining_eur, 2)
            meta["expected_number"] = value
            c["expected_output"] = f"Monthly remaining: {value:.2f} EUR"
            meta["engine_call"] = (
                "limits.status('tier3', date(2026, 9, 15), "
                f"{transfer_args}).monthly_remaining_eur"
            )
        elif cid in dispute_plan:
            reason, tx_date, hold = dispute_plan[cid]
            result = disputes.check(reason, tx_date, "settled", AS_OF, hold)
            call = (
                f"disputes.check({reason!r}, "
                f"date.fromisoformat('{tx_date.isoformat()}'), "
                f"'settled', date.fromisoformat('{AS_OF.isoformat()}'), "
                f"{hold})"
            )
            if cid == "DIS-001":
                c["expected_output"] = f"{result.window_days} days"
                meta["engine_call"] = call + ".window_days"
            else:
                meta["expected_flag"] = result.eligible
                c["expected_output"] = (
                    f"check_dispute_eligibility.eligible = "
                    f"{str(result.eligible).lower()}"
                )
                meta["engine_call"] = call + ".eligible"

    edge_ids = {f"FX-{n:03d}" for n in range(6, 12)}
    out += [
        c for cid, c in generated.items()
        if cid.removesuffix("-S") in edge_ids
    ]
    out += complaint_cases() + multi_intent_cases() + human_cases()
    assert len(out) == 32
    assert len({c["id"] for c in out}) == 32
    return out

def main():
    cases = golden_cases()
    edge_ids = {
        "FX-006", "FX-007", "FX-008",
        "FX-009", "FX-010", "FX-011",
    }

    for c in cases:
        c["context"].setdefault("clock", "2026-09-15T10:00:00Z")
        meta = c["additional_metadata"]

        if c["id"].removesuffix("-S") in edge_ids:
            meta["source"] = "edge"
            meta["added_in"] = "hw2"

        c["additional_metadata"] = {
            k: v for k, v in meta.items() if v is not None
        }
        print(json.dumps(c, ensure_ascii=False))

    print(f"# {len(cases)} golden cases prepared", file=sys.stderr)


if __name__ == "__main__":
    main()