# LM (2011) replication diagnostic — v2 (post-appendix fixes)

Analysis sample: **51,015 firm-years** / **8,950 unique permnos**.
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


## Table II — descriptive statistics (ours)

```
               variable     n    mean  median    std      min     max
                Fin-Neg 51015  1.3633  1.3401 0.5121   0.3735  2.8477
                Fin-Pos 51015  0.6921  0.6771 0.2089   0.2369  1.3467
Excess return [0,3] (%) 51015 -0.2980 -0.2472 6.1936 -21.5743 19.5875
              Size ($B) 51015  2.2295  0.3118 6.8151   0.0115 51.7606
         Book-to-market 51015  0.6020  0.5092 0.4264   0.0421  2.3333
 Turnover (pre, median) 51015  1.1774  0.7380 1.2841   0.0402  7.1235
1-yr pre-event FF alpha 51015  0.1261  0.0760 0.4732  -1.0229  1.9038
Institutional ownership 50796  0.4619  0.4509 0.2825   0.0065  1.0890
           NASDAQ dummy 51015  0.5789  1.0000 0.4937   0.0000  1.0000
```

## Table IV — Excess-return regressions, full 10-K (ours)

```
            label  ff48_dummies      sentiment_var    coef     se       t      p     n  n_quarters  adj_r2_avg
 col2_FinNeg_prop          True       fin_neg_prop -0.2800 0.0947 -2.9563 0.0031 50796          60      0.0236
col4_FinNeg_tfidf          True fin_neg_tfidf_full -0.0081 0.0031 -2.6160 0.0089 50796          60      0.0261
 col2_FinNeg_prop         False       fin_neg_prop -0.2994 0.0816 -3.6696 0.0002 50796          60      0.0171
col4_FinNeg_tfidf         False fin_neg_tfidf_full -0.0089 0.0028 -3.1522 0.0016 50796          60      0.0184
```

## Table V — Excess-return regressions, MD&A only (ours)

```
                label  ff48_dummies     sentiment_var    coef     se       t      p     n  n_quarters  adj_r2_avg
 col2_FinNeg_prop_MDA          True  fin_neg_prop_mda -0.2154 0.0617 -3.4882 0.0005 48248          60      0.0244
col4_FinNeg_tfidf_MDA          True fin_neg_tfidf_mda -0.0144 0.0043 -3.3813 0.0007 48248          60      0.0254
 col2_FinNeg_prop_MDA         False  fin_neg_prop_mda -0.2285 0.0620 -3.6869 0.0002 48248          60      0.0177
col4_FinNeg_tfidf_MDA         False fin_neg_tfidf_mda -0.0146 0.0045 -3.2493 0.0012 48248          60      0.0183
```

## LM (2011) reported reference values

Table IV col (2) Fin-Neg proportional: t ≈ -2.84, sign negative
Table IV col (4) Fin-Neg tf-idf:       t ≈ -5.27, larger magnitude than col (2)
Table V cols (2)/(4): same sign, larger |t| for tf-idf than proportional

_(LM signs are negative — higher negative tone predicts lower filing-period excess return.)_