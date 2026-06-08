# LM (2011) replication diagnostic — v2 (post-appendix fixes)

Analysis sample: **50,902 firm-years** / **8,937 unique permnos**.
Paper targets: **50,115 firm-years / 8,341 firms**.

## Methodology fixes applied (LM 2011 Internet Appendix)
- 10-K and 10-K405 only (drop 10-KSB family)
- Strip exhibits (`<TYPE>EX-*`), keep only the primary 10-K body
- Strip tables where > 25% of nonblank chars are digits
- Replace `hyphen + LF` with `hyphen` before tokenizing
- N_Words = count of tokens IN the master dictionary
- Excess return = buy-and-hold compounded × 100 (in percent)
- Control: log(turnover), not raw turnover
- Fama-MacBeth quarterly with Newey-West (1 lag) SEs


## Table II — descriptive statistics (mine)

```
               variable     n    mean  median    std      min     max
                Fin-Neg 50902  1.3634  1.3403 0.5124   0.3735  2.8485
                Fin-Pos 50902  0.6922  0.6773 0.2089   0.2368  1.3469
Excess return [0,3] (%) 50902 -0.2996 -0.2500 6.2001 -21.5993 19.6317
              Size ($B) 50902  2.2272  0.3104 6.8205   0.0115 51.8156
         Book-to-market 50902  0.6016  0.5085 0.4261   0.0422  2.3321
 Turnover (pre, median) 50902  1.1773  0.7373 1.2853   0.0401  7.1521
1-yr pre-event FF alpha 50902  0.1262  0.0761 0.4734  -1.0204  1.9051
Institutional ownership 50683  0.4617  0.4508 0.2826   0.0064  1.0887
           NASDAQ dummy 50902  0.5797  1.0000 0.4936   0.0000  1.0000
```

## Table IV — Excess-return regressions, full 10-K (mine)

```
            label  ff48_dummies      sentiment_var    coef     se       t      p     n  n_quarters  adj_r2_avg
 col2_FinNeg_prop          True       fin_neg_prop -0.2816 0.0942 -2.9900 0.0028 50683          60      0.0235
col4_FinNeg_tfidf          True fin_neg_tfidf_full -0.0091 0.0034 -2.6856 0.0072 50683          60      0.0258
 col2_FinNeg_prop         False       fin_neg_prop -0.3024 0.0814 -3.7137 0.0002 50683          60      0.0171
col4_FinNeg_tfidf         False fin_neg_tfidf_full -0.0099 0.0030 -3.2432 0.0012 50683          60      0.0182
```

## Table V — Excess-return regressions, MD&A only (mine)

```
                label  ff48_dummies     sentiment_var    coef     se       t      p     n  n_quarters  adj_r2_avg
 col2_FinNeg_prop_MDA          True  fin_neg_prop_mda -0.2133 0.0615 -3.4701 0.0005 48137          60      0.0242
col4_FinNeg_tfidf_MDA          True fin_neg_tfidf_mda -0.0147 0.0043 -3.3895 0.0007 48137          60      0.0252
 col2_FinNeg_prop_MDA         False  fin_neg_prop_mda -0.2277 0.0619 -3.6766 0.0002 48137          60      0.0177
col4_FinNeg_tfidf_MDA         False fin_neg_tfidf_mda -0.0150 0.0046 -3.2625 0.0011 48137          60      0.0183
```

## LM (2011) reported reference values

Table IV col (2) Fin-Neg proportional: t ≈ -2.84, sign negative
Table IV col (4) Fin-Neg tf-idf:       t ≈ -5.27, larger magnitude than col (2)
Table V cols (2)/(4): same sign, larger |t| for tf-idf than proportional

_(LM signs are negative — higher negative tone predicts lower filing-period excess return.)_