# Results

Every figure below comes from the full analysis of the private archive. The method and raw outputs are described in the README. Units are **cents per contract** unless stated. Intervals are 95% bootstrap intervals over trades.

The three-day public sample in `data/sample/` is a subset for checking the method. It does not reproduce these headline figures. Use the tables here for the results.

## 1. Settlement labels

Original label (inferred from the BTC spot price at close) versus Kalshi's own settlement result, across 1,056 usable windows closing 23 Jun – 4 Jul 2026:

- **84 of 1,056 labels (7.95%) disagree with Kalshi's result.**
- The original rule reproduces `btc_final ≥ strike` exactly on all 1,056 windows, so the error comes from the price source and not from a coding slip in the rule.

Error rate by distance between the BTC price at close and the strike:

| Distance from strike | Windows | Wrong labels | Error rate |
|---|---:|---:|---:|
| 0–5 USD | 37 | 15 | 40.5% |
| 5–10 USD | 45 | 16 | 35.6% |
| 10–25 USD | 124 | 31 | 25.0% |
| 25–50 USD | 185 | 13 | 7.0% |
| 50–100 USD | 268 | 5 | 1.9% |
| 100+ USD | 397 | 4 | 1.0% |

Errors cluster near the strike. Within 10 USD of the strike, 31 of 82 windows (38%) are labelled wrong.

## 2. Per-lane P&L, original versus corrected labels

The same 1,476 paper entries are scored under both label sets. Entries are identical under both. Only the settlement outcome changes.

| Lane | Trades | Win rate, original → corrected | Mean entry | Original [95% CI] | Corrected [95% CI] |
|---|---:|---|---:|---|---|
| REV01 cheap flip | 73 | 46.6% → 8.2% | 13.0¢ | +33.5 [+22.5, +44.8] | −4.8 [−10.5, +2.1] |
| S01 late-window fade | 390 | 36.1% → 25.4% | 26.9¢ | +9.2 [+4.7, +13.7] | −1.5 [−5.4, +2.5] |
| TB_N stale wide crowded | 221 | 82.8% → 76.5% | 75.8¢ | +7.0 [+1.9, +11.8] | +0.7 [−5.0, +6.2] |
| PR_NO 50–70 book | 291 | 66.3% → 63.2% | 60.2¢ | +6.1 [+0.7, +11.5] | +3.0 [−2.5, +8.7] |
| TB_Q midwide YES-heavy fade | 281 | 75.1% → 72.2% | 73.0¢ | +2.1 [−3.2, +7.0] | −0.8 [−6.0, +4.3] |
| TA_L burst wide fade | 220 | 73.6% → 72.3% | 74.5¢ | −0.9 [−6.9, +4.8] | −2.3 [−8.1, +3.6] |

**No corrected lane is clearly positive.** Every corrected interval includes zero. The largest corrected estimate, PR_NO at +3.0¢, has an interval from −2.5¢ to +8.7¢. REV01 is the lane that looked strongest under the original labels, and it is negative once the labels are corrected.

## 3. Fees

Fees are a sensitivity check, not a measured cost. The formula comes from secondary sources. Kalshi's fee schedule for this series was not verified (see caveats).

Net of an assumed taker fee of 0.07 × P × (1 − P) per contract, using corrected labels:

| Lane | Gross (c) | Taker fee (c) | Net, taker (c) [95% CI] | Net, maker scenario (c) |
|---|---:|---:|---|---:|
| REV01 (cheap flip) | −4.8 | 0.8 | −5.6 [−11.3, +1.3] | −5.0 |
| PR_NO (mid-window fade) | +3.0 | 1.6 | +1.4 [−4.1, +7.0] | +2.6 |
| TB_N (mid-window fade) | +0.7 | 1.3 | −0.6 [−6.3, +4.9] | +0.4 |
| TB_Q (mid-window fade) | −0.8 | 1.3 | −2.1 [−7.4, +3.0] | −1.1 |
| TA_L (mid-window fade) | −2.3 | 1.3 | −3.6 [−9.4, +2.3] | −2.6 |

After the assumed fees, no lane is clearly positive. The maker scenario uses 0.0175 × P × (1 − P), also from secondary sources.

## 4. Paper versus live

Live-traded signals, 11–22 June 2026. Each row is one signal, de-duplicated by window. The paper figure assumes a full fill at the signal price. Live counts unfilled signals as zero. Because no live window has a Kalshi-verified result, both sides use the original spot-inferred label, so the gap is valid within one label set. It is not a measure of true P&L.

| Measure | PR_NO 50–70 book | TB_N stale wide |
|---|---:|---:|
| Signals | 304 | 202 |
| Filled | 150 (49%) | 110 (54%) |
| Paper, cents per signal [CI] | +5.9 [+0.6, +10.8] | +4.9 [−0.8, +10.2] |
| Live, cents per signal, unfilled = 0 [CI] | +0.5 [−3.4, +4.4] | +1.7 [−2.9, +5.8] |
| Mean fill price minus signal price | +0.02¢ | +0.36¢ |

**Fill rate and API cancellations.** 153 of 506 live signals (30%) were cancelled after an API error (80 PR_NO, 73 TB_N). A further 93 timed out without filling. Paper counts every signal as a fill. Price slippage is small. The paper-to-live gap comes mainly from missed fills.

**Adverse selection (a hint, not a conclusion).** Win rates differ by fill status in the direction an adverse-selection effect would predict. Signals that filled won less often than signals that did not: PR_NO 58.7% filled versus 71.4% unfilled (n = 150 and 154); TB_N 78.2% versus 83.7% (n = 110 and 92). The samples are small, and the labels are the original spot-inferred ones. A proper test needs Kalshi results for these windows, which the API no longer serves.

## Caveats

- **The corrected labels are stored values, not re-checkable.** They come from Kalshi's `result` field, fetched and saved when the archive was relabelled. The public market endpoint now returns HTTP 404 for tickers from that period, including ones the archive marks as Kalshi-verified. Anyone checking these numbers has to trust the stored values, or re-collect results while the endpoint serves them.
- **Live windows have no Kalshi-verified results.** The live period (11–22 June) predates the relabelled window set, so Section 4 uses the original labels.
- **The fee formula is from secondary sources.** Kalshi's fee schedule for this series was not verified. Section 3 is a sensitivity range, not a measured cost.
- **The live P&L column disagrees with the original labels on 24 of 150 filled PR_NO rows.** The source of that column is not documented, so I did not use it.
- **Intervals are per trade.** Trades on the same window can be correlated across lanes, so the intervals are somewhat optimistic.
- **Paper fills are an upper bound.** The paper engine fills every entry in full at the signal price. Section 4 shows what that assumption costs.
